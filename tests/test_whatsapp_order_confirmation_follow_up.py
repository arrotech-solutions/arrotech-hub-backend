from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.models import CatalogProduct
from src.services.commerce_runtime.db_ports import DbOrderPort
from src.services.conversation_context_manager import (
    ConversationSession,
    context_manager,
)
from src.services.conversational_agent_service import ConversationalAgentService
from src.services.llm_service import LLMResponse


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

    async def fake_save(_session):
        return None

    return (
        patch.object(context_manager, "get_session_by_key", fake_get),
        patch.object(context_manager, "update_session_metadata", fake_update),
        patch.object(context_manager, "save_session", fake_save),
    )


def _checkout_session(session_key: str, owner: str, phone: str) -> ConversationSession:
    session = _session(session_key, owner, phone)
    item = {
        "id": "pilau-1",
        "name": "Pilau",
        "quantity": 1,
        "unit_price": 250,
    }
    session.metadata = {
        "welcome_sent": True,
        "preferred_language": "en",
        "commerce_phase": "awaiting_yes",
        "awaiting_order_confirmation": True,
        "checkout_customer": {
            "name": "Asha",
            "phone": phone,
            "delivery_method": "pickup",
        },
        "pending_confirmation": {"items": [dict(item)]},
        "cart": [dict(item)],
    }
    return session


async def _mock_create_order_proposal(agent, *, result=None):
    agent.llm_service.chat_completion = AsyncMock(
        side_effect=[
            LLMResponse(
                content="",
                tools_called=[
                    {
                        "name": "create_order",
                        "arguments": {
                            "customer_name": "Asha",
                            "customer_phone": "254700000001",
                            "delivery_method": "pickup",
                            "items": [{"name": "Pilau", "quantity": 1}],
                        },
                    }
                ],
            ),
            LLMResponse(content="Please continue checkout.", tools_called=None),
        ]
    )
    return AsyncMock(return_value=result or {"success": False, "result": "not confirmed"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {"cart": [{"id": "pilau-1", "name": "Pilau", "quantity": 1}]},
        {
            "cart": [{"id": "pilau-1", "name": "Pilau", "quantity": 1}],
            "checkout_customer": {
                "name": "Asha",
                "phone": "254700000001",
                "delivery_method": "pickup",
            },
            "commerce_phase": "awaiting_yes",
        },
    ],
    ids=["cart-only", "stale-checkout-details"],
)
async def test_bare_yes_without_active_checkout_summary_does_not_create_order(
    db_session, test_user, metadata
):
    phone = "254700000001"
    session_key = f"ccm:whatsapp:{test_user.id}:{phone}"
    session = _session(session_key, str(test_user.id), phone)
    session.metadata = {"welcome_sent": True, **metadata}
    agent = ConversationalAgentService()
    create_order = await _mock_create_order_proposal(agent)
    patches = _bind_session(session)
    with patches[0], patches[1], patches[2], patch.object(
        agent, "_sub_create_order", new=create_order
    ):
        result = await agent.execute(
            user_message="Yes",
            session_key=session_key,
            business_config={"order_type": "retail", "commerce_rails_enabled": False},
            user=test_user,
            db=db_session,
        )

    create_order.assert_not_awaited()
    assert result["order_created"] is False
    assert session.metadata.get("pending_confirmation") is None
    assert session.metadata.get("order_confirmed") is not True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "blocked_state",
    ["reservation", "handoff"],
    ids=["reservation_confirmation", "human_handoff"],
)
async def test_yes_during_reservation_or_handoff_does_not_create_checkout_order(
    db_session, test_user, blocked_state
):
    phone = "254700000001"
    session_key = f"ccm:whatsapp:{test_user.id}:{phone}"
    session = _checkout_session(session_key, str(test_user.id), phone)
    if blocked_state == "reservation":
        session.metadata["awaiting_reservation_confirmation"] = True
    else:
        session.metadata["human_handoff"] = True
    agent = ConversationalAgentService()
    create_order = await _mock_create_order_proposal(agent)
    patches = _bind_session(session)
    with patches[0], patches[1], patches[2], patch.object(
        agent, "_sub_create_order", new=create_order
    ):
        result = await agent.execute(
            user_message="Yes",
            session_key=session_key,
            business_config={
                "order_type": "food" if blocked_state == "reservation" else "retail",
                "commerce_rails_enabled": False,
                "reservations_enabled": True,
            },
            user=test_user,
            db=db_session,
        )

    create_order.assert_not_awaited()
    assert result["order_created"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["ok", "sure", "okay", "alright", "fine"])
async def test_ambiguous_ack_does_not_create_order(db_session, test_user, message):
    phone = "254700000001"
    session_key = f"ccm:whatsapp:{test_user.id}:{phone}"
    session = _checkout_session(session_key, str(test_user.id), phone)
    agent = ConversationalAgentService()
    agent.llm_service.chat_completion = AsyncMock(
        return_value=LLMResponse(content="Please reply YES to confirm.", tools_called=None)
    )
    create_order = AsyncMock()
    patches = _bind_session(session)
    with patches[0], patches[1], patches[2], patch.object(
        agent, "_sub_create_order", new=create_order
    ):
        await agent.execute(
            user_message=message,
            session_key=session_key,
            business_config={"order_type": "retail", "commerce_rails_enabled": False},
            user=test_user,
            db=db_session,
        )

    create_order.assert_not_awaited()
    assert session.metadata["pending_confirmation"]["items"]
    assert session.metadata["awaiting_order_confirmation"] is True
    assert session.metadata.get("order_confirmed") is not True


@pytest.mark.asyncio
async def test_cancel_during_checkout_confirmation_does_not_create_order(
    db_session, test_user
):
    phone = "254700000001"
    session_key = f"ccm:whatsapp:{test_user.id}:{phone}"
    session = _checkout_session(session_key, str(test_user.id), phone)
    session.metadata["order_confirmed"] = True
    agent = ConversationalAgentService()
    create_order = AsyncMock()
    patches = _bind_session(session)
    with patches[0], patches[1], patches[2], patch.object(
        agent, "_sub_create_order", new=create_order
    ):
        result = await agent.execute(
            user_message="cancel",
            session_key=session_key,
            business_config={"order_type": "retail", "commerce_rails_enabled": False},
            user=test_user,
            db=db_session,
        )

    create_order.assert_not_awaited()
    assert result["order_created"] is False
    assert session.metadata["cart"]
    assert "pending_confirmation" not in session.metadata
    assert session.metadata.get("order_confirmed") is not True
    assert session.metadata["awaiting_order_confirmation"] is False
    assert session.metadata["commerce_phase"] != "awaiting_yes"
    assert "edit" in result["response_text"].lower()


async def _assert_checkout_correction_requires_new_confirmation(
    db_session, test_user, message
):
    phone = "254700000001"
    session_key = f"ccm:whatsapp:{test_user.id}:{phone}"
    session = _checkout_session(session_key, str(test_user.id), phone)
    agent = ConversationalAgentService()
    create_order = AsyncMock()
    patches = _bind_session(session)
    with patches[0], patches[1], patches[2], patch.object(
        agent, "_sub_create_order", new=create_order
    ):
        result = await agent.execute(
            user_message=message,
            session_key=session_key,
            business_config={"order_type": "retail", "commerce_rails_enabled": False},
            user=test_user,
            db=db_session,
        )

    create_order.assert_not_awaited()
    assert result["order_created"] is False
    assert session.metadata["cart"][0]["quantity"] == 2
    assert "pending_confirmation" not in session.metadata
    assert session.metadata["awaiting_order_confirmation"] is False
    assert session.metadata["commerce_phase"] != "awaiting_yes"


@pytest.mark.asyncio
async def test_correction_after_summary_requires_new_confirmation(db_session, test_user):
    await _assert_checkout_correction_requires_new_confirmation(
        db_session, test_user, "change pilau to 2"
    )


@pytest.mark.asyncio
async def test_leading_yes_with_correction_does_not_create_order(db_session, test_user):
    await _assert_checkout_correction_requires_new_confirmation(
        db_session, test_user, "Yes, change pilau to 2"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("rails_enabled", [False, True], ids=["legacy", "rails"])
@pytest.mark.parametrize(
    ("message", "correction", "command"),
    [
        ("Yes add tea", "add tea", "add"),
        ("Yes, add tea", "add tea", "add"),
        ("Yes remove pilau", "remove pilau", "remove"),
        ("Yes, remove pilau", "remove pilau", "remove"),
        ("Yes change pilau to 2", "change pilau to 2", "set_quantity"),
        ("Yes, change pilau to 2", "change pilau to 2", "set_quantity"),
    ],
)
async def test_leading_yes_cart_correction_precedes_confirmation(
    db_session, test_user, rails_enabled, message, correction, command
):
    session_key = f"ccm:whatsapp:{test_user.id}:254700000001"
    session = _checkout_session(session_key, str(test_user.id), "254700000001")
    agent = ConversationalAgentService()
    agent.llm_service.chat_completion = AsyncMock(
        return_value=LLMResponse(content="Cart update received.", tools_called=None)
    )
    create_order = AsyncMock()
    rails_calls = []

    async def fake_rails_fast_cart(**kwargs):
        rails_calls.append(kwargs)
        return "Cart update received."

    patches = _bind_session(session)
    rails_patch = patch(
        "src.services.commerce_runtime.agent_wiring.try_rails_fast_cart",
        new=AsyncMock(side_effect=fake_rails_fast_cart),
    )
    business_config = {
        "order_type": "retail",
        "commerce_rails_enabled": rails_enabled,
    }
    with patches[0], patches[1], patches[2], patch.object(
        agent, "_sub_create_order", new=create_order
    ), rails_patch:
        result = await agent.execute(
            user_message=message,
            session_key=session_key,
            business_config=business_config,
            user=test_user,
            db=db_session,
        )

    create_order.assert_not_awaited()
    assert result.get("order_created") is not True
    if command in {"remove", "set_quantity"}:
        assert session.metadata.get("awaiting_order_confirmation") is False
    if rails_enabled and command in {"remove", "set_quantity"}:
        assert rails_calls
        assert rails_calls[0]["user_message"] == correction
    elif command == "add":
        sent_messages = agent.llm_service.chat_completion.await_args.kwargs["messages"]
        assert sent_messages[-1] == {"role": "user", "content": correction}


@pytest.mark.asyncio
async def test_order_follow_up_failure_sends_customer_fallback(
    test_user,
):
    from src.services.order_tracking_service import order_tracking_service

    class FakeTenantSession:
        async def __aenter__(self):
            return SimpleNamespace(
                execute=AsyncMock(
                    return_value=SimpleNamespace(
                        scalar_one_or_none=lambda: test_user
                    )
                )
            )

        async def __aexit__(self, *_args):
            return None

    agent = ConversationalAgentService()
    fallback = AsyncMock()
    with patch(
        "src.database.tenant_session", return_value=FakeTenantSession()
    ), patch.object(
        order_tracking_service,
        "notify_order_placed",
        new=AsyncMock(side_effect=RuntimeError("WhatsApp unavailable")),
    ), patch.object(
        order_tracking_service,
        "send_order_placement_fallback",
        new=fallback,
    ):
        await agent._bg_notify_order_placed(
            str(test_user.id),
            "254700000001",
            {"order_id": "ORD-FALLBACK"},
            "Shop",
            "254700000099",
            "KES",
            "wamid.fallback",
        )

    fallback.assert_awaited_once()
    assert fallback.await_args.kwargs["order_id"] == "ORD-FALLBACK"
    assert fallback.await_args.kwargs["meta_message_id"] == "wamid.fallback"


@pytest.mark.asyncio
async def test_partial_order_follow_up_delivery_does_not_send_fallback(test_user):
    from src.services.order_tracking_service import order_tracking_service

    class FakeTenantSession:
        async def __aenter__(self):
            return SimpleNamespace(
                execute=AsyncMock(
                    return_value=SimpleNamespace(
                        scalar_one_or_none=lambda: test_user
                    )
                )
            )

        async def __aexit__(self, *_args):
            return None

    agent = ConversationalAgentService()
    fallback = AsyncMock()
    with patch(
        "src.database.tenant_session", return_value=FakeTenantSession()
    ), patch.object(
        order_tracking_service,
        "notify_order_placed",
        new=AsyncMock(
            return_value={
                "success": False,
                "sent": ["confirmation"],
                "customer_delivery_succeeded": True,
            }
        ),
    ), patch.object(
        order_tracking_service,
        "send_order_placement_fallback",
        new=fallback,
    ):
        await agent._bg_notify_order_placed(
            str(test_user.id),
            "254700000001",
            {"order_id": "ORD-PARTIAL"},
            "Shop",
            "254700000099",
            "KES",
            "wamid.partial",
        )

    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_order_placement_fallback_is_safe_and_idempotent(test_user):
    from src.services.order_tracking_service import order_tracking_service

    whatsapp = SimpleNamespace(send_message=AsyncMock(return_value={"success": True}))
    registry = {}

    def save_registry(_owner_user_id, _order_id, value):
        registry.update(value)

    claim = AsyncMock(side_effect=[True, False])
    with patch.object(
        order_tracking_service,
        "_get_whatsapp_config",
        new=AsyncMock(return_value={"access_token": "token", "phone_number_id": "id"}),
    ), patch.object(
        order_tracking_service,
        "get_registered_order",
        side_effect=lambda *_args: dict(registry) if registry else None,
    ), patch.object(
        order_tracking_service, "_save_registry", side_effect=save_registry
    ), patch(
        "src.services.idempotency_service.idempotency_service.claim_order_followup_fallback",
        new=claim,
    ), patch(
        "src.services.whatsapp_service.WhatsAppService", return_value=whatsapp
    ):
        first = await order_tracking_service.send_order_placement_fallback(
            user=test_user,
            db=object(),
            customer_phone="254700000001",
            order_id="ORD-FALLBACK-IDEMPOTENT",
            business_name="Shop",
            business_phone="254700000099",
            meta_message_id="wamid.FALLBACK-IDEMPOTENT",
        )
        second = await order_tracking_service.send_order_placement_fallback(
            user=test_user,
            db=object(),
            customer_phone="254700000001",
            order_id="ORD-FALLBACK-IDEMPOTENT",
            business_name="Shop",
            business_phone="254700000099",
            meta_message_id="wamid.FALLBACK-IDEMPOTENT",
        )

    assert first["success"] is True
    assert second["skipped"] is True
    assert claim.await_count == 1
    whatsapp.send_message.assert_awaited_once()
    message = whatsapp.send_message.await_args.args[1].lower()
    assert "ord-fallback-idempotent" in message
    assert "pending" in message
    assert "couldn't send" in message
    assert "no payment has been initiated" in message


@pytest.mark.asyncio
@pytest.mark.parametrize("rails_enabled", [False, True], ids=["legacy", "rails"])
async def test_added_cart_item_invalidates_checkout_summary_before_yes(
    db_session, test_user, rails_enabled
):
    pilau = CatalogProduct(
        user_id=test_user.id,
        name="Pilau",
        price=Decimal("250.00"),
        description="Pilau",
        category="food",
        sku=f"PILAU-CHECKOUT-{rails_enabled}",
        brand="Shop",
        quantity=Decimal("5"),
        unit="pcs",
        condition="new",
        image_url="",
        availability="in_stock",
        search_text="pilau",
    )
    tea = CatalogProduct(
        user_id=test_user.id,
        name="Tea",
        price=Decimal("100.00"),
        description="Tea",
        category="drinks",
        sku=f"TEA-CHECKOUT-{rails_enabled}",
        brand="Shop",
        quantity=Decimal("5"),
        unit="pcs",
        condition="new",
        image_url="",
        availability="in_stock",
        search_text="tea",
    )
    db_session.add_all([pilau, tea])
    await db_session.commit()
    await db_session.refresh(pilau)
    await db_session.refresh(tea)

    phone = "254700000001"
    session_key = f"ccm:whatsapp:{test_user.id}:{phone}"
    session = _checkout_session(session_key, str(test_user.id), phone)
    session.metadata["pending_confirmation"]["items"][0].update(
        {"id": str(pilau.id), "unit_price": 250}
    )
    session.metadata["cart"][0].update(
        {"id": str(pilau.id), "unit_price": 250}
    )
    session.metadata["commerce_rails_state"] = {
        "cart_lines": [{"product_id": str(pilau.id), "qty": 1}],
        "fulfillment_method": "pickup",
        "checkout_fields": {
            "customer_name": "Asha",
            "customer_phone": phone,
        },
        "phase": "checkout",
    }

    agent = ConversationalAgentService()
    agent.llm_service.chat_completion = AsyncMock(
        side_effect=[
            LLMResponse(
                content="",
                tools_called=[
                    {
                        "name": "manage_cart",
                        "arguments": {
                            "action": "add",
                            "product_id": str(tea.id),
                            "product_name": "Tea",
                            "quantity": 1,
                            "unit_price": 100,
                        },
                    }
                ],
            ),
            LLMResponse(content="Tea was added.", tools_called=None),
            LLMResponse(
                content="",
                tools_called=[
                    {
                        "name": "create_order",
                        "arguments": {
                            "customer_name": "Asha",
                            "customer_phone": phone,
                            "delivery_method": "pickup",
                            "items": [
                                {"id": str(pilau.id), "name": "Pilau", "quantity": 1},
                                {"id": str(tea.id), "name": "Tea", "quantity": 1},
                            ],
                        },
                    }
                ],
            ),
            LLMResponse(content="Please review your updated cart.", tools_called=None),
        ]
    )
    create_order = AsyncMock()
    patches = _bind_session(session)
    with patches[0], patches[1], patches[2], patch.object(
        agent, "_sub_create_order", new=create_order
    ):
        added = await agent.execute(
            user_message="Add Tea to my cart",
            session_key=session_key,
            business_config={
                "order_type": "retail",
                "commerce_rails_enabled": rails_enabled,
            },
            user=test_user,
            db=db_session,
        )
        assert added["order_created"] is False
        assert len(session.metadata["cart"]) == 2
        assert "pending_confirmation" not in session.metadata
        assert session.metadata["awaiting_order_confirmation"] is False

        confirmed = await agent.execute(
            user_message="Yes",
            session_key=session_key,
            business_config={
                "order_type": "retail",
                "commerce_rails_enabled": rails_enabled,
            },
            user=test_user,
            db=db_session,
        )

    create_order.assert_not_awaited()
    assert confirmed["order_created"] is False
    assert len(session.metadata["cart"]) == 2


@pytest.mark.asyncio
async def test_typed_yes_dispatches_order_follow_up_once(db_session, test_user):
    product = CatalogProduct(
        user_id=test_user.id,
        name="Tea",
        price=Decimal("100.00"),
        description="Tea",
        category="drinks",
        sku="TEA-WA-YES",
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
                    "unit_price": 100,
                }
            ]
        },
        "cart": [
            {
                "id": str(product.id),
                "name": "Tea",
                "quantity": 1,
                "unit_price": 100,
            }
        ],
        "commerce_rails_state": {
            "cart_lines": [{"product_id": str(product.id), "qty": 1}],
            "fulfillment_method": "pickup",
            "checkout_fields": {
                "customer_name": "Asha",
                "customer_phone": phone,
            },
            "phase": "checkout",
        },
    }

    saved_orders = {}

    async def save_order(_port, order):
        saved_orders[order["id"]] = dict(order)
        return {"id": order["id"]}

    async def get_order(_port, order_id):
        order = saved_orders.get(order_id)
        if not order:
            return None
        fields = order.get("checkout_fields") or {}
        return {
            "id": order_id,
            "status": order["status"],
            "payment_status": order["payment_status"],
            "line_items": order["line_items"],
            "total": order["total"],
            "fulfillment_method": order["fulfillment_method"],
            "customer_phone": fields.get("customer_phone", ""),
            "customer_name": fields.get("customer_name", ""),
        }

    agent = ConversationalAgentService()
    session_patches = _bind_session(session)
    with (
        session_patches[0],
        session_patches[1],
        session_patches[2],
        patch.object(DbOrderPort, "save_order", new=save_order),
        patch.object(DbOrderPort, "get_order", new=get_order),
        patch.object(
            agent, "_bg_notify_order_placed", new_callable=AsyncMock
        ) as notify,
        patch.object(
            agent, "_sub_initiate_mpesa_payment", new_callable=AsyncMock
        ) as initiate_stk,
    ):
        result = await agent.execute(
            user_message="Yes",
            session_key=session_key,
            business_config={
                "order_type": "retail",
                "commerce_rails_enabled": True,
                "business_name": "Shop",
                "customer_name": "Asha",
                "customer_phone": phone,
                "platform": "whatsapp",
            },
            user=test_user,
            db=db_session,
            meta_message_id="wamid.test-yes",
        )

    assert len(saved_orders) == 1
    order_id = next(iter(saved_orders))
    order_data = result["order_data"]
    assert result["order_created"] is True
    assert order_data["order_id"] == order_id
    assert result["order_notification"]
    notify.assert_awaited_once()
    assert notify.await_args.args[0] == test_user.id
    assert notify.await_args.args[1] == phone
    assert notify.await_args.args[2]["order_id"] == order_id
    assert notify.await_args.args[6] == "wamid.test-yes"
    assert result["response_text"] == ""
    initiate_stk.assert_not_awaited()
