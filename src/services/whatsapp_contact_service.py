"""Helpers for WhatsApp contact delete and avatar file management."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy import ColumnElement, cast, delete, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    WhatsAppBroadcastRecipient,
    WhatsAppContact,
    WhatsAppMessage,
)

logger = logging.getLogger(__name__)

BULK_DELETE_MAX = 50
ALLOWED_AVATAR_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_AVATAR_BYTES = 2 * 1024 * 1024


async def delete_contact_and_related(
    db: AsyncSession,
    contact: WhatsAppContact,
) -> None:
    """Remove messages, broadcast recipients, avatar file, then the contact."""
    if contact.avatar_url:
        _remove_avatar_file(contact.avatar_url)

    await db.execute(
        delete(WhatsAppMessage).where(WhatsAppMessage.contact_id == contact.id)
    )
    await db.execute(
        delete(WhatsAppBroadcastRecipient).where(
            WhatsAppBroadcastRecipient.contact_id == contact.id
        )
    )
    await db.delete(contact)


async def bulk_delete_contacts(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    contact_ids: List[uuid.UUID],
) -> Tuple[int, List[dict]]:
    """Delete contacts owned by user. Returns (deleted_count, failed_items)."""
    if len(contact_ids) > BULK_DELETE_MAX:
        raise ValueError(f"Cannot delete more than {BULK_DELETE_MAX} contacts at once")

    unique_ids = list(dict.fromkeys(contact_ids))
    result = await db.execute(
        select(WhatsAppContact).where(
            WhatsAppContact.user_id == user_id,
            WhatsAppContact.id.in_(unique_ids),
        )
    )
    contacts = result.scalars().all()
    found_ids = {c.id for c in contacts}
    failed = [
        {"id": str(cid), "reason": "not_found"}
        for cid in unique_ids
        if cid not in found_ids
    ]

    deleted = 0
    for contact in contacts:
        try:
            await delete_contact_and_related(db, contact)
            deleted += 1
        except Exception as exc:
            logger.warning("Failed to delete contact %s: %s", contact.id, exc)
            failed.append({"id": str(contact.id), "reason": str(exc)})

    return deleted, failed


def _remove_avatar_file(storage_path: str) -> None:
    try:
        path = Path(storage_path)
        if path.is_file():
            path.unlink()
    except OSError as exc:
        logger.warning("Could not remove avatar file %s: %s", storage_path, exc)


def avatar_storage_path(user_id: uuid.UUID, contact_id: uuid.UUID, ext: str) -> str:
    return f"whatsapp-avatars/{user_id}/{contact_id}{ext}"


def resolve_avatar_full_path(upload_dir: Path, storage_key: str) -> Path:
    return upload_dir / storage_key


def contact_has_tag(tags_column, tag: str) -> ColumnElement[bool]:
    """Match contacts whose tags JSON array includes tag (PostgreSQL JSONB containment)."""
    normalized = tag.strip()
    if not normalized:
        raise ValueError("tag must be non-empty")
    return cast(tags_column, JSONB).contains([normalized])
