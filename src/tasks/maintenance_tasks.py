"""
Maintenance Tasks — Periodic background maintenance via Celery Beat.

Replaces the asyncio.create_task() fire-and-forget workers that were
running inside the FastAPI process lifespan.

Queue: low
"""

import logging
from typing import Dict, Any
from src.celery_app import app

logger = logging.getLogger(__name__)


from .utils import run_async as _run_async


@app.task(
    name="src.tasks.maintenance_tasks.log_cleanup_task",
    bind=True,
    max_retries=1,
    acks_late=True,
    ignore_result=True,
)
def log_cleanup_task(self, retention_days: int = 14):
    """
    Delete observability logs older than the retention period.

    Runs daily at 04:00 UTC via Celery Beat.
    Replaces the infinite-loop log_cleanup_job().
    """
    async def _cleanup():
        from src.database import get_session_maker
        from src.models import ObservabilityLog
        from sqlalchemy import delete
        import datetime

        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)
        session_maker = get_session_maker()

        async with session_maker() as session:
            result = await session.execute(
                delete(ObservabilityLog).where(ObservabilityLog.timestamp < cutoff)
            )
            await session.commit()
            return result.rowcount

    deleted_count = _run_async(_cleanup())
    if deleted_count > 0:
        logger.info(f"[CeleryMaintenance] Cleaned up {deleted_count} old logs")
    return {"deleted": deleted_count}


@app.task(
    name="src.tasks.maintenance_tasks.refresh_whatsapp_tokens_task",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    acks_late=True,
)
def refresh_whatsapp_tokens_task(self):
    """
    Check for WhatsApp tokens expiring within 7 days and refresh them.

    Runs daily at 03:00 UTC via Celery Beat.
    Replaces the APScheduler whatsapp_token_refresh_job.
    """
    logger.info("[CeleryMaintenance] Checking for expiring WhatsApp tokens...")

    async def _refresh():
        from src.database import get_session_maker
        from src.models import Connection, ConnectionStatus
        from src.config import settings
        from sqlalchemy import select
        from datetime import datetime, timedelta
        import httpx

        session_maker = get_session_maker()

        async with session_maker() as db:
            stmt = select(Connection).where(
                Connection.platform == "whatsapp",
                Connection.status == ConnectionStatus.ACTIVE,
            )
            result = await db.execute(stmt)
            connections = result.scalars().all()

            refreshed_count = 0
            now = datetime.utcnow()
            threshold = now + timedelta(days=7)

            async with httpx.AsyncClient() as client:
                for conn in connections:
                    config = conn.config or {}
                    expires_at_str = config.get("token_expires_at")

                    needs_refresh = True
                    if expires_at_str:
                        try:
                            expires_at = datetime.fromisoformat(expires_at_str)
                            if expires_at > threshold:
                                needs_refresh = False
                        except ValueError:
                            pass

                    if not needs_refresh:
                        continue

                    access_token = config.get("access_token")
                    if not access_token:
                        continue

                    logger.info(f"[CeleryMaintenance] Refreshing WhatsApp token for connection {conn.id}")

                    exchange_params = {
                        "grant_type": "fb_exchange_token",
                        "client_id": settings.WHATSAPP_APP_ID,
                        "client_secret": settings.WHATSAPP_APP_SECRET,
                        "fb_exchange_token": access_token,
                    }

                    graph_url = config.get("base_url", "https://graph.facebook.com/v22.0")
                    resp = await client.get(f"{graph_url}/oauth/access_token", params=exchange_params)

                    if resp.status_code == 200:
                        data = resp.json()
                        new_token = data.get("access_token")
                        if new_token:
                            config["access_token"] = new_token
                            config["token_refreshed_at"] = now.isoformat()
                            config["token_expires_at"] = (now + timedelta(days=60)).isoformat()
                            conn.config = config
                            refreshed_count += 1
                            logger.info(f"[CeleryMaintenance] Refreshed token for connection {conn.id}")
                    else:
                        logger.error(f"[CeleryMaintenance] Token refresh failed for {conn.id}: {resp.text}")

            if refreshed_count > 0:
                await db.commit()

            return refreshed_count

    count = _run_async(_refresh())
    logger.info(f"[CeleryMaintenance] Finished refreshing {count} WhatsApp tokens")
    return {"refreshed": count}


@app.task(
    name="src.tasks.maintenance_tasks.check_tiktok_schedules_task",
    bind=True,
    max_retries=1,
    acks_late=True,
)
def check_tiktok_schedules_task(self):
    """
    Check for scheduled TikTok posts that are due and publish them.

    Runs every 60s via Celery Beat.
    Replaces the APScheduler tiktok_schedule_job.
    """
    logger.info("[CeleryMaintenance] Checking for due TikTok posts...")

    async def _check():
        from src.database import get_session_maker
        from src.models import TikTokVideo
        from sqlalchemy import select
        from datetime import datetime

        session_maker = get_session_maker()
        now = datetime.utcnow()

        async with session_maker() as db:
            stmt = select(TikTokVideo).where(
                TikTokVideo.status == "scheduled",
                TikTokVideo.scheduled_for <= now,
            )
            result = await db.execute(stmt)
            due_posts = result.scalars().all()

            if not due_posts:
                return 0

            logger.info(f"[CeleryMaintenance] Found {len(due_posts)} due TikTok posts")

            from src.services.tiktok_service import TikTokService
            tiktok_service = TikTokService(db)

            published = 0
            for post in due_posts:
                success = await tiktok_service.publish_video(post)
                if success:
                    logger.info(f"✅ Published TikTok post {post.id}")
                    post.status = "published"
                    post.published_at = now
                    published += 1
                else:
                    logger.error(f"❌ Failed to publish TikTok post {post.id}")
                    post.status = "failed"

            await db.commit()
            await tiktok_service.close()
            return published

    count = _run_async(_check())
    return {"published": count}


@app.task(
    name="src.tasks.maintenance_tasks.cleanup_processed_webhook_messages_task",
    bind=True,
    max_retries=1,
    acks_late=True,
    ignore_result=True,
)
def cleanup_processed_webhook_messages_task(self, retention_days: int = 7):
    """
    Delete processed_webhook_messages records older than the retention period.

    These records only need to survive long enough to deduplicate retries
    (Meta retries within ~24h, Celery retries within minutes).  7 days
    gives ample margin while keeping the table small.

    Runs daily at 04:30 UTC via Celery Beat.
    """
    async def _cleanup():
        from src.database import get_session_maker
        from src.models import ProcessedWebhookMessage
        from sqlalchemy import delete
        import datetime

        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)
        session_maker = get_session_maker()

        async with session_maker() as session:
            result = await session.execute(
                delete(ProcessedWebhookMessage).where(
                    ProcessedWebhookMessage.created_at < cutoff
                )
            )
            await session.commit()
            return result.rowcount

    deleted_count = _run_async(_cleanup())
    if deleted_count > 0:
        logger.info(
            f"[CeleryMaintenance] Cleaned up {deleted_count} old processed_webhook_messages"
        )
    return {"deleted": deleted_count}
