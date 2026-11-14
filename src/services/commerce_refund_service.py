"""Refund payout or honest offline settlement.

A return becomes ``refunded`` only after B2C returns a receipt. With no
payout credentials, or when Daraja only accepts the request, the status
stays ``refund_pending``. ``settled_offline`` is the other terminal success.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import (
    CommerceOrder,
    CommerceRefundAttempt,
    CommerceRefundAttemptStatus,
    CommerceRefundMethod,
    CommerceReturn,
    CommerceReturnStatus,
)
from .daraja_service import daraja_service


class CommerceReturnError(Exception):
    """Domain failure for a return or refund action. ``code`` is stable."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def load_payout_credentials() -> dict:
    """Daraja B2C fields. Empty initiator means payout is not configured."""
    result_url = _clean(
        settings.MPESA_B2C_RESULT_URL or settings.MPESA_CALLBACK_URL
    )
    timeout_url = _clean(settings.MPESA_B2C_TIMEOUT_URL) or result_url
    short_code = _clean(
        settings.MPESA_B2C_SHORTCODE or settings.MPESA_BUSINESS_SHORT_CODE
    )
    return {
        "initiator_name": _clean(settings.MPESA_B2C_INITIATOR_NAME),
        "security_credential": _clean(settings.MPESA_B2C_SECURITY_CREDENTIAL),
        "short_code": short_code,
        "consumer_key": _clean(settings.MPESA_CONSUMER_KEY),
        "consumer_secret": _clean(settings.MPESA_CONSUMER_SECRET),
        "result_url": result_url,
        "timeout_url": timeout_url,
    }


def payout_credentials_configured() -> bool:
    """True only when a B2C payout can actually be submitted."""
    creds = load_payout_credentials()
    return bool(
        creds["initiator_name"]
        and creds["security_credential"]
        and creds["short_code"]
        and creds["consumer_key"]
        and creds["consumer_secret"]
        and creds["result_url"]
        and creds["timeout_url"]
    )


async def send_b2c_payout(**kwargs):
    """Indirection so tests can mock the payout without calling Daraja."""
    return await daraja_service.b2c_payment(**kwargs)


def _money_text(amount: Any) -> str:
    return f"{Decimal(str(amount)).quantize(Decimal('0.01'))}"


def _whole_shillings(amount: Any) -> int:
    quantized = Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(quantized)


def offline_pending_message(return_row: CommerceReturn) -> str:
    return (
        f"Your return {return_row.external_return_id} for KES {_money_text(return_row.amount)} "
        "is approved. M-Pesa payout is not set up, so the shop will pay you offline. "
        "This payment is not complete."
    )


def b2c_pending_message(return_row: CommerceReturn) -> str:
    return (
        f"Your return {return_row.external_return_id} for KES {_money_text(return_row.amount)} "
        "was submitted to M-Pesa and is waiting for confirmation. "
        "This payment is not complete."
    )


def failed_payout_message(return_row: CommerceReturn) -> str:
    return (
        f"Your return {return_row.external_return_id} for KES {_money_text(return_row.amount)} "
        "could not be paid. The shop has not completed payment."
    )


def refunded_message(return_row: CommerceReturn, receipt: str) -> str:
    return (
        f"Your return {return_row.external_return_id} for KES {_money_text(return_row.amount)} "
        f"was refunded by M-Pesa. Receipt: {receipt}."
    )


def settled_offline_message(return_row: CommerceReturn) -> str:
    return (
        f"The shop confirmed offline payment of KES {_money_text(return_row.amount)} "
        f"for return {return_row.external_return_id}. The return is settled offline."
    )


def _snapshot(return_row: CommerceReturn) -> dict:
    raw = return_row.raw_snapshot
    return dict(raw) if isinstance(raw, dict) else {}


def _remember(return_row: CommerceReturn, **fields: Any) -> None:
    snapshot = _snapshot(return_row)
    snapshot.update(fields)
    return_row.raw_snapshot = snapshot


async def list_refund_attempts(
    db: AsyncSession,
    return_id: UUID,
) -> list[CommerceRefundAttempt]:
    result = await db.execute(
        select(CommerceRefundAttempt)
        .where(CommerceRefundAttempt.return_id == return_id)
        .order_by(CommerceRefundAttempt.created_at.asc())
    )
    return list(result.scalars().all())


def _new_attempt(
    return_row: CommerceReturn,
    *,
    method: str,
    status: str,
    receipt: Optional[str] = None,
    error: Optional[str] = None,
) -> CommerceRefundAttempt:
    return CommerceRefundAttempt(
        return_id=return_row.id,
        method=method,
        status=status,
        amount=return_row.amount,
        mpesa_receipt=receipt,
        error=error,
    )


async def execute_refund(
    db: AsyncSession,
    return_row: CommerceReturn,
) -> CommerceRefundAttempt:
    """Create one payout attempt. Never sets ``refunded`` without a receipt."""
    if return_row.status == CommerceReturnStatus.DENIED.value:
        raise CommerceReturnError("already_denied", "Denied returns are not paid out")
    if return_row.status == CommerceReturnStatus.SETTLED_OFFLINE.value:
        raise CommerceReturnError(
            "already_settled",
            "This return was already settled offline",
        )

    existing = await list_refund_attempts(db, return_row.id)
    for attempt in existing:
        if attempt.status == CommerceRefundAttemptStatus.SUCCESS.value:
            return attempt
        if attempt.status == CommerceRefundAttemptStatus.PENDING.value:
            return attempt

    if payout_credentials_configured():
        return await _execute_b2c(db, return_row)
    return await _execute_offline(db, return_row)


async def _execute_offline(
    db: AsyncSession,
    return_row: CommerceReturn,
) -> CommerceRefundAttempt:
    attempt = _new_attempt(
        return_row,
        method=CommerceRefundMethod.OFFLINE.value,
        status=CommerceRefundAttemptStatus.PENDING.value,
    )
    db.add(attempt)
    return_row.status = CommerceReturnStatus.REFUND_PENDING.value
    _remember(
        return_row,
        customer_message=offline_pending_message(return_row),
        payout="offline",
    )
    await db.commit()
    await db.refresh(return_row)
    await db.refresh(attempt)
    return attempt


async def _execute_b2c(
    db: AsyncSession,
    return_row: CommerceReturn,
) -> CommerceRefundAttempt:
    creds = load_payout_credentials()
    whole = _whole_shillings(return_row.amount)
    result = await send_b2c_payout(
        phone_number=return_row.customer_phone,
        amount=whole,
        remarks=f"Refund {return_row.external_return_id}",
        occasion="Refund",
        command_id="BusinessPayment",
        consumer_key=creds["consumer_key"] or None,
        consumer_secret=creds["consumer_secret"] or None,
        short_code=creds["short_code"] or None,
        initiator_name=creds["initiator_name"] or None,
        security_credential=creds["security_credential"] or None,
        result_url=creds["result_url"] or None,
        timeout_url=creds["timeout_url"] or None,
    )
    receipt = _clean(result.get("receipt")) or None
    conversation_id = result.get("conversation_id")

    if result.get("success") and receipt:
        attempt = _new_attempt(
            return_row,
            method=CommerceRefundMethod.MPESA_B2C.value,
            status=CommerceRefundAttemptStatus.SUCCESS.value,
            receipt=receipt,
        )
        return_row.status = CommerceReturnStatus.REFUNDED.value
        _remember(
            return_row,
            customer_message=refunded_message(return_row, receipt),
            mpesa_conversation_id=conversation_id,
            mpesa_receipt=receipt,
        )
    elif result.get("success") or result.get("accepted"):
        attempt = _new_attempt(
            return_row,
            method=CommerceRefundMethod.MPESA_B2C.value,
            status=CommerceRefundAttemptStatus.PENDING.value,
        )
        return_row.status = CommerceReturnStatus.REFUND_PENDING.value
        _remember(
            return_row,
            customer_message=b2c_pending_message(return_row),
            mpesa_conversation_id=conversation_id,
            payout="mpesa_b2c_pending",
        )
    else:
        error = _clean(result.get("error")) or "B2C payout failed"
        attempt = _new_attempt(
            return_row,
            method=CommerceRefundMethod.MPESA_B2C.value,
            status=CommerceRefundAttemptStatus.FAILED.value,
            error=error,
        )
        return_row.status = CommerceReturnStatus.FAILED.value
        _remember(
            return_row,
            customer_message=failed_payout_message(return_row),
            payout_error=error,
        )

    db.add(attempt)
    await db.commit()
    await db.refresh(return_row)
    await db.refresh(attempt)
    return attempt


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


async def mark_settled_offline(
    db: AsyncSession,
    user_id: UUID,
    return_id: UUID,
    actor_user_id: UUID,
    note: Optional[str] = None,
) -> CommerceReturn:
    """Merchant confirms cash/offline payment. Does not set ``refunded``."""
    result = await db.execute(
        select(CommerceReturn).where(
            CommerceReturn.user_id == user_id,
            CommerceReturn.id == return_id,
        )
    )
    return_row = result.scalar_one_or_none()
    if return_row is None:
        raise CommerceReturnError("return_not_found", "Return not found")
    if return_row.status == CommerceReturnStatus.SETTLED_OFFLINE.value:
        return return_row
    if return_row.status == CommerceReturnStatus.REFUNDED.value:
        raise CommerceReturnError(
            "already_refunded",
            "This return was already paid by M-Pesa",
        )
    if return_row.status not in {
        CommerceReturnStatus.REFUND_PENDING.value,
        CommerceReturnStatus.FAILED.value,
        CommerceReturnStatus.APPROVED.value,
    }:
        raise CommerceReturnError(
            "not_ready",
            "Approve the return before marking it settled offline",
        )

    attempts = await list_refund_attempts(db, return_row.id)
    if any(
        attempt.method == CommerceRefundMethod.MPESA_B2C.value
        and attempt.status == CommerceRefundAttemptStatus.PENDING.value
        for attempt in attempts
    ):
        raise CommerceReturnError(
            "payout_in_flight",
            "An M-Pesa payout is still pending. Wait for it before settling offline",
        )

    offline = next(
        (
            attempt
            for attempt in attempts
            if attempt.method == CommerceRefundMethod.OFFLINE.value
            and attempt.status == CommerceRefundAttemptStatus.PENDING.value
        ),
        None,
    )
    if offline is None:
        offline = _new_attempt(
            return_row,
            method=CommerceRefundMethod.OFFLINE.value,
            status=CommerceRefundAttemptStatus.SUCCESS.value,
        )
        db.add(offline)
    else:
        offline.status = CommerceRefundAttemptStatus.SUCCESS.value

    fields: dict[str, Any] = {
        "settled_by": str(actor_user_id),
        "customer_message": settled_offline_message(return_row),
    }
    if note:
        fields["settlement_note"] = note
    _remember(return_row, **fields)
    return_row.status = CommerceReturnStatus.SETTLED_OFFLINE.value

    order = await _load_order(db, user_id, return_row.order_external_id)
    if order is not None:
        line = (
            f"Refund settled offline for return {return_row.external_return_id} "
            f"amount {return_row.amount} {return_row.currency}."
        )
        if note:
            line = f"{line} {note}"
        existing = (order.notes or "").strip()
        order.notes = f"{existing}\n{line}".strip() if existing else line

    await db.commit()
    await db.refresh(return_row)
    return return_row
