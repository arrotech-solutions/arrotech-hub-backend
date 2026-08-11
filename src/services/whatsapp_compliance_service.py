"""
WhatsApp compliance helpers: 24h messaging window, business hours, audit logging.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import WhatsAppBusinessProfile, WhatsAppContact, WhatsAppMessage, WhatsAppMessageDirection

logger = logging.getLogger(__name__)

MESSAGING_WINDOW_HOURS = 24


class WhatsAppComplianceService:
    """Meta WhatsApp compliance and inbox audit utilities."""

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    async def touch_inbound_customer_message(
        cls, contact: WhatsAppContact, db: AsyncSession
    ) -> None:
        """Record last customer message time for 24h window tracking."""
        meta = dict(contact.metadata_ or {})
        meta["last_customer_message_at"] = cls._now().isoformat()
        contact.metadata_ = meta
        await db.flush()

    @classmethod
    def is_messaging_window_open(cls, contact: WhatsAppContact) -> bool:
        """True if free-form messages are allowed (within 24h of last customer message)."""
        meta = contact.metadata_ or {}
        raw = meta.get("last_customer_message_at")
        if not raw:
            # Fallback: use last_message_at if we have no explicit inbound stamp
            if contact.last_message_at:
                try:
                    last = contact.last_message_at
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    return cls._now() - last <= timedelta(hours=MESSAGING_WINDOW_HOURS)
                except Exception:
                    pass
            return False
        try:
            last = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            return cls._now() - last <= timedelta(hours=MESSAGING_WINDOW_HOURS)
        except Exception:
            return False

    @classmethod
    async def is_business_open(cls, user_id: uuid.UUID, db: AsyncSession) -> bool:
        """Check WhatsApp business profile hours; open if no profile/hours configured."""
        result = await db.execute(
            select(WhatsAppBusinessProfile).where(WhatsAppBusinessProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if not profile or not profile.business_hours:
            return True
        from .whatsapp_auto_reply import WhatsAppAutoReplyService

        svc = WhatsAppAutoReplyService()
        return svc._is_within_business_hours(profile.business_hours)

    @classmethod
    async def log_audit_event(
        cls,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        contact_id: uuid.UUID,
        action: str,
        actor_id: Optional[uuid.UUID] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append audit event to contact metadata (no separate table migration required)."""
        result = await db.execute(
            select(WhatsAppContact).where(
                WhatsAppContact.id == contact_id,
                WhatsAppContact.user_id == user_id,
            )
        )
        contact = result.scalar_one_or_none()
        if not contact:
            return
        meta = dict(contact.metadata_ or {})
        audit_log = list(meta.get("audit_log") or [])
        audit_log.append(
            {
                "action": action,
                "actor_id": str(actor_id) if actor_id else None,
                "at": cls._now().isoformat(),
                "details": details or {},
            }
        )
        # Keep last 200 events per contact
        meta["audit_log"] = audit_log[-200:]
        contact.metadata_ = meta
        await db.flush()

    @classmethod
    async def attribute_csat(
        cls,
        contact: WhatsAppContact,
        score: int,
        agent_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Store CSAT score with resolving agent attribution."""
        meta = dict(contact.metadata_ or {})
        meta["csat_score"] = score
        meta["csat_at"] = cls._now().isoformat()
        if agent_id:
            meta["csat_agent_id"] = str(agent_id)
        elif contact.assigned_to_id:
            meta["csat_agent_id"] = str(contact.assigned_to_id)
        contact.metadata_ = meta

    @classmethod
    async def backfill_last_customer_message(
        cls, contact: WhatsAppContact, db: AsyncSession
    ) -> None:
        """Set last_customer_message_at from latest inbound message if missing."""
        if (contact.metadata_ or {}).get("last_customer_message_at"):
            return
        result = await db.execute(
            select(WhatsAppMessage)
            .where(
                WhatsAppMessage.contact_id == contact.id,
                WhatsAppMessage.direction == WhatsAppMessageDirection.INCOMING,
            )
            .order_by(WhatsAppMessage.created_at.desc())
            .limit(1)
        )
        msg = result.scalar_one_or_none()
        if msg and msg.created_at:
            meta = dict(contact.metadata_ or {})
            ts = msg.created_at.isoformat()
            meta["last_customer_message_at"] = ts
            contact.metadata_ = meta
