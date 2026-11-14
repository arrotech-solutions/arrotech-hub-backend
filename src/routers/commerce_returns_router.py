"""Merchant returns queue: list, detail, approve, deny, settle offline."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User
from ..services.commerce_refund_service import list_refund_attempts, retry_refund
from ..services.commerce_returns_service import (
    CommerceReturnError,
    approve_return,
    deny_return,
    get_return,
    list_returns,
    mark_settled_offline,
)
from .auth_router import get_current_user

router = APIRouter(prefix="/api/commerce", tags=["commerce"])


class DenyReturnBody(BaseModel):
    reason: Optional[str] = None


class SettleOfflineBody(BaseModel):
    note: Optional[str] = None


def _money(value: Any) -> Optional[str]:
    if value is None:
        return None
    return format(Decimal(str(value)), "f")


def _http_error(exc: CommerceReturnError) -> HTTPException:
    not_found = exc.code in {"return_not_found", "order_not_found"}
    return HTTPException(
        status_code=(
            status.HTTP_404_NOT_FOUND if not_found else status.HTTP_400_BAD_REQUEST
        ),
        detail=str(exc),
    )


def serialize_return(row, attempts) -> dict:
    snapshot = row.raw_snapshot if isinstance(row.raw_snapshot, dict) else {}
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "external_return_id": row.external_return_id,
        "order_external_id": row.order_external_id,
        "customer_phone": row.customer_phone,
        "reason_code": row.reason_code,
        "amount": _money(row.amount),
        "currency": row.currency,
        "status": row.status,
        "auto_approved": bool(row.auto_approved),
        "customer_message": snapshot.get("customer_message") or "",
        "refund_attempts": [
            {
                "id": str(attempt.id),
                "method": attempt.method,
                "status": attempt.status,
                "amount": _money(attempt.amount),
                "mpesa_receipt": attempt.mpesa_receipt,
                "error": attempt.error,
            }
            for attempt in attempts
        ],
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _payload(db: AsyncSession, row) -> dict:
    attempts = await list_refund_attempts(db, row.id)
    return serialize_return(row, attempts)


@router.get("/returns")
async def list_commerce_returns(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the caller's return requests."""
    rows = await list_returns(db, user.id, limit=limit, offset=offset)
    data = []
    for row in rows:
        data.append(await _payload(db, row))
    return {"success": True, "data": {"returns": data}}


@router.get("/returns/{return_id}")
async def get_commerce_return(
    return_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return one return request owned by the caller."""
    row = await get_return(db, user.id, return_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Return not found",
        )
    return {"success": True, "data": await _payload(db, row)}


@router.post("/returns/{return_id}/approve")
async def approve_commerce_return(
    return_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve a return and start the refund attempt."""
    try:
        row = await approve_return(db, user.id, return_id, actor_user_id=user.id)
    except CommerceReturnError as exc:
        raise _http_error(exc) from exc
    return {"success": True, "data": await _payload(db, row)}


@router.post("/returns/{return_id}/deny")
async def deny_commerce_return(
    return_id: UUID,
    body: DenyReturnBody | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deny a return. Does not create a payout."""
    reason = body.reason if body else None
    try:
        row = await deny_return(
            db,
            user.id,
            return_id,
            actor_user_id=user.id,
            reason=reason,
        )
    except CommerceReturnError as exc:
        raise _http_error(exc) from exc
    return {"success": True, "data": await _payload(db, row)}


@router.post("/returns/{return_id}/settle-offline")
async def settle_commerce_return_offline(
    return_id: UUID,
    body: SettleOfflineBody | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an approved offline refund as settled. Does not set refunded."""
    note = body.note if body else None
    try:
        row = await mark_settled_offline(
            db,
            user.id,
            return_id,
            actor_user_id=user.id,
            note=note,
        )
    except CommerceReturnError as exc:
        raise _http_error(exc) from exc
    return {"success": True, "data": await _payload(db, row)}


@router.post("/returns/{return_id}/retry-refund")
async def retry_commerce_refund(
    return_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed M-Pesa payout. Does not start one while another is pending."""
    try:
        row = await retry_refund(db, user.id, return_id, actor_user_id=user.id)
    except CommerceReturnError as exc:
        raise _http_error(exc) from exc
    return {"success": True, "data": await _payload(db, row)}
