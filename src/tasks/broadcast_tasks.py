"""
Broadcast Tasks — WhatsApp broadcast campaign execution via Celery.

Broadcast campaigns send messages to potentially hundreds of contacts.
Running in a Celery worker prevents blocking the API and allows
proper rate limiting.

Queue: default
"""

import logging
from typing import Dict, Any, List
from src.celery_app import app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Helper to run an async coroutine in a sync Celery task."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@app.task(
    name="src.tasks.broadcast_tasks.execute_broadcast_campaign_task",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
    acks_late=True,
    time_limit=1800,       # 30 minute hard limit for large campaigns
    soft_time_limit=1700,  # ~28 minute soft limit
)
def execute_broadcast_campaign_task(
    self,
    campaign_id: str,
    user_id: str,
    contact_ids: List[str],
    template_name: str = None,
    message_text: str = None,
    config: Dict[str, Any] = None,
):
    """
    Execute a WhatsApp broadcast campaign — sends messages to a list of contacts
    with rate limiting to comply with WhatsApp API limits.
    """
    logger.info(
        f"[CeleryBroadcast] Starting campaign {campaign_id}: "
        f"{len(contact_ids)} contacts"
    )

    async def _execute():
        import asyncio as aio
        from src.services.whatsapp_service import WhatsAppService
        from src.database import get_session_maker
        from src.models import WhatsAppContact, WhatsAppMessage, WhatsAppMessageDirection, WhatsAppMessageStatus
        from sqlalchemy import select
        import uuid as uuid_mod

        service = WhatsAppService()
        session_maker = get_session_maker()

        sent = 0
        failed = 0

        async with session_maker() as db:
            for contact_id in contact_ids:
                try:
                    # Fetch contact
                    result = await db.execute(
                        select(WhatsAppContact).filter(
                            WhatsAppContact.id == uuid_mod.UUID(contact_id)
                        )
                    )
                    contact = result.scalars().first()

                    if not contact or contact.is_blocked:
                        continue

                    # Send message
                    send_result = await service.send_message(
                        to_number=contact.phone_number,
                        message=message_text or f"[Template: {template_name}]",
                        config=config or {},
                    )

                    if send_result.get("success"):
                        sent += 1
                        # Save outgoing message
                        msg = WhatsAppMessage(
                            user_id=uuid_mod.UUID(user_id),
                            contact_id=contact.id,
                            direction=WhatsAppMessageDirection.OUTGOING,
                            message_type="text",
                            content=message_text or f"[Template: {template_name}]",
                            whatsapp_message_id=send_result.get("message_id"),
                            status=WhatsAppMessageStatus.SENT,
                        )
                        db.add(msg)
                    else:
                        failed += 1
                        logger.warning(
                            f"[CeleryBroadcast] Failed to send to {contact.phone_number}: "
                            f"{send_result.get('error')}"
                        )

                    # Rate limiting: WhatsApp allows ~80 messages/second for business
                    # but we throttle to ~10/s to be safe
                    await aio.sleep(0.1)

                except Exception as e:
                    failed += 1
                    logger.error(f"[CeleryBroadcast] Error sending to {contact_id}: {e}")

            await db.commit()

        return {"sent": sent, "failed": failed, "total": len(contact_ids)}

    result = _run_async(_execute())
    logger.info(
        f"[CeleryBroadcast] Campaign {campaign_id} complete: "
        f"sent={result['sent']}, failed={result['failed']}"
    )
    return result
