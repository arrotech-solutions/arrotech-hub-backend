"""Conversational agent uses Arrotech catalog search and DB storage."""

import json
import uuid

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
