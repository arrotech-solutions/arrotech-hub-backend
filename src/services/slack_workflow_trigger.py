"""
Slack Workflow Trigger Service.
Fires workflows based on Slack events (message received, app mention).
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
import uuid

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models import (
    Workflow, WorkflowStatus, WorkflowTriggerType
)
from ..services.workflow_builder_service import WorkflowBuilderService

logger = logging.getLogger(__name__)


class SlackWorkflowTrigger:
    """Service to trigger workflows based on Slack events."""
    
    TRIGGER_EVENTS = [
        "slack_message_received",
        "slack_app_mention"
    ]
    
    @classmethod
    async def on_message_received(
        cls,
        user_id: uuid.UUID,
        channel: str,
        message: str,
        slack_user_id: str,
        is_mention: bool = False
    ):
        """
        Called when a new Slack message is received.
        Checks for matching workflows and triggers them.
        """
        async with AsyncSessionLocal() as db:
            try:
                # Find workflows with Slack triggers
                result = await db.execute(
                    select(Workflow).where(
                        and_(
                            Workflow.user_id == user_id,
                            Workflow.status == WorkflowStatus.ACTIVE,
                            Workflow.trigger_type == WorkflowTriggerType.EVENT.value
                        )
                    )
                )
                workflows = result.scalars().all()
                
                logger.info(f"[SLACK_TRIGGER] Checking {len(workflows)} active event-triggered workflows for user {user_id}")
                for workflow in workflows:
                    trigger_config = workflow.trigger_config or {}
                    event_type = trigger_config.get("event_type") or trigger_config.get("trigger", "")
                    platform = trigger_config.get("platform", "")
                    
                    if platform != "slack":
                        logger.debug(f"[SLACK_TRIGGER] Skipping workflow {workflow.id}: platform mismatch ({platform} != slack)")
                        continue
                        
                    # Check if this workflow should trigger
                    should_trigger = False
                    
                    if event_type == "slack_message_received":
                        should_trigger = True
                    elif event_type == "slack_app_mention" and is_mention:
                        should_trigger = True
                    else:
                        logger.debug(f"[SLACK_TRIGGER] Skipping workflow {workflow.id}: event_type mismatch ({event_type}) or is_mention={is_mention}")
                        
                    # Check for keyword matching if specified
                    if should_trigger and "keywords" in trigger_config and trigger_config["keywords"]:
                        should_trigger = False
                        keywords = trigger_config.get("keywords", [])
                        content = (message or "").lower()
                        for keyword in keywords:
                            if keyword.lower() in content:
                                should_trigger = True
                                break
                        if not should_trigger:
                            logger.debug(f"[SLACK_TRIGGER] Skipping workflow {workflow.id}: keyword mismatch")
                    
                    if should_trigger:
                        # Build input variables for workflow
                        input_vars = {
                            "slack_channel": channel,
                            "slack_user_id": slack_user_id,
                            "slack_message": message or "",
                            "slack_is_mention": is_mention,
                            "timestamp": datetime.utcnow().isoformat()
                        }
                        
                        # Execute workflow
                        logger.info(f"[SLACK_TRIGGER] Firing workflow '{workflow.name}' for user {user_id}")
                        
                        try:
                            builder = WorkflowBuilderService()
                            await builder.execute_workflow(
                                workflow_id=workflow.id,
                                user_id=user_id,
                                db=db,
                                input_data=input_vars
                            )
                        except Exception as e:
                            logger.error(f"[SLACK_TRIGGER] Failed to execute workflow {workflow.id}: {e}")
                            
            except Exception as e:
                logger.error(f"[SLACK_TRIGGER] Error checking workflows: {e}")
