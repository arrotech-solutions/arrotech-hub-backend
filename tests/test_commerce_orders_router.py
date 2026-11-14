"""Commerce orders and reservations HTTP API for Hub ops."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User
from src.services.commerce_storage_service import CommerceStorageService


def _order_payload(**overrides):
    data = {
        "order_id": "ORD-20261113-HUB1",
        "customer_name": "Amina Wanjiku",
        "customer_phone": "+254712345678",
        "status": "pending",
        "delivery_method": "delivery",
        "delivery_address": "Kilimani, Nairobi",
        "total": "450.00",
        "items": [
            {"name": "Simba Chips", "qty": 2, "price": "120.00"},
            {"name": "Coca-Cola 500ml", "qty": 1, "price": "80.00"},
        ],
        "notes": "Leave at the gate",
    }
    data.update(overrides)
    return data


def _reservation_payload(**overrides):
    data = {
        "reservation_id": "RES-20261113-HUB1",
        "customer_name": "Brian Otieno",
        "customer_phone": "+254700111222",
        "reservation_date": "2026-11-20",
        "reservation_time": "19:30",
        "party_size": 4,
        "notes": "Window table",
    }
    data.update(overrides)
    return data


def _listed(body: dict, *keys: str):
    data = body.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            items = data.get(key)
            if isinstance(items, list):
                return items
        return data.get("items") or []
    return []


def _entity(body: dict):
    data = body.get("data")
    return data if isinstance(data, dict) else {}


@pytest.mark.asyncio
async def test_list_orders_returns_caller_orders_with_status_payment_and_items(
    client: AsyncClient,
    auth_headers,
    auth_headers_2,
    test_user: User,
    test_user_2: User,
    db_session: AsyncSession,
):
    """GET /api/commerce/orders and GET detail return the caller's order fields.

    Fails if the commerce orders router is missing, list omits status /
    payment_status / total / customer / line items, or another user's order
    is visible.
    """
    svc = CommerceStorageService()
    await svc.upsert_order(db_session, test_user.id, _order_payload())
    await svc.mark_order_paid(
        db_session, test_user.id, "ORD-20261113-HUB1", mpesa_receipt="QK123XYZ"
    )
    await svc.upsert_order(
        db_session,
        test_user_2.id,
        _order_payload(order_id="ORD-OTHER-USER", customer_name="Other Merchant"),
    )

    listed = await client.get("/api/commerce/orders", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body.get("success") is True
    orders = _listed(body, "orders")
    ids = [item.get("external_order_id") or item.get("order_id") for item in orders]
    assert "ORD-20261113-HUB1" in ids
    assert "ORD-OTHER-USER" not in ids
    order = next(
        item
        for item in orders
        if (item.get("external_order_id") or item.get("order_id")) == "ORD-20261113-HUB1"
    )
    assert order.get("status") == "pending"
    assert order.get("payment_status") == "paid"
    assert "450" in str(order.get("total"))
    assert order.get("customer_name") == "Amina Wanjiku"
    assert "+254712345678" in str(order.get("customer_phone") or "")
    names = [line.get("name") for line in (order.get("line_items") or order.get("items") or [])]
    assert "Simba Chips" in names
    assert "Coca-Cola 500ml" in names

    other_list = await client.get("/api/commerce/orders", headers=auth_headers_2)
    assert other_list.status_code == 200, other_list.text
    other_ids = [
        item.get("external_order_id") or item.get("order_id")
        for item in _listed(other_list.json(), "orders")
    ]
    assert "ORD-20261113-HUB1" not in other_ids
    assert "ORD-OTHER-USER" in other_ids

    detail = await client.get(
        "/api/commerce/orders/ORD-20261113-HUB1", headers=auth_headers
    )
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert detail_body.get("success") is True
    found = _entity(detail_body)
    assert found.get("status") == "pending"
    assert found.get("payment_status") == "paid"
    assert "450" in str(found.get("total"))
    assert found.get("customer_name") == "Amina Wanjiku"
    assert "+254712345678" in str(found.get("customer_phone") or "")
    detail_names = [
        line.get("name") for line in (found.get("line_items") or found.get("items") or [])
    ]
    assert "Simba Chips" in detail_names

    missing = await client.get(
        "/api/commerce/orders/ORD-20261113-HUB1", headers=auth_headers_2
    )
    assert missing.status_code == 404, missing.text


@pytest.mark.asyncio
async def test_patch_order_status_allows_transition_and_rejects_illegal(
    client: AsyncClient,
    auth_headers,
    test_user: User,
    db_session: AsyncSession,
):
    """PATCH /api/commerce/orders/{id} {status} only when STATUS_TRANSITIONS allow it.

    Fails if pending→shipped is written, pending→confirmed is rejected, a
    missing order is not 404, or the row is inserted on a miss.
    """
    svc = CommerceStorageService()
    await svc.upsert_order(db_session, test_user.id, _order_payload())

    illegal = await client.patch(
        "/api/commerce/orders/ORD-20261113-HUB1",
        headers=auth_headers,
        json={"status": "shipped"},
    )
    assert illegal.status_code == 400, illegal.text
    listed = await client.get("/api/commerce/orders", headers=auth_headers)
    order = next(
        item
        for item in _listed(listed.json(), "orders")
        if (item.get("external_order_id") or item.get("order_id")) == "ORD-20261113-HUB1"
    )
    assert order.get("status") == "pending"

    allowed = await client.patch(
        "/api/commerce/orders/ORD-20261113-HUB1",
        headers=auth_headers,
        json={"status": "confirmed"},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json().get("success") is True
    patched = _entity(allowed.json())
    assert patched.get("status") == "confirmed"

    relisted = await client.get("/api/commerce/orders", headers=auth_headers)
    updated = next(
        item
        for item in _listed(relisted.json(), "orders")
        if (item.get("external_order_id") or item.get("order_id")) == "ORD-20261113-HUB1"
    )
    assert updated.get("status") == "confirmed"

    missing = await client.patch(
        "/api/commerce/orders/ORD-MISSING",
        headers=auth_headers,
        json={"status": "confirmed"},
    )
    assert missing.status_code == 404, missing.text
    still_missing = await client.get(
        "/api/commerce/orders/ORD-MISSING", headers=auth_headers
    )
    assert still_missing.status_code == 404, still_missing.text


@pytest.mark.asyncio
async def test_list_reservations_returns_caller_reservations(
    client: AsyncClient,
    auth_headers,
    auth_headers_2,
    test_user: User,
    test_user_2: User,
    db_session: AsyncSession,
):
    """GET /api/commerce/reservations lists the caller's reservations only.

    Fails if the route is missing, reservation fields are omitted, or another
    user's reservation is visible.
    """
    svc = CommerceStorageService()
    await svc.upsert_reservation(db_session, test_user.id, _reservation_payload())
    await svc.upsert_reservation(
        db_session,
        test_user_2.id,
        _reservation_payload(
            reservation_id="RES-OTHER-USER", customer_name="Other Guest"
        ),
    )

    listed = await client.get("/api/commerce/reservations", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body.get("success") is True
    reservations = _listed(body, "reservations")
    ids = [
        item.get("external_reservation_id") or item.get("reservation_id")
        for item in reservations
    ]
    assert "RES-20261113-HUB1" in ids
    assert "RES-OTHER-USER" not in ids
    reservation = next(
        item
        for item in reservations
        if (item.get("external_reservation_id") or item.get("reservation_id"))
        == "RES-20261113-HUB1"
    )
    assert reservation.get("customer_name") == "Brian Otieno"
    assert "+254700111222" in str(reservation.get("customer_phone") or "")
    assert reservation.get("reservation_date") == "2026-11-20"
    assert reservation.get("reservation_time") == "19:30"
    assert reservation.get("party_size") == 4
    assert reservation.get("status") == "confirmed"

    other_list = await client.get("/api/commerce/reservations", headers=auth_headers_2)
    assert other_list.status_code == 200, other_list.text
    other_ids = [
        item.get("external_reservation_id") or item.get("reservation_id")
        for item in _listed(other_list.json(), "reservations")
    ]
    assert "RES-20261113-HUB1" not in other_ids
    assert "RES-OTHER-USER" in other_ids
