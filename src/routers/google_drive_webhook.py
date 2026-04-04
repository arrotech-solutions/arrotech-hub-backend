"""
Google Drive Webhook Router
Handles Google Drive push notifications for folder auto-sync
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import json

from ..database import get_db
from ..models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/google-drive", tags=["google-drive-webhook"])


@router.post("/events")
async def google_drive_events(
    request: Request,
    background_tasks: BackgroundTasks,
    x_goog_resource_state: Optional[str] = Header(None, alias="X-Goog-Resource-State"),
    x_goog_channel_id: Optional[str] = Header(None, alias="X-Goog-Channel-ID"),
    x_goog_resource_id: Optional[str] = Header(None, alias="X-Goog-Resource-ID"),
    x_goog_resource_uri: Optional[str] = Header(None, alias="X-Goog-Resource-URI"),
    db: AsyncSession = Depends(get_db)
):
    """Handle Google Drive Push Notifications."""
    # Acknowledge the webhook immediately
    if x_goog_resource_state == "sync":
        logger.info(f"Received sync event for Google Drive channel {x_goog_channel_id}")
        return {"status": "ok"}
        
    # We care about changes such as 'add', 'update', 'trash', 'remove'
    if x_goog_resource_state not in ("add", "update", "trash", "remove", "change"):
        return {"status": "ok"}
        
    logger.info(f"Received {x_goog_resource_state} event for Google Drive channel {x_goog_channel_id}")
    
    # Process the drive change asynchronously
    background_tasks.add_task(
        process_drive_change_async,
        channel_id=x_goog_channel_id,
        resource_id=x_goog_resource_id,
        state=x_goog_resource_state
    )
    
    return {"status": "ok"}


async def process_drive_change_async(
    channel_id: Optional[str],
    resource_id: Optional[str],
    state: Optional[str]
):
    """
    Process Google Drive change asynchronously.
    Find the workflow matching this channel/resource and trigger execution.
    """
    if not channel_id:
        return
        
    from ..database import get_session_maker
    from ..services.workflow_builder_service import WorkflowBuilderService
    from ..models import Workflow, WorkflowStatus, WorkflowTriggerType
    from sqlalchemy import select, and_
    
    session_maker = get_session_maker()
    async with session_maker() as db:
        try:
            # Find workflows with Google Drive triggers
            result = await db.execute(
                select(Workflow).where(
                    and_(
                        Workflow.status == WorkflowStatus.ACTIVE,
                        Workflow.trigger_type == WorkflowTriggerType.EVENT.value
                    )
                )
            )
            workflows = result.scalars().all()
            
            logger.info(f"[DRIVE_TRIGGER] Checking {len(workflows)} active event-triggered workflows for channel {channel_id}")
            
            builder = WorkflowBuilderService()
            for workflow in workflows:
                trigger_config = workflow.trigger_config or {}
                platform = trigger_config.get("platform", "")
                event_type = trigger_config.get("event_type", "")
                
                if platform == "google_drive" and event_type == "google_drive_folder_changed":
                    logger.info(f"[DRIVE_TRIGGER] Firing workflow '{workflow.name}' for user {workflow.user_id}")
                    try:
                        input_vars = {
                            "google_drive_channel_id": channel_id,
                            "google_drive_resource_id": resource_id,
                            "google_drive_state": state
                        }
                        await builder.execute_workflow(
                            workflow_id=workflow.id,
                            user_id=workflow.user_id,
                            db=db,
                            input_data=input_vars
                        )
                    except Exception as e:
                        logger.error(f"[DRIVE_TRIGGER] Failed to execute workflow {workflow.id}: {e}")
            
        except Exception as e:
            logger.error(f"Error processing Google Drive event: {e}", exc_info=True)
