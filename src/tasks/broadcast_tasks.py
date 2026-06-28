"""
Broadcast Tasks — WhatsApp broadcast campaign execution via Celery.

Broadcast campaigns send messages to potentially hundreds of contacts.
Running in a Celery worker prevents blocking the API and allows
proper rate limiting.

Queue: default
"""

import logging
import asyncio
from datetime import datetime
import uuid

from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from src.celery_app import app
from .utils import run_async as _run_async
from src.database import get_session_maker
from src.models import (
    WhatsAppContact, WhatsAppBroadcast, WhatsAppBroadcastRecipient,
    WhatsAppBroadcastStatus, WhatsAppTemplate, WhatsAppMessage,
    WhatsAppMessageStatus, WhatsAppMessageDirection
)
from src.services.whatsapp_service import WhatsAppService
from src.services.websocket_manager import connection_manager
from src.config import settings

logger = logging.getLogger(__name__)

@app.task(
    name="src.tasks.broadcast_tasks.execute_broadcast_campaign_task",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
    acks_late=True,
    time_limit=1800,       # 30 minute hard limit for large campaigns
    soft_time_limit=1700,  # ~28 minute soft limit
)
def execute_broadcast_campaign_task(self, broadcast_id: str, user_id: str):
    """
    Execute a WhatsApp broadcast campaign.
    Fetches the campaign, resolves recipients, sends messages with pacing,
    pushes WebSocket progress, and handles opt-outs.
    """
    logger.info(f"[CeleryBroadcast] Starting execution for broadcast {broadcast_id}")

    async def _execute():
        session_maker = get_session_maker()
        
        async with session_maker() as db:
            # 1. Load Broadcast
            broadcast = await db.get(WhatsAppBroadcast, uuid.UUID(broadcast_id))
            if not broadcast:
                logger.error(f"[CeleryBroadcast] Broadcast {broadcast_id} not found.")
                return {"success": False, "error": "Not found"}
                
            if broadcast.status == WhatsAppBroadcastStatus.CANCELLED:
                logger.info(f"[CeleryBroadcast] Broadcast {broadcast_id} is cancelled. Aborting.")
                return {"success": False, "error": "Cancelled"}

            # Get recipients to send to
            query = select(WhatsAppBroadcastRecipient).where(
                and_(
                    WhatsAppBroadcastRecipient.broadcast_id == broadcast.id,
                    WhatsAppBroadcastRecipient.status == "pending"
                )
            ).options(selectinload(WhatsAppBroadcastRecipient.contact))
            
            result = await db.execute(query)
            recipients = result.scalars().all()
            
            if not recipients:
                # Need to generate recipients if they weren't generated yet
                contact_query = select(WhatsAppContact).where(
                    and_(
                        WhatsAppContact.user_id == uuid.UUID(user_id),
                        WhatsAppContact.is_blocked == False,
                        WhatsAppContact.opted_out == False
                    )
                )
                
                if broadcast.target_type == "tag" and broadcast.target_tag:
                    contact_query = contact_query.where(WhatsAppContact.tags.contains([broadcast.target_tag]))
                elif broadcast.target_type == "selected" and broadcast.target_contact_ids:
                    contact_query = contact_query.where(WhatsAppContact.id.in_(broadcast.target_contact_ids))
                
                c_result = await db.execute(contact_query)
                contacts = c_result.scalars().all()
                
                for contact in contacts:
                    recipient = WhatsAppBroadcastRecipient(
                        broadcast_id=broadcast.id,
                        contact_id=contact.id,
                        status="pending"
                    )
                    db.add(recipient)
                    recipients.append(recipient)
                    
                await db.commit()

            if not recipients:
                logger.info(f"[CeleryBroadcast] No valid recipients for {broadcast_id}. Completing.")
                broadcast.status = WhatsAppBroadcastStatus.COMPLETED
                await db.commit()
                return {"success": True, "sent": 0, "failed": 0}

            logger.info(f"[CeleryBroadcast] Sending to {len(recipients)} recipients...")

            # 2. Init Service & Template
            wa_service = WhatsAppService(
                access_token=settings.WHATSAPP_TOKEN,
                phone_number_id=settings.WHATSAPP_PHONE_NUMBER_ID
            )
            
            template = None
            if broadcast.message_type == "template" and broadcast.template_id:
                template = await db.get(WhatsAppTemplate, broadcast.template_id)

            sent = 0
            failed = 0
            total = len(recipients)
            error_counts = {}
            
            # Send Rate configuration (e.g. 10 msgs per sec -> 0.1s sleep)
            send_rate = broadcast.send_rate or 10
            sleep_duration = 1.0 / send_rate if send_rate > 0 else 0.1

            # 3. Execution Loop
            for i, recipient in enumerate(recipients):
                # Check for cancellation mid-run
                if i % 10 == 0:
                    await db.refresh(broadcast)
                    if broadcast.status == WhatsAppBroadcastStatus.CANCELLED:
                        logger.info(f"[CeleryBroadcast] Campaign cancelled mid-flight. Stopping.")
                        break

                contact = recipient.contact
                
                # Double check opt-out / blocked
                if contact.is_blocked or contact.opted_out:
                    recipient.status = "failed"
                    recipient.error_message = "Contact opted out or blocked"
                    failed += 1
                    await db.commit()
                    continue

                try:
                    if broadcast.message_type == "template" and template:
                        response = await wa_service.send_template_message(
                            to_number=contact.phone_number,
                            template_name=template.name,
                            language_code=template.language,
                            components=broadcast.template_variables
                        )
                    elif broadcast.media_url and broadcast.media_type:
                        response = await wa_service.send_media_message(
                            to_number=contact.phone_number,
                            media_url=broadcast.media_url,
                            media_type=broadcast.media_type,
                            caption=broadcast.text_content
                        )
                    else:
                        response = await wa_service.send_text_message(
                            to_number=contact.phone_number,
                            text=broadcast.text_content or ""
                        )

                    if response.get("success"):
                        recipient.status = "sent"
                        recipient.sent_at = datetime.utcnow()
                        msg_id = response.get("message_id")
                        recipient.whatsapp_message_id = msg_id
                        sent += 1
                        
                        # Store the message in history
                        msg = WhatsAppMessage(
                            user_id=uuid.UUID(user_id),
                            contact_id=contact.id,
                            direction=WhatsAppMessageDirection.OUTGOING,
                            message_type=broadcast.message_type,
                            content=broadcast.text_content or f"[Template: {template.name if template else 'Unknown'}]",
                            media_url=broadcast.media_url,
                            media_mime_type=broadcast.media_type,
                            whatsapp_message_id=msg_id,
                            status=WhatsAppMessageStatus.SENT,
                        )
                        db.add(msg)
                        
                    else:
                        error_msg = response.get("error", "Unknown error")
                        recipient.status = "failed"
                        recipient.error_message = str(error_msg)
                        failed += 1
                        # Aggregate errors for summary
                        err_key = str(error_msg)[:50]
                        error_counts[err_key] = error_counts.get(err_key, 0) + 1
                        logger.warning(f"[CeleryBroadcast] Failed to send to {contact.phone_number}: {error_msg}")

                except Exception as e:
                    recipient.status = "failed"
                    recipient.error_message = str(e)
                    failed += 1
                    err_key = str(e)[:50]
                    error_counts[err_key] = error_counts.get(err_key, 0) + 1
                    logger.error(f"[CeleryBroadcast] Exception sending to {contact.phone_number}: {e}")

                # Commit batch
                if i % 5 == 0 or i == len(recipients) - 1:
                    broadcast.sent_count = sent
                    broadcast.failed_count = failed
                    await db.commit()
                    
                    # Push WS progress
                    await connection_manager.push_to_user(
                        user_id=uuid.UUID(user_id),
                        event_type="broadcast_progress",
                        data={
                            "broadcast_id": str(broadcast.id),
                            "sent": sent,
                            "failed": failed,
                            "total": total
                        }
                    )

                # Rate limiting pacing
                await asyncio.sleep(sleep_duration)

            # 4. Finalize
            if broadcast.status != WhatsAppBroadcastStatus.CANCELLED:
                broadcast.status = WhatsAppBroadcastStatus.COMPLETED
                broadcast.completed_at = datetime.utcnow()
                
            broadcast.sent_count = sent
            broadcast.failed_count = failed
            broadcast.error_summary = error_counts
            await db.commit()

            logger.info(f"[CeleryBroadcast] Finished campaign {broadcast_id}. Sent: {sent}, Failed: {failed}")
            return {"sent": sent, "failed": failed, "total": total}

    result = _run_async(_execute())
    return result
