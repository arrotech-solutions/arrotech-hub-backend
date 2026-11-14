"""Return requests, complaint intake, and auto-approve evaluation.

``request_return`` / ``request_complaint`` stay off ``CommerceRuntime.apply``.
Task 3 locks those command names out of the cart runtime. ``apply_aftersale_command``
is the thin wrapper the agent can call later.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    CommerceComplaint,
    CommerceComplaintStatus,
    CommerceOrder,
    CommerceReturn,
    CommerceReturnStatus,
)
from .commerce_policy import get_policy
from .commerce_refund_service import (
    CommerceReturnError,
    execute_refund,
    mark_settled_offline,
    reserved_refund_amount,
)
from .commerce_runtime.state import CommerceState

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


async def request_return(
    db: AsyncSession,
    user_id: UUID,
    *,
    order_external_id: str,
    phone: str,
    reason_code: str,
    amount: Any,
) -> CommerceReturn:
    """Create a return. Auto-approve pays only when policy and payout say so."""
    policy = await get_policy(db, user_id)
    external_id = str(order_external_id or "").strip()
    order = await _load_order(db, user_id, external_id)
    if order is None:
        raise CommerceReturnError(
            "order_not_found",
            f"Order {external_id} not found",
        )

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

    phone_text = str(phone or "").strip()
    if not phone_text:
        raise CommerceReturnError("invalid_phone", "Customer phone is required")

    existing = await _matching_open_return(
        db,
        user_id,
        external_id,
        amount=money,
        reason_code=code,
        phone=phone_text,
    )
    if existing is not None:
        return existing

    reserved = await reserved_refund_amount(db, user_id, external_id)
    remaining = _money(order.total) - reserved
    if money > remaining:
        raise CommerceReturnError(
            "amount_exceeds_order",
            "Return amount exceeds the remaining refundable total",
        )

    created = _as_utc(order.created_at)
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
        raw_snapshot={
            "order_created_at": created.isoformat() if created else None,
            "order_total": str(_money(order.total)),
        },
    )
    if evaluate_auto_approve(policy, row, order):
        row.auto_approved = True
        row.status = CommerceReturnStatus.APPROVED.value
        snapshot = _snapshot(row)
        snapshot["approved_by"] = "auto"
        row.raw_snapshot = snapshot

    db.add(row)
    await db.commit()
    await db.refresh(row)
    if row.auto_approved:
        await execute_refund(db, row)
        await db.refresh(row)
    return row


async def approve_return(
    db: AsyncSession,
    user_id: UUID,
    return_id: Any,
    actor_user_id: UUID,
) -> CommerceReturn:
    """Hub approve. Creates one refund attempt via ``execute_refund``."""
    row = await _require_return(db, user_id, return_id)
    if row.status in _TERMINAL_APPROVAL:
        return row
    if row.status == CommerceReturnStatus.FAILED.value:
        return row
    if row.status == CommerceReturnStatus.DENIED.value:
        raise CommerceReturnError("already_denied", "This return was denied")

    snapshot = _snapshot(row)
    snapshot["approved_by"] = str(actor_user_id)
    row.raw_snapshot = snapshot
    row.status = CommerceReturnStatus.APPROVED.value
    await db.commit()
    await execute_refund(db, row)
    await db.refresh(row)
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
    row = CommerceComplaint(
        user_id=user_id,
        external_complaint_id=_new_external_id("CMP"),
        order_external_id=order_id or None,
        customer_phone=phone_text,
        category=normalized,
        status=status,
        raw_snapshot={"detail": detail} if detail else {},
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    effects: list[dict] = []
    if not self_serve:
        effects = [{"type": "handoff", "complaint_id": str(row.id)}]
    return row, {"ok": True, "effects": effects}


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
    "get_return",
    "list_returns",
    "mark_settled_offline",
    "request_complaint",
    "request_return",
]
