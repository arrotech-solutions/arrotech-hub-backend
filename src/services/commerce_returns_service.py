"""Return requests, complaint intake, and auto-approve evaluation.

``request_return`` / ``request_complaint`` stay off ``CommerceRuntime.apply``.
Task 3 locks those command names out of the cart runtime. ``apply_aftersale_command``
is the thin wrapper the agent can call later.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    CommerceComplaint,
    CommerceComplaintStatus,
    CommerceOrder,
    CommerceReturn,
    CommerceReturnStatus,
)
from .commerce_policy import away_message_if_closed, get_policy
from .commerce_refund_service import (
    CommerceReturnError,
    execute_refund,
    mark_settled_offline,
    reserved_refund_amount,
)
from .commerce_runtime.state import CommerceState
from .commerce_status_notify import notify_customer_text, phones_match

logger = logging.getLogger(__name__)

_COLLECTED_PAYMENT_STATUSES = frozenset({"paid", "collected", "settled"})
_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

SELF_SERVE_CATEGORIES = frozenset(
    {
        "where_is_my_order",
        "hours",
        "away",
        "payment_pending",
        "payment_failed",
        "start_return",
        "cancel",
    }
)

_OPEN_RETURN_STATUSES = frozenset(
    {
        CommerceReturnStatus.REQUESTED.value,
        CommerceReturnStatus.PENDING_APPROVAL.value,
        CommerceReturnStatus.APPROVED.value,
        CommerceReturnStatus.REFUND_PENDING.value,
    }
)

_TERMINAL_APPROVAL = frozenset(
    {
        CommerceReturnStatus.REFUNDED.value,
        CommerceReturnStatus.SETTLED_OFFLINE.value,
        CommerceReturnStatus.REFUND_PENDING.value,
    }
)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _money(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _as_uuid(value: Any) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _new_external_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def payment_already_collected(order: Any) -> bool:
    """True when the buyer has already paid this order."""
    status = str(_get(order, "payment_status") or "").strip().lower()
    if status in _COLLECTED_PAYMENT_STATUSES:
        return True
    receipt = str(_get(order, "mpesa_receipt") or "").strip()
    if not receipt:
        return False
    return status not in {"failed", "pending", "refunded", "refund_pending"}


def _pending_return_message(row: CommerceReturn) -> str:
    return (
        f"Your return {row.external_return_id} for KES {_money(row.amount)} "
        "is waiting for the shop to approve it. This payment is not complete."
    )


def _restock_qty(line_qty: Any, return_amount: Decimal, order_total: Decimal) -> Decimal:
    try:
        qty = Decimal(str(line_qty))
    except Exception:
        return Decimal("0")
    if not qty.is_finite() or qty <= 0:
        return Decimal("0")
    if order_total <= 0 or return_amount >= order_total:
        return qty
    share = qty * return_amount / order_total
    if qty == qty.to_integral_value():
        whole = share.to_integral_value(rounding=ROUND_HALF_UP)
        if whole < 1:
            return Decimal("0")
        return min(whole, qty)
    quantized = share.quantize(Decimal("0.01"))
    if quantized <= 0:
        return Decimal("0")
    return min(quantized, qty)


def _as_utc(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.replace("Z", "+00:00")
        value = datetime.fromisoformat(text)
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def evaluate_auto_approve(policy: dict, return_row: Any, order: Any) -> bool:
    """True only when policy allows this amount, reason, and order age.

    Over the cap, outside the window, or with auto-approve off → False.
    Missing order time cannot prove the window, so it stays False.
    """
    if not isinstance(policy, dict) or not policy.get("auto_approve_enabled"):
        return False
    amount = _money(_get(return_row, "amount"))
    cap = _money(policy.get("auto_approve_max_amount_kes"))
    if amount > cap:
        return False
    reason = str(_get(return_row, "reason_code") or "").strip()
    codes = policy.get("return_reason_codes") or []
    if codes and reason not in codes:
        return False
    try:
        window_days = int(policy.get("return_window_days"))
    except (TypeError, ValueError):
        return False
    if window_days < 0:
        return False
    created = _as_utc(_get(order, "created_at"))
    if created is None:
        return False
    age = datetime.now(timezone.utc) - created
    if age > timedelta(days=window_days):
        return False
    return True


def _snapshot(row: CommerceReturn) -> dict:
    raw = row.raw_snapshot
    return dict(raw) if isinstance(raw, dict) else {}


async def _load_order(
    db: AsyncSession,
    user_id: UUID,
    external_order_id: str,
) -> Optional[CommerceOrder]:
    result = await db.execute(
        select(CommerceOrder).where(
            CommerceOrder.user_id == user_id,
            CommerceOrder.external_order_id == external_order_id,
        )
    )
    return result.scalar_one_or_none()


async def _matching_open_return(
    db: AsyncSession,
    user_id: UUID,
    order_external_id: str,
    *,
    amount: Decimal,
    reason_code: str,
    phone: str,
) -> Optional[CommerceReturn]:
    result = await db.execute(
        select(CommerceReturn).where(
            CommerceReturn.user_id == user_id,
            CommerceReturn.order_external_id == order_external_id,
            CommerceReturn.reason_code == reason_code,
            CommerceReturn.customer_phone == phone,
            CommerceReturn.status.in_(_OPEN_RETURN_STATUSES),
        )
    )
    for row in result.scalars().all():
        if _money(row.amount) == amount:
            return row
    return None


async def get_return(
    db: AsyncSession,
    user_id: UUID,
    return_id: Any,
) -> Optional[CommerceReturn]:
    result = await db.execute(
        select(CommerceReturn).where(
            CommerceReturn.user_id == user_id,
            CommerceReturn.id == _as_uuid(return_id),
        )
    )
    return result.scalar_one_or_none()


async def list_returns(
    db: AsyncSession,
    user_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[CommerceReturn]:
    result = await db.execute(
        select(CommerceReturn)
        .where(CommerceReturn.user_id == user_id)
        .order_by(CommerceReturn.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def _require_return(
    db: AsyncSession,
    user_id: UUID,
    return_id: Any,
) -> CommerceReturn:
    row = await get_return(db, user_id, return_id)
    if row is None:
        raise CommerceReturnError("return_not_found", "Return not found")
    return row


def _require_buyer_phone(order: CommerceOrder, phone: str) -> None:
    if phones_match(order.customer_phone, phone):
        return
    raise CommerceReturnError(
        "phone_mismatch",
        "I couldn't find that order on your number.",
    )


async def _orders_for_user(db: AsyncSession, user_id: UUID) -> list[CommerceOrder]:
    result = await db.execute(
        select(CommerceOrder)
        .where(CommerceOrder.user_id == user_id)
        .order_by(CommerceOrder.created_at.desc(), CommerceOrder.id.desc())
    )
    return list(result.scalars().all())


async def find_buyer_order(
    db: AsyncSession,
    user_id: UUID,
    phone: str,
    order_external_id: Optional[str] = None,
) -> Optional[CommerceOrder]:
    """Order on this number. A supplied id still has to match the buyer phone."""
    external_id = str(order_external_id or "").strip()
    if external_id:
        order = await _load_order(db, user_id, external_id)
        if order is None or not phones_match(order.customer_phone, phone):
            return None
        return order
    for order in await _orders_for_user(db, user_id):
        if phones_match(order.customer_phone, phone):
            return order
    return None


async def _notify_return_message(db: AsyncSession, row: CommerceReturn) -> None:
    snapshot = _snapshot(row)
    await notify_customer_text(
        db,
        row.user_id,
        row.customer_phone,
        str(snapshot.get("customer_message") or ""),
        context=f"return={row.external_return_id} status={row.status}",
    )


async def _restock_return_lines(db: AsyncSession, user_id: UUID, row: CommerceReturn) -> None:
    """Put tracked units back once. Unknown or untracked lines are skipped."""
    from .commerce_runtime.db_ports import DbCatalogPort
    from .commerce_runtime.inventory import Inventory, InventoryError

    order = await _load_order(db, user_id, row.order_external_id)
    if order is None:
        logger.warning(
            "return restock skipped; order missing return=%s",
            row.external_return_id,
        )
        return
    catalog = DbCatalogPort(db, user_id)
    inventory = Inventory(catalog)
    order_total = _money(order.total)
    return_amount = _money(row.amount)
    for line in list(order.line_items or []):
        if not isinstance(line, dict):
            continue
        product_id = str(line.get("product_id") or "").strip()
        if not product_id:
            continue
        qty = _restock_qty(line.get("qty", line.get("quantity")), return_amount, order_total)
        if qty <= 0:
            continue
        try:
            await inventory.restock(product_id, qty)
        except InventoryError as exc:
            logger.warning(
                "return restock skipped product=%s return=%s code=%s",
                product_id,
                row.external_return_id,
                exc.code,
            )


def _policy_reason(policy: dict) -> str:
    codes = [str(code).strip() for code in (policy.get("return_reason_codes") or []) if str(code).strip()]
    if "changed_mind" in codes:
        return "changed_mind"
    if codes:
        return codes[0]
    return ""


def _hours_answer(policy: dict) -> str:
    closed = away_message_if_closed(policy)
    if closed:
        return closed
    hours = policy.get("business_hours") or {}
    parts = []
    if isinstance(hours, dict):
        for day in _WEEKDAYS:
            window = hours.get(day)
            if not isinstance(window, dict):
                continue
            opening = str(window.get("open") or "").strip()
            closing = str(window.get("close") or "").strip()
            if opening and closing:
                parts.append(f"{day.capitalize()} {opening}-{closing}")
    if parts:
        return "The shop is open now. Hours: " + ", ".join(parts) + "."
    return "The shop is open. Send your order here and we will help."


def _payment_recovery_answer(order: CommerceOrder) -> str:
    status = str(order.payment_status or "pending").strip().lower()
    order_id = order.external_order_id
    amount = _money(order.total)
    if status in _COLLECTED_PAYMENT_STATUSES:
        receipt = str(order.mpesa_receipt or "").strip()
        paid = f"Order {order_id} is already paid."
        if receipt:
            paid = f"{paid} Receipt: {receipt}."
        return f"{paid} There is nothing to pay again."
    if status == "failed":
        return (
            f"Order {order_id} payment failed. I can send the M-Pesa prompt again "
            f"for the same order. The amount is KES {amount}. Reply YES to pay."
        )
    return (
        f"Order {order_id} payment is {status}. "
        f"I can send the M-Pesa prompt for KES {amount}. Reply YES to pay."
    )


async def _self_serve_answer(
    db: AsyncSession,
    user_id: UUID,
    *,
    phone: str,
    category: str,
    order_external_id: Optional[str],
) -> str:
    """A real answer for categories the shop can close in chat."""
    if category in {"hours", "away"}:
        try:
            policy = await get_policy(db, user_id)
        except Exception as exc:
            logger.warning("complaint hours read failed: %s", exc)
            return "I couldn't read the shop hours just now. Please try again in a moment."
        return _hours_answer(policy if isinstance(policy, dict) else {})

    order = await find_buyer_order(db, user_id, phone, order_external_id)
    if category == "where_is_my_order":
        if order is None:
            return "I couldn't find an order on your number."
        return (
            f"Order {order.external_order_id} is {order.status}. "
            f"Payment is {order.payment_status}."
        )
    if category in {"payment_pending", "payment_failed"}:
        if order is None:
            return "I couldn't find an order on your number to recover payment."
        return _payment_recovery_answer(order)
    if category == "cancel":
        if order is None:
            return "I couldn't find an order on your number to cancel."
        return (
            f"Order {order.external_order_id} is {order.status}. "
            f"Payment is {order.payment_status}."
        )
    if category == "start_return":
        if order is None:
            return "I couldn't find an order on your number to return."
        if not payment_already_collected(order):
            return (
                f"Order {order.external_order_id} payment is {order.payment_status}. "
                "There is no collected payment to return."
            )
        return (
            f"Order {order.external_order_id} total KES {_money(order.total)} "
            "can be returned. Tell me the reason and I will start it."
        )
    return "Tell me the order and what you need help with."


async def request_return(
    db: AsyncSession,
    user_id: UUID,
    *,
    order_external_id: str,
    phone: str,
    reason_code: str,
    amount: Any,
    inventory_already_restocked: bool = False,
) -> CommerceReturn:
    """Create a return. Auto-approve pays only when policy and payout say so.

    The phone must match the buyer on the order. Payout uses that same number.
    """
    policy = await get_policy(db, user_id)
    external_id = str(order_external_id or "").strip()
    order = await _load_order(db, user_id, external_id)
    if order is None:
        raise CommerceReturnError(
            "order_not_found",
            f"Order {external_id} not found",
        )
    phone_text = str(phone or "").strip()
    if not phone_text:
        raise CommerceReturnError("invalid_phone", "Customer phone is required")
    _require_buyer_phone(order, phone_text)

    code = str(reason_code or "").strip()
    allowed = list(policy.get("return_reason_codes") or [])
    if code not in allowed:
        raise CommerceReturnError(
            "invalid_reason",
            f"Reason '{code}' is not in the shop return policy",
        )

    money = _money(amount)
    if money <= 0:
        raise CommerceReturnError("invalid_amount", "Amount must be greater than 0")
    if money > _money(order.total):
        raise CommerceReturnError(
            "amount_exceeds_order",
            "Return amount cannot exceed the order total",
        )

    existing = await _matching_open_return(
        db,
        user_id,
        external_id,
        amount=money,
        reason_code=code,
        phone=phone_text,
    )
    if existing is not None:
        if inventory_already_restocked and not _snapshot(existing).get("inventory_restocked"):
            existing_snapshot = _snapshot(existing)
            existing_snapshot["inventory_restocked"] = True
            existing_snapshot["opened_from"] = "paid_cancel"
            existing.raw_snapshot = existing_snapshot
            await db.commit()
            await db.refresh(existing)
        return existing

    reserved = await reserved_refund_amount(db, user_id, external_id)
    remaining = _money(order.total) - reserved
    if money > remaining:
        raise CommerceReturnError(
            "amount_exceeds_order",
            "Return amount exceeds the remaining refundable total",
        )

    created = _as_utc(order.created_at)
    snapshot = {
        "order_created_at": created.isoformat() if created else None,
        "order_total": str(_money(order.total)),
    }
    if inventory_already_restocked:
        snapshot["inventory_restocked"] = True
        snapshot["opened_from"] = "paid_cancel"
    row = CommerceReturn(
        user_id=user_id,
        external_return_id=_new_external_id("RET"),
        order_external_id=external_id,
        customer_phone=phone_text,
        reason_code=code,
        amount=money,
        currency=order.currency or "KES",
        status=CommerceReturnStatus.PENDING_APPROVAL.value,
        auto_approved=False,
        raw_snapshot=snapshot,
    )
    should_restock = False
    if evaluate_auto_approve(policy, row, order):
        row.auto_approved = True
        row.status = CommerceReturnStatus.APPROVED.value
        snapshot = _snapshot(row)
        snapshot["approved_by"] = "auto"
        if not snapshot.get("inventory_restocked"):
            snapshot["inventory_restocked"] = True
            should_restock = True
        row.raw_snapshot = snapshot
    else:
        snapshot = _snapshot(row)
        snapshot["customer_message"] = _pending_return_message(row)
        row.raw_snapshot = snapshot

    db.add(row)
    await db.commit()
    await db.refresh(row)
    if should_restock:
        await _restock_return_lines(db, user_id, row)
        await db.refresh(row)
    if row.auto_approved:
        await execute_refund(db, row)
        await db.refresh(row)
    return row


async def open_paid_cancel_return(
    db: AsyncSession,
    user_id: UUID,
    order_external_id: str,
    phone: str,
) -> Optional[CommerceReturn]:
    """Open the refund pipeline after a paid cancel. None when the order was not paid.

    Stock was already returned by cancel, so approval must not restock again.
    """
    external_id = str(order_external_id or "").strip()
    order = await _load_order(db, user_id, external_id)
    if order is None:
        raise CommerceReturnError("order_not_found", f"Order {external_id} not found")
    if not payment_already_collected(order):
        return None
    _require_buyer_phone(order, phone)
    policy = await get_policy(db, user_id)
    reason = _policy_reason(policy)
    if not reason:
        raise CommerceReturnError(
            "invalid_reason",
            "The shop has no return reason for this paid cancellation",
        )
    row = await request_return(
        db,
        user_id,
        order_external_id=external_id,
        phone=phone,
        reason_code=reason,
        amount=order.total,
        inventory_already_restocked=True,
    )
    if row.status == CommerceReturnStatus.REFUNDED.value:
        return row
    snapshot = _snapshot(row)
    stored = str(snapshot.get("customer_message") or "").strip()
    if "refunded" in stored.lower():
        stored = ""
    lead = f"Order {order.external_order_id} is cancelled."
    if stored and lead not in stored:
        stored = f"{lead} {stored}"
    elif not stored:
        stored = (
            f"{lead} Your return {row.external_return_id} for KES {_money(row.amount)} "
            "is waiting for the shop to pay you. This payment is not complete."
        )
    snapshot["customer_message"] = stored
    snapshot["opened_from"] = "paid_cancel"
    snapshot["inventory_restocked"] = True
    row.raw_snapshot = snapshot
    await db.commit()
    await db.refresh(row)
    return row


async def approve_return(
    db: AsyncSession,
    user_id: UUID,
    return_id: Any,
    actor_user_id: UUID,
) -> CommerceReturn:
    """Hub approve. Restocks tracked units once, then starts one refund attempt."""
    row = await _require_return(db, user_id, return_id)
    if row.status in _TERMINAL_APPROVAL:
        return row
    if row.status == CommerceReturnStatus.FAILED.value:
        return row
    if row.status == CommerceReturnStatus.DENIED.value:
        raise CommerceReturnError("already_denied", "This return was denied")

    should_restock = False
    if row.status != CommerceReturnStatus.APPROVED.value:
        snapshot = _snapshot(row)
        snapshot["approved_by"] = str(actor_user_id)
        if not snapshot.get("inventory_restocked"):
            snapshot["inventory_restocked"] = True
            should_restock = True
        claimed = await db.execute(
            update(CommerceReturn)
            .where(
                CommerceReturn.id == row.id,
                CommerceReturn.status == row.status,
            )
            .values(
                status=CommerceReturnStatus.APPROVED.value,
                raw_snapshot=snapshot,
            )
        )
        await db.commit()
        if claimed.rowcount != 1:
            await db.refresh(row)
            return row
        await db.refresh(row)
    elif not _snapshot(row).get("inventory_restocked"):
        snapshot = _snapshot(row)
        snapshot["inventory_restocked"] = True
        row.raw_snapshot = snapshot
        await db.commit()
        should_restock = True
        await db.refresh(row)

    if should_restock:
        await _restock_return_lines(db, user_id, row)
        await db.refresh(row)
    await execute_refund(db, row)
    await db.refresh(row)
    await _notify_return_message(db, row)
    return row


async def deny_return(
    db: AsyncSession,
    user_id: UUID,
    return_id: Any,
    actor_user_id: UUID,
    reason: Optional[str] = None,
) -> CommerceReturn:
    row = await _require_return(db, user_id, return_id)
    if row.status == CommerceReturnStatus.DENIED.value:
        return row
    if row.status in _TERMINAL_APPROVAL or row.status == CommerceReturnStatus.APPROVED.value:
        raise CommerceReturnError(
            "already_progressed",
            "This return can no longer be denied",
        )
    snapshot = _snapshot(row)
    snapshot["denied_by"] = str(actor_user_id)
    if reason:
        snapshot["deny_reason"] = reason
    row.raw_snapshot = snapshot
    row.status = CommerceReturnStatus.DENIED.value
    await db.commit()
    await db.refresh(row)
    return row


async def request_complaint(
    db: AsyncSession,
    user_id: UUID,
    *,
    phone: str,
    category: str,
    order_external_id: Optional[str] = None,
    detail: Optional[str] = None,
) -> tuple[CommerceComplaint, dict]:
    """Self-serve categories close without Hub. Everything else hands off."""
    phone_text = str(phone or "").strip()
    if not phone_text:
        raise CommerceReturnError("invalid_phone", "Customer phone is required")
    normalized = str(category or "").strip().lower()
    if not normalized:
        raise CommerceReturnError("invalid_category", "Complaint category is required")

    self_serve = normalized in SELF_SERVE_CATEGORIES
    status = (
        CommerceComplaintStatus.RESOLVED_SELF_SERVE.value
        if self_serve
        else CommerceComplaintStatus.HANDED_OFF.value
    )
    order_id = str(order_external_id).strip() if order_external_id else None
    answer = ""
    if self_serve:
        answer = await _self_serve_answer(
            db,
            user_id,
            phone=phone_text,
            category=normalized,
            order_external_id=order_id,
        )
    snapshot: dict[str, Any] = {}
    if detail:
        snapshot["detail"] = detail
    if answer:
        snapshot["customer_message"] = answer
    row = CommerceComplaint(
        user_id=user_id,
        external_complaint_id=_new_external_id("CMP"),
        order_external_id=order_id or None,
        customer_phone=phone_text,
        category=normalized,
        status=status,
        raw_snapshot=snapshot,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    effects: list[dict] = []
    if not self_serve:
        effects = [{"type": "handoff", "complaint_id": str(row.id)}]
    return row, {"ok": True, "effects": effects, "customer_message": answer}


async def apply_aftersale_command(
    db: AsyncSession,
    user_id: UUID,
    state: CommerceState,
    command: dict,
) -> tuple[CommerceState, dict]:
    """Handle return/complaint commands without registering them on the cart runtime."""
    command_type = ""
    if isinstance(command, dict):
        command_type = str(command.get("type") or "").strip().lower()

    if command_type == "request_return":
        try:
            row = await request_return(
                db,
                user_id,
                order_external_id=command.get("order_external_id"),
                phone=command.get("phone"),
                reason_code=command.get("reason_code"),
                amount=command.get("amount"),
            )
        except CommerceReturnError as exc:
            return state, {"ok": False, "error_code": exc.code, "effects": []}
        return state, {
            "ok": True,
            "effects": [
                {
                    "type": "persist_return",
                    "return_id": str(row.id),
                    "external_return_id": row.external_return_id,
                    "status": row.status,
                }
            ],
        }

    if command_type == "request_complaint":
        try:
            row, result = await request_complaint(
                db,
                user_id,
                phone=command.get("phone"),
                category=command.get("category"),
                order_external_id=command.get("order_external_id"),
                detail=command.get("detail"),
            )
        except CommerceReturnError as exc:
            return state, {"ok": False, "error_code": exc.code, "effects": []}
        return state, {
            "ok": True,
            "complaint_id": str(row.id),
            "status": row.status,
            "customer_message": result.get("customer_message") or "",
            "effects": result["effects"],
        }

    return state, {"ok": False, "error_code": "unknown_command", "effects": []}


__all__ = [
    "CommerceReturnError",
    "SELF_SERVE_CATEGORIES",
    "apply_aftersale_command",
    "approve_return",
    "deny_return",
    "evaluate_auto_approve",
    "find_buyer_order",
    "get_return",
    "list_returns",
    "mark_settled_offline",
    "open_paid_cancel_return",
    "payment_already_collected",
    "phones_match",
    "request_complaint",
    "request_return",
]
