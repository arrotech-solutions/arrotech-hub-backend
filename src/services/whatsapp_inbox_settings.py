"""Round-robin assignment and inbox settings helpers."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import WhatsAppBusinessProfile, WhatsAppContact


def default_inbox_settings() -> Dict[str, Any]:
    return {
        "round_robin_enabled": False,
        "round_robin_agent_ids": [],
        "round_robin_index": 0,
        "sla_first_response_minutes": 5,
    }


def merge_inbox_settings(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    base = default_inbox_settings()
    if raw:
        base.update({k: v for k, v in raw.items() if v is not None})
    return base


async def get_inbox_settings(db: AsyncSession, user_id: uuid.UUID) -> Dict[str, Any]:
    from sqlalchemy import select

    result = await db.execute(
        select(WhatsAppBusinessProfile).where(WhatsAppBusinessProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    return merge_inbox_settings(profile.inbox_settings if profile else None)


async def pick_round_robin_agent(
    db: AsyncSession,
    user_id: uuid.UUID,
    profile: WhatsAppBusinessProfile,
) -> Optional[uuid.UUID]:
    settings = merge_inbox_settings(profile.inbox_settings)
    if not settings.get("round_robin_enabled"):
        return None

    agent_ids: List[str] = settings.get("round_robin_agent_ids") or []
    if not agent_ids:
        return None

    index = int(settings.get("round_robin_index") or 0) % len(agent_ids)
    next_id = uuid.UUID(agent_ids[index])
    settings["round_robin_index"] = (index + 1) % len(agent_ids)
    profile.inbox_settings = settings
    return next_id


async def maybe_auto_assign_contact(
    db: AsyncSession,
    user_id: uuid.UUID,
    contact: WhatsAppContact,
) -> bool:
    """Assign unassigned contact via round-robin if enabled."""
    if contact.assigned_to_id:
        return False

    from sqlalchemy import select

    result = await db.execute(
        select(WhatsAppBusinessProfile).where(WhatsAppBusinessProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return False

    agent_id = await pick_round_robin_agent(db, user_id, profile)
    if not agent_id:
        return False

    contact.assigned_to_id = agent_id
    return True
