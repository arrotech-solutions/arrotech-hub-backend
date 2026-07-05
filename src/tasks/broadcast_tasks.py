"""
Broadcast Tasks — WhatsApp broadcast campaign execution via Celery.
"""

import logging
import asyncio
from datetime import datetime
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from src.celery_app import app
from .utils import run_async as _run_async
from src.database import get_session_maker
from src.models import (
    WhatsAppContact, WhatsAppBroadcast, WhatsAppBroadcastRecipient,
    WhatsAppBroadcastStatus, WhatsAppTemplate, WhatsAppMessage,
    WhatsAppMessageStatus, WhatsAppMessageDirection,
)
from src.services.whatsapp_service import WhatsAppService
from src.services.whatsapp_config_helper import get_whatsapp_config
from src.services.whatsapp_contact_service import contact_has_tag
logger = logging.getLogger(__name__)


def _template_components(raw: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("components"), list):
        return raw["components"]
    return None


def _is_rate_limit_error(response: Dict[str, Any]) -> bool:
    error = str(response.get("error", "")).lower()
    return "429" in error or "rate limit" in error or "too many" in error


@app.task(
    name="src.tasks.broadcast_tasks.execute_broadcast_campaign_task",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
    acks_late=True,
    time_limit=1800,
    soft_time_limit=1700,
)
def execute_broadcast_campaign_task(self, broadcast_id: str, user_id: str):
    """Execute a WhatsApp broadcast campaign."""
    logger.info(f"[CeleryBroadcast] Starting execution for broadcast {broadcast_id}")

    async def _execute():
        session_maker = get_session_maker()
        user_uuid = uuid.UUID(user_id)

        async with session_maker() as db:
            broadcast = await db.get(WhatsAppBroadcast, uuid.UUID(broadcast_id))
            if not broadcast:
                logger.error(f"[CeleryBroadcast] Broadcast {broadcast_id} not found.")
                return {"success": False, "error": "Not found"}

            if broadcast.status == WhatsAppBroadcastStatus.CANCELLED:
                logger.info(f"[CeleryBroadcast] Broadcast {broadcast_id} is cancelled. Aborting.")
                return {"success": False, "error": "Cancelled"}

            try:
                wa_config = await get_whatsapp_config(db, user_uuid, require_active=True)
            except Exception as exc:
                broadcast.status = WhatsAppBroadcastStatus.FAILED
                broadcast.error_summary = {"config": str(exc)}
                await db.commit()
                return {"success": False, "error": str(exc)}

            wa_service = WhatsAppService()

            query = select(WhatsAppBroadcastRecipient).where(
                and_(
                    WhatsAppBroadcastRecipient.broadcast_id == broadcast.id,
                    WhatsAppBroadcastRecipient.status == "pending",
                )
            ).options(selectinload(WhatsAppBroadcastRecipient.contact))

            result = await db.execute(query)
            recipients = result.scalars().all()

            if not recipients:
                contact_query = select(WhatsAppContact).where(
                    and_(
                        WhatsAppContact.user_id == user_uuid,
                        WhatsAppContact.is_blocked == False,
                        WhatsAppContact.opted_out == False,
                    )
                )

                if broadcast.target_type == "tag" and broadcast.target_tag:
                    contact_query = contact_query.where(
                        contact_has_tag(WhatsAppContact.tags, broadcast.target_tag)
                    )
                elif broadcast.target_type == "selected" and broadcast.target_contact_ids:
                    raw_ids = broadcast.target_contact_ids
                    contact_ids = []
                    for cid in raw_ids:
                        try:
                            contact_ids.append(uuid.UUID(str(cid)))
                        except ValueError:
                            continue
                    if contact_ids:
                        contact_query = contact_query.where(
                            WhatsAppContact.id.in_(contact_ids)
                        )

                c_result = await db.execute(contact_query)
                contacts = c_result.scalars().all()

                for contact in contacts:
                    recipient = WhatsAppBroadcastRecipient(
                        broadcast_id=broadcast.id,
                        contact_id=contact.id,
                        status="pending",
                    )
                    db.add(recipient)
                    recipients.append(recipient)

                await db.commit()
                for recipient in recipients:
                    await db.refresh(recipient, attribute_names=["contact"])

            if not recipients:
                logger.info(f"[CeleryBroadcast] No valid recipients for {broadcast_id}. Completing.")
                broadcast.status = WhatsAppBroadcastStatus.COMPLETED
                await db.commit()
                return {"success": True, "sent": 0, "failed": 0}

            template = None
            if broadcast.message_type == "template" and broadcast.template_id:
                template = await db.get(WhatsAppTemplate, broadcast.template_id)

            sent = 0
            failed = 0
            total = len(recipients)
            error_counts: Dict[str, int] = {}

            send_rate = broadcast.send_rate or 10
            sleep_duration = 1.0 / send_rate if send_rate > 0 else 0.1
            components = _template_components(broadcast.template_variables)

            for i, recipient in enumerate(recipients):
                if i % 10 == 0:
                    await db.refresh(broadcast)
                    if broadcast.status == WhatsAppBroadcastStatus.CANCELLED:
                        logger.info(f"[CeleryBroadcast] Campaign cancelled mid-flight. Stopping.")
                        break

                contact = recipient.contact
                if contact.is_blocked or contact.opted_out:
                    recipient.status = "failed"
                    recipient.error_message = "Contact opted out or blocked"
                    failed += 1
                    await db.commit()
                    continue

                try:
                    response: Dict[str, Any]
                    if broadcast.message_type == "template" and template:
                        response = await wa_service.send_template_message(
                            to_number=contact.phone_number,
                            template_name=template.name,
                            language_code=template.language,
                            components=components,
                            config=wa_config,
                        )
                    elif broadcast.media_url and broadcast.media_type:
                        response = await wa_service.send_media_message(
                            to_number=contact.phone_number,
                            media_url=broadcast.media_url,
                            media_type=broadcast.media_type,
                            caption=broadcast.text_content,
                            config=wa_config,
                        )
                    else:
                        response = await wa_service.send_message(
                            to_number=contact.phone_number,
                            message=broadcast.text_content or "",
                            config=wa_config,
                        )

                    if _is_rate_limit_error(response):
                        logger.warning("[CeleryBroadcast] Rate limited — backing off 30s")
                        await asyncio.sleep(30)
                        response = await wa_service.send_message(
                            to_number=contact.phone_number,
                            message=broadcast.text_content or "",
                            config=wa_config,
                        ) if broadcast.message_type != "template" else await wa_service.send_template_message(
                            to_number=contact.phone_number,
                            template_name=template.name,
                            language_code=template.language,
                            components=components,
                            config=wa_config,
                        )

                    if response.get("success"):
                        recipient.status = "sent"
                        recipient.sent_at = datetime.utcnow()
                        msg_id = response.get("message_id")
                        recipient.whatsapp_message_id = msg_id
                        sent += 1

                        if template:
                            template.times_used = (template.times_used or 0) + 1
                            template.last_used_at = datetime.utcnow()

                        msg = WhatsAppMessage(
                            user_id=user_uuid,
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
                        err_key = str(error_msg)[:50]
                        error_counts[err_key] = error_counts.get(err_key, 0) + 1
                        logger.warning(
                            f"[CeleryBroadcast] Failed to send to {contact.phone_number}: {error_msg}"
                        )

                except Exception as e:
                    recipient.status = "failed"
                    recipient.error_message = str(e)
                    failed += 1
                    err_key = str(e)[:50]
                    error_counts[err_key] = error_counts.get(err_key, 0) + 1
                    logger.error(f"[CeleryBroadcast] Exception sending to {contact.phone_number}: {e}")

                if i % 5 == 0 or i == len(recipients) - 1:
                    broadcast.sent_count = sent
                    broadcast.failed_count = failed
                    await db.commit()

                    from ..services.whatsapp_inbox_events import emit_whatsapp_inbox_event_sync

                    emit_whatsapp_inbox_event_sync(
                        user_uuid,
                        "broadcast_progress",
                        {
                            "broadcast_id": str(broadcast.id),
                            "sent": sent,
                            "failed": failed,
                            "total": total,
                        },
                    )

                await asyncio.sleep(sleep_duration)

            if broadcast.status != WhatsAppBroadcastStatus.CANCELLED:
                if sent == 0 and failed > 0:
                    broadcast.status = WhatsAppBroadcastStatus.FAILED
                else:
                    broadcast.status = WhatsAppBroadcastStatus.COMPLETED
                broadcast.completed_at = datetime.utcnow()

            broadcast.sent_count = sent
            broadcast.failed_count = failed
            broadcast.error_summary = error_counts
            await db.commit()

            logger.info(
                f"[CeleryBroadcast] Finished campaign {broadcast_id}. Sent: {sent}, Failed: {failed}"
            )
            return {"sent": sent, "failed": failed, "total": total}

    result = _run_async(_execute())
    return result
