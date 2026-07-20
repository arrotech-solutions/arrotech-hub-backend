"""
Webhook Tasks — Offload heavy webhook processing to Celery workers.

Webhook endpoints return 200 OK immediately and delegate the actual
message processing (AI agent calls, DB writes, API calls) to these tasks.

Queue: high (real-time user-facing, low latency)
Retry: 2 attempts with 30s backoff
"""

import logging
from typing import Dict, Any
from src.celery_app import app

logger = logging.getLogger(__name__)


from .utils import run_async as _run_async

@app.task(
    name="src.tasks.webhook_tasks.process_whatsapp_message_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    retry_backoff=True,
    # NOTE: acks_late and autoretry_for deliberately removed.
    # acks_late caused duplicate processing when a worker crashed after
    # order creation but before ack — Celery would redeliver the task.
    # The DB-level idempotency guard (ProcessedWebhookMessage unique
    # constraint) now prevents duplicates even if a task is retried.
)
def process_whatsapp_message_task(self, payload: Dict[str, Any], user_id: str = None):
    """
    Process an incoming WhatsApp webhook message payload.

    This handles the heavy lifting: contact resolution, message persistence,
    auto-reply engine, and AI agent invocation.
    """
    logger.info(f"[CeleryWebhook] Processing WhatsApp message payload")

    async def _process():
        from src.database import get_session_maker
        from src.routers.whatsapp_webhook import process_incoming_messages

        session_maker = get_session_maker()
        async with session_maker() as db:
            try:
                await process_incoming_messages(payload, db, background_tasks=None)
            except Exception as e:
                logger.error(f"[CeleryWebhook] WhatsApp processing error: {e}")
                raise

    _run_async(_process())
    return {"status": "processed", "type": "whatsapp"}


@app.task(
    name="src.tasks.webhook_tasks.process_telegram_message_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    acks_late=True,
)
def process_telegram_message_task(self, payload: Dict[str, Any]):
    """Process an incoming Telegram webhook update."""
    logger.info(f"[CeleryWebhook] Processing Telegram update")

    async def _process():
        from src.services.telegram_service import TelegramService
        from src.database import get_session_maker

        service = TelegramService()
        session_maker = get_session_maker()
        async with session_maker() as db:
            try:
                await service.handle_update(payload, db)
            except Exception as e:
                logger.error(f"[CeleryWebhook] Telegram processing error: {e}")
                raise

    _run_async(_process())
    return {"status": "processed", "type": "telegram"}


@app.task(
    name="src.tasks.webhook_tasks.process_slack_event_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    acks_late=True,
)
def process_slack_event_task(self, event_data: Dict[str, Any], user_id: str = None):
    """Process an incoming Slack event (message, interaction, etc.)."""
    logger.info(f"[CeleryWebhook] Processing Slack event: {event_data.get('type', 'unknown')}")

    async def _process():
        from src.services.slack_service import SlackService
        from src.database import get_session_maker

        service = SlackService()
        session_maker = get_session_maker()
        async with session_maker() as db:
            try:
                await service.handle_event(event_data, db)
            except Exception as e:
                logger.error(f"[CeleryWebhook] Slack processing error: {e}")
                raise

    _run_async(_process())
    return {"status": "processed", "type": "slack"}


@app.task(
    name="src.tasks.webhook_tasks.process_gmail_notification_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    acks_late=True,
)
def process_gmail_notification_task(self, notification_data: Dict[str, Any]):
    """Process a Gmail Pub/Sub push notification."""
    logger.info(f"[CeleryWebhook] Processing Gmail notification")

    async def _process():
        from src.database import get_session_maker

        session_maker = get_session_maker()
        async with session_maker() as db:
            try:
                # Import the processing function from the gmail webhook router
                from src.routers.gmail_webhook import _process_gmail_notification
                await _process_gmail_notification(notification_data, db)
            except ImportError:
                logger.warning("[CeleryWebhook] Gmail webhook processor not available")
            except Exception as e:
                logger.error(f"[CeleryWebhook] Gmail processing error: {e}")
                raise

    _run_async(_process())
    return {"status": "processed", "type": "gmail"}


@app.task(
    name="src.tasks.webhook_tasks.process_drive_webhook_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    acks_late=True,
)
def process_drive_webhook_task(self, payload: Dict[str, Any]):
    """Process a Google Drive Changes API push notification."""
    logger.info(
        f"[CeleryWebhook] Processing Drive notification "
        f"channel={payload.get('channel_id')}"
    )

    async def _process():
        from src.services.drive_watch_service import process_drive_notification

        result = await process_drive_notification(
            channel_id=payload.get("channel_id"),
            resource_state=payload.get("state"),
        )
        logger.info(f"[CeleryWebhook] Drive result: {result}")

    _run_async(_process())
    return {"status": "processed", "type": "google_drive"}


@app.task(
    name="src.tasks.webhook_tasks.poll_stk_order_payment_task",
    bind=True,
    max_retries=0,
    acks_late=True,
)
def poll_stk_order_payment_task(self, **kwargs):
    """Poll Daraja STK status when callback mapping is missing or delayed."""
    logger.info(
        "[CeleryWebhook] STK poll fallback order=%s checkout=%s",
        kwargs.get("order_id"),
        kwargs.get("checkout_request_id"),
    )

    async def _poll():
        from src.services.order_stk_payment_service import poll_stk_and_finalize_order_payment

        await poll_stk_and_finalize_order_payment(**kwargs)

    _run_async(_poll())
    return {"status": "polled", "order_id": kwargs.get("order_id")}
