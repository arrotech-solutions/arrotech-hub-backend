"""WhatsApp text when a merchant changes a commerce order status in Hub.

The caller persists the new status first. Send failures are logged and
never raised, so the status update stays committed.
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Connection, ConnectionStatus, MessagingConversation
from .whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

_LANG_KEYS = (
    "preferred_language",
    "language",
    "lang",
    "customer_language",
    "customer_lang",
)

_SW_STATUS = {
    "pending": "inasubiri",
    "confirmed": "imethibitishwa",
    "preparing": "inaandaliwa",
    "ready": "tayari",
    "shipped": "imesafirishwa",
    "out_for_delivery": "inaletwa",
    "delivered": "imewasilishwa",
    "cancelled": "imeghairiwa",
    "refunded": "imerudishwa",
}


def _as_uuid(value) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _normalize_lang(value) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw.startswith("sw") or raw in {"swahili", "kiswahili"}:
        return "sw"
    if raw.startswith("en") or raw == "english":
        return "en"
    return None


def _lang_from_mapping(data) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in _LANG_KEYS:
        lang = _normalize_lang(data.get(key))
        if lang:
            return lang
    customer = data.get("customer")
    if isinstance(customer, dict):
        for key in _LANG_KEYS:
            lang = _normalize_lang(customer.get(key))
            if lang:
                return lang
    return None


def status_message(order_id: str, status: str, lang: str) -> str:
    """Customer text that always includes the order id and status token."""
    token = (status or "").strip().lower().replace(" ", "_")
    if lang == "sw":
        label = _SW_STATUS.get(token, token.replace("_", " "))
        return f"Oda yako *{order_id}* sasa ni {label} ({token})."
    return f"Your order *{order_id}* is now {token}."


def phones_match(customer_phone: str, sender_id: str) -> bool:
    """True when both numbers share the same last 9 digits."""
    phone = _digits(customer_phone)
    sender = _digits(sender_id)
    if not phone or not sender:
        return False
    if phone == sender:
        return True
    phone_tail = phone[-9:] if len(phone) >= 9 else phone
    sender_tail = sender[-9:] if len(sender) >= 9 else sender
    return phone_tail == sender_tail


async def _customer_lang(db: AsyncSession, user_id, order) -> str:
    snapshot = getattr(order, "raw_snapshot", None)
    lang = _lang_from_mapping(snapshot)
    if lang:
        return lang

    phone = getattr(order, "customer_phone", None) or ""
    if not _digits(phone):
        return "en"

    result = await db.execute(
        select(MessagingConversation).where(
            MessagingConversation.owner_user_id == _as_uuid(user_id),
            MessagingConversation.platform == "whatsapp",
        )
    )
    for row in result.scalars().all():
        if not phones_match(phone, row.sender_id or ""):
            continue
        found = _lang_from_mapping(row.metadata_)
        if found:
            return found
    return "en"


async def _whatsapp_config(db: AsyncSession, user_id) -> dict | None:
    result = await db.execute(
        select(Connection).where(
            Connection.user_id == _as_uuid(user_id),
            Connection.platform == "whatsapp",
            Connection.status == ConnectionStatus.ACTIVE,
        )
    )
    connection = result.scalars().first()
    if connection is None or not isinstance(connection.config, dict):
        return None
    token = connection.config.get("access_token")
    phone_number_id = connection.config.get("phone_number_id")
    if not token or not phone_number_id:
        return None
    config = {"access_token": token, "phone_number_id": phone_number_id}
    base_url = connection.config.get("base_url")
    if base_url:
        config["base_url"] = base_url
    return config


async def notify_customer_text(
    db,
    user_id,
    phone: str,
    message: str,
    *,
    context: str = "",
) -> None:
    """Send stored customer copy on the merchant WhatsApp connection.

    Failures are logged and never raised, so a refund row stays committed.
    """
    try:
        text = (message or "").strip()
        destination = (phone or "").strip()
        if not text or not destination:
            logger.warning(
                "commerce customer notify skipped; missing phone or message %s",
                context,
            )
            return
        config = await _whatsapp_config(db, user_id)
        if config is None:
            logger.warning(
                "commerce customer notify skipped; WhatsApp not connected %s",
                context,
            )
            return
        result = await WhatsAppService().send_message(destination, text, config=config)
        if not isinstance(result, dict) or not result.get("success"):
            error = result.get("error") if isinstance(result, dict) else result
            logger.warning(
                "commerce customer notify failed %s error=%s",
                context,
                error,
            )
    except Exception:
        logger.exception("commerce customer notify failed %s", context)


async def notify_order_status_change(db, user_id, order, previous_status: str) -> None:
    """Send an EN/SW WhatsApp text. Failures are logged and not raised."""
    order_id = getattr(order, "external_order_id", None)
    try:
        new_status = (getattr(order, "status", None) or "").strip().lower().replace(" ", "_")
        previous = (previous_status or "").strip().lower().replace(" ", "_")
        if not new_status or new_status == previous:
            return

        phone = (getattr(order, "customer_phone", None) or "").strip()
        if not phone or not order_id:
            logger.warning(
                "commerce status notify skipped; missing phone or order id user=%s order=%s",
                user_id,
                order_id,
            )
            return

        config = await _whatsapp_config(db, user_id)
        if config is None:
            logger.warning(
                "commerce status notify skipped; WhatsApp not connected user=%s order=%s",
                user_id,
                order_id,
            )
            return

        lang = await _customer_lang(db, user_id, order)
        message = status_message(str(order_id), new_status, lang)
        result = await WhatsAppService().send_message(phone, message, config=config)
        if not isinstance(result, dict) or not result.get("success"):
            error = result.get("error") if isinstance(result, dict) else result
            logger.warning(
                "commerce status notify failed user=%s order=%s status=%s error=%s",
                user_id,
                order_id,
                new_status,
                error,
            )
    except Exception:
        logger.exception(
            "commerce status notify failed user=%s order=%s",
            user_id,
            order_id,
        )
