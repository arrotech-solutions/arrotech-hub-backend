"""
Workflow Scheduler Service using APScheduler.
"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Set
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session_maker
from ..models import Workflow, WorkflowStatus, WorkflowTriggerType
from .workflow_builder_service import WorkflowBuilderService

logger = logging.getLogger(__name__)

class WorkflowSchedulerService:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.workflow_service = WorkflowBuilderService()
        self._scheduled_workflow_ids: Set[int] = set()

    async def start(self):
        """Start the scheduler service."""
        logger.info("Starting Workflow Scheduler Service...")
        
        # Add the synchronization job to run every 60 seconds
        self.scheduler.add_job(
            self.sync_workflows,
            'interval',
            seconds=60,
            id='workflow_sync_job',
            replace_existing=True
        )

        # Add TikTok Schedule Checker (Every 60s)
        self.scheduler.add_job(
            self.check_tiktok_schedules,
            'interval',
            seconds=60,
            id='tiktok_schedule_job',
            replace_existing=True
        )

        # Add WhatsApp Token Refresh Checker (Every 24h)
        self.scheduler.add_job(
            self.refresh_whatsapp_tokens,
            'interval',
            hours=24,
            id='whatsapp_token_refresh_job',
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info("Workflow Scheduler Service started. Syncing initial workflows...")
        
        # Initial sync
        await self.sync_workflows()

    def shutdown(self):
        """Shutdown the scheduler."""
        logger.info("Shutting down Workflow Scheduler Service...")
        self.scheduler.shutdown()

    async def sync_workflows(self):
        """
        Synchronize active scheduled workflows from DB with the internal scheduler.
        """
        logger.info("Syncing scheduled workflows...")
        
        session_maker = get_session_maker()
        async with session_maker() as db:
            try:
                # Fetch all active workflows with SCHEDULED trigger
                stmt = select(Workflow).where(
                    Workflow.status == WorkflowStatus.ACTIVE,
                    Workflow.trigger_type == WorkflowTriggerType.SCHEDULED
                )
                result = await db.execute(stmt)
                active_workflows = result.scalars().all()
                logger.info(f"Found {len(active_workflows)} active scheduled workflows")
                for w in active_workflows:
                    logger.info(f"Checking workflow {w.id}: config={w.trigger_config}")
                
                active_ids = {w.id for w in active_workflows}
                
                # 1. Add/Update jobs for active workflows
                for workflow in active_workflows:
                    job_id = f"workflow_{workflow.id}"
                    
                    # Validate config
                    trigger_config = workflow.trigger_config or {}
                    cron_expression = trigger_config.get("cron_expression")
                    
                    if not cron_expression:
                        logger.warning(f"Workflow {workflow.id} is SCHEDULED but missing cron_expression. Skipping.")
                        continue
                        
                    try:
                        # Check if job exists and update if needed, or add if missing
                        # For simplicity, we assume we just add_job with replace_existing=True 
                        # to ensure latest cron config is applied.
                        
                        # Note: APScheduler requires a trigger object for cron
                        trigger = CronTrigger.from_crontab(cron_expression)
                        
                        self.scheduler.add_job(
                            self.execute_scheduled_workflow,
                            trigger=trigger,
                            args=[workflow.id, workflow.user_id],
                            id=job_id,
                            replace_existing=True,
                            name=f"Workflow: {workflow.name}"
                        )
                        
                        if workflow.id not in self._scheduled_workflow_ids:
                            logger.info(f"Scheduled workflow {workflow.id} ({workflow.name}) with cron: {cron_expression}")
                            self._scheduled_workflow_ids.add(workflow.id)
                            
                    except Exception as e:
                        logger.error(f"Failed to schedule workflow {workflow.id}: {e}")

                # 2. Remove jobs for workflows that are no longer active or scheduled
                # We track currently scheduled IDs in _scheduled_workflow_ids
                # But to be safe, we can inspect the scheduler's jobs if we wanted to be stateless.
                # Here we compare against our sets.
                
                removed_ids = self._scheduled_workflow_ids - active_ids
                for workflow_id in removed_ids:
                    job_id = f"workflow_{workflow_id}"
                    if self.scheduler.get_job(job_id):
                        self.scheduler.remove_job(job_id)
                        logger.info(f"Removed scheduled job for workflow {workflow_id}")
                
                self._scheduled_workflow_ids = active_ids
                
            except Exception as e:
                logger.error(f"Error executing workflow sync: {e}")

    async def execute_scheduled_workflow(self, workflow_id: uuid.UUID, user_id: uuid.UUID):
        """
        Wrapper to execute a workflow from the scheduler.
        """
        logger.info(f"⏰ Triggering scheduled workflow {workflow_id} for user {user_id}")
        
        session_maker = get_session_maker()
        async with session_maker() as db:
            try:
                # Trigger Execution
                result = await self.workflow_service.execute_workflow(
                    workflow_id=workflow_id,
                    user_id=user_id,
                    db=db,
                    input_data={"source": "scheduler", "timestamp": datetime.utcnow().isoformat()},
                    trigger_type=WorkflowTriggerType.SCHEDULED
                )
                logger.info(f"✅ Scheduled workflow {workflow_id} executed. Status: {result.status}")
                
            except Exception as e:
                logger.error(f"❌ Failed to execute scheduled workflow {workflow_id}: {e}")

    async def check_tiktok_schedules(self):
        """
        Check for scheduled TikTok posts that are due and publish them.
        """
        logger.info("Checking for due TikTok posts...")
        session_maker = get_session_maker()
        async with session_maker() as db:
            try:
                from ..models import TikTokVideo
                
                # Find due posts
                now = datetime.utcnow()
                stmt = select(TikTokVideo).where(
                    TikTokVideo.status == "scheduled",
                    TikTokVideo.scheduled_for <= now
                )
                result = await db.execute(stmt)
                due_posts = result.scalars().all()
                
                if not due_posts:
                    # DEBUG: Check what the next scheduled post is to verify TZ issues
                    stmt_future = select(TikTokVideo).where(
                         TikTokVideo.status == "scheduled"
                    ).order_by(TikTokVideo.scheduled_for.asc()).limit(1)
                    res_future = await db.execute(stmt_future)
                    next_post = res_future.scalar_one_or_none()
                    if next_post:
                       logger.info(f"DEBUG SCHEDULER: No due posts. Next post is: {next_post.scheduled_for} vs Now(UTC): {now}")
                    return

                logger.info(f"Found {len(due_posts)} due TikTok posts to publish.")
                
                from ..services.tiktok_service import TikTokService
                tiktok_service = TikTokService(db)

                for post in due_posts:
                    success = await tiktok_service.publish_video(post)
                    
                    if success:
                        logger.info(f"✅ Published post {post.id}")
                        post.status = "published"
                        post.published_at = now
                        # post.tiktok_video_id set by service
                    else:
                        logger.error(f"❌ Failed to publish post {post.id}")
                        post.status = "failed"
                    
                await db.commit()
                await tiktok_service.close()
                logger.info(f"Processed {len(due_posts)} posts.")
                
            except Exception as e:
                logger.error(f"Error checking TikTok schedules: {e}")

    async def refresh_whatsapp_tokens(self):
        """
        Check for WhatsApp tokens expiring within 7 days and refresh them.
        """
        logger.info("Checking for expiring WhatsApp tokens...")
        
        session_maker = get_session_maker()
        async with session_maker() as db:
            try:
                from ..models import Connection, ConnectionStatus
                from ..config import settings
                import httpx
                from datetime import datetime, timedelta
                
                # We need to find active WhatsApp connections
                stmt = select(Connection).where(
                    Connection.platform == "whatsapp",
                    Connection.status == ConnectionStatus.ACTIVE
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
                        
                        # If no expiry date is set, or if it's within 7 days, refresh it
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
                            
                        logger.info(f"Refreshing WhatsApp token for connection {conn.id}")
                        
                        exchange_params = {
                            "grant_type": "fb_exchange_token",
                            "client_id": settings.WHATSAPP_APP_ID,
                            "client_secret": settings.WHATSAPP_APP_SECRET,
                            "fb_exchange_token": access_token
                        }
                        
                        # Use the Graph URL from config if available, otherwise default
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
                                logger.info(f"Successfully refreshed token for connection {conn.id}")
                        else:
                            logger.error(f"Failed to refresh token for {conn.id}: {resp.text}")
                            
                if refreshed_count > 0:
                    await db.commit()
                
                logger.info(f"Finished refreshing {refreshed_count} WhatsApp tokens.")
                
            except Exception as e:
                logger.error(f"Error refreshing WhatsApp tokens: {e}")
