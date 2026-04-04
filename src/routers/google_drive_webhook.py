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
    from ..models import Workflow, WorkflowStatus, WorkflowTriggerType, User
    from ..services.google_workspace.base_client import GoogleWorkspaceBaseClient
    from ..services.google_workspace.drive_service import DriveService
    from sqlalchemy import select, and_, update
    
    session_maker = get_session_maker()
    async with session_maker() as db:
        try:
            # Find workflows associated with this channel
            result = await db.execute(
                select(Workflow).where(
                    and_(
                        Workflow.status == WorkflowStatus.ACTIVE,
                        Workflow.workflow_metadata["google_drive_channel_id"].astext == channel_id
                    )
                )
            )
            workflows = result.scalars().all()
            
            if not workflows:
                logger.info(f"[DRIVE_WEBHOOK] No active workflows found for channel {channel_id}")
                return

            # Group workflows by user to avoid redundant change listing
            user_workflows = {}
            for wf in workflows:
                if wf.user_id not in user_workflows:
                    user_workflows[wf.user_id] = []
                user_workflows[wf.user_id].append(wf)

            base_client = GoogleWorkspaceBaseClient()
            drive_service = DriveService(base_client)
            builder = WorkflowBuilderService()

            for user_id, wfs in user_workflows.items():
                # Get the user to authenticate
                user_result = await db.execute(select(User).where(User.id == user_id))
                user = user_result.scalar_one_or_none()
                if not user:
                    continue

                # Get the last page token from the first workflow (they should share the same channel/token if grouped)
                # In reality, multiple workflows might share a channel, but we'll use the one from the metadata
                last_token = wfs[0].workflow_metadata.get("google_drive_last_page_token")
                
                if not last_token:
                    logger.warning(f"[DRIVE_WEBHOOK] No page token found for workflow {wfs[0].id}")
                    continue

                # Fetch changes
                changes_result = await drive_service.list_changes(last_token)
                if not changes_result.get("success"):
                    logger.error(f"[DRIVE_WEBHOOK] Failed to list changes for user {user_id}: {changes_result.get('error')}")
                    continue

                changes = changes_result.get("changes", [])
                new_token = changes_result.get("new_start_page_token")

                # Update the page token in the database for ALL workflows sharing this channel
                for wf in wfs:
                    metadata = dict(wf.workflow_metadata)
                    metadata["google_drive_last_page_token"] = new_token
                    await db.execute(
                        update(Workflow).where(Workflow.id == wf.id).values(workflow_metadata=metadata)
                    )
                await db.commit()

                if not changes:
                    logger.info(f"[DRIVE_WEBHOOK] No actual changes found in the notification for user {user_id}")
                    continue

                # For each workflow, check if any change matches its configured folder(s)
                for wf in wfs:
                    # Identify target folders from trigger_config or rag_ingest_source tool
                    target_folders = []
                    
                    # 1. Check trigger config
                    tc = wf.trigger_config or {}
                    if tc.get("platform") == "google_drive" and tc.get("folder_id"):
                        target_folders.append(tc.get("folder_id"))
                    
                    # 2. Check steps for rag_ingest_source with auto_sync
                    for step in wf.steps:
                        if step.tool_name == "rag_ingest_source":
                            params = step.tool_parameters or {}
                            if params.get("auto_sync") and params.get("source_type") == "google_drive":
                                target_folders.append(params.get("url_or_id"))

                    if not target_folders:
                        # If no specific folder is targeted, maybe the user wants to monitor everything?
                        # For now, let's assume we need a target folder to avoid noise.
                        logger.info(f"[DRIVE_WEBHOOK] Workflow {wf.id} has no target folder configured.")
                        continue

                    # Check if any change intersects with target folders
                    triggered = False
                    for change in changes:
                        file_data = change.get("file", {})
                        parents = file_data.get("parents", [])
                        
                        # Check if file itself is a target folder OR if any of its parents are target folders
                        if file_data.get("id") in target_folders or any(p in target_folders for p in parents):
                            triggered = True
                            break
                    
                    if triggered:
                        logger.info(f"[DRIVE_WEBHOOK] Triggering workflow {wf.name} for user {user_id} due to drive changes.")
                        try:
                            await builder.execute_workflow(
                                workflow_id=wf.id,
                                user_id=user_id,
                                db=db,
                                input_data={
                                    "google_drive_event": state,
                                    "google_drive_changes": changes
                                }
                            )
                        except Exception as e:
                            logger.error(f"[DRIVE_WEBHOOK] Execution failed for {wf.id}: {e}")
            
        except Exception as e:
            logger.error(f"Error processing Google Drive event: {e}", exc_info=True)
