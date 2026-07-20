"""Shared helpers for WhatsApp inbox list/preview formatting."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

PREVIEW_LABELS = {
    "image": "📷 Photo",
    "document": "📄 Document",
    "audio": "🎤 Voice note",
    "video": "🎥 Video",
    "location": "📍 Location",
    "sticker": "Sticker",
    "contacts": "👤 Contact",
    "interactive": "💬 Interactive",
}


def format_message_preview(
    content: Optional[str],
    message_type: Optional[str] = None,
    max_len: int = 40,
) -> str:
    """Human-readable truncated preview for conversation list."""
    text = (content or "").replace("\n", " ").strip()
    mtype = (message_type or "text").lower()
    if not text:
        return PREVIEW_LABELS.get(mtype, "[Message]")
    if mtype != "text" and len(text) > max_len:
        prefix = PREVIEW_LABELS.get(mtype, "")
        if prefix and not text.startswith(prefix):
            text = f"{prefix} {text}"
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def is_sla_breached(
    contact,
    sla_minutes: int,
    now: Optional[datetime] = None,
) -> bool:
    """True when an open conversation exceeded first-response SLA."""
    if not contact.first_inbound_at:
        return False
    if (contact.status or "open") not in ("open", "pending"):
        return False
    ref = now or datetime.utcnow()
    first = contact.first_inbound_at
    if first.tzinfo:
        first = first.replace(tzinfo=None)
    deadline = first + timedelta(minutes=max(1, sla_minutes))
    return ref > deadline


def media_proxy_url(message_id) -> str:
    return f"/api/whatsapp/messages/{message_id}/media"


def record_csat_score(contact, score: int) -> None:
    """Persist CSAT rating on contact metadata."""
    from sqlalchemy.orm.attributes import flag_modified

    meta = dict(getattr(contact, "metadata_", None) or {})
    meta["csat_score"] = score
    meta["csat_at"] = datetime.utcnow().isoformat()
    meta.pop("csat_pending", None)
    contact.metadata_ = meta
    flag_modified(contact, "metadata_")


OPT_OUT_KEYWORDS = frozenset({"stop", "unsubscribe", "opt out", "opt-out"})
OPT_IN_KEYWORDS = frozenset({"start", "subscribe"})
