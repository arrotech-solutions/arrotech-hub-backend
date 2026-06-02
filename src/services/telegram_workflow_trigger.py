"""
Telegram Workflow Trigger Service.
Fires workflows based on Telegram events (e.g., Message received).
"""
import logging
from datetime import datetime
from sqlalchemy import select, and_
from ..database import get_session_maker
from ..models import Workflow, WorkflowStatus, WorkflowTriggerType, Connection
from ..services.workflow_builder_service import WorkflowBuilderService

logger = logging.getLogger(__name__)

class TelegramWorkflowTrigger:
    """Service to trigger workflows based on Telegram events."""

    @classmethod
    async def on_message_received(
        cls,
        sender_id: str,
        chat_id: str,
        message: str
    ):
        """
        Process incoming Telegram messages and route them to relevant workflows.
        Since Telegram connects differently (usually 1 bot per system or per user),
        we check all active workflows listening for Telegram events and fire them.
        """
        session_maker = get_session_maker()
        async with session_maker() as db:
            try:
                # Find all active workflows listening for telegram events
                workflow_stmt = select(Workflow).where(
                    and_(
                        Workflow.status == WorkflowStatus.ACTIVE,
                        Workflow.trigger_type == WorkflowTriggerType.EVENT.value
                    )
                )
                workflow_res = await db.execute(workflow_stmt)
                workflows = workflow_res.scalars().all()
                
                workflows_triggered = 0
                
                for workflow in workflows:
                    trigger_config = workflow.trigger_config or {}
                    event_type = trigger_config.get("event_type") or trigger_config.get("trigger", "")
                    platform = trigger_config.get("platform", "")
                    
                    if platform != "telegram":
                        continue
                        
                    should_trigger = False
                    
                    # Check if event matches
                    if event_type in ["telegram_message_received"]:
                        should_trigger = True
                        
                    # Evaluate custom keyword filters
                    if should_trigger and "keywords" in trigger_config and trigger_config["keywords"]:
                        should_trigger = False
                        keywords = trigger_config.get("keywords", [])
                        content = (message or "").lower()
                        for keyword in keywords:
                            if keyword.lower() in content:
                                should_trigger = True
                                break
                    
                    if should_trigger:
                        workflows_triggered += 1
                        
                        # Fetch Telegram connection to get the correct bot token
                        try:
                            conn_stmt = select(Connection).where(
                                and_(
                                    Connection.user_id == workflow.user_id,
                                    Connection.platform == "telegram",
                                    Connection.status == "active"
                                )
                            )
                            conn_res = await db.execute(conn_stmt)
                            connection = conn_res.scalar_one_or_none()
                            
                            if connection:
                                from ..services.telegram_service import TelegramService
                                tg_svc = TelegramService()
                                await tg_svc.send_chat_action(
                                    chat_id=chat_id,
                                    action="typing",
                                    config=connection.config
                                )
                        except Exception as e:
                            logger.error(f"[TG_TRIGGER] Failed to send typing indicator: {e}")
                        
                        # ── CCM: Persist incoming message to conversation session ──
                        session_key = ""
                        try:
                            from .conversation_context_manager import context_manager

                            session = await context_manager.get_or_create_session(
                                platform="telegram",
                                owner_user_id=str(workflow.user_id),
                                sender_id=str(chat_id),
                                metadata={
                                    "sender_id": sender_id,
                                    "chat_id": chat_id,
                                }
                            )
                            session_key = session.session_key

                            # Add incoming message to history
                            await context_manager.add_message(
                                session, "user", message or ""
                            )
                        except Exception as ccm_err:
                            logger.warning(f"[TG_TRIGGER] CCM session init failed (non-blocking): {ccm_err}")

                        if session_key:
                            try:
                                from ..config import settings

                                ttl_hours = int(
                                    getattr(settings, "AGENT_HUMAN_HANDOFF_TTL_HOURS", 24) or 0
                                )
                                if ttl_hours > 0:
                                    await context_manager.maybe_expire_human_handoff(
                                        session_key, ttl_hours * 3600
                                    )
                                if await context_manager.is_human_handoff_active(session_key):
                                    logger.info(
                                        "[TG_TRIGGER] Human handoff active — skipping AI workflow"
                                    )
                                    continue
                            except Exception as handoff_err:
                                logger.warning(
                                    f"[TG_TRIGGER] Handoff check failed: {handoff_err}"
                                )

                        input_vars = {
                            "telegram_message": message or "",
                            "sender_id": sender_id,
                            "chat_id": chat_id,
                            "timestamp": datetime.utcnow().isoformat(),
                            # ── CCM: Inject session key for context-aware tools ──
                            "session_key": session_key,
                            "platform": "telegram",
                            # ── Inject workflow-level config for agent tools ──
                            "config": (workflow.variables or {}).get("config", {}),
                        }
                        
                        logger.info(f"[TG_TRIGGER] Firing workflow '{workflow.name}' for user {workflow.user_id}")
                        try:
                            # Start workflow
                            builder = WorkflowBuilderService()
                            await builder.execute_workflow(
                                workflow_id=workflow.id,
                                user_id=workflow.user_id,
                                db=db,
                                input_data=input_vars
                            )
                        except Exception as e:
                            logger.error(f"[TG_TRIGGER] Failed to execute workflow {workflow.id}: {e}")
                            
                if workflows_triggered == 0:
                    logger.debug(f"[TG_TRIGGER] Payload dropped: No matching Telegram workflows for event `telegram_message_received`.")
                    
            except Exception as e:
                logger.error(f"[TG_TRIGGER] Error processing workflows: {e}", exc_info=True)
