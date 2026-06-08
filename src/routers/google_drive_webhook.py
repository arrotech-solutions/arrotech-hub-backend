"""
Google Drive Webhook Router
Handles Google Drive Changes API push notifications for folder auto-sync.
"""
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/google-drive", tags=["google-drive-webhook"])


@router.post("/events")
async def google_drive_events(
    request: Request,
    background_tasks: BackgroundTasks,
    x_goog_resource_state: Optional[str] = Header(None, alias="X-Goog-Resource-State"),
    x_goog_channel_id: Optional[str] = Header(None, alias="X-Goog-Channel-ID"),
    x_goog_resource_id: Optional[str] = Header(None, alias="X-Goog-Resource-ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    Handle Google Drive push notifications.

    Acknowledges immediately; heavy work (changes.list + ingest) runs async.
    """
    if x_goog_resource_state == "sync":
        logger.info(
            f"[DRIVE_WEBHOOK] Sync handshake for channel {x_goog_channel_id}"
        )
        return {"status": "ok"}

    if x_goog_resource_state not in (
        "add",
        "update",
        "trash",
        "remove",
        "change",
        None,
    ):
        return {"status": "ok"}

    logger.info(
        f"[DRIVE_WEBHOOK] {x_goog_resource_state} event "
        f"channel={x_goog_channel_id} resource={x_goog_resource_id}"
    )

    payload = {
        "channel_id": x_goog_channel_id,
        "resource_id": x_goog_resource_id,
        "state": x_goog_resource_state,
    }

    use_celery = getattr(settings, "GOOGLE_DRIVE_USE_CELERY_WEBHOOK", True)
    dispatched = False

    if use_celery:
        try:
            from ..tasks.webhook_tasks import process_drive_webhook_task

            process_drive_webhook_task.delay(payload)
            dispatched = True
            logger.info("[DRIVE_WEBHOOK] Queued to Celery")
        except Exception as e:
            logger.warning(
                f"[DRIVE_WEBHOOK] Celery dispatch failed, using inline fallback: {e}"
            )

    if not dispatched:
        background_tasks.add_task(_process_drive_change_inline, payload)

    return {"status": "ok"}


async def _process_drive_change_inline(payload: dict) -> None:
    from ..services.drive_watch_service import process_drive_notification

    try:
        result = await process_drive_notification(
            channel_id=payload.get("channel_id"),
            resource_state=payload.get("state"),
        )
        logger.info(f"[DRIVE_WEBHOOK] Inline result: {result}")
    except Exception as e:
        logger.error(f"[DRIVE_WEBHOOK] Inline processing error: {e}", exc_info=True)


@router.get("/events/health")
async def google_drive_webhook_health():
    """Health check for the Drive webhook endpoint."""
    from ..services.drive_watch_service import drive_webhook_url

    return {
        "status": "healthy",
        "service": "google-drive-webhook",
        "webhook_url": drive_webhook_url(),
    }
