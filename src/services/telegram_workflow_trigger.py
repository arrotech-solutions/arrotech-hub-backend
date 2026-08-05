"""
Telegram Workflow Trigger Service.
Fires workflows based on Telegram events (e.g., Message received).
Tenant-scoped: only runs workflows for the connection owner that owns the bot.
"""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from ..database import get_session_maker
from ..models import Workflow, WorkflowStatus, WorkflowTriggerType
from ..services.workflow_builder_service import WorkflowBuilderService
from .whatsapp_workflow_trigger import _merge_workflow_storage_into_config

logger = logging.getLogger(__name__)


class TelegramWorkflowTrigger:
    """Service to trigger workflows based on Telegram events."""

    @classmethod
    async def has_active_conversational_agent(
        cls,
        user_id: uuid.UUID,
        db,
    ) -> bool:
        """True if user has an active Telegram workflow with a conversational_agent step."""
        from ..models import WorkflowStep

        result = await db.execute(
            select(Workflow).where(
                and_(
                    Workflow.user_id == user_id,
                    Workflow.status == WorkflowStatus.ACTIVE,
                    Workflow.trigger_type == WorkflowTriggerType.EVENT.value,
                )
            )
        )
        workflows = result.scalars().all()
        for workflow in workflows:
            trigger_config = workflow.trigger_config or {}
            if trigger_config.get("event_type") != "telegram_message_received":
                continue
            if trigger_config.get("platform") and trigger_config.get("platform") != "telegram":
                continue
            step_result = await db.execute(
                select(WorkflowStep).where(
                    and_(
                        WorkflowStep.workflow_id == workflow.id,
                        WorkflowStep.tool_name == "conversational_agent",
                    )
                )
            )
            if step_result.scalar_one_or_none():
                return True
        return False

    @classmethod
    async def on_message_received(
        cls,
        user_id: uuid.UUID,
        sender_id: str,
        chat_id: str,
        message: str,
        sender_name: str = "Customer",
        connection_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Process incoming Telegram messages and route them to the owner's workflows.
        """
        session_maker = get_session_maker()
        async with session_maker() as db:
            try:
                session_key = ""
                try:
                    from .conversation_context_manager import context_manager

                    session = await context_manager.get_or_create_session(
                        platform="telegram",
                        owner_user_id=str(user_id),
                        sender_id=str(chat_id),
                        metadata={
                            "sender_id": sender_id,
                            "chat_id": chat_id,
                            "sender_name": sender_name,
                        },
                    )
                    session_key = session.session_key
                    await context_manager.add_message(session, "user", message or "")
                except Exception as ccm_err:
                    logger.warning(
                        f"[TG_TRIGGER] CCM session init failed (non-blocking): {ccm_err}"
                    )

                result = await db.execute(
                    select(Workflow)
                    .options(selectinload(Workflow.steps))
                    .where(
                        and_(
                            Workflow.user_id == user_id,
                            Workflow.status == WorkflowStatus.ACTIVE,
                            Workflow.trigger_type == WorkflowTriggerType.EVENT.value,
                        )
                    )
                )
                workflows = result.scalars().all()

                if session_key:
                    try:
                        from ..config import settings

                        ttl_hours = int(
                            getattr(settings, "AGENT_HUMAN_HANDOFF_TTL_HOURS", 24) or 0
                        )
                        for wf in workflows:
                            tc = wf.trigger_config or {}
                            if tc.get("event_type") != "telegram_message_received":
                                continue
                            cfg = (wf.variables or {}).get("config") or {}
                            if cfg.get("human_handoff_ttl_hours") is not None:
                                try:
                                    ttl_hours = int(cfg["human_handoff_ttl_hours"])
                                except (TypeError, ValueError):
                                    pass
                                break
                        if ttl_hours > 0:
                            await context_manager.maybe_expire_human_handoff(
                                session_key, ttl_hours * 3600
                            )
                    except Exception as handoff_err:
                        logger.warning(
                            f"[TG_TRIGGER] Handoff TTL check failed: {handoff_err}"
                        )

                def _has_conversational_agent(wf: Workflow) -> bool:
                    return any(
                        s.tool_name == "conversational_agent" for s in (wf.steps or [])
                    )

                matched: List[Workflow] = []
                for workflow in workflows:
                    trigger_config = workflow.trigger_config or {}
                    event_type = (
                        trigger_config.get("event_type")
                        or trigger_config.get("trigger")
                        or ""
                    )
                    platform = trigger_config.get("platform", "")
                    if platform and platform != "telegram":
                        continue
                    if event_type != "telegram_message_received":
                        continue

                    should_trigger = True
                    keywords = trigger_config.get("keywords") or []
                    if keywords:
                        should_trigger = False
                        content = (message or "").lower()
                        for keyword in keywords:
                            if str(keyword).lower() in content:
                                should_trigger = True
                                break
                    if should_trigger:
                        matched.append(workflow)

                if not matched:
                    logger.debug(
                        "[TG_TRIGGER] No matching Telegram workflows for user %s",
                        user_id,
                    )
                    return

                preferred = next(
                    (w for w in matched if _has_conversational_agent(w)),
                    matched[0],
                )
                if len(matched) > 1:
                    logger.warning(
                        "[TG_TRIGGER] %s telegram_message_received workflows matched; "
                        "running only '%s'",
                        len(matched),
                        preferred.name,
                    )

                # Typing indicator with the owner's bot token
                try:
                    from .telegram_service import TelegramService

                    tg_svc = TelegramService()
                    await tg_svc.send_chat_action(
                        chat_id=chat_id,
                        action="typing",
                        config=connection_config or {},
                    )
                except Exception as e:
                    logger.error(f"[TG_TRIGGER] Failed to send typing indicator: {e}")

                wf_config = dict((preferred.variables or {}).get("config", {}) or {})
                wf_config = _merge_workflow_storage_into_config(
                    wf_config, preferred.variables
                )
                # Never treat Telegram chat_id as a phone number for M-Pesa/orders
                if "customer_phone" in wf_config and str(
                    wf_config.get("customer_phone")
                ) == str(chat_id):
                    wf_config.pop("customer_phone", None)
                wf_config.setdefault("customer_name", sender_name or "Customer")
                wf_config.setdefault("customer_telegram_chat_id", chat_id)
                wf_config.setdefault("platform", "telegram")
                if connection_config and connection_config.get("notify_chat_id"):
                    wf_config.setdefault(
                        "business_telegram_chat_id",
                        connection_config.get("notify_chat_id"),
                    )

                input_vars = {
                    "telegram_message": message or "",
                    "sender_id": sender_id,
                    "chat_id": chat_id,
                    "sender_name": sender_name,
                    "timestamp": datetime.utcnow().isoformat(),
                    "session_key": session_key,
                    "platform": "telegram",
                    "config": wf_config,
                }

                logger.info(
                    "[TG_TRIGGER] Firing workflow '%s' for user %s chat %s",
                    preferred.name,
                    user_id,
                    chat_id,
                )
                try:
                    builder = WorkflowBuilderService()
                    await builder.execute_workflow(
                        workflow_id=preferred.id,
                        user_id=user_id,
                        db=db,
                        input_data=input_vars,
                        trigger_type="telegram_message_received",
                    )
                except Exception as e:
                    logger.error(
                        f"[TG_TRIGGER] Failed to execute workflow {preferred.id}: {e}"
                    )

            except Exception as e:
                logger.error(
                    f"[TG_TRIGGER] Error processing workflows: {e}", exc_info=True
                )
