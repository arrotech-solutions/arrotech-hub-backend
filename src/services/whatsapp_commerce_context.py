"""Commerce context for WhatsApp contact sidebar (cart, orders, payments)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import StkOrderMapping, StkPaymentAttempt, WhatsAppContact
from .conversation_context_manager import context_manager, _build_session_key
from .whatsapp_ordering_helpers import format_cart_summary


async def get_contact_commerce_context(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    contact: WhatsAppContact,
) -> Dict[str, Any]:
    phone = contact.phone_number
    session_key = _build_session_key("whatsapp", str(user_id), phone)

    cart: List[Dict[str, Any]] = []
    pending_order_id: Optional[str] = None
    human_handoff = "human_handoff" in (contact.tags or [])

    try:
        session = await context_manager.get_session_by_key(session_key)
        if session:
            cart = context_manager.get_cart(session) or []
            meta = session.metadata or {}
            pending_order_id = meta.get("last_order_id") or meta.get("pending_order_id")
            if context_manager.is_human_handoff(session):
                human_handoff = True
    except Exception:
        pass

    cart_summary = format_cart_summary(cart, "KES", "menu") if cart else None

    # Latest STK payment for this WhatsApp phone
    payment_status = None
    payment_order_id = None
    payment_amount = None
    can_retry_payment = False

    norm_phone = phone.replace("+", "").strip()
    pay_result = await db.execute(
        select(StkPaymentAttempt)
        .where(
            StkPaymentAttempt.user_id == user_id,
            StkPaymentAttempt.whatsapp_phone.in_([norm_phone, f"+{norm_phone}"]),
        )
        .order_by(desc(StkPaymentAttempt.created_at))
        .limit(1)
    )
    latest_payment = pay_result.scalar_one_or_none()
    if latest_payment:
        payment_status = latest_payment.status
        payment_order_id = latest_payment.order_id
        payment_amount = float(latest_payment.amount) if latest_payment.amount else None
        can_retry_payment = latest_payment.status in ("failed", "timeout", "api_error")

    if not payment_order_id:
        map_result = await db.execute(
            select(StkOrderMapping)
            .where(
                StkOrderMapping.user_id == user_id,
                StkOrderMapping.whatsapp_sender.in_([norm_phone, f"+{norm_phone}"]),
            )
            .order_by(desc(StkOrderMapping.created_at))
            .limit(1)
        )
        mapping = map_result.scalar_one_or_none()
        if mapping:
            payment_order_id = mapping.order_id

    order_id = pending_order_id or payment_order_id

    return {
        "has_cart": bool(cart),
        "cart_items": cart,
        "cart_summary": cart_summary,
        "order_id": order_id,
        "payment_status": payment_status,
        "payment_amount": payment_amount,
        "can_retry_payment": can_retry_payment,
        "human_handoff": human_handoff,
        "ai_handling": not human_handoff,
        "session_key": session_key,
    }
