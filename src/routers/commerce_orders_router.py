"""Merchant commerce orders and reservations HTTP API."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User
from ..services.commerce_storage_service import (
    CommerceOrderNotFound,
    CommerceStorageService,
)
from ..services.order_service import STATUS_TRANSITIONS
from .auth_router import get_current_user

router = APIRouter(prefix="/api/commerce", tags=["commerce"])
_storage = CommerceStorageService()


class OrderStatusBody(BaseModel):
    status: str = Field(..., min_length=1)


def _money(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def whatsapp_link(phone: Optional[str]) -> Optional[str]:
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return None
    return f"https://wa.me/{digits}"


def serialize_order(order) -> Dict[str, Any]:
    current = (order.status or "").strip().lower()
    return {
        "id": str(order.id),
        "user_id": str(order.user_id),
        "external_order_id": order.external_order_id,
        "order_id": order.external_order_id,
        "status": order.status,
        "payment_status": order.payment_status,
        "payment_method": order.payment_method,
        "total": _money(order.total),
        "currency": order.currency,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "whatsapp_url": whatsapp_link(order.customer_phone),
        "line_items": list(order.line_items or []),
        "delivery_method": order.delivery_method,
        "delivery_address": order.delivery_address,
        "notes": order.notes,
        "mpesa_receipt": order.mpesa_receipt,
        "allowed_statuses": list(STATUS_TRANSITIONS.get(current, [])),
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }


def serialize_reservation(reservation) -> Dict[str, Any]:
    return {
        "id": str(reservation.id),
        "user_id": str(reservation.user_id),
        "external_reservation_id": reservation.external_reservation_id,
        "reservation_id": reservation.external_reservation_id,
        "customer_name": reservation.customer_name,
        "customer_phone": reservation.customer_phone,
        "whatsapp_url": whatsapp_link(reservation.customer_phone),
        "reservation_date": reservation.reservation_date,
        "reservation_time": reservation.reservation_time,
        "party_size": reservation.party_size,
        "status": reservation.status,
        "notes": reservation.notes,
        "created_at": reservation.created_at.isoformat() if reservation.created_at else None,
        "updated_at": reservation.updated_at.isoformat() if reservation.updated_at else None,
    }


def _allowed_next(current_status: str) -> list[str]:
    current = (current_status or "").strip().lower().replace(" ", "_")
    return list(STATUS_TRANSITIONS.get(current, []))


@router.get("/orders")
async def list_commerce_orders(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the caller's commerce orders."""
    orders = await _storage.list_orders(db, user.id, limit=limit, offset=offset)
    return {
        "success": True,
        "data": {"orders": [serialize_order(order) for order in orders]},
    }


@router.get("/reservations")
async def list_commerce_reservations(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the caller's commerce reservations."""
    reservations = await _storage.list_reservations(
        db, user.id, limit=limit, offset=offset
    )
    return {
        "success": True,
        "data": {
            "reservations": [serialize_reservation(item) for item in reservations]
        },
    }


@router.get("/orders/{external_order_id}")
async def get_commerce_order(
    external_order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return one commerce order owned by the caller."""
    order = await _storage.get_order(db, user.id, external_order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {external_order_id} not found",
        )
    return {"success": True, "data": serialize_order(order)}


@router.patch("/orders/{external_order_id}")
async def patch_commerce_order_status(
    external_order_id: str,
    body: OrderStatusBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Move an order to an allowed STATUS_TRANSITIONS target."""
    order = await _storage.get_order(db, user.id, external_order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {external_order_id} not found",
        )
    target = (body.status or "").strip().lower().replace(" ", "_")
    allowed = _allowed_next(order.status)
    if target not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot change status from '{order.status}' to '{target}'. "
                f"Allowed: {', '.join(allowed) if allowed else 'none'}"
            ),
        )
    try:
        updated = await _storage.update_order_status(
            db, user.id, external_order_id, target
        )
    except CommerceOrderNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {"success": True, "data": serialize_order(updated)}
