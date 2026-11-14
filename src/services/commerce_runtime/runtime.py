"""Deterministic cart, checkout, place, and cancel transitions."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Optional, Protocol

from ..commerce_policy import DEFAULT_COMMERCE_POLICY
from ..order_service import ORDER_STATUSES
from .inventory import Inventory, InventoryError, _emit, _positive_qty
from .state import CommerceState

_CART_COMMANDS = frozenset(
    {
        "add_line",
        "update_line",
        "remove_line",
        "set_fulfillment",
        "set_checkout_field",
    }
)
_TERMINAL_STATUSES = frozenset({"cancelled", "refunded"})
_MAX_STATUS_CAS_ATTEMPTS = 32


class OrderPort(Protocol):
    async def save_order(self, order: dict) -> dict:
        """Insert or replace an order. Must return the stored order."""

    async def get_order(self, order_id: str) -> Optional[dict]:
        """Return the stored order, or None."""

    async def compare_and_set_status(
        self, order_id: str, expected_status: str, new_status: str
    ) -> bool:
        """Set status only when it is still ``expected_status``.

        The check and the write are one atomic step. Exactly one caller
        wins when two cancels race the same status.
        """


def _ok(state: CommerceState, effects: Optional[list] = None) -> tuple[CommerceState, dict]:
    return state, {"ok": True, "effects": list(effects or [])}


def _fail(state: CommerceState, code: str) -> tuple[CommerceState, dict]:
    return state, {"ok": False, "error_code": code, "effects": []}


def _money(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _money_str(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def _cancel_allowed(status: Any, cutoff: Any) -> bool:
    current = str(status or "").strip().lower()
    limit = str(cutoff or "").strip().lower()
    if current not in ORDER_STATUSES or limit not in ORDER_STATUSES:
        return False
    if current in _TERMINAL_STATUSES:
        return False
    return ORDER_STATUSES.index(current) < ORDER_STATUSES.index(limit)


class CommerceRuntime:
    def __init__(self, policy: dict, catalog_port, order_port: OrderPort):
        self.policy = policy or {}
        self.catalog_port = catalog_port
        self.order_port = order_port
        self.inventory = Inventory(catalog_port)

    async def apply(
        self, state: CommerceState, command: dict
    ) -> tuple[CommerceState, dict]:
        current = state.copy()
        command_type = ""
        if isinstance(command, dict):
            command_type = str(command.get("type") or "").strip().lower()
        handler = {
            "add_line": self._add_line,
            "update_line": self._update_line,
            "remove_line": self._remove_line,
            "set_fulfillment": self._set_fulfillment,
            "set_checkout_field": self._set_checkout_field,
            "place_order": self._place_order,
            "cancel_order": self._cancel_order,
        }.get(command_type)
        if handler is None:
            return _fail(current, "unknown_command")
        return await handler(current, command)

    def _reject_if_placed(self, state: CommerceState):
        if state.order_id:
            return _fail(state, "already_placed")
        return None

    async def _add_line(self, state: CommerceState, command: dict):
        locked = self._reject_if_placed(state)
        if locked:
            return locked
        product_id = str(command.get("product_id") or "").strip()
        if not product_id:
            return _fail(state, "unknown_product")
        try:
            existing = next(
                (line for line in state.cart_lines if line.get("product_id") == product_id),
                None,
            )
            requested = _positive_qty(command.get("qty"))
            if existing is None:
                total_qty = requested
            else:
                total_qty = _positive_qty(existing["qty"]) + requested
            await self.inventory.assert_sellable(product_id, total_qty)
        except InventoryError as exc:
            return _fail(state, exc.code)

        updated = state.copy()
        lines = []
        found = False
        emitted = _emit(_positive_qty(total_qty))
        for line in updated.cart_lines:
            if line.get("product_id") == product_id:
                lines.append({"product_id": product_id, "qty": emitted})
                found = True
            else:
                lines.append(dict(line))
        if not found:
            lines.append({"product_id": product_id, "qty": emitted})
        updated.cart_lines = lines
        return _ok(updated)

    async def _update_line(self, state: CommerceState, command: dict):
        locked = self._reject_if_placed(state)
        if locked:
            return locked
        product_id = str(command.get("product_id") or "").strip()
        if not any(line.get("product_id") == product_id for line in state.cart_lines):
            return _fail(state, "line_not_found")
        try:
            await self.inventory.assert_sellable(product_id, command.get("qty"))
        except InventoryError as exc:
            return _fail(state, exc.code)

        try:
            emitted = _emit(_positive_qty(command.get("qty")))
        except InventoryError as exc:
            return _fail(state, exc.code)
        updated = state.copy()
        updated.cart_lines = [
            {"product_id": product_id, "qty": emitted}
            if line.get("product_id") == product_id
            else dict(line)
            for line in updated.cart_lines
        ]
        return _ok(updated)

    async def _remove_line(self, state: CommerceState, command: dict):
        locked = self._reject_if_placed(state)
        if locked:
            return locked
        product_id = str(command.get("product_id") or "").strip()
        if not any(line.get("product_id") == product_id for line in state.cart_lines):
            return _fail(state, "line_not_found")
        updated = state.copy()
        updated.cart_lines = [
            dict(line)
            for line in updated.cart_lines
            if line.get("product_id") != product_id
        ]
        return _ok(updated)

    async def _set_fulfillment(self, state: CommerceState, command: dict):
        locked = self._reject_if_placed(state)
        if locked:
            return locked
        raw = str(command.get("fulfillment_method") or "").strip()
        match = self._match_fulfillment(raw)
        if match is None:
            return _fail(state, "fulfillment_not_allowed")
        updated = state.copy()
        updated.fulfillment_method = match
        return _ok(updated)

    async def _set_checkout_field(self, state: CommerceState, command: dict):
        locked = self._reject_if_placed(state)
        if locked:
            return locked
        field = command.get("field")
        if not isinstance(field, str) or not field.strip():
            return _fail(state, "invalid_checkout_field")
        updated = state.copy()
        updated.checkout_fields[field.strip()] = command.get("value")
        return _ok(updated)

    def _match_fulfillment(self, raw: str) -> Optional[str]:
        if not raw:
            return None
        for method in self.policy.get("delivery_methods") or []:
            text = str(method).strip()
            if text.lower() == raw.lower():
                return text
        return None

    async def _place_order(self, state: CommerceState, command: dict):
        del command
        if state.order_id:
            return _fail(state, "already_placed")
        if not state.cart_lines:
            return _fail(state, "empty_cart")
        if not state.fulfillment_method:
            return _fail(state, "fulfillment_required")
        if self._match_fulfillment(state.fulfillment_method) is None:
            return _fail(state, "fulfillment_not_allowed")

        snapshots = []
        try:
            for line in state.cart_lines:
                product = await self.inventory.assert_sellable(
                    line["product_id"], line["qty"]
                )
                snapshots.append((line, product))
        except InventoryError as exc:
            return _fail(state, exc.code)

        effects: list[dict] = []
        reserved: list[dict] = []
        try:
            for line, _product in snapshots:
                effect = await self.inventory.reserve(line["product_id"], line["qty"])
                reserved.append(line)
                if effect:
                    effects.append(effect)
            order = self._build_order(state, snapshots)
            await self.order_port.save_order(order)
        except InventoryError as exc:
            await self._undo_reserve(reserved)
            return _fail(state, exc.code)
        except Exception:
            await self._undo_reserve(reserved)
            return _fail(state, "persist_failed")

        effects.append({"type": "persist_order", "order_id": order["id"]})
        updated = state.copy()
        updated.order_id = order["id"]
        updated.payment_status = "pending"
        updated.phase = "placed"
        return _ok(updated, effects)

    def _build_order(self, state: CommerceState, snapshots: list) -> dict:
        line_items = []
        total = Decimal("0.00")
        for line, product in snapshots:
            qty = Decimal(str(line["qty"]))
            unit = _money(product.get("price"))
            total += unit * qty
            line_items.append(
                {
                    "product_id": str(line["product_id"]),
                    "qty": int(qty) if qty == qty.to_integral_value() else float(qty),
                    "name": str(product.get("name") or ""),
                    "unit_price": _money_str(unit),
                }
            )
        return {
            "id": uuid.uuid4().hex,
            "status": "pending",
            "payment_status": "pending",
            "fulfillment_method": state.fulfillment_method,
            "checkout_fields": dict(state.checkout_fields),
            "currency": "KES",
            "line_items": line_items,
            "total": _money_str(total),
        }

    async def _undo_reserve(self, lines: list[dict]) -> None:
        for line in reversed(lines):
            try:
                await self.inventory.restock(line["product_id"], line["qty"])
            except InventoryError:
                continue

    async def _cancel_order(self, state: CommerceState, command: dict):
        del command
        if not state.order_id:
            return _fail(state, "no_order")
        cutoff = self.policy.get("cancel_until_status") or DEFAULT_COMMERCE_POLICY[
            "cancel_until_status"
        ]
        claimed = await self._claim_cancel(state.order_id, cutoff)
        if isinstance(claimed, str):
            return _fail(state, claimed)

        order, previous_status = claimed
        line_items = list(order.get("line_items") or [])
        effects: list[dict] = [
            {
                "type": "persist_order",
                "order_id": state.order_id,
                "status": "cancelled",
            }
        ]
        restocked: list[dict] = []
        try:
            for line in line_items:
                effect = await self.inventory.restock(line["product_id"], line["qty"])
                restocked.append(line)
                if effect:
                    effects.append(effect)
        except InventoryError as exc:
            await self._undo_restock(restocked)
            await self.order_port.compare_and_set_status(
                state.order_id, "cancelled", previous_status
            )
            return _fail(state, exc.code)
        except Exception:
            await self._undo_restock(restocked)
            await self.order_port.compare_and_set_status(
                state.order_id, "cancelled", previous_status
            )
            return _fail(state, "persist_failed")

        updated = state.copy()
        updated.phase = "cancelled"
        return _ok(updated, effects)

    async def _claim_cancel(self, order_id: str, cutoff: Any):
        """Move the order to cancelled once. Returns (order, previous) or an error code.

        Restock runs only after this wins, so a second cancel cannot add stock.
        """
        for _ in range(_MAX_STATUS_CAS_ATTEMPTS):
            order = await self.order_port.get_order(order_id)
            if not order:
                return "no_order"
            status = str(order.get("status") or "")
            if not _cancel_allowed(status, cutoff):
                return "cancel_not_allowed"
            won = await self.order_port.compare_and_set_status(
                order_id, status, "cancelled"
            )
            if won:
                return order, status
        return "cancel_not_allowed"

    async def _undo_restock(self, lines: list[dict]) -> None:
        for line in reversed(lines):
            try:
                await self.inventory.adjust_tracked(
                    line["product_id"], -Decimal(str(line["qty"]))
                )
            except InventoryError:
                continue


# Re-exported so callers can see which cart commands this runtime owns.
CORE_COMMANDS = _CART_COMMANDS | frozenset({"place_order", "cancel_order"})
