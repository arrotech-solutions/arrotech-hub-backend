"""
Instagram Workflow Trigger Service.
Fires workflows based on Instagram events (e.g., DM received).
"""
import logging
from datetime import datetime
from sqlalchemy import select, and_
from ..database import get_session_maker
from ..models import Workflow, WorkflowStatus, WorkflowTriggerType, Connection, ConnectionStatus
from ..services.workflow_builder_service import WorkflowBuilderService

logger = logging.getLogger(__name__)

class InstagramWorkflowTrigger:
    """Service to trigger workflows based on Instagram events."""

    @classmethod
    async def on_message_received(
        cls,
        sender_id: str,
        recipient_id: str,
        message: str
    ):
        session_maker = get_session_maker()
        async with session_maker() as db:
            try:
                # Find all active Instagram connections to see who owns this page/app installation.
                # In the future we would map this directly to the user_id or connection via recipient_id.
                stmt = select(Connection).where(
                    Connection.platform == "instagram",
                    Connection.status == ConnectionStatus.ACTIVE
                )
                result = await db.execute(stmt)
                connections = result.scalars().all()
                
                if not connections:
                    logger.warning("No active Instagram connections found to process webhook.")
                    return
                
                # Check workflows for all users associated with an active connection
                for connection in connections:
                    user_id = connection.user_id
                    
                    workflow_stmt = select(Workflow).where(
                        and_(
                            Workflow.user_id == user_id,
                            Workflow.status == WorkflowStatus.ACTIVE,
                            Workflow.trigger_type == WorkflowTriggerType.EVENT.value
                        )
                    )
                    workflow_res = await db.execute(workflow_stmt)
                    workflows = workflow_res.scalars().all()
                    
                    for workflow in workflows:
                        trigger_config = workflow.trigger_config or {}
                        event_type = trigger_config.get("event_type") or trigger_config.get("trigger", "")
                        platform = trigger_config.get("platform", "")
                        
                        if platform != "instagram":
                            continue
                            
                        should_trigger = False
                        # Flexible match for event types
                        if event_type in ["instagram_dm_received", "instagram_message_received"]:
                            should_trigger = True
                            
                        # If keywords are set, verify keyword matches
                        if should_trigger and "keywords" in trigger_config and trigger_config["keywords"]:
                            should_trigger = False
                            keywords = trigger_config.get("keywords", [])
                            content = (message or "").lower()
                            for keyword in keywords:
                                if keyword.lower() in content:
                                    should_trigger = True
                                    break
                        
                        if should_trigger:
                            input_vars = {
                                "instagram_message": message or "",
                                "instagram_sender_id": sender_id,
                                "instagram_recipient_id": recipient_id,
                                "timestamp": datetime.utcnow().isoformat()
                            }
                            
                            logger.info(f"[IG_TRIGGER] Firing workflow '{workflow.name}' for user {user_id}")
                            try:
                                builder = WorkflowBuilderService()
                                await builder.execute_workflow(
                                    workflow_id=workflow.id,
                                    user_id=user_id,
                                    db=db,
                                    input_data=input_vars,
                                    trigger_type=WorkflowTriggerType.EVENT
                                )
                            except Exception as e:
                                logger.error(f"[IG_TRIGGER] Failed to execute workflow {workflow.id}: {e}")
                                
            except Exception as e:
                logger.error(f"[IG_TRIGGER] Error processing workflows: {e}")
