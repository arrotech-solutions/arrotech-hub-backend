"""
Deterministic cart command handling for WhatsApp ordering.

Handles view/clear/checkout/reset/remove/quantity without waiting on the LLM,
and sends the customer reply directly via the WhatsApp API.
"""

import logging
import uuid
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Connection, WhatsAppContact
from .conversation_context_manager import context_manager, _build_session_key
from .whatsapp_ordering_helpers import (
    cart_cleared_message,
    cart_item_removed_message,
    cart_quantity_updated_message,
    format_cart_summary,
    match_cart_command,
    parse_remove_item_name,
    parse_set_quantity_message,
    cart_action_buttons,
)
from .whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)


async def _get_whatsapp_config(db: AsyncSession, user_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    result = await db.execute(
        select(Connection).filter(
            Connection.user_id == user_id,
            Connection.platform == "whatsapp",
            Connection.status == "active",
        )
    )
    conn = result.scalar_one_or_none()
    if not conn or not conn.config:
        return None
    cfg = conn.config
    if not cfg.get("access_token") or not cfg.get("phone_number_id"):
        return None
    return cfg


async def send_customer_whatsapp_text(
    db: AsyncSession,
    user_id: uuid.UUID,
    contact: WhatsAppContact,
    text: str,
    with_cart_buttons: bool = False,
    button_body: Optional[str] = None,
) -> bool:
    """Send a text (and optional cart buttons) to the customer. Returns True if sent."""
    if not text or not text.strip():
        return False
    config = await _get_whatsapp_config(db, user_id)
    if not config:
        logger.warning("[WA_CART] No WhatsApp config — cannot send reply")
        return False

    wa = WhatsAppService()
    result = await wa.send_message(
        contact.phone_number,
        text,
        config={
            "access_token": config.get("access_token"),
            "phone_number_id": config.get("phone_number_id"),
        },
    )
    if not result.get("success"):
        logger.warning(f"[WA_CART] send_message failed: {result}")
        return False

    if with_cart_buttons:
        await wa.send_quick_reply_buttons(
            to_number=contact.phone_number,
            body_text=(button_body or "What would you like to do next?")[:1024],
            buttons=cart_action_buttons(), # TODO pass catalog_word
            config={
                "access_token": config.get("access_token"),
                "phone_number_id": config.get("phone_number_id"),
            },
        )
    return True


async def build_cart_command_reply(
    command: str,
    message_text: str,
    session_key: str,
    currency: str = "KES",
    business_name: str = "Our Business",
    catalog_word: str = "menu",
    reset_intro: str = "what would you like today?",
) -> Tuple[str, bool]:
    """
    Execute cart command against CCM.
    Returns (reply_text, with_cart_buttons).
    """
    if command == "clear":
        await context_manager.clear_cart(session_key)
        return cart_cleared_message(catalog_word), True

    if command == "view":
        session = await context_manager.get_session_by_key(session_key)
        cart = context_manager.get_cart(session) if session else []
        return format_cart_summary(cart, currency, catalog_word), bool(cart)

    if command == "checkout":
        session = await context_manager.get_session_by_key(session_key)
        cart = context_manager.get_cart(session) if session else []
        if not cart:
            return (
                "Your cart is empty right now. 🛒\n"
                f"Browse the {catalog_word} and tap *Add to Cart* on something you like!",
                True,
            )
        summary = format_cart_summary(cart, currency, catalog_word)
        return (
            f"{summary}\n\n"
            "Great! To checkout, please share:\n"
            "1️⃣ Your name\n"
            "2️⃣ Delivery or pickup?\n"
            "(I'll use your WhatsApp number for contact.)",
            True,
        )

    if command == "reset":
        session = await context_manager.get_session_by_key(session_key)
        if session:
            await context_manager.clear_session(session)
        return (
            f"🔄 Fresh start! Your cart and chat history are cleared.\n\n"
            f"Welcome back to *{business_name}* — {reset_intro}",
            True,
        )

    if command == "remove":
        name = parse_remove_item_name(message_text)
        cart, removed, removed_name = await context_manager.remove_cart_item(
            session_key, product_name=name
        )
        if removed:
            reply = (
                f"{cart_item_removed_message(removed_name)}\n\n"
                f"{format_cart_summary(cart, currency, catalog_word)}"
            )
        else:
            reply = (
                f"I couldn't find *{name}* in your cart.\n\n"
                f"{format_cart_summary(cart, currency, catalog_word)}"
            )
        return reply, True

    if command == "set_quantity":
        name, qty = parse_set_quantity_message(message_text)
        if name is None or qty is None:
            return (
                "To change quantity, say e.g. *change pilau to 2* or *2 chicken stew*.",
                True,
            )
        cart, ok, item_name, _key = await context_manager.set_cart_item_quantity(
            session_key, qty, product_name=name
        )
        if ok:
            reply = (
                f"{cart_quantity_updated_message(item_name, qty)}\n\n"
                f"{format_cart_summary(cart, currency, catalog_word)}"
            )
        else:
            reply = (
                f"I couldn't find *{name}* in your cart.\n\n"
                f"{format_cart_summary(cart, currency, catalog_word)}"
            )
        return reply, True

    return "", False


async def try_handle_cart_command(
    db: AsyncSession,
    user_id: uuid.UUID,
    contact: WhatsAppContact,
    message_text: str,
    business_name: str = "Our Business",
    currency: str = "KES",
    order_type: str = "general",
) -> bool:
    """
    If message is a cart/reset command, reply immediately on WhatsApp.
    Returns True if handled (caller should skip workflow to avoid duplicate replies).
    """
    cmd = match_cart_command(message_text or "")
    if not cmd:
        return False

    session_key = _build_session_key("whatsapp", str(user_id), contact.phone_number)

    try:
        catalog_word = "menu" if order_type == "food" else "catalog"
        reset_intro = "what would you like today?"
        if order_type in ("retail", "clothing"):
            reset_intro = "what are you looking for today?"
        elif order_type != "food":
            reset_intro = "how can we help you today?"
        reply, with_buttons = await build_cart_command_reply(
            cmd, message_text or "", session_key, currency, business_name, catalog_word, reset_intro
        )
        if not reply:
            return False

        sent = await send_customer_whatsapp_text(
            db, user_id, contact, reply, with_cart_buttons=with_buttons
        )
        if sent:
            session = await context_manager.get_session_by_key(session_key)
            if session:
                await context_manager.add_message(session, "assistant", reply)
            logger.info(f"[WA_CART] Handled command '{cmd}' for {contact.phone_number}")
            return True

        logger.warning(f"[WA_CART] Command '{cmd}' matched but WhatsApp send failed")
        return False
    except Exception as e:
        logger.error(f"[WA_CART] Error handling cart command '{cmd}': {e}", exc_info=True)
        return False
