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
        session.metadata["commerce_phase"] = "awaiting_yes"
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
    phone = "254700000001"
    session_key = f"ccm:whatsapp:{test_user.id}:{phone}"
    session = _session(session_key, str(test_user.id), phone)
    session.metadata = {"commerce_phase": "awaiting_yes", "welcome_sent": True}
    patches = _bind_session(session)
    with patches[0], patches[1], patches[2], patch(
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
        "commerce_phase": "awaiting_yes",
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
    alert = result.get("order_notification") or ""
    assert "Asha" in alert
    assert phone in alert
    assert "Unknown" not in alert
    assert "N/A" not in alert
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


def test_business_alert_reads_flat_customer_fields():
    agent = ConversationalAgentService()
    alert = agent._format_business_notification(
        {
            "order_id": "ORD-1",
            "customer_name": "Asha",
            "customer_phone": "254700000001",
            "delivery_method": "pickup",
            "subtotal": 100,
            "items": [],
        },
        "Shop",
        "KES",
    )
    assert "Asha" in alert
    assert "254700000001" in alert
    assert "Unknown" not in alert
    assert "N/A" not in alert


@pytest.mark.asyncio
async def test_paid_cancel_opens_a_refund_and_restocks_once(db_session, test_user):
    """Paid cancel before preparing restocks once and leaves a non-refunded return."""
    product = CatalogProduct(
        user_id=test_user.id,
        name="Tea",
        price=Decimal("100.00"),
        description="Tea",
        category="drinks",
        sku="TEA-CANCEL",
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
    with patches[0], patches[1], patches[2]:
        await _tool(
            agent,
            test_user,
            db_session,
            session_key,
            "manage_cart",
            {"action": "add", "product_id": str(product.id), "quantity": 1},
        )
        session.metadata["commerce_phase"] = "awaiting_yes"
        placed = await _tool(
            agent,
            test_user,
            db_session,
            session_key,
            "create_order",
            {
                "customer_name": "Asha",
                "customer_phone": phone,
                "delivery_method": "pickup",
            },
        )
        order_id = placed["order_data"]["order_id"]
        stored = await db_session.execute(
            select(CommerceOrder).where(CommerceOrder.external_order_id == order_id)
        )
        order = stored.scalar_one()
        order.payment_status = "paid"
        order.mpesa_receipt = "QKPAID1"
        await db_session.commit()
        cancelled = await _tool(
            agent,
            test_user,
            db_session,
            session_key,
            "cancel_order",
            {"order_id": order_id, "customer_phone": phone},
        )

    message = cancelled.get("verbatim_customer_message") or ""
    assert cancelled["success"] is True
    assert "refunded" not in message.lower()
    assert "not complete" in message.lower()
    assert order_id in message
    await db_session.refresh(product)
    await db_session.refresh(order)
    assert int(product.quantity) == 5
    assert order.status == "cancelled"
    assert order.payment_status == "paid"
    returns = (
        await db_session.execute(
            select(CommerceReturn).where(CommerceReturn.user_id == test_user.id)
        )
    ).scalars().all()
    assert len(returns) == 1
    assert returns[0].status != "refunded"
    assert returns[0].order_external_id == order_id
    assert (returns[0].raw_snapshot or {}).get("inventory_restocked") is True

    from src.services.commerce_returns_service import approve_return

    await approve_return(db_session, test_user.id, returns[0].id, actor_user_id=test_user.id)
    await db_session.refresh(product)
    assert int(product.quantity) == 5


@pytest.mark.asyncio
async def test_return_refuses_a_sender_who_is_not_the_buyer(db_session, test_user):
    order = CommerceOrder(
        user_id=test_user.id,
        external_order_id="ORD-OTHER",
        customer_name="Asha",
        customer_phone="254700000001",
        status="delivered",
        payment_status="paid",
        currency="KES",
        total=Decimal("100.00"),
        line_items=[],
        delivery_method="pickup",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(order)
    await db_session.commit()
    agent = ConversationalAgentService()
    sender = "254711111111"
    result = await _tool(
        agent,
        test_user,
        db_session,
        f"ccm:whatsapp:{test_user.id}:{sender}",
        "request_return",
        {
            "order_external_id": "ORD-OTHER",
            "phone": sender,
            "reason_code": "damaged",
            "amount": "100.00",
        },
    )
    assert result.get("success") is False
    stored = await db_session.execute(
        select(CommerceReturn).where(CommerceReturn.user_id == test_user.id)
    )
    assert stored.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_self_serve_complaints_answer_status_hours_and_payment(db_session, test_user):
    order = CommerceOrder(
        user_id=test_user.id,
        external_order_id="ORD-ASK",
        customer_name="Asha",
        customer_phone="254700000001",
        status="preparing",
        payment_status="failed",
        currency="KES",
        total=Decimal("80.00"),
        line_items=[],
        delivery_method="pickup",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(order)
    await db_session.commit()
    await upsert_policy(
        db_session,
        test_user.id,
        {
            "business_hours": {
                day: {"open": "08:00", "close": "20:00"}
                for day in (
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                    "saturday",
                    "sunday",
                )
            }
        },
    )
    agent = ConversationalAgentService()
    phone = "254700000001"
    session_key = f"ccm:whatsapp:{test_user.id}:{phone}"

    status = await _tool(
        agent,
        test_user,
        db_session,
        session_key,
        "request_complaint",
        {"category": "where_is_my_order", "order_external_id": "ORD-ASK"},
    )
    hours = await _tool(
        agent,
        test_user,
        db_session,
        session_key,
        "request_complaint",
        {"category": "hours"},
    )
    payment = await _tool(
        agent,
        test_user,
        db_session,
        session_key,
        "request_complaint",
        {"category": "payment_failed", "order_external_id": "ORD-ASK"},
    )
    for result in (status, hours, payment):
        text = result.get("verbatim_customer_message") or ""
        assert result.get("success") is True
        assert "noted that" not in text.lower()
        assert text.strip()
    assert "ORD-ASK" in status["verbatim_customer_message"]
    assert "preparing" in status["verbatim_customer_message"]
    assert "Hours:" in hours["verbatim_customer_message"] or "closed" in hours["verbatim_customer_message"].lower()
    assert "M-Pesa" in payment["verbatim_customer_message"]
    assert "failed" in payment["verbatim_customer_message"].lower()

    started = await _tool(
        agent,
        test_user,
        db_session,
        session_key,
        "request_complaint",
        {"category": "start_return", "order_external_id": "ORD-ASK"},
    )
    started_text = started.get("verbatim_customer_message") or ""
    assert "noted that" not in started_text.lower()
    assert "no collected payment" in started_text.lower()

    order.payment_status = "paid"
    order.status = "pending"
    await db_session.commit()
    session = _session(session_key, str(test_user.id), phone)
    patches = _bind_session(session)
    with patches[0], patches[1], patches[2]:
        cancelled = await _tool(
            agent,
            test_user,
            db_session,
            session_key,
            "request_complaint",
            {"category": "cancel", "order_external_id": "ORD-ASK"},
        )
    cancel_text = cancelled.get("verbatim_customer_message") or ""
    assert "noted that" not in cancel_text.lower()
    assert "refunded" not in cancel_text.lower()
    assert "ORD-ASK" in cancel_text
    await db_session.refresh(order)
    assert order.status == "cancelled"
    opened = (
        await db_session.execute(
            select(CommerceReturn).where(CommerceReturn.order_external_id == "ORD-ASK")
        )
    ).scalar_one()
    assert opened.status != "refunded"


@pytest.mark.asyncio
async def test_policy_load_failure_does_not_fall_through_to_legacy(db_session, test_user):
    agent = ConversationalAgentService()
    session_key = f"ccm:whatsapp:{test_user.id}:254700000001"
    with patch(
        "src.services.commerce_runtime.agent_wiring.get_policy",
        new_callable=AsyncMock,
        side_effect=RuntimeError("policy db down"),
    ), patch.object(
        agent, "_sub_create_order", new_callable=AsyncMock
    ) as legacy:
        result = await agent._execute_sub_tool(
            tool_name="create_order",
            arguments={"customer_name": "Asha", "delivery_method": "pickup", "items": []},
            kb_id="",
            order_type="retail",
            currency="KES",
            business_name="Shop",
            storage_config={"provider": "none"},
            session_key=session_key,
            user=test_user,
            db=db_session,
            default_customer_phone="254700000001",
            default_customer_name="Asha",
            business_config={"order_type": "retail"},
        )
    legacy.assert_not_called()
    assert result.get("human_handoff") is True
    assert (result.get("verbatim_customer_message") or "").strip()
    assert "refunded" not in result["verbatim_customer_message"].lower()

    with patch(
        "src.services.commerce_runtime.agent_wiring.get_policy",
        new_callable=AsyncMock,
        side_effect=RuntimeError("policy db down"),
    ), patch.object(
        agent,
        "_sub_create_order",
        new_callable=AsyncMock,
        return_value={"success": True, "result": "legacy"},
    ) as rent_legacy:
        rent = await agent._execute_sub_tool(
            tool_name="create_order",
            arguments={"customer_name": "Asha", "items": []},
            kb_id="",
            order_type="rent_collection",
            currency="KES",
            business_name="Shop",
            storage_config={"provider": "none"},
            session_key=session_key,
            user=test_user,
            db=db_session,
            default_customer_phone="254700000001",
            default_customer_name="Asha",
            business_config={"order_type": "rent_collection"},
        )
    rent_legacy.assert_awaited()
    assert rent.get("result") == "legacy"


class _GreetingTurn:
    error = None
    content = "Hi! How can I help you today?"
    tools_called = []


def _retail_config():
    return {
        "order_type": "retail",
        "commerce_rails_enabled": True,
        "business_name": "Shop",
        "delivery_methods": ["pickup"],
        "customer_name": "",
    }


async def _add_tea(db_session, test_user, sku: str) -> CatalogProduct:
    product = CatalogProduct(
        user_id=test_user.id,
        name="Tea",
        price=Decimal("100.00"),
        description="Tea",
        category="drinks",
        sku=sku,
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
    return product


def _cart_session(test_user, phone: str, product: CatalogProduct, **metadata):
    session_key = f"ccm:whatsapp:{test_user.id}:{phone}"
    session = _session(session_key, str(test_user.id), phone)
    session.metadata = {
        "welcome_sent": True,
        "preferred_language": "en",
        "cart": [
            {
                "id": str(product.id),
                "name": "Tea",
                "quantity": 1,
                "unit_price": 100,
            }
        ],
    }
    session.metadata.update(metadata)
    return session


async def _present(agent, session, test_user, db_session, phone: str):
    patches = _bind_session(session)
    with patches[0], patches[1], patches[2]:
        return await agent._present_checkout_confirmation(
            session_key=session.session_key,
            cart=list(session.metadata["cart"]),
            currency="KES",
            customer_name="Asha",
            customer_phone=phone,
            delivery_method="pickup",
            delivery_methods=["pickup"],
            user=test_user,
            db=db_session,
        )


async def _say(agent, session, test_user, db_session, message: str):
    patches = _bind_session(session)
    with patches[0], patches[1], patches[2], patch.object(
        agent.llm_service, "chat_completion", new_callable=AsyncMock
    ) as chat:
        chat.return_value = _GreetingTurn()
        result = await agent.execute(
            user_message=message,
            session_key=session.session_key,
            business_config=_retail_config(),
            user=test_user,
            db=db_session,
        )
    return result, chat


_NOT_NAMES = (
    "My Orders",
    "orders",
    "browse catalog",
    "cancel",
    "return",
    "help",
    "human",
    "agent",
    "pay",
    "yes",
    "ndio",
)


@pytest.mark.parametrize("message", _NOT_NAMES)
def test_intent_phrase_is_not_a_checkout_name(message):
    from src.services.whatsapp_ordering_helpers import parse_checkout_details

    assert (parse_checkout_details(message).get("name") or "") == ""


def test_person_name_still_parses_for_checkout():
    from src.services.whatsapp_ordering_helpers import parse_checkout_details

    assert parse_checkout_details("Asha Wanjiku").get("name") == "Asha Wanjiku"


@pytest.mark.asyncio
async def test_present_checkout_confirmation_sets_awaiting_yes(db_session, test_user):
    product = await _add_tea(db_session, test_user, "TEA-PHASE")
    phone = "254700000111"
    session = _cart_session(test_user, phone, product)
    agent = ConversationalAgentService()

    presented = await _present(agent, session, test_user, db_session, phone)

    assert session.metadata.get("commerce_phase") == "awaiting_yes"
    assert session.metadata.get("awaiting_order_confirmation") is True
    assert session.metadata.get("pending_confirmation")
    assert "YES" in (presented.get("response_text") or "")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("word", "phone"),
    (
        ("yea", "254700000121"),
        ("ok", "254700000122"),
        ("okay", "254700000123"),
        ("sure", "254700000124"),
        ("alright", "254700000125"),
        ("fine", "254700000126"),
    ),
)
async def test_soft_confirm_after_present_places_the_order(
    db_session, test_user, word, phone
):
    product = await _add_tea(db_session, test_user, f"TEA-{word.upper()}")
    session = _cart_session(test_user, phone, product)
    agent = ConversationalAgentService()
    await _present(agent, session, test_user, db_session, phone)

    result, chat = await _say(agent, session, test_user, db_session, word)

    assert result.get("order_created") is True
    text = (result.get("response_text") or "").lower()
    assert "placed" in text
    assert "how can i help" not in text
    assert session.metadata.get("commerce_phase") == "placed"
    chat.assert_not_called()
    stored = await db_session.execute(
        select(CommerceOrder).where(CommerceOrder.user_id == test_user.id)
    )
    assert len(list(stored.scalars().all())) == 1


@pytest.mark.asyncio
async def test_second_confirm_says_already_placed_not_greeting(db_session, test_user):
    phone = "254700000113"
    session_key = f"ccm:whatsapp:{test_user.id}:{phone}"
    session = _session(session_key, str(test_user.id), phone)
    session.metadata = {
        "welcome_sent": True,
        "preferred_language": "en",
        "commerce_phase": "placed",
        "placed_order_id": "ORD-9",
    }
    agent = ConversationalAgentService()

    result, chat = await _say(agent, session, test_user, db_session, "YES")

    text = result.get("response_text") or ""
    assert "ORD-9" in text
    assert "already placed" in text.lower()
    assert "how can i help" not in text.lower()
    chat.assert_not_called()


@pytest.mark.asyncio
async def test_bare_ok_outside_awaiting_yes_does_not_place(db_session, test_user):
    product = await _add_tea(db_session, test_user, "TEA-OUTSIDE")
    phone = "254700000114"
    session = _cart_session(
        test_user,
        phone,
        product,
        commerce_phase="browsing",
        awaiting_order_confirmation=True,
        checkout_customer={
            "name": "Asha",
            "phone": phone,
            "delivery_method": "pickup",
        },
        pending_confirmation={
            "items": [
                {
                    "id": str(product.id),
                    "name": "Tea",
                    "quantity": 1,
                    "unit_price": 100,
                }
            ]
        },
    )
    agent = ConversationalAgentService()

    result, _chat = await _say(agent, session, test_user, db_session, "ok")

    assert result.get("order_created") is not True
    assert session.metadata.get("commerce_phase") != "placed"
    stored = await db_session.execute(
        select(CommerceOrder).where(CommerceOrder.user_id == test_user.id)
    )
    assert list(stored.scalars().all()) == []


@pytest.mark.asyncio
async def test_yes_without_checkout_does_not_greet(db_session, test_user):
    phone = "254700000115"
    session_key = f"ccm:whatsapp:{test_user.id}:{phone}"
    session = _session(session_key, str(test_user.id), phone)
    session.metadata = {
        "welcome_sent": True,
        "preferred_language": "en",
        "commerce_phase": "browsing",
    }
    agent = ConversationalAgentService()

    result, chat = await _say(agent, session, test_user, db_session, "YES")

    text = (result.get("response_text") or "").lower()
    assert "reply yes to confirm" in text
    assert "how can i help" not in text
    assert result.get("order_created") is not True
    chat.assert_not_called()


@pytest.mark.asyncio
async def test_my_orders_is_not_stored_as_the_summary_name(db_session, test_user):
    product = await _add_tea(db_session, test_user, "TEA-NAME")
    phone = "254700000116"
    session = _cart_session(
        test_user,
        phone,
        product,
        commerce_phase="collecting_details",
        awaiting_checkout_details=True,
    )
    agent = ConversationalAgentService()

    result, _chat = await _say(agent, session, test_user, db_session, "My Orders")

    stored_name = str((session.metadata.get("checkout_customer") or {}).get("name") or "")
    draft_name = str((session.metadata.get("checkout_draft") or {}).get("name") or "")
    blob = " ".join(
        [result.get("response_text") or "", stored_name, draft_name]
    ).lower()
    assert "my orders" not in blob
    assert stored_name.strip().lower() != "my orders"


@pytest.mark.asyncio
async def test_name_is_not_captured_while_browsing(db_session, test_user):
    product = await _add_tea(db_session, test_user, "TEA-BROWSE-NAME")
    phone = "254700000117"
    session = _cart_session(test_user, phone, product, commerce_phase="browsing")
    agent = ConversationalAgentService()

    result, _chat = await _say(agent, session, test_user, db_session, "Asha Wanjiku")

    text = result.get("response_text") or ""
    stored_name = str((session.metadata.get("checkout_customer") or {}).get("name") or "")
    assert "Name: Asha Wanjiku" not in text
    assert stored_name != "Asha Wanjiku"
    assert session.metadata.get("commerce_phase") == "browsing"


@pytest.mark.asyncio
async def test_collecting_details_stores_a_real_name_and_waits_for_yes(
    db_session, test_user
):
    product = await _add_tea(db_session, test_user, "TEA-REAL-NAME")
    phone = "254700000118"
    session = _cart_session(
        test_user,
        phone,
        product,
        commerce_phase="collecting_details",
        awaiting_checkout_details=True,
    )
    agent = ConversationalAgentService()

    result, _chat = await _say(agent, session, test_user, db_session, "Asha Wanjiku")

    assert "Name: Asha Wanjiku" in (result.get("response_text") or "")
    assert session.metadata.get("commerce_phase") == "awaiting_yes"
    assert (session.metadata.get("checkout_customer") or {}).get("name") == "Asha Wanjiku"


@pytest.mark.asyncio
async def test_yes_without_phase_represents_and_does_not_place(db_session, test_user):
    """Pending checkout with no commerce_phase must not place on YES."""
    product = await _add_tea(db_session, test_user, "TEA-NO-PHASE")
    phone = "254700000131"
    session = _cart_session(
        test_user,
        phone,
        product,
        awaiting_order_confirmation=True,
        order_confirmed=True,
        checkout_customer={
            "name": "Asha",
            "phone": phone,
            "delivery_method": "pickup",
        },
        pending_confirmation={
            "items": [
                {
                    "id": str(product.id),
                    "name": "Tea",
                    "quantity": 1,
                    "unit_price": 100,
                }
            ]
        },
    )
    agent = ConversationalAgentService()

    result, chat = await _say(agent, session, test_user, db_session, "YES")

    assert result.get("order_created") is not True
    assert session.metadata.get("commerce_phase") == "awaiting_yes"
    text = (result.get("response_text") or "").lower()
    assert "yes" in text
    assert "placed" not in text
    assert "how can i help" not in text
    chat.assert_not_called()
    stored = await db_session.execute(
        select(CommerceOrder).where(CommerceOrder.user_id == test_user.id)
    )
    assert list(stored.scalars().all()) == []
    await db_session.refresh(product)
    assert int(product.quantity) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ("", "browsing", "collecting_details"))
async def test_create_order_tool_does_not_place_outside_awaiting_yes(
    db_session, test_user, phase
):
    product = await _add_tea(db_session, test_user, f"TEA-TOOL-{phase or 'EMPTY'}")
    phone = "254700000132"
    session_key = f"ccm:whatsapp:{test_user.id}:{phone}"
    session = _session(session_key, str(test_user.id), phone)
    if phase:
        session.metadata["commerce_phase"] = phase
    agent = ConversationalAgentService()
    patches = _bind_session(session)

    with patches[0], patches[1], patches[2]:
        added = await _tool(
            agent,
            test_user,
            db_session,
            session_key,
            "manage_cart",
            {
                "action": "add",
                "product_id": str(product.id),
                "product_name": "Tea",
                "quantity": 1,
            },
        )
        assert added["success"] is True
        if phase:
            session.metadata["commerce_phase"] = phase
        else:
            session.metadata.pop("commerce_phase", None)
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

    assert placed.get("success") is not True
    assert session.metadata.get("commerce_phase") != "placed"
    stored = await db_session.execute(
        select(CommerceOrder).where(CommerceOrder.user_id == test_user.id)
    )
    assert list(stored.scalars().all()) == []
    await db_session.refresh(product)
    assert int(product.quantity) == 5
