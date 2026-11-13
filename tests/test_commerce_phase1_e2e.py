"""Phase 1 Kenya WhatsApp commerce sell-loop end-to-end.

Uses real CatalogSearchService, CommerceStorageService, and the library
ordering template. WhatsApp/STK are not invoked — the pinned steps do not
send a message.
"""

import json
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User
from src.routers.templates_router import WORKFLOW_TEMPLATES
from src.services.commerce_storage_service import CommerceStorageService
from src.services.conversational_agent_service import ConversationalAgentService


def _chips_payload(**overrides):
    data = {
        "name": "Simba Chips",
        "price": "120",
        "category": "Snacks",
        "sku": "SIMBA-50",
        "brand": "Simba",
        "description": "Crispy maize snacks",
        "availability": "in_stock",
    }
    data.update(overrides)
    return data


def _cola_payload(**overrides):
    data = {
        "name": "Coca-Cola 500ml",
        "price": "80",
        "category": "Drinks",
        "sku": "COKE-500",
        "brand": "Coca-Cola",
        "description": "Cold soda",
        "availability": "in_stock",
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


def _products_from_search(result: dict) -> list:
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
    parsed, _ = json.JSONDecoder().raw_decode(text[start:])
    return parsed if isinstance(parsed, list) else []


def _order_payload(**overrides):
    data = {
        "order_id": "ORD-20261113-E2E1",
        "customer_name": "Amina Wanjiku",
        "customer_phone": "+254712345678",
        "status": "pending",
        "delivery_method": "delivery",
        "delivery_address": "Kilimani, Nairobi",
        "total": "320.00",
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
        "reservation_id": "RES-20261113-E2E1",
        "customer_name": "Brian Otieno",
        "customer_phone": "+254700111222",
        "reservation_date": "2026-11-20",
        "reservation_time": "19:30",
        "party_size": 4,
        "notes": "Window table",
    }
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_phase1_sell_loop_search_paid_order_reservation_and_template(
    client: AsyncClient,
    auth_headers,
    test_user: User,
    db_session: AsyncSession,
    monkeypatch,
):
    """Pinned Phase 1 sell loop: catalog → empty-kb search → paid order → reservation → template.

    Fails if two products cannot be created, empty kb_id still calls RAG, chips
    or the named item is missing from hits, GET /api/commerce/orders does not
    show payment_status=paid, reservations list is empty, or the library
    template is not WhatsApp-only with storage default arrotech_db.
    """
    created_chips = await client.post(
        "/api/catalog/products",
        headers=auth_headers,
        json=_chips_payload(),
    )
    assert created_chips.status_code in (200, 201), created_chips.text
    assert created_chips.json().get("success") is True
    assert created_chips.json().get("data", {}).get("name") == "Simba Chips"

    created_cola = await client.post(
        "/api/catalog/products",
        headers=auth_headers,
        json=_cola_payload(),
    )
    assert created_cola.status_code in (200, 201), created_cola.text
    assert created_cola.json().get("success") is True
    assert created_cola.json().get("data", {}).get("name") == "Coca-Cola 500ml"

    listed_catalog = await client.get("/api/catalog/products", headers=auth_headers)
    assert listed_catalog.status_code == 200, listed_catalog.text
    catalog_names = [item.get("name") for item in _listed(listed_catalog.json(), "products")]
    assert "Simba Chips" in catalog_names
    assert "Coca-Cola 500ml" in catalog_names

    rag_must_not_run = AsyncMock(
        side_effect=AssertionError("RAG must not be called when kb_id is empty")
    )
    monkeypatch.setattr(
        "src.services.tool_executor.ToolExecutor.execute_tool",
        rag_must_not_run,
    )
    monkeypatch.setattr(
        "src.services.rag_pipeline_service.RAGPipelineService.rag_search_query",
        rag_must_not_run,
    )

    agent = ConversationalAgentService()
    chips_hit = await agent._sub_search_products("chips", "", test_user, db_session)
    named_hit = await agent._sub_search_products(
        "Simba Chips", "", test_user, db_session
    )

    assert rag_must_not_run.await_count == 0
    assert chips_hit.get("success") is True
    assert named_hit.get("success") is True
    chips_names = [p.get("name") for p in _products_from_search(chips_hit)]
    named_names = [p.get("name") for p in _products_from_search(named_hit)]
    assert "Simba Chips" in chips_names
    assert "Simba Chips" in named_names
    assert "No knowledge base configured" not in (chips_hit.get("result") or "")
    assert "No knowledge base configured" not in (named_hit.get("result") or "")

    svc = CommerceStorageService()
    await svc.upsert_order(db_session, test_user.id, _order_payload())
    paid = await svc.mark_order_paid(
        db_session, test_user.id, "ORD-20261113-E2E1", mpesa_receipt="QK123XYZ"
    )
    assert paid.payment_status == "paid"

    listed_orders = await client.get("/api/commerce/orders", headers=auth_headers)
    assert listed_orders.status_code == 200, listed_orders.text
    orders_body = listed_orders.json()
    assert orders_body.get("success") is True
    orders = _listed(orders_body, "orders")
    order = next(
        item
        for item in orders
        if (item.get("external_order_id") or item.get("order_id"))
        == "ORD-20261113-E2E1"
    )
    assert order.get("payment_status") == "paid"

    await svc.upsert_reservation(db_session, test_user.id, _reservation_payload())
    listed_reservations = await client.get(
        "/api/commerce/reservations", headers=auth_headers
    )
    assert listed_reservations.status_code == 200, listed_reservations.text
    reservations_body = listed_reservations.json()
    assert reservations_body.get("success") is True
    reservations = _listed(reservations_body, "reservations")
    assert reservations
    reservation_ids = [
        item.get("external_reservation_id") or item.get("reservation_id")
        for item in reservations
    ]
    assert "RES-20261113-E2E1" in reservation_ids

    template = next(t for t in WORKFLOW_TEMPLATES if t["id"] == "whatsapp_ordering_agent")
    assert template["required_connections"] == ["whatsapp"]
    assert template["variables"]["storage_provider"]["default"] == "arrotech_db"
