"""Per-user commerce order and reservation persistence."""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CommerceOrder, CommerceReservation
from .order_service import ORDER_STATUSES

_DEFAULT_ORDER_STATUS = "pending"
_DEFAULT_PAYMENT_STATUS = "pending"
_DEFAULT_CURRENCY = "KES"
_DEFAULT_RESERVATION_STATUS = "confirmed"


class CommerceOrderNotFound(LookupError):
    """Raised when an order is missing for the calling user."""

    def __init__(self, external_order_id: str):
        self.external_order_id = external_order_id
        super().__init__(f"Order {external_order_id} not found")


def _as_uuid(value) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _text(value, default: str | None = None) -> str | None:
    if value is None:
        return default
    return str(value).strip()


def _require_text(data: dict, keys: tuple[str, ...], field: str) -> str:
    for key in keys:
        if key in data:
            text = _text(data[key], "")
            if not text:
                raise ValueError(f"{field} is required")
            return text
    raise ValueError(f"{field} is required")


def _money(value) -> Decimal:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError("total is required")
    if isinstance(value, Decimal):
        if not value.is_finite() or value < 0:
            raise ValueError("total is invalid")
        return value.quantize(Decimal("0.01"))
    try:
        parsed = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError("total is invalid") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("total is invalid")
    return parsed.quantize(Decimal("0.01"))


def _party_size(value) -> int:
    if value is None or (isinstance(value, str) and not str(value).strip()):
        raise ValueError("party_size is required")
    if isinstance(value, bool):
        raise ValueError("party_size is invalid")
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("party_size is invalid") from exc
    if size < 1:
        raise ValueError("party_size is invalid")
    return size


def _require_order_status(status: str) -> str:
    normalized = (status or "").strip().lower().replace(" ", "_")
    if normalized not in ORDER_STATUSES:
        raise ValueError(
            f"Invalid status: '{status}'. Valid statuses: {', '.join(ORDER_STATUSES)}"
        )
    return normalized


class CommerceStorageService:
    """Durable WhatsApp commerce orders and reservations, scoped per user."""

    async def upsert_order(self, db: AsyncSession, user_id, order: dict) -> CommerceOrder:
        payload = dict(order or {})
        uid = _as_uuid(user_id)
        external_id = _require_text(payload, ("order_id", "external_order_id"), "order_id")
        existing = await self.get_order(db, uid, external_id)
        values = self._order_values(payload, existing)
        if existing is None:
            row = CommerceOrder(user_id=uid, external_order_id=external_id, **values)
            db.add(row)
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            row = existing
        await db.commit()
        await db.refresh(row)
        return row

    async def update_order_status(
        self,
        db: AsyncSession,
        user_id,
        external_order_id: str,
        status: str,
    ) -> CommerceOrder:
        normalized = _require_order_status(status)
        order = await self._get_owned_order(db, user_id, external_order_id)
        order.status = normalized
        await db.commit()
        await db.refresh(order)
        return order

    async def mark_order_paid(
        self,
        db: AsyncSession,
        user_id,
        external_order_id: str,
        *,
        mpesa_receipt: str | None = None,
    ) -> CommerceOrder:
        order = await self._get_owned_order(db, user_id, external_order_id)
        order.payment_status = "paid"
        if mpesa_receipt is not None:
            order.mpesa_receipt = mpesa_receipt
        await db.commit()
        await db.refresh(order)
        return order

    async def list_orders(
        self,
        db: AsyncSession,
        user_id,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CommerceOrder]:
        result = await db.execute(
            select(CommerceOrder)
            .where(CommerceOrder.user_id == _as_uuid(user_id))
            .order_by(CommerceOrder.created_at.desc(), CommerceOrder.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_order(
        self,
        db: AsyncSession,
        user_id,
        external_order_id: str,
    ) -> CommerceOrder | None:
        result = await db.execute(
            select(CommerceOrder).where(
                CommerceOrder.user_id == _as_uuid(user_id),
                CommerceOrder.external_order_id == external_order_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_reservation(
        self,
        db: AsyncSession,
        user_id,
        reservation: dict,
    ) -> CommerceReservation:
        payload = dict(reservation or {})
        uid = _as_uuid(user_id)
        external_id = _require_text(
            payload, ("reservation_id", "external_reservation_id"), "reservation_id"
        )
        existing = await self._get_reservation(db, uid, external_id)
        values = self._reservation_values(payload, existing)
        if existing is None:
            row = CommerceReservation(
                user_id=uid,
                external_reservation_id=external_id,
                **values,
            )
            db.add(row)
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            row = existing
        await db.commit()
        await db.refresh(row)
        return row

    async def list_reservations(
        self,
        db: AsyncSession,
        user_id,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CommerceReservation]:
        result = await db.execute(
            select(CommerceReservation)
            .where(CommerceReservation.user_id == _as_uuid(user_id))
            .order_by(
                CommerceReservation.created_at.desc(),
                CommerceReservation.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def _get_owned_order(
        self,
        db: AsyncSession,
        user_id,
        external_order_id: str,
    ) -> CommerceOrder:
        order = await self.get_order(db, user_id, external_order_id)
        if order is None:
            raise CommerceOrderNotFound(str(external_order_id or ""))
        return order

    async def _get_reservation(
        self,
        db: AsyncSession,
        user_id,
        external_reservation_id: str,
    ) -> CommerceReservation | None:
        result = await db.execute(
            select(CommerceReservation).where(
                CommerceReservation.user_id == _as_uuid(user_id),
                CommerceReservation.external_reservation_id == external_reservation_id,
            )
        )
        return result.scalar_one_or_none()

    def _order_values(self, order: dict, existing: CommerceOrder | None) -> dict:
        creating = existing is None
        values: dict = {}

        self._assign_required_text(
            values, order, ("customer_name",), "customer_name", creating
        )
        self._assign_required_text(
            values, order, ("customer_phone",), "customer_phone", creating
        )
        self._assign_required_text(
            values, order, ("delivery_method",), "delivery_method", creating
        )

        if "status" in order:
            status = _text(order.get("status"), "") or (
                _DEFAULT_ORDER_STATUS if creating else ""
            )
            if not status:
                raise ValueError("status is required")
            values["status"] = _require_order_status(status)
        elif creating:
            values["status"] = _DEFAULT_ORDER_STATUS

        if "payment_status" in order:
            values["payment_status"] = (
                _text(order.get("payment_status"), "") or _DEFAULT_PAYMENT_STATUS
            )
        elif creating:
            values["payment_status"] = _DEFAULT_PAYMENT_STATUS

        if "currency" in order:
            values["currency"] = _text(order.get("currency"), "") or _DEFAULT_CURRENCY
        elif creating:
            values["currency"] = _DEFAULT_CURRENCY

        if "total" in order or creating:
            if "total" not in order:
                raise ValueError("total is required")
            values["total"] = _money(order.get("total"))

        if "items" in order or "line_items" in order or creating:
            items = order["items"] if "items" in order else order.get("line_items")
            if not isinstance(items, list):
                raise ValueError("items is required")
            values["line_items"] = list(items)

        for key in ("delivery_address", "notes", "payment_method"):
            if key in order:
                values[key] = _text(order.get(key), "") or None
            elif creating:
                values[key] = None

        if "mpesa_receipt" in order:
            values["mpesa_receipt"] = _text(order.get("mpesa_receipt"), "") or None

        if "raw_snapshot" in order:
            values["raw_snapshot"] = order["raw_snapshot"]
        else:
            values["raw_snapshot"] = dict(order)

        return values

    def _reservation_values(
        self,
        reservation: dict,
        existing: CommerceReservation | None,
    ) -> dict:
        creating = existing is None
        values: dict = {}

        self._assign_required_text(
            values, reservation, ("customer_name",), "customer_name", creating
        )
        self._assign_required_text(
            values, reservation, ("customer_phone",), "customer_phone", creating
        )
        self._assign_required_text(
            values, reservation, ("reservation_date",), "reservation_date", creating
        )
        self._assign_required_text(
            values, reservation, ("reservation_time",), "reservation_time", creating
        )

        if "party_size" in reservation or creating:
            if "party_size" not in reservation:
                raise ValueError("party_size is required")
            values["party_size"] = _party_size(reservation.get("party_size"))

        if "status" in reservation:
            values["status"] = (
                _text(reservation.get("status"), "") or _DEFAULT_RESERVATION_STATUS
            )
        elif creating:
            values["status"] = _DEFAULT_RESERVATION_STATUS

        if "notes" in reservation:
            values["notes"] = _text(reservation.get("notes"), "") or None
        elif creating:
            values["notes"] = None

        if "raw_snapshot" in reservation:
            values["raw_snapshot"] = reservation["raw_snapshot"]
        else:
            values["raw_snapshot"] = dict(reservation)

        return values

    def _assign_required_text(
        self,
        values: dict,
        data: dict,
        keys: tuple[str, ...],
        field: str,
        creating: bool,
    ) -> None:
        present = any(key in data for key in keys)
        if not present:
            if creating:
                raise ValueError(f"{field} is required")
            return
        values[field] = _require_text(data, keys, field)
