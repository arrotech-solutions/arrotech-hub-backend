"""CommerceRuntime cart, place, and cancel rails.

In-memory catalog and order ports. No database.
"""

import asyncio
from copy import deepcopy

import pytest

from src.services.commerce_policy import DEFAULT_COMMERCE_POLICY
from src.services.commerce_runtime import CommerceRuntime, CommerceState


class MemoryCatalog:
    def __init__(self, products: dict):
        self.products = deepcopy(products)
        self.quantity_writes: list[tuple[str, object]] = []
        self._lock = asyncio.Lock()

    async def get_product(self, product_id: str):
        row = self.products.get(str(product_id))
        return deepcopy(row) if row else None

    async def update_quantity(self, product_id: str, quantity):
        self.products[str(product_id)]["quantity"] = quantity
        self.quantity_writes.append((str(product_id), quantity))

    async def compare_and_set_quantity(self, product_id: str, expected, new) -> bool:
        async with self._lock:
            row = self.products.get(str(product_id))
            if row is None or row.get("quantity") != expected:
                return False
            row["quantity"] = new
            self.quantity_writes.append((str(product_id), new))
            return True


class MemoryOrders:
    def __init__(self):
        self.orders: dict = {}
        self.saves: list[dict] = []
        self.race = False
        self._lock = asyncio.Lock()

    async def save_order(self, order: dict) -> dict:
        stored = deepcopy(order)
        self.orders[stored["id"]] = stored
        self.saves.append(deepcopy(stored))
        return deepcopy(stored)

    async def get_order(self, order_id: str):
        if self.race:
            await asyncio.sleep(0)
        row = self.orders.get(order_id)
        return deepcopy(row) if row else None

    async def compare_and_set_status(
        self, order_id: str, expected_status: str, new_status: str
    ) -> bool:
        if self.race:
            await asyncio.sleep(0)
        async with self._lock:
            row = self.orders.get(order_id)
            if row is None or row.get("status") != expected_status:
                return False
            row["status"] = new_status
            self.saves.append(deepcopy(row))
            return True


class _ArriveBarrier:
    """Release once `parties` callers are inside `arrive`, before any of them continues."""

    def __init__(self, parties: int):
        self._parties = parties
        self._arrived = 0
        self._event = asyncio.Event()

    async def arrive(self):
        self._arrived += 1
        if self._arrived >= self._parties:
            self._event.set()
        await self._event.wait()


class RacingCatalog(MemoryCatalog):
    """Overlapping reads, plus a barrier on the non-atomic quantity write.

    Compare-and-set sleeps before taking the lock so both places compute
    ``quantity - qty`` from the same snapshot. A plain ``update_quantity``
    waits until every racer has entered, which is the lost-update shape.
    """

    def __init__(self, products: dict):
        super().__init__(products)
        self.race = False
        self._quantity_write_barrier: _ArriveBarrier | None = None

    def arm_quantity_writers(self, parties: int):
        self._quantity_write_barrier = _ArriveBarrier(parties)

    async def get_product(self, product_id: str):
        if self.race:
            await asyncio.sleep(0)
        return await super().get_product(product_id)

    async def update_quantity(self, product_id: str, quantity):
        barrier = self._quantity_write_barrier
        if barrier is not None:
            await barrier.arrive()
        await super().update_quantity(product_id, quantity)

    async def compare_and_set_quantity(self, product_id: str, expected, new) -> bool:
        if self.race:
            await asyncio.sleep(0)
        return await super().compare_and_set_quantity(product_id, expected, new)


def _policy(**overrides):
    policy = deepcopy(DEFAULT_COMMERCE_POLICY)
    policy.update(overrides)
    return policy


def _runtime(catalog, orders=None, **policy_overrides):
    return CommerceRuntime(
        policy=_policy(**policy_overrides),
        catalog_port=catalog,
        order_port=orders or MemoryOrders(),
    )


def _state(**overrides) -> CommerceState:
    state = CommerceState(
        cart_lines=[],
        fulfillment_method=None,
        checkout_fields={},
        order_id=None,
        payment_status=None,
        phase="cart",
    )
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def _product(
    product_id="sku-1",
    *,
    name="Chapati",
    price="80.00",
    availability="in_stock",
    quantity=5,
):
    return {
        "product_id": product_id,
        "name": name,
        "price": price,
        "availability": availability,
        "quantity": quantity,
    }


async def _add(runtime, state, product_id="sku-1", qty=2):
    return await runtime.apply(
        state,
        {"type": "add_line", "product_id": product_id, "qty": qty},
    )


async def _ready_to_place(runtime, state=None, product_id="sku-1", qty=2):
    state = _state() if state is None else state
    state, added = await _add(runtime, state, product_id, qty)
    assert added["ok"] is True
    state, fulfillment = await runtime.apply(
        state,
        {"type": "set_fulfillment", "fulfillment_method": "pickup"},
    )
    assert fulfillment["ok"] is True
    state, field = await runtime.apply(
        state,
        {
            "type": "set_checkout_field",
            "field": "customer_phone",
            "value": "254700000000",
        },
    )
    assert field["ok"] is True
    return state


@pytest.mark.asyncio
async def test_add_line_appends_product_and_qty():
    """Dropping the cart append would leave cart_lines empty."""
    catalog = MemoryCatalog({"sku-1": _product()})
    runtime = _runtime(catalog)
    state, result = await _add(runtime, _state(), qty=2)

    assert result["ok"] is True
    assert "error_code" not in result or result["error_code"] is None
    assert result["effects"] == []
    assert state.cart_lines == [{"product_id": "sku-1", "qty": 2}]
    assert state.phase == "cart"
    assert catalog.quantity_writes == []


@pytest.mark.asyncio
async def test_add_line_sums_same_product_and_blocks_combined_oversell():
    """Summing past tracked quantity must not leave the extra units in the cart."""
    catalog = MemoryCatalog({"sku-1": _product(quantity=3)})
    runtime = _runtime(catalog)
    state, first = await _add(runtime, _state(), qty=2)
    assert first["ok"] is True

    state, second = await _add(runtime, state, qty=2)

    assert second["ok"] is False
    assert second["error_code"] == "insufficient_quantity"
    assert second["effects"] == []
    assert state.cart_lines == [{"product_id": "sku-1", "qty": 2}]


@pytest.mark.asyncio
async def test_add_line_blocks_when_availability_is_not_sellable():
    """Treating out_of_stock as sellable would put the line in the cart."""
    catalog = MemoryCatalog(
        {"sku-1": _product(availability="out_of_stock", quantity=10)}
    )
    runtime = _runtime(catalog)
    before = _state()
    state, result = await _add(runtime, before, qty=1)

    assert result["ok"] is False
    assert result["error_code"] == "out_of_stock"
    assert result["effects"] == []
    assert state.cart_lines == []
    assert before.cart_lines == []


@pytest.mark.asyncio
async def test_add_line_blocks_unknown_product():
    catalog = MemoryCatalog({})
    runtime = _runtime(catalog)
    state, result = await _add(runtime, _state(), product_id="missing", qty=1)

    assert result["ok"] is False
    assert result["error_code"] == "unknown_product"
    assert state.cart_lines == []


@pytest.mark.asyncio
async def test_update_and_remove_line():
    """A no-op update/remove would leave the original qty in the cart."""
    catalog = MemoryCatalog({"sku-1": _product(quantity=5)})
    runtime = _runtime(catalog)
    state, _ = await _add(runtime, _state(), qty=2)

    state, updated = await runtime.apply(
        state,
        {"type": "update_line", "product_id": "sku-1", "qty": 4},
    )
    assert updated["ok"] is True
    assert state.cart_lines == [{"product_id": "sku-1", "qty": 4}]

    state, removed = await runtime.apply(
        state,
        {"type": "remove_line", "product_id": "sku-1"},
    )
    assert removed["ok"] is True
    assert state.cart_lines == []


@pytest.mark.asyncio
async def test_update_line_blocks_oversell_without_changing_cart():
    catalog = MemoryCatalog({"sku-1": _product(quantity=3)})
    runtime = _runtime(catalog)
    state, _ = await _add(runtime, _state(), qty=1)
    state, result = await runtime.apply(
        state,
        {"type": "update_line", "product_id": "sku-1", "qty": 4},
    )

    assert result["ok"] is False
    assert result["error_code"] == "insufficient_quantity"
    assert state.cart_lines == [{"product_id": "sku-1", "qty": 1}]


@pytest.mark.asyncio
async def test_set_fulfillment_rejects_method_outside_policy():
    """Accepting dine_in would ignore delivery_methods."""
    catalog = MemoryCatalog({"sku-1": _product()})
    runtime = _runtime(catalog, delivery_methods=["delivery", "pickup"])
    state, result = await runtime.apply(
        _state(),
        {"type": "set_fulfillment", "fulfillment_method": "dine_in"},
    )

    assert result["ok"] is False
    assert result["error_code"] == "fulfillment_not_allowed"
    assert state.fulfillment_method is None


@pytest.mark.asyncio
async def test_set_checkout_field_stores_value():
    catalog = MemoryCatalog({})
    runtime = _runtime(catalog)
    state, result = await runtime.apply(
        _state(),
        {"type": "set_checkout_field", "field": "customer_phone", "value": "254700000000"},
    )

    assert result["ok"] is True
    assert state.checkout_fields == {"customer_phone": "254700000000"}


@pytest.mark.asyncio
async def test_place_order_persists_order_and_reserve_effect():
    """Skipping persist_order would leave the order port empty."""
    catalog = MemoryCatalog({"sku-1": _product(price="80.00", quantity=5)})
    orders = MemoryOrders()
    runtime = _runtime(catalog, orders)
    state = await _ready_to_place(runtime, qty=2)

    state, result = await runtime.apply(state, {"type": "place_order"})

    assert result["ok"] is True
    assert state.phase == "placed"
    assert state.payment_status == "pending"
    assert state.order_id
    assert result["effects"] == [
        {"type": "reserve_inventory", "product_id": "sku-1", "qty": 2},
        {"type": "persist_order", "order_id": state.order_id},
    ]
    saved = orders.orders[state.order_id]
    assert saved["status"] == "pending"
    assert saved["payment_status"] == "pending"
    assert saved["fulfillment_method"] == "pickup"
    assert saved["checkout_fields"] == {"customer_phone": "254700000000"}
    assert saved["currency"] == "KES"
    assert saved["line_items"] == [
        {
            "product_id": "sku-1",
            "qty": 2,
            "name": "Chapati",
            "unit_price": "80.00",
        }
    ]
    assert saved["total"] == "160.00"


@pytest.mark.asyncio
async def test_place_order_rejects_empty_cart_and_missing_fulfillment():
    catalog = MemoryCatalog({"sku-1": _product()})
    orders = MemoryOrders()
    runtime = _runtime(catalog, orders)

    empty, empty_result = await runtime.apply(_state(), {"type": "place_order"})
    assert empty_result["ok"] is False
    assert empty_result["error_code"] == "empty_cart"
    assert empty.order_id is None
    assert orders.saves == []

    with_line, _ = await _add(runtime, _state(), qty=1)
    missing, missing_result = await runtime.apply(with_line, {"type": "place_order"})
    assert missing_result["ok"] is False
    assert missing_result["error_code"] == "fulfillment_required"
    assert missing.order_id is None
    assert orders.saves == []


@pytest.mark.asyncio
async def test_place_blocks_out_of_stock_without_partial_decrement():
    """A later unsellable line must not decrement the earlier line or persist."""
    catalog = MemoryCatalog(
        {
            "sku-1": _product(product_id="sku-1", quantity=4),
            "sku-2": _product(
                product_id="sku-2",
                name="Tea",
                price="50.00",
                availability="in_stock",
                quantity=4,
            ),
        }
    )
    orders = MemoryOrders()
    runtime = _runtime(catalog, orders)
    state, _ = await _add(runtime, _state(), "sku-1", 1)
    state, _ = await _add(runtime, state, "sku-2", 1)
    state, _ = await runtime.apply(
        state,
        {"type": "set_fulfillment", "fulfillment_method": "delivery"},
    )
    catalog.products["sku-2"]["availability"] = "out_of_stock"

    state, result = await runtime.apply(state, {"type": "place_order"})

    assert result["ok"] is False
    assert result["error_code"] == "out_of_stock"
    assert result["effects"] == []
    assert state.order_id is None
    assert state.phase == "cart"
    assert catalog.products["sku-1"]["quantity"] == 4
    assert catalog.products["sku-2"]["quantity"] == 4
    assert catalog.quantity_writes == []
    assert orders.saves == []


@pytest.mark.asyncio
async def test_place_decrements_tracked_quantity_and_cancel_restocks():
    """Place must take stock; cancel before preparing must put the same units back."""
    catalog = MemoryCatalog({"sku-1": _product(quantity=5)})
    orders = MemoryOrders()
    runtime = _runtime(catalog, orders)
    state = await _ready_to_place(runtime, qty=2)

    state, placed = await runtime.apply(state, {"type": "place_order"})
    assert placed["ok"] is True
    assert catalog.products["sku-1"]["quantity"] == 3

    state, cancelled = await runtime.apply(state, {"type": "cancel_order"})

    assert cancelled["ok"] is True
    assert cancelled["effects"] == [
        {
            "type": "persist_order",
            "order_id": state.order_id,
            "status": "cancelled",
        },
        {"type": "restock_inventory", "product_id": "sku-1", "qty": 2},
    ]
    assert state.phase == "cancelled"
    assert catalog.products["sku-1"]["quantity"] == 5
    assert orders.orders[state.order_id]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_untracked_quantity_is_not_written_on_place_or_cancel():
    """Null quantity means untracked; writing a number would invent stock."""
    catalog = MemoryCatalog({"sku-1": _product(quantity=None)})
    orders = MemoryOrders()
    runtime = _runtime(catalog, orders)
    state = await _ready_to_place(runtime, qty=2)

    state, placed = await runtime.apply(state, {"type": "place_order"})
    assert placed["ok"] is True
    assert placed["effects"] == [
        {"type": "persist_order", "order_id": state.order_id},
    ]
    assert catalog.products["sku-1"]["quantity"] is None
    assert catalog.quantity_writes == []

    state, cancelled = await runtime.apply(state, {"type": "cancel_order"})
    assert cancelled["ok"] is True
    assert catalog.products["sku-1"]["quantity"] is None
    assert catalog.quantity_writes == []
    assert cancelled["effects"] == [
        {
            "type": "persist_order",
            "order_id": state.order_id,
            "status": "cancelled",
        },
    ]


@pytest.mark.asyncio
async def test_cancel_rejected_once_status_reaches_preparing_and_stock_stays_decremented():
    """Allowing cancel at preparing would restock a kitchen that already started."""
    catalog = MemoryCatalog({"sku-1": _product(quantity=5)})
    orders = MemoryOrders()
    runtime = _runtime(catalog, orders, cancel_until_status="preparing")
    state = await _ready_to_place(runtime, qty=2)
    state, placed = await runtime.apply(state, {"type": "place_order"})
    assert placed["ok"] is True
    orders.orders[state.order_id]["status"] = "preparing"

    state, result = await runtime.apply(state, {"type": "cancel_order"})

    assert result["ok"] is False
    assert result["error_code"] == "cancel_not_allowed"
    assert result["effects"] == []
    assert state.phase == "placed"
    assert catalog.products["sku-1"]["quantity"] == 3
    assert orders.orders[state.order_id]["status"] == "preparing"


@pytest.mark.asyncio
async def test_cancel_allowed_while_confirmed_which_is_before_preparing():
    """confirmed is still before the default cutoff; rejecting it would trap the customer."""
    catalog = MemoryCatalog({"sku-1": _product(quantity=5)})
    orders = MemoryOrders()
    runtime = _runtime(catalog, orders)
    state = await _ready_to_place(runtime, qty=2)
    state, _ = await runtime.apply(state, {"type": "place_order"})
    orders.orders[state.order_id]["status"] = "confirmed"

    state, result = await runtime.apply(state, {"type": "cancel_order"})

    assert result["ok"] is True
    assert catalog.products["sku-1"]["quantity"] == 5
    assert orders.orders[state.order_id]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_second_cancel_does_not_restock_again():
    catalog = MemoryCatalog({"sku-1": _product(quantity=5)})
    orders = MemoryOrders()
    runtime = _runtime(catalog, orders)
    state = await _ready_to_place(runtime, qty=2)
    state, _ = await runtime.apply(state, {"type": "place_order"})
    state, first = await runtime.apply(state, {"type": "cancel_order"})
    assert first["ok"] is True

    state, second = await runtime.apply(state, {"type": "cancel_order"})

    assert second["ok"] is False
    assert second["error_code"] == "cancel_not_allowed"
    assert catalog.products["sku-1"]["quantity"] == 5


@pytest.mark.asyncio
async def test_second_place_does_not_decrement_again():
    catalog = MemoryCatalog({"sku-1": _product(quantity=5)})
    orders = MemoryOrders()
    runtime = _runtime(catalog, orders)
    state = await _ready_to_place(runtime, qty=2)
    state, first = await runtime.apply(state, {"type": "place_order"})
    assert first["ok"] is True

    state, second = await runtime.apply(state, {"type": "place_order"})

    assert second["ok"] is False
    assert second["error_code"] == "already_placed"
    assert second["effects"] == []
    assert catalog.products["sku-1"]["quantity"] == 3
    assert len(orders.saves) == 1


@pytest.mark.asyncio
async def test_cart_edits_rejected_after_place():
    catalog = MemoryCatalog({"sku-1": _product(quantity=5), "sku-2": _product(product_id="sku-2", name="Tea", quantity=5)})
    orders = MemoryOrders()
    runtime = _runtime(catalog, orders)
    state = await _ready_to_place(runtime, qty=2)
    state, placed = await runtime.apply(state, {"type": "place_order"})
    assert placed["ok"] is True
    lines = deepcopy(state.cart_lines)

    state, result = await runtime.apply(
        state,
        {"type": "add_line", "product_id": "sku-2", "qty": 1},
    )

    assert result["ok"] is False
    assert result["error_code"] == "already_placed"
    assert state.cart_lines == lines


@pytest.mark.asyncio
async def test_request_return_is_not_a_core_command():
    """Task 4 owns request_return; the core runtime must not accept it."""
    catalog = MemoryCatalog({})
    runtime = _runtime(catalog)
    state, result = await runtime.apply(_state(), {"type": "request_return"})

    assert result["ok"] is False
    assert result["error_code"] == "unknown_command"
    assert state.phase == "cart"


@pytest.mark.asyncio
async def test_concurrent_place_cannot_oversell_tracked_stock():
    """Two places that both read the same quantity must not both commit quantity - qty."""
    catalog = RacingCatalog({"sku-1": _product(quantity=5)})
    orders = MemoryOrders()
    runtime_a = _runtime(catalog, orders)
    runtime_b = _runtime(catalog, orders)
    state_a = await _ready_to_place(runtime_a, qty=3)
    state_b = await _ready_to_place(runtime_b, qty=3)
    catalog.arm_quantity_writers(2)
    catalog.race = True

    (state_a, result_a), (state_b, result_b) = await asyncio.gather(
        runtime_a.apply(state_a, {"type": "place_order"}),
        runtime_b.apply(state_b, {"type": "place_order"}),
    )

    results = (result_a, result_b)
    successes = [result for result in results if result["ok"]]
    assert len(successes) == 1
    assert [result["error_code"] for result in results if not result["ok"]] == [
        "insufficient_quantity"
    ]
    assert catalog.products["sku-1"]["quantity"] == 2
    assert len(orders.orders) == 1
    assert sum(1 for state in (state_a, state_b) if state.order_id) == 1


@pytest.mark.asyncio
async def test_concurrent_cancel_restocks_once():
    """Two cancels that both read pending must not both add the line quantity back."""
    catalog = RacingCatalog({"sku-1": _product(quantity=5)})
    orders = MemoryOrders()
    runtime_a = _runtime(catalog, orders)
    state = await _ready_to_place(runtime_a, qty=2)
    state, placed = await runtime_a.apply(state, {"type": "place_order"})
    assert placed["ok"] is True
    assert catalog.products["sku-1"]["quantity"] == 3

    runtime_b = _runtime(catalog, orders)
    other = state.copy()
    catalog.arm_quantity_writers(2)
    catalog.race = True
    orders.race = True
    (state, result_a), (other, result_b) = await asyncio.gather(
        runtime_a.apply(state, {"type": "cancel_order"}),
        runtime_b.apply(other, {"type": "cancel_order"}),
    )

    results = (result_a, result_b)
    assert sum(1 for result in results if result["ok"]) == 1
    assert [result["error_code"] for result in results if not result["ok"]] == [
        "cancel_not_allowed"
    ]
    assert catalog.products["sku-1"]["quantity"] == 5
    assert orders.orders[state.order_id]["status"] == "cancelled"
    phases = sorted(state.phase for state in (state, other))
    assert phases == ["cancelled", "placed"]
