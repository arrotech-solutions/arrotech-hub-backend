"""Conversational agent uses Arrotech catalog search and DB storage."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.models import CommerceOrder, CommerceReservation, User
from src.services.catalog_service import CatalogService
from src.services.conversational_agent_service import ConversationalAgentService


def _user(email: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        name="Merchant",
        password_hash="hash",
    )


def _products_from_search(result: dict) -> list:
    """READY_TO_DISPLAY_PRODUCTS JSON, or structured data.products."""
    data = result.get("data") or {}
    products = data.get("products")
    if isinstance(products, list) and products:
        return products
    text = result.get("result") or ""
    marker = "READY_TO_DISPLAY_PRODUCTS"
    if marker not in text:
        return []
    start = text.find("[", text.find(marker))
    if start < 0:
        return []
    decoder = json.JSONDecoder()
    parsed, _ = decoder.raw_decode(text[start:])
    return parsed if isinstance(parsed, list) else []


@pytest.mark.asyncio
async def test_search_products_uses_catalog_when_kb_id_empty(db_session):
    """Empty kb_id searches the merchant catalog; a seeded product is returned.

    Fails if blank kb_id still returns 'No knowledge base configured', if RAG
    ToolExecutor is required, or if the inserted product is missing from hits.
    """
    user = _user("agent-catalog@test.com")
    db_session.add(user)
    await db_session.commit()

    await CatalogService().create_product(
        db_session,
        user.id,
        {
            "name": "Simba Chips",
            "Price": "120",
            "Description": "Crispy maize snacks",
            "Category": "Snacks",
            "SKU": "SIMBA-50",
            "image_url": "https://cdn.example/simba.jpg",
            "Availability": "in_stock",
        },
    )

    agent = ConversationalAgentService()
    result = await agent._sub_search_products("chips", "", user, db_session)

    assert result.get("success") is True
    text = result.get("result") or ""
    assert "No knowledge base configured" not in text
    products = _products_from_search(result)
    assert any(p.get("name") == "Simba Chips" for p in products)
    simba = next(p for p in products if p.get("name") == "Simba Chips")
    assert simba.get("image_url") == "https://cdn.example/simba.jpg"

    miss = await agent._sub_search_products("xyzzy-no-match", "", user, db_session)
    miss_products = _products_from_search(miss)
    assert miss_products == []
    miss_text = (miss.get("result") or "").lower()
    assert "simba" not in miss_text
    assert "no product" in miss_text or "not found" in miss_text or "no match" in miss_text


@pytest.mark.asyncio
async def test_sub_search_products_normalizes_chiken_typo_when_kb_id_empty(
    db_session,
):
    """Blank kb_id catalog search returns Chicken for the Kenyan typo 'chiken'.

    Fails if _search_arrotech_catalog_products skips normalize_search_query:
    'chiken' does not prefix-match 'chicken' and is not a synonym group.
    Uses the real catalog and real normalizer; CatalogSearchService is not mocked.
    """
    from src.services.whatsapp_ordering_helpers import normalize_search_query

    assert "chicken" in normalize_search_query("chiken").lower()

    user = _user("agent-typo-chiken@test.com")
    db_session.add(user)
    await db_session.commit()

    await CatalogService().create_product(
        db_session,
        user.id,
        {
            "name": "Chicken",
            "Price": "350",
            "Description": "Grilled chicken",
            "Category": "Mains",
            "SKU": "CHK-1",
            "Availability": "in_stock",
        },
    )

    agent = ConversationalAgentService()
    result = await agent._sub_search_products("chiken", "", user, db_session)

    assert result.get("success") is True
    products = _products_from_search(result)
    assert any(p.get("name") == "Chicken" for p in products)


@pytest.mark.asyncio
async def test_persist_order_arrotech_db(db_session):
    """Persist order with provider arrotech_db writes a commerce_orders row.

    Fails if _persist_to_storage skips arrotech_db or writes no owned row.
    """
    user = _user("agent-order@test.com")
    db_session.add(user)
    await db_session.commit()

    order_data = {
        "order_id": "ORD-20261113-A1B2C3",
        "status": "pending",
        "customer": {
            "name": "Amina Wanjiku",
            "phone": "+254712345678",
        },
        "items": [
            {"name": "Simba Chips", "quantity": 2, "unit_price": 120.00},
            {"name": "Coca-Cola 500ml", "quantity": 1, "unit_price": 80.00},
        ],
        "subtotal": 320.00,
        "currency": "KES",
        "delivery_method": "delivery",
        "delivery_address": "Kilimani, Nairobi",
        "notes": "Leave at the gate",
    }

    agent = ConversationalAgentService()
    await agent._persist_to_storage(
        order_data=order_data,
        storage_config={"provider": "arrotech_db"},
        business_name="Test Kiosk",
        user=user,
        db=db_session,
        background_tasks=None,
    )

    rows = (
        await db_session.execute(
            select(CommerceOrder).where(CommerceOrder.user_id == user.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.external_order_id == "ORD-20261113-A1B2C3"
    assert row.customer_name == "Amina Wanjiku"
    assert row.customer_phone == "+254712345678"
    assert row.user_id == user.id


@pytest.mark.asyncio
async def test_persist_reservation_arrotech_db(db_session):
    """Persist reservation with provider arrotech_db writes a commerce_reservations row.

    Fails if reservation persist skips arrotech_db or writes no owned row.
    """
    user = _user("agent-res@test.com")
    db_session.add(user)
    await db_session.commit()

    reservation = {
        "reservation_id": "RES-20261113-F4E5D6",
        "status": "requested",
        "customer": {"name": "Brian Otieno", "phone": "+254700111222"},
        "reservation_date": "2026-11-20",
        "reservation_time": "19:30",
        "party_size": 4,
        "notes": "Window table",
    }

    agent = ConversationalAgentService()
    await agent._persist_reservation_to_storage(
        reservation=reservation,
        storage_config={"provider": "arrotech_db"},
        user=user,
        db=db_session,
    )

    rows = (
        await db_session.execute(
            select(CommerceReservation).where(CommerceReservation.user_id == user.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.external_reservation_id == "RES-20261113-F4E5D6"
    assert row.customer_name == "Brian Otieno"
    assert row.customer_phone == "+254700111222"
    assert row.user_id == user.id
    assert row.party_size == 4


def _order_payload(order_id: str, phone: str, name: str = "Customer") -> dict:
    return {
        "order_id": order_id,
        "customer_name": name,
        "customer_phone": phone,
        "status": "pending",
        "delivery_method": "pickup",
        "total": "80.00",
        "items": [{"name": "Coca-Cola 500ml", "qty": 1, "price": "80.00"}],
    }


@pytest.mark.asyncio
async def test_arrotech_db_history_and_ownership_survive_fifty_newer_orders(
    db_session,
):
    """Customer history and ownership still find an older order after 50 newer ones.

    Fails if _get_orders_from_arrotech_db uses list_orders(limit=50) as a
    customer index, so the owned order falls out of the newest-50 window.
    """
    from src.services.commerce_storage_service import CommerceStorageService

    user = _user("agent-history-window@test.com")
    db_session.add(user)
    await db_session.commit()

    svc = CommerceStorageService()
    customer_phone = "+254712345678"
    customer_order_id = "ORD-20261113-MINE"

    mine = await svc.upsert_order(
        db_session,
        user.id,
        _order_payload(customer_order_id, customer_phone, "Amina Wanjiku"),
    )
    mine.created_at = datetime.now(timezone.utc) - timedelta(days=2)
    await db_session.commit()

    for i in range(51):
        await svc.upsert_order(
            db_session,
            user.id,
            _order_payload(
                f"ORD-20261113-NEW{i:02d}",
                f"+2547000000{i:02d}",
                f"Other {i}",
            ),
        )

    agent = ConversationalAgentService()
    storage_config = {"provider": "arrotech_db"}

    history = await agent._sub_get_user_orders(
        {"customer_phone": customer_phone},
        storage_config,
        user,
        db_session,
    )
    assert history.get("success") is True
    history_ids = [str(o.get("Order ID") or "") for o in (history.get("orders") or [])]
    assert customer_order_id in history_ids

    owns = await agent._customer_owns_order(
        customer_order_id,
        customer_phone,
        storage_config,
        user,
        db_session,
    )
    assert owns is True
