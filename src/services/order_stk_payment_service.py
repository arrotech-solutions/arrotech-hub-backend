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
from .cache_service import cache_service
from .daraja_service import DarajaService
from .order_tracking_service import order_tracking_service
from .stk_result_messages import STK_TERMINAL_FAILURE_CODES, stk_customer_message

logger = logging.getLogger(__name__)


def _failure_notified_key(checkout_request_id: str) -> str:
    return f"mpesa:stk:failure_notified:{checkout_request_id}"


def _registry_payment_settled(registry: Dict[str, Any]) -> bool:
    """True when M-Pesa already succeeded. Receipt delivery is a separate flag."""
    registry = registry or {}
    if str(registry.get("payment_status") or "").lower() == "paid":
        return True
    if str(registry.get("status") or "").lower() == "paid":
        return True
    return bool(registry.get("payment_notified"))


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
    lang: str = "en",
    session_key: str = "",
) -> None:
    """Send payment confirmation or failure notice (idempotent per checkout attempt)."""
    order_id = await _resolve_hub_order_id(
        db,
        owner_user_id,
        order_id,
        checkout_request_id=checkout_request_id,
        merchant_request_id=merchant_request_id,
    )
    if not order_id:
        return

    registry = order_tracking_service.get_registered_order(owner_user_id, order_id) or {}
    resolved_session = session_key or str(registry.get("session_key") or "")

    if is_paid and registry.get("payment_notified"):
        logger.info("[STK_PAY] Order %s already has payment_notified — skip", order_id)
        return

    if not is_paid and _registry_payment_settled(registry):
        logger.info("[STK_PAY] Order %s paid — ignore late failure callback", order_id)
        return

    if not is_paid and checkout_request_id:
        if cache_service.get(_failure_notified_key(checkout_request_id)):
            logger.info(
                "[STK_PAY] Failure already notified for checkout %s — skip",
                checkout_request_id,
            )
            return

    owner_uuid = uuid.UUID(str(owner_user_id))
    owner_stmt = select(User).where(User.id == owner_uuid)
    owner_res = await db.execute(owner_stmt)
    owner_user = owner_res.scalar_one_or_none()
    if not owner_user:
        logger.warning("[STK_PAY] Owner user %s not found for order %s", owner_user_id, order_id)
        return

    if is_paid:
        await _reconcile_commerce_payment(
            db,
            owner_user_id,
            order_id,
            is_paid=True,
            mpesa_receipt=mpesa_receipt,
            session_key=resolved_session,
        )
        msg_ok = (
            f"✅ Payment received for order {order_id}. "
            f"Receipt: {mpesa_receipt or 'pending'}"
        )
        try:
            if platform == "whatsapp" and whatsapp_sender:
                wa_config = await order_tracking_service._get_whatsapp_config(owner_user, db)
                if wa_config:
                    from .whatsapp_service import WhatsAppService

                    wa = WhatsAppService()
                    await wa.send_message(
                        to_number=whatsapp_sender, message=msg_ok, config=wa_config
                    )
            elif platform == "telegram" and whatsapp_sender:
                from .telegram_service import TelegramService

                tg = TelegramService()
                await tg.send_message(chat_id=whatsapp_sender, message=msg_ok)
        except Exception as msg_err:
            logger.warning("[STK_PAY] Failed to send payment text for %s: %s", order_id, msg_err)

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

        await order_tracking_service.record_payment_attempt(
            db,
            owner_user_id=owner_user_id,
            order_id=order_id,
            status="paid",
            checkout_request_id=checkout_request_id,
            merchant_request_id=merchant_request_id,
            mpesa_phone=mpesa_phone,
            whatsapp_phone=whatsapp_sender,
            amount=amount_paid,
            currency=currency,
            result_code=result_code,
            result_desc=result_desc,
        )

        if storage_config.get("provider") not in (None, "", "none"):
            try:
                from .conversational_agent_service import ConversationalAgentService

                registry = order_tracking_service.get_registered_order(owner_user_id, order_id) or {}
                order_snapshot = dict(registry.get("order") or {})
                order_snapshot["order_id"] = order_id
                order_snapshot["whatsapp_sender"] = registry.get("whatsapp_sender", "")
                order_snapshot["mpesa_phone"] = registry.get("mpesa_phone", "")
                if amount_paid:
                    order_snapshot.setdefault("subtotal", amount_paid)

                tx_data = {
                    "order_id": order_id,
                    "transaction_id": mpesa_receipt or "",
                    "checkout_request_id": checkout_request_id,
                    "merchant_request_id": merchant_request_id,
                    "amount": float(amount_paid or 0),
                    "currency": currency,
                    "customer_phone": mpesa_phone or whatsapp_sender,
                    "mpesa_phone": mpesa_phone or whatsapp_sender,
                    "whatsapp_phone": whatsapp_sender or "",
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
                    order_data=order_snapshot,
                )
            except Exception as tx_err:
                logger.warning("[STK_PAY] Transaction storage failed for %s: %s", order_id, tx_err)
        return

    # ── Failure path ──
    await _reconcile_commerce_payment(
        db,
        owner_user_id,
        order_id,
        is_paid=False,
        session_key=resolved_session,
    )
    customer_msg = stk_customer_message(result_code, lang=lang, result_desc=result_desc)
    body = f"⚠️ Payment for order *{order_id}* was not completed.\n\n{customer_msg}"

    try:
        if platform == "whatsapp" and whatsapp_sender:
            await order_tracking_service.send_payment_retry_buttons(
                owner_user,
                db,
                order_id=order_id,
                customer_phone=whatsapp_sender,
                body_text=body,
            )
        elif platform == "telegram" and whatsapp_sender:
            from .telegram_service import TelegramService

            tg = TelegramService()
            await tg.send_message(chat_id=whatsapp_sender, message=body)
    except Exception as msg_err:
        logger.warning("[STK_PAY] Failed to send failure notice for %s: %s", order_id, msg_err)

    if checkout_request_id:
        cache_service.set(_failure_notified_key(checkout_request_id), True, expire_seconds=86400)

    failure_count = order_tracking_service.record_payment_failure_metadata(
        owner_user_id,
        order_id,
        result_code=result_code,
        result_desc=result_desc,
        checkout_request_id=checkout_request_id,
    )

    await order_tracking_service.record_payment_attempt(
        db,
        owner_user_id=owner_user_id,
        order_id=order_id,
        status="failed",
        checkout_request_id=checkout_request_id,
        merchant_request_id=merchant_request_id,
        mpesa_phone=mpesa_phone,
        whatsapp_phone=whatsapp_sender,
        amount=float(amount_paid or registry.get("amount") or 0),
        currency=currency,
        result_code=result_code,
        result_desc=result_desc,
        customer_message=customer_msg,
        failure_notified=True,
    )

    if storage_config.get("provider") not in (None, "", "none"):
        try:
            from .conversational_agent_service import ConversationalAgentService

            tx_data = {
                "order_id": order_id,
                "transaction_id": checkout_request_id or f"fail-{order_id}-{datetime.utcnow().timestamp():.0f}",
                "checkout_request_id": checkout_request_id,
                "merchant_request_id": merchant_request_id,
                "amount": float(amount_paid or registry.get("amount") or 0),
                "currency": currency,
                "customer_phone": mpesa_phone or whatsapp_sender,
                "mpesa_phone": mpesa_phone or whatsapp_sender,
                "whatsapp_phone": whatsapp_sender or "",
                "status": "failed",
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
                order_data=None,
            )
        except Exception as tx_err:
            logger.warning("[STK_PAY] Failed transaction storage for %s: %s", order_id, tx_err)

    try:
        await order_tracking_service.maybe_alert_business_payment_failures(
            owner_user,
            db,
            owner_user_id=owner_user_id,
            order_id=order_id,
            customer_phone=whatsapp_sender or mpesa_phone,
            failure_count=failure_count,
            last_reason=customer_msg,
        )
    except Exception as alert_err:
        logger.warning("[STK_PAY] Business alert failed for %s: %s", order_id, alert_err)


async def _already_paid_for_poll(owner_user_id: str, order_id: str, registry: Dict[str, Any]) -> bool:
    """True when the registry or Hub row already records a successful STK."""
    if _registry_payment_settled(registry):
        return True
    try:
        uuid.UUID(str(owner_user_id))
    except (ValueError, TypeError, AttributeError):
        return False
    from ..database import get_session_maker
    from .commerce_storage_service import CommerceStorageService

    try:
        from ..database import set_tenant_context

        session_maker = get_session_maker()
        async with session_maker() as db:
            await set_tenant_context(db, owner_user_id)
            row = await CommerceStorageService().get_order(db, owner_user_id, order_id)
    except Exception as exc:
        logger.warning("[STK_PAY] Hub paid lookup failed for %s: %s", order_id, exc)
        return False
    return row is not None and str(getattr(row, "payment_status", "") or "").lower() == "paid"


async def _retry_paid_receipt(
    *,
    owner_user_id: str,
    order_id: str,
    registry: Dict[str, Any],
    whatsapp_sender: str = "",
    amount_paid: float = 0.0,
    currency: str = "KES",
) -> None:
    """Send the receipt again. The STK charge already succeeded."""
    from ..database import get_session_maker, set_tenant_context

    session_maker = get_session_maker()
    async with session_maker() as db:
        await set_tenant_context(db, owner_user_id)
        try:
            owner_uuid = uuid.UUID(str(owner_user_id))
        except (ValueError, TypeError, AttributeError):
            return
        owner_res = await db.execute(select(User).where(User.id == owner_uuid))
        owner_user = owner_res.scalar_one_or_none()
        if not owner_user:
            return
        await order_tracking_service.notify_payment_received(
            user=owner_user,
            db=db,
            order_id=order_id,
            mpesa_receipt=str(registry.get("mpesa_receipt") or ""),
            amount_paid=float(registry.get("amount_paid") or registry.get("amount") or amount_paid or 0),
            currency=str(registry.get("currency") or currency or "KES"),
            customer_phone=whatsapp_sender or str(registry.get("whatsapp_sender") or ""),
        )


async def _resolve_hub_order_id(
    db: AsyncSession,
    owner_user_id: str,
    order_id: str,
    *,
    checkout_request_id: str = "",
    merchant_request_id: str = "",
) -> str:
    """Pick the commerce order id from the callback, Redis, STK mapping, or registry."""
    given = str(order_id or "").strip()
    try:
        uuid.UUID(str(owner_user_id))
    except (ValueError, TypeError, AttributeError):
        return given
    try:
        if given:
            from .commerce_storage_service import CommerceStorageService

            existing = await CommerceStorageService().get_order(db, owner_user_id, given)
            registry = order_tracking_service.get_registered_order(owner_user_id, given) or {}
            if existing is not None or registry.get("order") or registry.get("order_id") == given:
                return given

        ctx = order_tracking_service.resolve_stk_notify_context(
            owner_user_id,
            checkout_request_id or "",
            merchant_request_id or "",
        )
        if not ctx:
            ctx = await order_tracking_service.resolve_stk_notify_context_from_db(
                db,
                owner_user_id,
                checkout_request_id or "",
                merchant_request_id or "",
            )
        resolved = str((ctx or {}).get("order_id") or "").strip()
        if resolved:
            return resolved
    except Exception as exc:
        logger.warning("[STK_PAY] order resolve failed for %s: %s", given or checkout_request_id, exc)
    return given


def _hub_order_payload(order_id: str, registry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build a commerce_orders upsert from the tracking registry, when it has enough fields."""
    order = registry.get("order") if isinstance(registry.get("order"), dict) else {}
    phone = (
        order.get("customer_phone")
        or registry.get("whatsapp_sender")
        or registry.get("customer_phone")
        or ""
    )
    phone = str(phone or "").strip()
    if not phone:
        return None
    total = order.get("total", order.get("subtotal", registry.get("amount")))
    if total in (None, ""):
        return None
    items = order.get("items") if isinstance(order.get("items"), list) else []
    return {
        "order_id": order_id,
        "customer_name": order.get("customer_name") or "Customer",
        "customer_phone": phone,
        "delivery_method": order.get("delivery_method") or "pickup",
        "total": total,
        "items": items,
        "status": order.get("status") or "pending",
        "currency": registry.get("currency") or order.get("currency") or "KES",
    }


async def _sync_rails_payment_status(session_key: str, status: str) -> None:
    if not session_key:
        return
    from .conversation_context_manager import context_manager

    session = await context_manager.get_session_by_key(session_key)
    if session is None:
        return
    raw = session.metadata.get("commerce_rails_state") if session.metadata else None
    if not isinstance(raw, dict):
        return
    updated = dict(raw)
    updated["payment_status"] = status
    if status == "paid":
        updated["phase"] = "paid"
    elif status == "failed":
        updated["phase"] = "payment_failed"
    await context_manager.update_session_metadata(
        session_key, {"commerce_rails_state": updated}
    )


async def _reconcile_commerce_payment(
    db: AsyncSession,
    owner_user_id: str,
    order_id: str,
    *,
    is_paid: bool,
    mpesa_receipt: str = "",
    session_key: str = "",
) -> None:
    """Write STK success or failure onto the rails order, not only the sheet."""
    if not order_id or not owner_user_id:
        return
    try:
        from .commerce_storage_service import CommerceStorageService

        storage = CommerceStorageService()
        existing = await storage.get_order(db, owner_user_id, order_id)
        if existing is None and is_paid:
            registry = order_tracking_service.get_registered_order(owner_user_id, order_id) or {}
            payload = _hub_order_payload(order_id, registry)
            if payload:
                await storage.upsert_order(db, owner_user_id, payload)
                existing = await storage.get_order(db, owner_user_id, order_id)
        if existing is None:
            return
        if is_paid:
            await storage.mark_order_paid(
                db,
                owner_user_id,
                order_id,
                mpesa_receipt=mpesa_receipt or None,
            )
            status = "paid"
        elif str(existing.payment_status or "") != "paid":
            existing.payment_status = "failed"
            await db.commit()
            await db.refresh(existing)
            status = "failed"
        else:
            status = "paid"
        await _sync_rails_payment_status(session_key, status)
    except Exception as exc:
        logger.warning(
            "[STK_PAY] commerce payment reconcile failed for %s: %s",
            order_id,
            exc,
        )
        try:
            await db.rollback()
        except Exception as rollback_err:
            logger.warning(
                "[STK_PAY] rollback after reconcile failure for %s: %s",
                order_id,
                rollback_err,
            )


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
    from ..database import get_session_maker, set_tenant_context

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
        )
        if not ctx:
            session_maker = get_session_maker()
            async with session_maker() as lookup_db:
                await set_tenant_context(lookup_db, owner_user_id)
                ctx = await order_tracking_service.resolve_stk_notify_context_from_db(
                    lookup_db,
                    owner_user_id,
                    checkout_request_id,
                    merchant_request_id,
                )
        if not ctx:
            ctx = _notify_context_from_registry(registry)
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
            fresh = order_tracking_service.get_registered_order(owner_user_id, order_id) or {}
            if _registry_payment_settled(fresh) and not fresh.get("payment_notified"):
                await _retry_paid_receipt(
                    owner_user_id=owner_user_id,
                    order_id=order_id,
                    registry=fresh,
                    whatsapp_sender=whatsapp_sender,
                    amount_paid=amount_paid,
                    currency=currency,
                )
                fresh = order_tracking_service.get_registered_order(owner_user_id, order_id) or fresh
                if fresh.get("payment_notified"):
                    return
                await asyncio.sleep(interval)
                continue
            session_maker = get_session_maker()
            async with session_maker() as db:
                await set_tenant_context(db, owner_user_id)
                await finalize_order_stk_payment(
                    db=db,
                    owner_user_id=owner_user_id,
                    order_id=order_id,
                    whatsapp_sender=whatsapp_sender,
                    mpesa_phone=mpesa_phone,
                    platform=platform,
                    storage_config=storage_config,
                    is_paid=True,
                    mpesa_receipt="",
                    amount_paid=amount_paid,
                    currency=currency,
                    result_code=result_code,
                    result_desc=result_desc,
                    checkout_request_id=checkout_request_id,
                    merchant_request_id=merchant_request_id,
                )
            fresh = order_tracking_service.get_registered_order(owner_user_id, order_id) or {}
            if fresh.get("receipt_send_status") == "failed" and not fresh.get("payment_notified"):
                await asyncio.sleep(interval)
                continue
            return

        if result_code in STK_TERMINAL_FAILURE_CODES:
            logger.info(
                "[STK_PAY] Poll terminal failure order=%s code=%s desc=%s",
                order_id,
                result_code,
                result_desc,
            )
            session_maker = get_session_maker()
            async with session_maker() as db:
                await set_tenant_context(db, owner_user_id)
                await finalize_order_stk_payment(
                    db=db,
                    owner_user_id=owner_user_id,
                    order_id=order_id,
                    whatsapp_sender=whatsapp_sender,
                    mpesa_phone=mpesa_phone,
                    platform=platform,
                    storage_config=storage_config,
                    is_paid=False,
                    amount_paid=amount_paid,
                    currency=currency,
                    result_code=result_code,
                    result_desc=result_desc,
                    checkout_request_id=checkout_request_id,
                    merchant_request_id=merchant_request_id,
                )
            return

        await asyncio.sleep(interval)

    registry = order_tracking_service.get_registered_order(owner_user_id, order_id) or {}
    if await _already_paid_for_poll(owner_user_id, order_id, registry):
        logger.info(
            "[STK_PAY] Poll timeout skipped inconclusive — order %s already paid",
            order_id,
        )
        if not registry.get("payment_notified"):
            await _retry_paid_receipt(
                owner_user_id=owner_user_id,
                order_id=order_id,
                registry=registry,
                whatsapp_sender=str(
                    registry.get("whatsapp_sender") or registry.get("customer_phone") or ""
                ),
                amount_paid=float(registry.get("amount_paid") or registry.get("amount") or 0),
                currency=str(registry.get("currency") or "KES"),
            )
        return

    logger.warning(
        "[STK_PAY] Poll timed out for order %s checkout=%s — verify Daraja callback URL",
        order_id,
        checkout_request_id,
    )
    session_maker = get_session_maker()
    async with session_maker() as db:
        await set_tenant_context(db, owner_user_id)
        owner_uuid = uuid.UUID(str(owner_user_id))
        owner_res = await db.execute(select(User).where(User.id == owner_uuid))
        owner_user = owner_res.scalar_one_or_none()
        if owner_user:
            registry = order_tracking_service.get_registered_order(owner_user_id, order_id) or {}
            whatsapp_sender = (
                registry.get("whatsapp_sender") or registry.get("customer_phone") or ""
            )
            await order_tracking_service.notify_stk_payment_inconclusive(
                owner_user,
                db,
                owner_user_id=owner_user_id,
                order_id=order_id,
                whatsapp_sender=whatsapp_sender,
                checkout_request_id=checkout_request_id,
            )


def schedule_stk_payment_poll(**kwargs: Any) -> None:
    """Schedule STK poll fallback (Celery when available, else asyncio task)."""
    order_id = kwargs.get("order_id")
    try:
        from src.tasks.webhook_tasks import poll_stk_order_payment_task

        poll_stk_order_payment_task.delay(**kwargs)
        logger.info("[STK_PAY] Scheduled Celery poll for order %s", order_id)
        return
    except Exception as celery_err:
        logger.debug("[STK_PAY] Celery poll unavailable for order %s: %s", order_id, celery_err)

    try:
        asyncio.create_task(poll_stk_and_finalize_order_payment(**kwargs))
        logger.info("[STK_PAY] Scheduled asyncio poll for order %s", order_id)
    except RuntimeError:
        logger.warning("[STK_PAY] Could not schedule poll for order %s", order_id)
