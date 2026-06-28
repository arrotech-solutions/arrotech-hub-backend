"""
Scheduled Broadcast Beat Task.
Checks for scheduled WhatsApp broadcast campaigns that are due,
and triggers the Celery worker task to execute them.
"""

import logging
from datetime import datetime
from sqlalchemy import select, and_

from src.celery_app import app
from .utils import run_async as _run_async
from src.database import get_session_maker
from src.models import WhatsAppBroadcast, WhatsAppBroadcastStatus
from .broadcast_tasks import execute_broadcast_campaign_task

logger = logging.getLogger(__name__)

@app.task(name="src.tasks.scheduled_broadcast_beat.check_scheduled_broadcasts_task")
def check_scheduled_broadcasts_task():
    """
    Find broadcasts that are SCHEDULED and due, then trigger them.
    Runs every minute via Celery Beat.
    """
    logger.info("[BroadcastBeat] Checking for due scheduled broadcasts...")
    
    async def _execute():
        session_maker = get_session_maker()
        triggered_count = 0
        
        async with session_maker() as db:
            now = datetime.utcnow()
            
            # Find due broadcasts
            query = select(WhatsAppBroadcast).where(
                and_(
                    WhatsAppBroadcast.status == WhatsAppBroadcastStatus.SCHEDULED,
                    WhatsAppBroadcast.scheduled_at <= now
                )
            )
            
            result = await db.execute(query)
            due_broadcasts = result.scalars().all()
            
            for broadcast in due_broadcasts:
                # Mark as sending so it doesn't get picked up again
                broadcast.status = WhatsAppBroadcastStatus.SENDING
                broadcast.started_at = now
                
                # Trigger the main execution task
                execute_broadcast_campaign_task.delay(
                    str(broadcast.id),
                    str(broadcast.user_id)
                )
                
                logger.info(f"[BroadcastBeat] Triggered scheduled broadcast {broadcast.id}")
                triggered_count += 1
                
            if due_broadcasts:
                await db.commit()
                
        return {"triggered": triggered_count}

    return _run_async(_execute())
