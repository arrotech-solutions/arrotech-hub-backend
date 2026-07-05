"""Real-time WebSocket events for the WhatsApp dashboard inbox."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def emit_whatsapp_inbox_event(
    user_id: uuid.UUID,
    event_type: str,
    data: Dict[str, Any],
) -> None:
    """Best-effort push to connected dashboard clients."""
    try:
        from .websocket_manager import connection_manager

        await connection_manager.push_to_user(user_id, event_type, data)
    except Exception as exc:
        logger.debug("WhatsApp inbox WS emit failed: %s", exc)


async def emit_to_org_members(
    owner_user_id: uuid.UUID,
    event_type: str,
    data: Dict[str, Any],
    exclude_user_id: Optional[uuid.UUID] = None,
    db=None,
) -> None:
    """Notify org team members (for presence / collision)."""
    user_ids = {owner_user_id}
    if db is not None:
        try:
            from sqlalchemy import select
            from ..models import OrganizationMember

            result = await db.execute(
                select(OrganizationMember.user_id).where(
                    OrganizationMember.org_id.in_(
                        select(OrganizationMember.org_id).where(
                            OrganizationMember.user_id == owner_user_id
                        )
                    )
                )
            )
            for row in result.scalars().all():
                user_ids.add(row)
        except Exception:
            pass

    for uid in user_ids:
        if exclude_user_id and uid == exclude_user_id:
            continue
        await emit_whatsapp_inbox_event(uid, event_type, data)
