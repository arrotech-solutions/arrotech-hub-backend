"""
Finalize WhatsApp order payments after M-Pesa STK (callback or poll fallback).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from .daraja_service import DarajaService
from .order_tracking_service import order_tracking_service

logger = logging.getLogger(__name__)

# Daraja STK terminal failure codes (stop polling)
_STK_TERMINAL_FAILURE_CODES = frozenset({"1032", "1037", "1", "2001", "17"})


async def finalize_order_stk_payment(
    *,
    db: AsyncSession,
    owner_user_id: str,
    order_id: str,
    whatsapp_sender: str,
    mpesa_phone: str,
    platform: str,
    storage_config: Dict[str, Any],
    is_paid: bool,
    mpesa_receipt: str = "",
    amount_paid: float = 0.0,
    currency: str = "KES",
    result_code: str = "",
    result_desc: str = "",
    checkout_request_id: str = "",
    merchant_request_id: str = "",
    payment_record: Any = None,
) -> None:
    """Send payment confirmation + PAID PDF (idempotent per order)."""
    if not order_id:
        return

    registry = order_tracking_service.get_registered_order(owner_user_id, order_id) or {}
    if is_paid and registry.get("payment_notified"):
        logger.info("[STK_PAY] Order %s already has payment_notified — skip", order_id)
        return

    owner_uuid = uuid.UUID(str(owner_user_id))
    owner_stmt = select(User).where(User.id == owner_uuid)
    owner_res = await db.execute(owner_stmt)
    owner_user = owner_res.scalar_one_or_none()
    if not owner_user:
        logger.warning("[STK_PAY] Owner user %s not found for order %s", owner_user_id, order_id)
        return

    wa_config = None
    if platform == "whatsapp" and whatsapp_sender:
        try:
            wa_config = await order_tracking_service._get_whatsapp_config(owner_user, db)
        except Exception as cfg_err:
            logger.warning("[STK_PAY] WhatsApp config failed: %s", cfg_err)

    msg_ok = (
        f"✅ Payment received for order {order_id}. "
        f"Receipt: {mpesa_receipt or 'pending'}"
        if is_paid
        else f"⚠️ Payment failed for order {order_id}. {result_desc or ''}".strip()
    )

    try:
        if platform == "whatsapp" and whatsapp_sender and wa_config:
            from .whatsapp_service import WhatsAppService

            wa = WhatsAppService()
            await wa.send_message(to_number=whatsapp_sender, message=msg_ok, config=wa_config)
        elif platform == "telegram" and whatsapp_sender:
            from .telegram_service import TelegramService

            tg = TelegramService()
            await tg.send_message(chat_id=whatsapp_sender, message=msg_ok)
    except Exception as msg_err:
        logger.warning("[STK_PAY] Failed to send payment text for %s: %s", order_id, msg_err)

    if is_paid:
        try:
            await order_tracking_service.notify_payment_received(
                user=owner_user,
                db=db,
                order_id=order_id,
                mpesa_receipt=mpesa_receipt,
                amount_paid=amount_paid,
                currency=currency,
                customer_phone=whatsapp_sender or "",
            )
        except Exception as receipt_err:
            logger.warning("[STK_PAY] PAID receipt failed for %s: %s", order_id, receipt_err)

        if payment_record and storage_config.get("provider") not in (None, "", "none"):
            try:
                from .conversational_agent_service import ConversationalAgentService

                tx_data = {
                    "order_id": order_id,
                    "transaction_id": mpesa_receipt or checkout_request_id,
                    "checkout_request_id": checkout_request_id,
                    "merchant_request_id": merchant_request_id,
                    "amount": float(amount_paid or 0),
                    "currency": currency,
                    "customer_phone": mpesa_phone or whatsapp_sender,
                    "status": "paid",
                    "result_code": result_code,
                    "result_desc": result_desc,
                    "paid_at": datetime.utcnow().isoformat(),
                }
                conv_service = ConversationalAgentService()
                await conv_service.persist_payment_transaction_to_storage(
                    transaction_data=tx_data,
                    storage_config=storage_config,
                    user=owner_user,
                    db=db,
                )
            except Exception as tx_err:
                logger.warning("[STK_PAY] Transaction storage failed for %s: %s", order_id, tx_err)


def _notify_context_from_registry(registry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "order_id": registry.get("order_id"),
        "whatsapp_sender": registry.get("whatsapp_sender") or registry.get("customer_phone"),
        "mpesa_phone": registry.get("mpesa_phone", ""),
        "platform": registry.get("platform", "whatsapp"),
        "storage_config": registry.get("storage_config") or {},
        "amount": registry.get("amount") or 0,
        "currency": registry.get("currency", "KES"),
    }


async def poll_stk_and_finalize_order_payment(
    *,
    owner_user_id: str,
    order_id: str,
    checkout_request_id: str,
    merchant_request_id: str = "",
    amount: float = 0.0,
    currency: str = "KES",
    daraja_environment: str = "sandbox",
    consumer_key: str,
    consumer_secret: str,
    short_code: str,
    passkey: str,
    poll_interval_seconds: int = 5,
    max_wait_seconds: int = 180,
    initial_delay_seconds: int = 8,
) -> None:
    """
    Poll Daraja STK query when callbacks are missing (common in dev / misconfigured URLs).
    Idempotent: exits if callback already marked payment_notified.
    """
    from ..database import get_session_maker

    if not checkout_request_id or not order_id:
        return

    logger.info(
        "[STK_PAY] Starting poll fallback order=%s checkout=%s (max %ss)",
        order_id,
        checkout_request_id,
        max_wait_seconds,
    )

    await asyncio.sleep(initial_delay_seconds)
    daraja = DarajaService(environment=daraja_environment)
    interval = max(1, poll_interval_seconds)
    polls = max(1, max_wait_seconds // interval)

    for attempt in range(polls):
        registry = order_tracking_service.get_registered_order(owner_user_id, order_id) or {}
        if registry.get("payment_notified"):
            logger.info("[STK_PAY] Poll stopped — callback already finalized order %s", order_id)
            return

        ctx = order_tracking_service.resolve_stk_notify_context(
            owner_user_id,
            checkout_request_id,
            merchant_request_id,
        ) or _notify_context_from_registry(registry)
        whatsapp_sender = ctx.get("whatsapp_sender") or ctx.get("sender_id") or ""
        mpesa_phone = ctx.get("mpesa_phone") or ""
        platform = ctx.get("platform") or "whatsapp"
        storage_config = ctx.get("storage_config") or {}
        amount_paid = float(amount or ctx.get("amount") or 0)

        try:
            query = await daraja.stk_push_query(
                checkout_request_id=checkout_request_id,
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                short_code=short_code,
                passkey=passkey,
            )
        except Exception as query_err:
            logger.warning(
                "[STK_PAY] STK query error order=%s attempt=%s: %s",
                order_id,
                attempt + 1,
                query_err,
            )
            await asyncio.sleep(interval)
            continue

        if not query.get("success"):
            logger.debug(
                "[STK_PAY] STK query not accepted order=%s: %s",
                order_id,
                query.get("error") or query.get("result_desc"),
            )
            await asyncio.sleep(interval)
            continue

        result_code = str(query.get("result_code", ""))
        result_desc = str(query.get("result_desc") or "")

        if result_code == "0":
            logger.info("[STK_PAY] Poll confirmed payment for order %s", order_id)
            session_maker = get_session_maker()
            async with session_maker() as db:
                await finalize_order_stk_payment(
                    db=db,
                    owner_user_id=owner_user_id,
                    order_id=order_id,
                    whatsapp_sender=whatsapp_sender,
                    mpesa_phone=mpesa_phone,
                    platform=platform,
                    storage_config=storage_config,
                    is_paid=True,
                    mpesa_receipt=checkout_request_id,
                    amount_paid=amount_paid,
                    currency=currency,
                    result_code=result_code,
                    result_desc=result_desc,
                    checkout_request_id=checkout_request_id,
                    merchant_request_id=merchant_request_id,
                )
            return

        if result_code in _STK_TERMINAL_FAILURE_CODES:
            logger.info(
                "[STK_PAY] Poll terminal failure order=%s code=%s desc=%s",
                order_id,
                result_code,
                result_desc,
            )
            return

        await asyncio.sleep(interval)

    logger.warning(
        "[STK_PAY] Poll timed out for order %s checkout=%s — verify Daraja callback URL",
        order_id,
        checkout_request_id,
    )


def schedule_stk_payment_poll(**kwargs: Any) -> None:
    """Fire-and-forget STK poll task."""
    try:
        asyncio.create_task(poll_stk_and_finalize_order_payment(**kwargs))
    except RuntimeError:
        logger.warning("[STK_PAY] Could not schedule poll for order %s", kwargs.get("order_id"))
