"""Database catalog and order ports for CommerceRuntime.

Quantity and status changes are one conditional UPDATE. A second caller
that still expects the old value loses and writes nothing.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import CatalogProduct, CommerceOrder
from ..commerce_storage_service import CommerceStorageService


def _uuid(value: Any) -> Optional[uuid.UUID]:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _product_dict(row: CatalogProduct) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "price": row.price,
        "quantity": row.quantity,
        "availability": row.availability,
    }


class DbCatalogPort:
    def __init__(self, db: AsyncSession, user_id: Any):
        self.db = db
        self.user_id = _uuid(user_id)

    async def get_product(self, product_id: str) -> Optional[dict]:
        pid = _uuid(product_id)
        if pid is None or self.user_id is None:
            return None
        result = await self.db.execute(
            select(CatalogProduct).where(
                CatalogProduct.user_id == self.user_id,
                CatalogProduct.id == pid,
            )
        )
        row = result.scalar_one_or_none()
        return _product_dict(row) if row else None

    async def find_product(self, product_id: str = "", name: str = "") -> Optional[dict]:
        found = await self.get_product(product_id) if product_id else None
        if found or not name or self.user_id is None:
            return found
        result = await self.db.execute(
            select(CatalogProduct).where(
                CatalogProduct.user_id == self.user_id,
                func.lower(CatalogProduct.name) == name.strip().lower(),
            )
        )
        row = result.scalars().first()
        return _product_dict(row) if row else None

    async def compare_and_set_quantity(self, product_id: str, expected: Any, new: Any) -> bool:
        pid = _uuid(product_id)
        if pid is None or self.user_id is None:
            return False
        expected_match = (
            CatalogProduct.quantity.is_(None)
            if expected is None
            else CatalogProduct.quantity == expected
        )
        result = await self.db.execute(
            update(CatalogProduct)
            .where(
                CatalogProduct.user_id == self.user_id,
                CatalogProduct.id == pid,
                expected_match,
            )
            .values(quantity=new)
        )
        await self.db.commit()
        return result.rowcount == 1


class DbOrderPort:
    def __init__(self, db: AsyncSession, user_id: Any):
        self.db = db
        self.user_id = user_id
        self._storage = CommerceStorageService()

    async def save_order(self, order: dict) -> dict:
        fields = order.get("checkout_fields") or {}
        payload = {
            "order_id": order.get("id") or order.get("order_id"),
            "customer_name": fields.get("customer_name") or fields.get("name") or "Customer",
            "customer_phone": str(fields.get("customer_phone") or fields.get("phone") or ""),
            "delivery_method": order.get("fulfillment_method") or "pickup",
            "delivery_address": fields.get("delivery_address") or "",
            "status": order.get("status") or "pending",
            "payment_status": order.get("payment_status") or "pending",
            "currency": order.get("currency") or "KES",
            "total": order.get("total") or "0.00",
            "line_items": list(order.get("line_items") or []),
            "notes": fields.get("notes") or None,
            "raw_snapshot": dict(order),
        }
        row = await self._storage.upsert_order(self.db, self.user_id, payload)
        stored = await self.get_order(row.external_order_id)
        return stored or {"id": row.external_order_id, "status": row.status}

    async def get_order(self, order_id: str) -> Optional[dict]:
        row = await self._storage.get_order(self.db, self.user_id, str(order_id))
        if row is None:
            return None
        return {
            "id": row.external_order_id,
            "status": row.status,
            "payment_status": row.payment_status,
            "line_items": list(row.line_items or []),
            "total": str(row.total),
            "fulfillment_method": row.delivery_method,
            "customer_phone": row.customer_phone,
            "customer_name": row.customer_name,
            "mpesa_receipt": row.mpesa_receipt,
        }

    async def compare_and_set_status(
        self, order_id: str, expected_status: str, new_status: str
    ) -> bool:
        user_id = _uuid(self.user_id)
        if user_id is None:
            return False
        result = await self.db.execute(
            update(CommerceOrder)
            .where(
                CommerceOrder.user_id == user_id,
                CommerceOrder.external_order_id == str(order_id),
                CommerceOrder.status == expected_status,
            )
            .values(status=new_status)
        )
        await self.db.commit()
        return result.rowcount == 1
