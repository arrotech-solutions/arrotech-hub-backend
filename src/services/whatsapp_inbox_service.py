"""
Persist and merge WhatsApp inbox messages for the dashboard Conversations tab.

Agent/workflow outbound messages are sent via Meta API but historically were not
written to whatsapp_messages — only CCM (messaging_conversations). This module
bridges agent sends into the same store the dashboard reads.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    MessagingConversation,
    WhatsAppContact,
    WhatsAppMessage,
    WhatsAppMessageDirection,
    WhatsAppMessageStatus,
)

logger = logging.getLogger(__name__)

_SYSTEM_CCM_PREFIX = re.compile(r"^\[SYSTEM:", re.IGNORECASE)


def normalize_whatsapp_phone(phone_number: str) -> str:
    return (phone_number or "").replace("+", "").replace(" ", "").replace("-", "").strip()


def build_ccm_session_key(owner_user_id: Union[str, UUID], phone_number: str) -> str:
    phone = normalize_whatsapp_phone(phone_number)
    return f"ccm:whatsapp:{owner_user_id}:{phone}"


def _normalize_content(content: Optional[str]) -> str:
    return " ".join((content or "").split()).strip().lower()


def _is_internal_ccm_assistant_content(content: str) -> bool:
    text = (content or "").strip()
    if not text:
        return True
    if _SYSTEM_CCM_PREFIX.match(text):
        return True
    return False


async def resolve_contact(
    db: AsyncSession,
    *,
    user_id: UUID,
    phone_number: str,
    profile_name: Optional[str] = None,
    create_if_missing: bool = True,
) -> Optional[WhatsAppContact]:
    """Find contact by owner + phone; optionally create for outbound logging."""
    phone = normalize_whatsapp_phone(phone_number)
    if not phone:
        return None

    result = await db.execute(
        select(WhatsAppContact).where(
            WhatsAppContact.user_id == user_id,
            WhatsAppContact.phone_number == phone,
        )
    )
    contact = result.scalar_one_or_none()
    if contact or not create_if_missing:
        return contact

    contact = WhatsAppContact(
        user_id=user_id,
        phone_number=phone,
        profile_name=profile_name,
        name=profile_name,
        tags=[],
        message_count=0,
    )
    db.add(contact)
    await db.flush()
    return contact


async def record_outbound_message(
    db: AsyncSession,
    *,
    user_id: UUID,
    phone_number: str,
    content: Optional[str],
    message_type: str = "text",
    media_url: Optional[str] = None,
    whatsapp_message_id: Optional[str] = None,
    contact_id: Optional[UUID] = None,
    is_agent: bool = True,
    is_auto_reply: bool = False,
    commit: bool = True,
) -> Optional[WhatsAppMessage]:
    """
    Store an outbound WhatsApp message in whatsapp_messages for the dashboard inbox.
    Best-effort: failures are logged and do not break send flows.
    """
    text = (content or "").strip()
    if not text and not media_url:
        return None

    try:
        contact: Optional[WhatsAppContact] = None
        if contact_id:
            result = await db.execute(
                select(WhatsAppContact).where(
                    WhatsAppContact.id == contact_id,
                    WhatsAppContact.user_id == user_id,
                )
            )
            contact = result.scalar_one_or_none()

        if not contact:
            contact = await resolve_contact(
                db,
                user_id=user_id,
                phone_number=phone_number,
                create_if_missing=True,
            )
        if not contact:
            return None

        # Skip duplicate agent text within a short window
        if text and is_agent:
            recent = await db.execute(
                select(WhatsAppMessage)
                .where(
                    WhatsAppMessage.contact_id == contact.id,
                    WhatsAppMessage.direction == WhatsAppMessageDirection.OUTGOING,
                    WhatsAppMessage.is_agent.is_(True),
                )
                .order_by(WhatsAppMessage.created_at.desc())
                .limit(3)
            )
            for row in recent.scalars().all():
                if _normalize_content(row.content) == _normalize_content(text):
                    return row

        now = datetime.now(timezone.utc)
        message = WhatsAppMessage(
            user_id=user_id,
            contact_id=contact.id,
            direction=WhatsAppMessageDirection.OUTGOING,
            message_type=message_type or "text",
            content=text or None,
            media_url=media_url,
            whatsapp_message_id=whatsapp_message_id,
            status=WhatsAppMessageStatus.SENT,
            is_agent=is_agent,
            is_auto_reply=is_auto_reply,
            created_at=now,
        )
        db.add(message)
        contact.last_message_at = now
        contact.message_count = (contact.message_count or 0) + 1

        if commit:
            await db.commit()
            await db.refresh(message)
        else:
            await db.flush()
        return message
    except Exception as exc:
        logger.warning(
            "[WA_INBOX] Failed to record outbound for %s: %s",
            phone_number,
            exc,
            exc_info=True,
        )
        try:
            await db.rollback()
        except Exception:
            pass
        return None


def _synthetic_id(session_key: str, index: int, content: str) -> UUID:
    seed = f"{session_key}:{index}:{_normalize_content(content)}"
    return uuid.uuid5(uuid.NAMESPACE_URL, seed)


def _parse_ccm_timestamp(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _outgoing_content_exists(persisted: List[WhatsAppMessage], content: str) -> bool:
    norm = _normalize_content(content)
    if not norm:
        return False
    for msg in persisted:
        if (msg.direction or "").lower() != WhatsAppMessageDirection.OUTGOING:
            continue
        if _normalize_content(msg.content) == norm:
            return True
    return False


async def merge_ccm_assistant_messages(
    db: AsyncSession,
    *,
    user_id: UUID,
    contact: WhatsAppContact,
    persisted_messages: List[WhatsAppMessage],
) -> List[Dict[str, Any]]:
    """
    Build synthetic outgoing message dicts from CCM assistant turns not already
    present in whatsapp_messages (backfill for human handoff context).
    """
    session_key = build_ccm_session_key(user_id, contact.phone_number)
    result = await db.execute(
        select(MessagingConversation).where(
            MessagingConversation.session_key == session_key,
        )
    )
    row = result.scalar_one_or_none()
    if not row or not row.messages:
        return []

    synthetics: List[Dict[str, Any]] = []
    for idx, entry in enumerate(row.messages or []):
        if not isinstance(entry, dict):
            continue
        if entry.get("role") != "assistant":
            continue
        content = (entry.get("content") or "").strip()
        if _is_internal_ccm_assistant_content(content):
            continue
        if _outgoing_content_exists(persisted_messages, content):
            continue

        created_at = _parse_ccm_timestamp(entry.get("timestamp"))
        synthetics.append(
            {
                "id": _synthetic_id(session_key, idx, content),
                "direction": WhatsAppMessageDirection.OUTGOING,
                "message_type": "text",
                "content": content,
                "media_url": None,
                "status": WhatsAppMessageStatus.SENT,
                "is_auto_reply": False,
                "is_agent": True,
                "is_internal_note": False,
                "created_at": created_at,
                "delivered_at": None,
                "read_at": None,
                "from_ccm_backfill": True,
            }
        )
    return synthetics


def merge_message_rows_for_api(
    persisted: List[WhatsAppMessage],
    ccm_synthetics: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge DB rows and CCM synthetics, sorted chronologically."""
    rows: List[Dict[str, Any]] = []
    for msg in persisted:
        rows.append(
            {
                "id": msg.id,
                "direction": msg.direction,
                "message_type": msg.message_type,
                "content": msg.content,
                "media_url": msg.media_url,
                "status": msg.status,
                "is_auto_reply": bool(msg.is_auto_reply),
                "is_agent": bool(getattr(msg, "is_agent", False)),
                "is_internal_note": bool(msg.is_internal_note),
                "created_at": msg.created_at,
                "delivered_at": msg.delivered_at,
                "read_at": msg.read_at,
            }
        )
    rows.extend(ccm_synthetics)
    rows.sort(key=lambda r: r.get("created_at") or datetime.min.replace(tzinfo=timezone.utc))
    return rows
