"""Refund payout or honest offline settlement.

A return becomes ``refunded`` only after B2C returns a receipt, either on
the accept body or on the later result callback. The pending attempt row is
committed before the HTTP call. A timeout leaves that row pending so a
second payout cannot start. A failed attempt is not auto-retried.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
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
    MpesaAgentConfig,
)
from .commerce_status_notify import notify_customer_text, phones_match
from .daraja_service import daraja_service

logger = logging.getLogger(__name__)

_payout_locks: dict[str, asyncio.Lock] = {}
_payout_locks_guard = asyncio.Lock()

RESERVED_RETURN_STATUSES = frozenset(
    {
        CommerceReturnStatus.REQUESTED.value,
        CommerceReturnStatus.PENDING_APPROVAL.value,
        CommerceReturnStatus.APPROVED.value,
        CommerceReturnStatus.REFUND_PENDING.value,
        CommerceReturnStatus.REFUNDED.value,
        CommerceReturnStatus.SETTLED_OFFLINE.value,
    }
)


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


def tenant_daraja_callback_url(webhook_secret: str, base_url: Optional[str] = None) -> str:
    """Same path STK uses: the tenant callback that applies a B2C result."""
    base = _clean(base_url if base_url is not None else settings.API_BASE_URL).rstrip("/")
    secret = _clean(webhook_secret)
    return f"{base}/api/agents/daraja/callback/{secret}"


async def b2c_callback_urls_for_user(
    db: AsyncSession,
    user_id: UUID,
) -> tuple[Optional[str], Optional[str]]:
    """ResultURL and timeout URL for this merchant's Daraja webhook.

    When a webhook secret and a public base URL exist, both URLs are the
    tenant callback. That route calls ``apply_b2c_result``. If either is
    missing, the caller must not send B2C to the payments logger.
    """
    found = await db.execute(
        select(MpesaAgentConfig).where(MpesaAgentConfig.user_id == user_id)
    )
    config = found.scalar_one_or_none()
    if config is None:
        return None, None
    secret = _clean(config.webhook_secret)
    base = _clean(config.callback_url_override) or _clean(settings.API_BASE_URL)
    if not secret or not base:
        return None, None
    url = tenant_daraja_callback_url(secret, base)
    return url, url


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
        created_at=datetime.now(timezone.utc),
    )


def _mirror(caller: CommerceReturn, locked: CommerceReturn) -> None:
    if caller is locked:
        return
    caller.status = locked.status
    caller.raw_snapshot = locked.raw_snapshot
    caller.auto_approved = locked.auto_approved


async def _return_lock(return_id: UUID) -> asyncio.Lock:
    key = str(return_id)
    async with _payout_locks_guard:
        lock = _payout_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _payout_locks[key] = lock
        return lock


async def _lock_return_row(db: AsyncSession, return_id: UUID) -> CommerceReturn:
    stmt = select(CommerceReturn).where(CommerceReturn.id == return_id)
    try:
        conn = await db.connection()
        if conn.dialect.name != "sqlite":
            stmt = stmt.with_for_update()
    except Exception:
        logger.debug("Return row lock fallback for %s", return_id, exc_info=True)
    result = await db.execute(stmt)
    return result.scalar_one()


async def reserved_refund_amount(
    db: AsyncSession,
    user_id: UUID,
    order_external_id: str,
) -> Decimal:
    """Sum of return amounts that are queued, in flight, or already settled."""
    result = await db.execute(
        select(CommerceReturn).where(
            CommerceReturn.user_id == user_id,
            CommerceReturn.order_external_id == order_external_id,
            CommerceReturn.status.in_(RESERVED_RETURN_STATUSES),
        )
    )
    total = Decimal("0.00")
    for row in result.scalars().all():
        total += _money_amount(row.amount)
    return total


def _money_amount(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"))


async def execute_refund(
    db: AsyncSession,
    return_row: CommerceReturn,
    *,
    allow_retry: bool = False,
) -> CommerceRefundAttempt:
    """Create at most one in-flight payout. Never sets ``refunded`` without a receipt."""
    lock = await _return_lock(return_row.id)
    async with lock:
        return await _execute_refund_locked(db, return_row, allow_retry=allow_retry)


async def _execute_refund_locked(
    db: AsyncSession,
    return_row: CommerceReturn,
    *,
    allow_retry: bool,
) -> CommerceRefundAttempt:
    if return_row.status == CommerceReturnStatus.DENIED.value:
        raise CommerceReturnError("already_denied", "Denied returns are not paid out")
    if return_row.status == CommerceReturnStatus.SETTLED_OFFLINE.value:
        raise CommerceReturnError(
            "already_settled",
            "This return was already settled offline",
        )

    locked = await _lock_return_row(db, return_row.id)
    attempts = await list_refund_attempts(db, locked.id)
    success = next(
        (item for item in attempts if item.status == CommerceRefundAttemptStatus.SUCCESS.value),
        None,
    )
    if success is not None:
        _mirror(return_row, locked)
        return success
    pending = next(
        (item for item in attempts if item.status == CommerceRefundAttemptStatus.PENDING.value),
        None,
    )
    if pending is not None:
        _mirror(return_row, locked)
        return pending

    order = await _load_order(db, locked.user_id, locked.order_external_id)
    if order is None or not phones_match(order.customer_phone, locked.customer_phone):
        raise CommerceReturnError(
            "phone_mismatch",
            "Refund phone does not match the buyer on the order",
        )

    failed = [item for item in attempts if item.status == CommerceRefundAttemptStatus.FAILED.value]
    if failed and not allow_retry:
        if locked.status != CommerceReturnStatus.FAILED.value:
            locked.status = CommerceReturnStatus.FAILED.value
            await db.commit()
        _mirror(return_row, locked)
        return failed[-1]
    if allow_retry and not failed:
        raise CommerceReturnError(
            "retry_not_allowed",
            "A refund can be retried only after a payout has failed",
        )

    tenant_result, tenant_timeout = await b2c_callback_urls_for_user(db, locked.user_id)
    creds_ready = payout_credentials_configured()
    use_b2c = bool(creds_ready and tenant_result and tenant_timeout)
    if creds_ready and not use_b2c:
        logger.warning(
            "B2C payout skipped for user %s: no tenant callback URL that can apply the result",
            locked.user_id,
        )
    attempt = _new_attempt(
        locked,
        method=(
            CommerceRefundMethod.MPESA_B2C.value
            if use_b2c
            else CommerceRefundMethod.OFFLINE.value
        ),
        status=CommerceRefundAttemptStatus.PENDING.value,
    )
    db.add(attempt)
    locked.status = CommerceReturnStatus.REFUND_PENDING.value
    _remember(
        locked,
        customer_message=(
            b2c_pending_message(locked) if use_b2c else offline_pending_message(locked)
        ),
        payout="mpesa_b2c_pending" if use_b2c else "offline",
    )
    await db.commit()
    await db.refresh(attempt)
    await db.refresh(locked)
    _mirror(return_row, locked)
    if not use_b2c:
        return attempt

    try:
        creds = load_payout_credentials()
        result = await send_b2c_payout(
            phone_number=locked.customer_phone,
            amount=_whole_shillings(locked.amount),
            remarks=f"Refund {locked.external_return_id}",
            occasion="Refund",
            command_id="BusinessPayment",
            consumer_key=creds["consumer_key"] or None,
            consumer_secret=creds["consumer_secret"] or None,
            short_code=creds["short_code"] or None,
            initiator_name=creds["initiator_name"] or None,
            security_credential=creds["security_credential"] or None,
            result_url=tenant_result,
            timeout_url=tenant_timeout,
        )
    except Exception as exc:
        logger.warning("B2C payout uncertain for return %s: %s", locked.id, exc)
        _remember(locked, payout_uncertain=str(exc))
        await db.commit()
        _mirror(return_row, locked)
        return attempt

    return await _apply_b2c_accept(db, locked, attempt, result or {}, return_row)


async def _apply_b2c_accept(
    db: AsyncSession,
    locked: CommerceReturn,
    attempt: CommerceRefundAttempt,
    result: dict,
    caller: CommerceReturn,
) -> CommerceRefundAttempt:
    receipt = _clean(result.get("receipt")) or None
    conversation_id = _clean(result.get("conversation_id")) or None
    originator = _clean(result.get("originator_conversation_id")) or None
    if conversation_id:
        attempt.conversation_id = conversation_id
    if originator:
        attempt.originator_conversation_id = originator

    if locked.status == CommerceReturnStatus.SETTLED_OFFLINE.value:
        if receipt:
            attempt.mpesa_receipt = receipt
            _remember(locked, mpesa_result_after_offline=receipt)
        logger.warning(
            "B2C accept arrived after return %s was settled offline; receipt stored, status unchanged",
            locked.id,
        )
        await db.commit()
        _mirror(caller, locked)
        return attempt

    if result.get("uncertain") or result.get("timed_out"):
        _remember(locked, payout_uncertain=result.get("error") or "uncertain")
        await db.commit()
        _mirror(caller, locked)
        return attempt

    if result.get("success") and receipt:
        attempt.status = CommerceRefundAttemptStatus.SUCCESS.value
        attempt.mpesa_receipt = receipt
        attempt.error = None
        locked.status = CommerceReturnStatus.REFUNDED.value
        _remember(
            locked,
            customer_message=refunded_message(locked, receipt),
            mpesa_conversation_id=conversation_id,
            mpesa_receipt=receipt,
        )
    elif result.get("success") or result.get("accepted"):
        locked.status = CommerceReturnStatus.REFUND_PENDING.value
        _remember(
            locked,
            customer_message=b2c_pending_message(locked),
            mpesa_conversation_id=conversation_id,
            payout="mpesa_b2c_pending",
        )
    else:
        error = _clean(result.get("error")) or "B2C payout failed"
        attempt.status = CommerceRefundAttemptStatus.FAILED.value
        attempt.error = error
        locked.status = CommerceReturnStatus.FAILED.value
        _remember(
            locked,
            customer_message=failed_payout_message(locked),
            payout_error=error,
        )

    await db.commit()
    await db.refresh(locked)
    await db.refresh(attempt)
    _mirror(caller, locked)
    return attempt


def parse_b2c_result(payload: Any) -> Optional[dict]:
    """Parse a Daraja B2C Result callback. None when the body is not one."""
    if not isinstance(payload, dict):
        return None
    result = payload.get("Result")
    if not isinstance(result, dict):
        return None
    originator = _clean(result.get("OriginatorConversationID")) or None
    conversation = _clean(result.get("ConversationID")) or None
    if not originator and not conversation:
        return None
    raw_params = (result.get("ResultParameters") or {}).get("ResultParameter") or []
    if isinstance(raw_params, dict):
        raw_params = [raw_params]
    params: dict[str, Any] = {}
    for item in raw_params:
        if isinstance(item, dict) and item.get("Key"):
            params[str(item["Key"])] = item.get("Value")
    code = result.get("ResultCode")
    receipt = _clean(params.get("TransactionReceipt") or result.get("TransactionID")) or None
    return {
        "result_code": None if code is None else str(code),
        "result_desc": _clean(result.get("ResultDesc")),
        "originator_conversation_id": originator,
        "conversation_id": conversation,
        "receipt": receipt,
    }


async def _find_b2c_attempt(db: AsyncSession, parsed: dict) -> Optional[CommerceRefundAttempt]:
    for column, value in (
        (CommerceRefundAttempt.originator_conversation_id, parsed.get("originator_conversation_id")),
        (CommerceRefundAttempt.conversation_id, parsed.get("conversation_id")),
    ):
        if not value:
            continue
        found = await db.execute(select(CommerceRefundAttempt).where(column == value))
        attempt = found.scalar_one_or_none()
        if attempt is not None:
            return attempt
    return None


async def apply_b2c_result(
    db: AsyncSession,
    payload: Any,
    user_id: Optional[UUID] = None,
) -> Optional[CommerceReturn]:
    """Complete or fail the pending M-Pesa attempt from a Daraja result callback."""
    parsed = parse_b2c_result(payload)
    if parsed is None:
        return None
    matched = await _find_b2c_attempt(db, parsed)
    if matched is None:
        return None

    lock = await _return_lock(matched.return_id)
    async with lock:
        locked = await _lock_return_row(db, matched.return_id)
        if user_id is not None and str(locked.user_id) != str(user_id):
            return None
        previous_message = str(_snapshot(locked).get("customer_message") or "")
        attempt = await db.get(CommerceRefundAttempt, matched.id)
        if attempt is None:
            return None
        if (
            locked.status == CommerceReturnStatus.REFUNDED.value
            and attempt.status == CommerceRefundAttemptStatus.SUCCESS.value
        ):
            return locked

        if locked.status == CommerceReturnStatus.SETTLED_OFFLINE.value:
            if parsed["result_code"] == "0" and parsed["receipt"]:
                attempt.mpesa_receipt = parsed["receipt"]
                _remember(locked, mpesa_result_after_offline=parsed["receipt"])
                logger.warning(
                    "B2C result arrived after return %s was settled offline; receipt stored, status unchanged",
                    locked.id,
                )
                await db.commit()
            return locked

        desc = (parsed["result_desc"] or "").lower()
        if "timeout" in desc:
            _remember(locked, payout_uncertain=parsed["result_desc"])
            await db.commit()
            return locked

        if parsed["result_code"] == "0" and parsed["receipt"]:
            if attempt.status == CommerceRefundAttemptStatus.PENDING.value:
                attempt.status = CommerceRefundAttemptStatus.SUCCESS.value
                attempt.mpesa_receipt = parsed["receipt"]
                attempt.error = None
            locked.status = CommerceReturnStatus.REFUNDED.value
            _remember(
                locked,
                customer_message=refunded_message(locked, parsed["receipt"]),
                mpesa_receipt=parsed["receipt"],
                mpesa_conversation_id=parsed.get("conversation_id"),
            )
        elif parsed["result_code"] == "0":
            return locked
        else:
            error = parsed["result_desc"] or f"B2C result {parsed['result_code']}"
            if attempt.status == CommerceRefundAttemptStatus.PENDING.value:
                attempt.status = CommerceRefundAttemptStatus.FAILED.value
                attempt.error = error
            locked.status = CommerceReturnStatus.FAILED.value
            _remember(
                locked,
                customer_message=failed_payout_message(locked),
                payout_error=error,
            )

        await db.commit()
        await db.refresh(locked)
        current_message = str(_snapshot(locked).get("customer_message") or "")
        if current_message and current_message != previous_message:
            await notify_customer_text(
                db,
                locked.user_id,
                locked.customer_phone,
                current_message,
                context=f"b2c return={locked.external_return_id} status={locked.status}",
            )
        return locked


async def retry_refund(
    db: AsyncSession,
    user_id: UUID,
    return_id: UUID,
    actor_user_id: UUID,
) -> CommerceReturn:
    """Merchant retry. Inserts a new pending attempt only when the last payout failed."""
    result = await db.execute(
        select(CommerceReturn).where(
            CommerceReturn.user_id == user_id,
            CommerceReturn.id == return_id,
        )
    )
    return_row = result.scalar_one_or_none()
    if return_row is None:
        raise CommerceReturnError("return_not_found", "Return not found")
    if return_row.status == CommerceReturnStatus.REFUNDED.value:
        raise CommerceReturnError("already_refunded", "This return was already paid by M-Pesa")
    if return_row.status == CommerceReturnStatus.SETTLED_OFFLINE.value:
        raise CommerceReturnError("already_settled", "This return was already settled offline")
    _remember(return_row, retried_by=str(actor_user_id))
    await execute_refund(db, return_row, allow_retry=True)
    await db.refresh(return_row)
    await notify_customer_text(
        db,
        return_row.user_id,
        return_row.customer_phone,
        str(_snapshot(return_row).get("customer_message") or ""),
        context=f"retry return={return_row.external_return_id}",
    )
    return return_row


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
    in_flight = next(
        (
            attempt
            for attempt in attempts
            if attempt.method == CommerceRefundMethod.MPESA_B2C.value
            and attempt.status == CommerceRefundAttemptStatus.PENDING.value
        ),
        None,
    )
    if in_flight is not None:
        raise CommerceReturnError(
            "payout_in_flight",
            "An M-Pesa payout is still pending. Wait for it to fail before settling offline",
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
    await notify_customer_text(
        db,
        return_row.user_id,
        return_row.customer_phone,
        str(_snapshot(return_row).get("customer_message") or ""),
        context=f"settle return={return_row.external_return_id}",
    )
    return return_row
