"""Catalog availability checks and tracked-quantity reserve/restock.

Quantity ``None`` means the merchant does not track stock. Those products
are never decremented or incremented. A non-null quantity is a hard cap:
this module never leaves stock negative.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Protocol


class InventoryError(Exception):
    """Sellability or quantity rule failed. ``code`` is the runtime error_code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class CatalogPort(Protocol):
    async def get_product(self, product_id: str) -> Optional[dict]:
        """Return the product dict, or None when it does not exist."""

    async def update_quantity(self, product_id: str, quantity: Any) -> None:
        """Persist a tracked quantity. Not called when quantity is null."""


_SELLABLE_AVAILABILITY = frozenset({"in_stock"})


def _positive_qty(qty: Any) -> Decimal:
    if isinstance(qty, bool) or qty is None:
        raise InventoryError("invalid_quantity")
    try:
        number = Decimal(str(qty))
    except (InvalidOperation, ValueError) as exc:
        raise InventoryError("invalid_quantity") from exc
    if not number.is_finite() or number <= 0:
        raise InventoryError("invalid_quantity")
    return number


def _emit(number: Decimal) -> int | float:
    integral = number.to_integral_value()
    if number == integral:
        return int(integral)
    return float(number)


class Inventory:
    def __init__(self, catalog_port: CatalogPort):
        self.catalog = catalog_port

    async def assert_sellable(self, product_id: str, qty: Any) -> dict:
        product = await self.catalog.get_product(str(product_id))
        if product is None:
            raise InventoryError("unknown_product")
        availability = str(product.get("availability") or "").strip().lower()
        if availability not in _SELLABLE_AVAILABILITY:
            raise InventoryError("out_of_stock")
        requested = _positive_qty(qty)
        available = product.get("quantity")
        if available is not None and requested > Decimal(str(available)):
            raise InventoryError("insufficient_quantity")
        return product

    async def reserve(self, product_id: str, qty: Any) -> Optional[dict]:
        """Decrement tracked quantity. Returns an effect, or None if untracked."""
        await self.assert_sellable(product_id, qty)
        requested = _positive_qty(qty)
        wrote = await self.adjust_tracked(product_id, -requested)
        if wrote is None:
            return None
        return {
            "type": "reserve_inventory",
            "product_id": str(product_id),
            "qty": _emit(requested),
        }

    async def restock(self, product_id: str, qty: Any) -> Optional[dict]:
        """Put tracked units back. No-op when quantity is null."""
        amount = _positive_qty(qty)
        wrote = await self.adjust_tracked(product_id, amount)
        if wrote is None:
            return None
        return {
            "type": "restock_inventory",
            "product_id": str(product_id),
            "qty": _emit(amount),
        }

    async def adjust_tracked(self, product_id: str, delta: Any) -> Optional[int | float]:
        """Add ``delta`` to a tracked quantity without an availability check.

        Used for restock and for rolling back a reserve/restock when persist
        fails. Returns the new quantity, or None when quantity is null.
        """
        product = await self.catalog.get_product(str(product_id))
        if product is None:
            raise InventoryError("unknown_product")
        available = product.get("quantity")
        if available is None:
            return None
        change = Decimal(str(delta))
        if not change.is_finite():
            raise InventoryError("invalid_quantity")
        remaining = Decimal(str(available)) + change
        if remaining < 0:
            raise InventoryError("insufficient_quantity")
        emitted = _emit(remaining)
        await self.catalog.update_quantity(str(product_id), emitted)
        return emitted
