"""
Workflow Tasks — Celery replacements for APScheduler workflow execution.

Handles cron-triggered workflow execution and periodic workflow sync
from the database. Replaces the in-process WorkflowSchedulerService.

Queue: default
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from src.celery_app import app

logger = logging.getLogger(__name__)


from .utils import run_async as _run_async

@app.task(
    name="src.tasks.workflow_tasks.execute_scheduled_workflow_task",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    acks_late=True,
)
def execute_scheduled_workflow_task(self, workflow_id: str, user_id: str):
    """
    Execute a scheduled workflow.

    This is the task that Celery Beat triggers based on cron schedules.
    Replaces WorkflowSchedulerService.execute_scheduled_workflow().
    """
    logger.info(f"⏰ [CeleryWorkflow] Triggering scheduled workflow {workflow_id} for user {user_id}")

    async def _execute():
        from src.database import get_session_maker
        from src.services.workflow_builder_service import WorkflowBuilderService

        service = WorkflowBuilderService()
        session_maker = get_session_maker()

        async with session_maker() as db:
            try:
                result = await service.execute_workflow(
                    workflow_id=uuid.UUID(workflow_id),
                    user_id=uuid.UUID(user_id),
                    db=db,
                    input_data={
                        "source": "celery_beat",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                logger.info(f"✅ [CeleryWorkflow] Workflow {workflow_id} executed. Status: {result.status}")
                return {"status": str(result.status), "workflow_id": workflow_id}
            except Exception as e:
                logger.error(f"❌ [CeleryWorkflow] Failed to execute workflow {workflow_id}: {e}")
                raise

    return _run_async(_execute())


@app.task(
    name="src.tasks.workflow_tasks.sync_workflows_task",
    bind=True,
    max_retries=1,
    acks_late=True,
)
def sync_workflows_task(self):
    """
    Synchronize active scheduled workflows from DB with Celery Beat.

    This task runs every 60 seconds via Celery Beat. It queries the database
    for active SCHEDULED workflows and ensures they have corresponding
    periodic tasks registered.

    NOTE: In a full implementation, this would use celery-redbeat or
    django-celery-beat for dynamic schedule management. For now, we
    trigger workflow execution directly from the sync task when cron matches.
    """
    logger.info("[CeleryWorkflow] Syncing scheduled workflows from DB...")

    async def _sync():
        from src.database import get_session_maker
        from src.models import Workflow, WorkflowStatus, WorkflowTriggerType
        from sqlalchemy import select
        from croniter import croniter

        session_maker = get_session_maker()

        async with session_maker() as db:
            try:
                # Fetch all active scheduled workflows
                stmt = select(Workflow).where(
                    Workflow.status == WorkflowStatus.ACTIVE,
                    Workflow.trigger_type == WorkflowTriggerType.SCHEDULED
                )
                result = await db.execute(stmt)
                active_workflows = result.scalars().all()
                logger.info(f"[CeleryWorkflow] Found {len(active_workflows)} active scheduled workflows")

                now = datetime.utcnow()

                for workflow in active_workflows:
                    trigger_config = workflow.trigger_config or {}
                    cron_expression = trigger_config.get("cron_expression")

                    if not cron_expression:
                        continue

                    try:
                        # Check if this workflow should have fired in the last 60 seconds
                        cron = croniter(cron_expression, now)
                        prev_fire = cron.get_prev(datetime)

                        # If the previous fire time is within the last 65 seconds, trigger it
                        seconds_since_fire = (now - prev_fire).total_seconds()
                        if seconds_since_fire <= 65:
                            logger.info(
                                f"[CeleryWorkflow] Cron match for workflow {workflow.id} "
                                f"(cron: {cron_expression}, fired {seconds_since_fire:.0f}s ago)"
                            )
                            # Enqueue the actual execution as a separate task
                            execute_scheduled_workflow_task.delay(
                                str(workflow.id), str(workflow.user_id)
                            )
                    except Exception as e:
                        logger.error(f"[CeleryWorkflow] Error checking cron for workflow {workflow.id}: {e}")

            except Exception as e:
                logger.error(f"[CeleryWorkflow] Sync error: {e}")

    _run_async(_sync())
    return {"status": "synced"}
