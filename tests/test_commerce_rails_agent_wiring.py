"""Ordering-agent mutations go through CommerceRuntime when rails are on."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.models import CatalogProduct, CommerceOrder, CommerceReturn
from src.services.commerce_policy import upsert_policy
from src.services.conversation_context_manager import (
    ConversationSession,
    context_manager,
)
from src.services.conversational_agent_service import ConversationalAgentService


def _session(session_key: str, owner: str, phone: str) -> ConversationSession:
    return ConversationSession(
        session_key=session_key,
        platform="whatsapp",
        owner_user_id=owner,
        sender_id=phone,
        messages=[],
        metadata={},
    )


def _bind_session(session: ConversationSession):
    async def fake_get(key):
        return session if key == session.session_key else None

    async def fake_update(key, updates):
        if key == session.session_key:
            session.metadata.update(updates)

    async def fake_save(sess):
        return None

    return (
        patch.object(context_manager, "get_session_by_key", fake_get),
        patch.object(context_manager, "update_session_metadata", fake_update),
        patch.object(context_manager, "save_session", fake_save),
    )


async def _tool(agent, user, db, session_key, name, arguments, **config):
    business = {"order_type": "retail", "commerce_rails_enabled": True}
    business.update(config)
    return await agent._execute_sub_tool(
        tool_name=name,
        arguments=arguments,
        kb_id="",
        order_type=business.get("order_type", "retail"),
        currency="KES",
        business_name="Shop",
        storage_config={"provider": "none"},
        session_key=session_key,
        user=user,
        db=db,
        default_customer_phone="254700000001",
        default_customer_name="Asha",
        business_config=business,
    )


@pytest.mark.asyncio
async def test_rails_place_order_goes_through_runtime_not_legacy(db_session, test_user):
    product = CatalogProduct(
        user_id=test_user.id,
        name="Tea",
        price=Decimal("100.00"),
        description="Tea",
        category="drinks",
        sku="TEA",
        brand="Shop",
        quantity=Decimal("5"),
        unit="pcs",
        condition="new",
        image_url="",
        availability="in_stock",
        search_text="tea",
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)

    phone = "254700000001"
    session_key = f"ccm:whatsapp:{test_user.id}:{phone}"
    session = _session(session_key, str(test_user.id), phone)
    agent = ConversationalAgentService()
    patches = _bind_session(session)

    with patches[0], patches[1], patches[2], patch.object(
        agent.order_service, "handle_operation", new_callable=AsyncMock
    ) as legacy:
        added = await _tool(
            agent,
            test_user,
            db_session,
            session_key,
            "manage_cart",
            {"action": "add", "product_id": str(product.id), "product_name": "Tea", "quantity": 1},
        )
        assert added["success"] is True
        placed = await _tool(
            agent,
            test_user,
            db_session,
            session_key,
            "create_order",
            {
                "customer_name": "Asha",
                "customer_phone": phone,
                "items": [{"name": "Tea", "quantity": 1, "unit_price": 1}],
                "delivery_method": "pickup",
            },
        )

    legacy.assert_not_called()
    assert placed["success"] is True
    effects = placed.get("effects") or []
    assert any(effect.get("type") == "persist_order" for effect in effects)
    await db_session.refresh(product)
    assert int(product.quantity) == 4
    stored = await db_session.execute(
        select(CommerceOrder).where(CommerceOrder.user_id == test_user.id)
    )
    orders = list(stored.scalars().all())
    assert len(orders) == 1
    assert orders[0].total == Decimal("100.00")


@pytest.mark.asyncio
async def test_rails_off_cart_stays_on_legacy_path(db_session, test_user):
    agent = ConversationalAgentService()
    session_key = f"ccm:whatsapp:{test_user.id}:254700000001"
    with patch(
        "src.services.commerce_runtime.runtime.CommerceRuntime.apply",
        new_callable=AsyncMock,
    ) as apply_cmd, patch.object(
        context_manager, "add_cart_item", new_callable=AsyncMock, return_value=[]
    ) as add_item:
        result = await _tool(
            agent,
            test_user,
            db_session,
            session_key,
            "manage_cart",
            {"action": "add", "product_name": "Tea", "quantity": 1, "unit_price": 50},
            commerce_rails_enabled=False,
            order_type="food",
        )
    apply_cmd.assert_not_called()
    add_item.assert_awaited()
    assert result["success"] is True


def test_non_ordering_templates_do_not_enable_rails():
    from src.services.whatsapp_ordering_helpers import normalize_commerce_rails_enabled

    policy = {"commerce_rails_enabled": True}
    assert normalize_commerce_rails_enabled(
        {"order_type": "rent_collection", "commerce_rails_enabled": True}, policy
    ) is False
    assert normalize_commerce_rails_enabled(
        {"order_type": "real_estate", "commerce_rails_enabled": True}, policy
    ) is False
    assert normalize_commerce_rails_enabled(
        {"order_type": "support", "agent_mode": "support", "commerce_rails_enabled": True},
        policy,
    ) is False
    assert normalize_commerce_rails_enabled(
        {"order_type": "food", "commerce_rails_enabled": False}, policy
    ) is False
    assert normalize_commerce_rails_enabled(
        {"order_type": "retail", "commerce_rails_enabled": True}, policy
    ) is True


@pytest.mark.asyncio
async def test_runtime_error_returns_customer_message_and_handoff(db_session, test_user):
    agent = ConversationalAgentService()
    session_key = f"ccm:whatsapp:{test_user.id}:254700000001"
    with patch(
        "src.services.commerce_runtime.runtime.CommerceRuntime.apply",
        new_callable=AsyncMock,
        side_effect=RuntimeError("db down"),
    ):
        result = await _tool(
            agent,
            test_user,
            db_session,
            session_key,
            "create_order",
            {
                "customer_name": "Asha",
                "customer_phone": "254700000001",
                "items": [],
                "delivery_method": "pickup",
            },
        )
    message = result.get("verbatim_customer_message") or ""
    assert message.strip()
    assert result.get("human_handoff") is True
    assert "refunded" not in message.lower()


@pytest.mark.asyncio
async def test_offline_refund_sends_stored_customer_message(db_session, test_user):
    now = datetime.now(timezone.utc)
    order = CommerceOrder(
        user_id=test_user.id,
        external_order_id="ORD-REFUND-1",
        customer_name="Asha",
        customer_phone="254700000001",
        status="delivered",
        payment_status="paid",
        currency="KES",
        total=Decimal("500.00"),
        line_items=[{"product_id": "tea", "qty": 1, "name": "Tea", "unit_price": "500.00"}],
        delivery_method="pickup",
        created_at=now,
    )
    db_session.add(order)
    await db_session.commit()
    await upsert_policy(
        db_session,
        test_user.id,
        {
            "commerce_rails_enabled": True,
            "auto_approve_enabled": True,
            "auto_approve_max_amount_kes": 1000,
        },
    )

    agent = ConversationalAgentService()
    phone = "254700000001"
    session_key = f"ccm:whatsapp:{test_user.id}:{phone}"
    session = _session(session_key, str(test_user.id), phone)
    patches = _bind_session(session)
    llm_invention = "You have been refunded. Receipt ABC."

    class ToolTurn:
        error = None
        content = ""
        tools_called = [
            {
                "name": "request_return",
                "arguments": {
                    "order_external_id": "ORD-REFUND-1",
                    "phone": phone,
                    "reason_code": "damaged",
                    "amount": "100.00",
                },
            }
        ]

    class FinalTurn:
        error = None
        content = llm_invention
        tools_called = []

    with patches[0], patches[1], patches[2], patch(
        "src.services.commerce_refund_service.payout_credentials_configured",
        return_value=False,
    ), patch.object(
        agent.llm_service, "chat_completion", new_callable=AsyncMock
    ) as chat:
        chat.side_effect = [ToolTurn(), FinalTurn()]
        result = await agent.execute(
            user_message="I want to return this",
            session_key=session_key,
            business_config={
                "order_type": "retail",
                "commerce_rails_enabled": True,
                "business_name": "Shop",
            },
            user=test_user,
            db=db_session,
        )

    stored = await db_session.execute(
        select(CommerceReturn).where(CommerceReturn.user_id == test_user.id)
    )
    row = stored.scalar_one()
    snapshot_message = (row.raw_snapshot or {}).get("customer_message")
    assert row.status == "refund_pending"
    assert snapshot_message
    assert result["response_text"] == snapshot_message
    assert result["response_text"] != llm_invention
    assert "refunded" not in result["response_text"].lower()


@pytest.mark.asyncio
async def test_catalog_and_order_cas_are_single_conditional_updates(db_session, test_user):
    from src.services.commerce_runtime.db_ports import DbCatalogPort, DbOrderPort

    product = CatalogProduct(
        user_id=test_user.id,
        name="Tea",
        price=Decimal("100.00"),
        description="Tea",
        category="drinks",
        sku="TEA2",
        brand="Shop",
        quantity=Decimal("5"),
        unit="pcs",
        condition="new",
        image_url="",
        availability="in_stock",
        search_text="tea",
    )
    order = CommerceOrder(
        user_id=test_user.id,
        external_order_id="ORD-CAS-1",
        customer_name="Asha",
        customer_phone="254700000001",
        status="pending",
        payment_status="pending",
        currency="KES",
        total=Decimal("100.00"),
        line_items=[],
        delivery_method="pickup",
    )
    db_session.add(product)
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(product)

    catalog = DbCatalogPort(db_session, test_user.id)
    orders = DbOrderPort(db_session, test_user.id)
    current = await catalog.get_product(str(product.id))
    first_qty = await catalog.compare_and_set_quantity(
        str(product.id), current["quantity"], 4
    )
    second_qty = await catalog.compare_and_set_quantity(
        str(product.id), current["quantity"], 3
    )
    first_status = await orders.compare_and_set_status("ORD-CAS-1", "pending", "cancelled")
    second_status = await orders.compare_and_set_status("ORD-CAS-1", "pending", "cancelled")

    assert first_qty is True
    assert second_qty is False
    assert first_status is True
    assert second_status is False
    await db_session.refresh(product)
    await db_session.refresh(order)
    assert int(product.quantity) == 4
    assert order.status == "cancelled"


@pytest.mark.asyncio
async def test_yes_checkout_returns_payable_total_for_payment(db_session, test_user):
    """YES places the rails order, tells the customer the total, and registers it for STK."""
    from src.services.order_tracking_service import order_tracking_service

    product = CatalogProduct(
        user_id=test_user.id,
        name="Tea",
        price=Decimal("100.00"),
        description="Tea",
        category="drinks",
        sku="TEA-YES",
        brand="Shop",
        quantity=Decimal("5"),
        unit="pcs",
        condition="new",
        image_url="",
        availability="in_stock",
        search_text="tea",
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)

    phone = "254700000001"
    session_key = f"ccm:whatsapp:{test_user.id}:{phone}"
    session = _session(session_key, str(test_user.id), phone)
    session.metadata = {
        "welcome_sent": True,
        "preferred_language": "en",
        "awaiting_order_confirmation": True,
        "order_confirmed": True,
        "checkout_customer": {
            "name": "Asha",
            "phone": phone,
            "delivery_method": "pickup",
        },
        "pending_confirmation": {
            "items": [
                {
                    "id": str(product.id),
                    "name": "Tea",
                    "quantity": 1,
                    "unit_price": 1,
                }
            ]
        },
        "commerce_rails_state": {
            "cart_lines": [{"product_id": str(product.id), "qty": 1}],
            "fulfillment_method": "pickup",
            "checkout_fields": {"customer_name": "Asha", "customer_phone": phone},
            "phase": "checkout",
        },
    }
    agent = ConversationalAgentService()
    patches = _bind_session(session)

    with patches[0], patches[1], patches[2], patch.object(
        order_tracking_service, "register_order", wraps=order_tracking_service.register_order
    ) as register:
        result = await agent.execute(
            user_message="YES",
            session_key=session_key,
            business_config={
                "order_type": "retail",
                "commerce_rails_enabled": True,
                "business_name": "Shop",
            },
            user=test_user,
            db=db_session,
        )

    assert (result.get("response_text") or "").strip()
    assert "100" in result["response_text"]
    order_data = result.get("order_data") or {}
    assert order_tracking_service._order_amount(order_data) == 100.0
    register.assert_called()
    snapshot = register.call_args.args[3]
    assert order_tracking_service._order_amount(snapshot) == 100.0
    assert register.call_args.args[2] == phone

    await db_session.refresh(product)
    assert int(product.quantity) == 4
    stored = await db_session.execute(
        select(CommerceOrder).where(CommerceOrder.user_id == test_user.id)
    )
    saved = stored.scalar_one()
    assert saved.total == Decimal("100.00")


@pytest.mark.asyncio
async def test_request_return_uses_whatsapp_sender_not_llm_phone(db_session, test_user):
    now = datetime.now(timezone.utc)
    order = CommerceOrder(
        user_id=test_user.id,
        external_order_id="ORD-PHONE-1",
        customer_name="Asha",
        customer_phone="254700000001",
        status="delivered",
        payment_status="paid",
        currency="KES",
        total=Decimal("500.00"),
        line_items=[{"product_id": "tea", "qty": 1, "name": "Tea", "unit_price": "500.00"}],
        delivery_method="pickup",
        created_at=now,
    )
    db_session.add(order)
    await db_session.commit()

    agent = ConversationalAgentService()
    sender = "254700000001"
    session_key = f"ccm:whatsapp:{test_user.id}:{sender}"
    result = await _tool(
        agent,
        test_user,
        db_session,
        session_key,
        "request_return",
        {
            "order_external_id": "ORD-PHONE-1",
            "phone": "254799999999",
            "customer_phone": "254799999999",
            "reason_code": "damaged",
            "amount": "100.00",
        },
    )

    assert result.get("success") is True
    stored = await db_session.execute(
        select(CommerceReturn).where(CommerceReturn.user_id == test_user.id)
    )
    row = stored.scalar_one()
    assert row.customer_phone == sender
    assert row.customer_phone != "254799999999"
