"""
Ask AI tool confirmation (HITL) + audit helpers.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Set, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from src.models import ToolAuditLog, ToolProposal

logger = logging.getLogger(__name__)

# Tools / operations that must be proposed before execution when feature flag is on
CONFIRM_RULES: Dict[str, Set[str]] = {
    "whatsapp_send_message": {"*", "send_message"},
    "whatsapp_messaging": {"send_message", "send_media", "send_location", "*"},
    "whatsapp_templates": {"send_template", "create_template", "*"},
    "google_workspace_gmail": {
        "send_email", "send", "reply", "forward", "compose", "delete_email",
        "create_draft", "create_label", "apply_label", "mark_as_read",
        "list_drafts", "get_draft", "update_draft",
    },
    "google_workspace_calendar": {
        "create", "create_event", "update", "update_event", "delete", "delete_event", "create_meeting",
    },
    "google_workspace_drive": {"upload_file", "delete_file", "share_file", "move_file", "create_folder"},
    "google_workspace_sheets": {
        "write_range", "append_rows", "clear_range", "batch_update", "create_spreadsheet",
        "update_spreadsheet_properties",
    },
    "google_workspace_docs": {
        "create_document", "insert_text", "append_text", "replace_text", "batch_update",
        "format_text", "insert_table",
    },
    # Broader messaging / CRM / tasks (Phase 3 expansion)
    "slack_send_message": {"*", "send_message"},
    "outlook_send_email": {"*", "send_email", "send"},
    "outlook_email_management": {"send_email", "send", "reply", "forward"},
    "telegram_send_message": {"*"},
    "hubspot_contact_operations": {"create", "update"},
    "jira_create_issue": {"*", "create", "create_issue"},
    "trello_create_card": {"*", "create", "create_card"},
    "asana_create_task": {"*", "create", "create_task"},
    "notion_create_page": {"*", "create", "create_page"},
}

PROPOSAL_TTL_MINUTES = 15


def args_hash(arguments: Optional[Dict[str, Any]]) -> str:
    raw = json.dumps(arguments or {}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sanitize_args_preview(arguments: Optional[Dict[str, Any]], max_len: int = 500) -> Dict[str, Any]:
    """Strip secrets and truncate large values for audit storage."""
    if not arguments:
        return {}
    out: Dict[str, Any] = {}
    secret_keys = {"access_token", "refresh_token", "token", "password", "secret", "api_key"}
    for k, v in arguments.items():
        if k.lower() in secret_keys or "token" in k.lower():
            out[k] = "[redacted]"
            continue
        s = str(v)
        out[k] = s[:max_len] + ("…" if len(s) > max_len else "")
    return out


def needs_confirmation(tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> bool:
    """Return True if this tool/op should go through HITL proposal flow."""
    from src.config import settings

    if not getattr(settings, "ASK_AI_WA_GW_V1", True):
        return False
    if not getattr(settings, "ASK_AI_REQUIRE_CONFIRM", True):
        return False

    rules = CONFIRM_RULES.get(tool_name)
    if not rules:
        if tool_name.startswith("whatsapp_") and tool_name not in (
            "whatsapp_inbox",
            "whatsapp_agent_control",
            "whatsapp_account_info",
        ):
            op = (arguments or {}).get("operation") or (arguments or {}).get("action") or "send_message"
            return str(op).lower() in {"send_message", "send_template", "send_media", "send_location"}
        return False

    op = str((arguments or {}).get("operation") or (arguments or {}).get("action") or "").lower()
    if tool_name == "whatsapp_send_message":
        return True
    if tool_name in ("slack_send_message", "telegram_send_message", "outlook_send_email", "jira_create_issue", "trello_create_card", "asana_create_task", "notion_create_page"):
        return True
    if tool_name == "whatsapp_templates":
        # Default without template_name is list — do not confirm
        if not op:
            return bool((arguments or {}).get("template_name") or (arguments or {}).get("to_number"))
        return op in {"send_template", "create_template"}
    if tool_name == "whatsapp_messaging":
        if not op:
            return True  # defaults to send_message
        return op in {"send_message", "send_media", "send_location"}
    if "*" in rules:
        return True
    if not op:
        return False
    return op in rules


def summarize_proposal(tool_name: str, arguments: Dict[str, Any]) -> str:
    args = arguments or {}
    if tool_name in ("whatsapp_send_message", "whatsapp_messaging"):
        to = args.get("to_number") or args.get("to") or "?"
        msg = (args.get("message") or "")[:120]
        return f"Send WhatsApp message to {to}: {msg}"
    if tool_name == "whatsapp_templates":
        return f"Send WhatsApp template '{args.get('template_name')}' to {args.get('to_number')}"
    if tool_name == "google_workspace_gmail":
        return f"Gmail {args.get('operation') or args.get('action') or 'send'}: to={args.get('to') or args.get('to_email')}"
    if tool_name == "google_workspace_calendar":
        return f"Calendar {args.get('operation') or args.get('action')}: {args.get('summary') or args.get('title') or ''}"
    return f"Execute {tool_name} with {len(args)} argument(s)"


async def create_proposal(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    tool_name: str,
    arguments: Dict[str, Any],
    conversation_id: Optional[uuid.UUID] = None,
) -> ToolProposal:
    proposal = ToolProposal(
        id=uuid.uuid4(),
        user_id=user_id,
        conversation_id=conversation_id,
        tool_name=tool_name,
        arguments=arguments or {},
        summary=summarize_proposal(tool_name, arguments or {}),
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=PROPOSAL_TTL_MINUTES),
    )
    db.add(proposal)
    await db.commit()
    await db.refresh(proposal)
    return proposal


async def get_proposal(db: AsyncSession, proposal_id: uuid.UUID, user_id: uuid.UUID) -> Optional[ToolProposal]:
    from sqlalchemy import select

    result = await db.execute(
        select(ToolProposal).where(ToolProposal.id == proposal_id, ToolProposal.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def record_tool_audit(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    tool_name: str,
    arguments: Optional[Dict[str, Any]],
    success: bool,
    error: Optional[str] = None,
    latency_ms: Optional[int] = None,
    conversation_id: Optional[uuid.UUID] = None,
    confirmed: Optional[bool] = None,
) -> None:
    try:
        entry = ToolAuditLog(
            id=uuid.uuid4(),
            user_id=user_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            args_hash=args_hash(arguments),
            arguments_preview=sanitize_args_preview(arguments),
            success=success,
            error=(error or "")[:2000] if error else None,
            latency_ms=latency_ms,
            confirmed=confirmed,
        )
        db.add(entry)
        await db.commit()
    except Exception as e:
        logger.debug("tool audit write failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
