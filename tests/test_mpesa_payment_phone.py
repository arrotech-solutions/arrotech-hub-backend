"""Tests for M-Pesa alternate payment phone flows."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.conversation_context_manager import ConversationSession, context_manager
from src.services.conversational_agent_service import ConversationalAgentService
from src.services.whatsapp_ordering_helpers import (
    PAY_MPESA_OTHER_PREFIX,
    extract_phone_from_text,
    mask_mpesa_phone,
    normalize_ke_mpesa_phone,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0712345678", "254712345678"),
        ("254712345678", "254712345678"),
        ("712345678", "254712345678"),
        ("+254 712 345 678", "254712345678"),
        ("invalid", None),
        ("0612345678", None),
    ],
)
def test_normalize_ke_mpesa_phone(raw, expected):
    assert normalize_ke_mpesa_phone(raw) == expected


def test_extract_phone_from_text():
    assert extract_phone_from_text("0712345678") == "254712345678"
    assert extract_phone_from_text("my mpesa is 0722 111 222") == "254722111222"
    assert extract_phone_from_text("hello") is None
    assert extract_phone_from_text("cancel") is None


def test_mask_mpesa_phone():
    masked = mask_mpesa_phone("254712345678")
    assert "***" in masked
    assert masked.startswith("25471")


@pytest.mark.asyncio
async def test_notify_order_placed_sends_two_payment_buttons(sample_order_fixture):
    from src.services.order_tracking_service import OrderTrackingService

    tracking_service = OrderTrackingService()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-1"
    db = AsyncMock()
    sample_order = sample_order_fixture

    with patch("src.services.order_tracking_service.cache_service") as cache, \
         patch.object(tracking_service, "_get_whatsapp_config", new_callable=AsyncMock) as wa_cfg, \
         patch.object(tracking_service.order_service, "format_order_receipt", new_callable=AsyncMock) as fmt, \
         patch.object(tracking_service, "_generate_receipt_pdf_bytes", new_callable=AsyncMock) as gen_pdf, \
         patch("src.services.whatsapp_service.WhatsAppService") as WaCls:

        cache.get.return_value = {}
        wa_cfg.return_value = {"access_token": "tok", "phone_number_id": "pnid"}
        fmt.return_value = {"success": True, "message": "text receipt"}
        gen_pdf.return_value = b"%PDF"

        wa = WaCls.return_value
        wa.send_message = AsyncMock(return_value={"success": True})
        wa.upload_and_send_document = AsyncMock(return_value={"success": True})
        wa.send_quick_reply_buttons = AsyncMock(return_value={"success": True})

        await tracking_service.notify_order_placed(
            user=mock_user,
            db=db,
            customer_phone=sample_order["customer_phone"],
            order_data={"order": sample_order},
            business_name="Test Cafe",
        )

        wa.send_quick_reply_buttons.assert_called_once()
        buttons = wa.send_quick_reply_buttons.call_args.kwargs.get("buttons") or \
            wa.send_quick_reply_buttons.call_args[1].get("buttons") or \
            wa.send_quick_reply_buttons.call_args[0][2]
        titles = {b["title"] for b in buttons}
        ids = {b["id"] for b in buttons}
        assert "Pay on this number" in titles
        assert "Other number" in titles
        assert f"pay_mpesa:{sample_order['order_id']}" in ids
        assert f"pay_mpesa_other:{sample_order['order_id']}" in ids


@pytest.fixture
def sample_order_fixture():
    return {
        "order_id": "ORD-20250626-ABC123",
        "customer_name": "Jane Doe",
        "customer_phone": "254712345678",
        "items": [{"name": "Burger", "quantity": 1, "unit_price": 500, "total": 500}],
        "subtotal": 500,
        "delivery_method": "pickup",
        "status": "pending",
    }


@pytest.mark.asyncio
async def test_pay_mpesa_other_sets_awaiting_state(sample_order_fixture):
    agent = ConversationalAgentService()
    user = MagicMock()
    user.id = "user-uuid-1"
    db = AsyncMock()
    order_id = sample_order_fixture["order_id"]
    session_key = f"ccm:whatsapp:{user.id}:254711371265"
    msg = f"{PAY_MPESA_OTHER_PREFIX}{order_id}"

    session = ConversationSession(
        session_key=session_key,
        platform="whatsapp",
        owner_user_id=str(user.id),
        sender_id="254711371265",
        messages=[],
        metadata={},
    )

    metadata_updates = []

    async def fake_get_session_by_key(key):
        return session

    async def fake_update_metadata(key, updates):
        metadata_updates.append(updates)
        session.metadata.update({k: v for k, v in updates.items() if v is not None})

    with patch.object(context_manager, "get_session_by_key", fake_get_session_by_key), \
         patch.object(context_manager, "update_session_metadata", fake_update_metadata), \
         patch.object(context_manager, "maybe_expire_human_handoff", AsyncMock()), \
         patch.object(agent, "_cart_fast_path_result", new_callable=AsyncMock) as fast_path:

        fast_path.return_value = {"response_text": "ask phone"}

        await agent.execute(
            user_message=msg,
            session_key=session_key,
            business_config={"business_name": "Test Cafe", "customer_phone": "254711371265"},
            user=user,
            db=db,
        )

        assert any(
            u.get("awaiting_mpesa_payment", {}).get("order_id") == order_id
            for u in metadata_updates
        )
        fast_path.assert_called_once()
        assert fast_path.call_args[0][1]  # reply mentions M-Pesa number


@pytest.mark.asyncio
async def test_awaiting_phone_triggers_stk_with_parsed_number(sample_order_fixture):
    agent = ConversationalAgentService()
    user = MagicMock()
    user.id = "user-uuid-1"
    db = AsyncMock()
    order_id = sample_order_fixture["order_id"]
    session_key = f"ccm:whatsapp:{user.id}:254711371265"
    alt_phone = "254722111222"

    session = ConversationSession(
        session_key=session_key,
        platform="whatsapp",
        owner_user_id=str(user.id),
        sender_id="254711371265",
        messages=[],
        metadata={
            "awaiting_mpesa_payment": {
                "order_id": order_id,
                "default_phone": "254711371265",
            }
        },
    )

    async def fake_get_session_by_key(key):
        return session

    async def fake_update_metadata(key, updates):
        for k, v in updates.items():
            if v is None:
                session.metadata.pop(k, None)
            else:
                session.metadata[k] = v

    with patch.object(context_manager, "get_session_by_key", fake_get_session_by_key), \
         patch.object(context_manager, "update_session_metadata", fake_update_metadata), \
         patch.object(context_manager, "maybe_expire_human_handoff", AsyncMock()), \
         patch.object(agent, "_sub_initiate_mpesa_payment", new_callable=AsyncMock) as stk, \
         patch.object(agent, "_cart_fast_path_result", new_callable=AsyncMock) as fast_path:

        stk.return_value = {"success": True}
        fast_path.return_value = {"response_text": "stk sent"}

        await agent.execute(
            user_message="0722111222",
            session_key=session_key,
            business_config={"business_name": "Test Cafe", "customer_phone": "254711371265"},
            user=user,
            db=db,
        )

        stk.assert_called_once()
        assert stk.call_args.kwargs["phone_number"] == alt_phone
        assert stk.call_args.kwargs["order_id"] == order_id
        assert "awaiting_mpesa_payment" not in session.metadata


@pytest.mark.asyncio
async def test_initiate_mpesa_allowlist_permits_alt_phone(sample_order_fixture):
    agent = ConversationalAgentService()
    user = MagicMock()
    user.id = "user-uuid-1"
    db = AsyncMock()
    order_id = sample_order_fixture["order_id"]
    session_key = f"ccm:whatsapp:{user.id}:254711371265"
    alt_phone = "254722111222"

    session = ConversationSession(
        session_key=session_key,
        platform="whatsapp",
        owner_user_id=str(user.id),
        sender_id="254711371265",
        messages=[],
        metadata={
            "awaiting_mpesa_payment": {"resolved_phone": alt_phone},
            "orders_by_id": {order_id: sample_order_fixture},
        },
    )

    async def fake_get_session_by_key(key):
        return session

    with patch.object(context_manager, "get_session_by_key", fake_get_session_by_key), \
         patch.object(agent, "_sub_initiate_mpesa_payment", new_callable=AsyncMock) as stk:

        stk.return_value = {"success": True}

        await agent._execute_sub_tool(
            tool_name="initiate_mpesa_payment",
            arguments={
                "order_id": order_id,
                "phone_number": alt_phone,
                "amount": 500,
            },
            kb_id="",
            order_type="food",
            currency="KES",
            business_name="Test Cafe",
            storage_config={"provider": "none"},
            session_key=session_key,
            user=user,
            db=db,
            default_customer_phone="254711371265",
        )

        stk.assert_called_once()
        assert stk.call_args.kwargs["phone_number"] == alt_phone


@pytest.mark.asyncio
async def test_initiate_mpesa_allowlist_overrides_random_llm_phone(sample_order_fixture):
    agent = ConversationalAgentService()
    user = MagicMock()
    user.id = "user-uuid-1"
    db = AsyncMock()
    order_id = sample_order_fixture["order_id"]
    session_key = f"ccm:whatsapp:{user.id}:254711371265"

    session = ConversationSession(
        session_key=session_key,
        platform="whatsapp",
        owner_user_id=str(user.id),
        sender_id="254711371265",
        messages=[],
        metadata={"orders_by_id": {order_id: sample_order_fixture}},
    )

    async def fake_get_session_by_key(key):
        return session

    with patch.object(context_manager, "get_session_by_key", fake_get_session_by_key), \
         patch.object(agent, "_sub_initiate_mpesa_payment", new_callable=AsyncMock) as stk:

        stk.return_value = {"success": True}

        await agent._execute_sub_tool(
            tool_name="initiate_mpesa_payment",
            arguments={
                "order_id": order_id,
                "phone_number": "254799999999",
                "amount": 500,
            },
            kb_id="",
            order_type="food",
            currency="KES",
            business_name="Test Cafe",
            storage_config={"provider": "none"},
            session_key=session_key,
            user=user,
            db=db,
            default_customer_phone="254711371265",
        )

        stk.assert_called_once()
        assert stk.call_args.kwargs["phone_number"] == "254711371265"


def test_record_stk_context_and_find_by_stk_ids(sample_order_fixture):
    from src.services.order_tracking_service import OrderTrackingService

    svc = OrderTrackingService()
    owner_id = "user-uuid-1"
    order_id = sample_order_fixture["order_id"]
    checkout_id = "ws_CO_12345"
    merchant_id = "mr_67890"

    stored = {}

    def fake_set(key, value, expire_seconds=3600):
        stored[key] = value
        return True

    def fake_get(key):
        return stored.get(key)

    def fake_keys(pattern):
        prefix = pattern.replace("*", "")
        return [k for k in stored if k.startswith(prefix.rstrip(":"))]

    with patch("src.services.order_tracking_service.cache_service") as cache:
        cache.set.side_effect = fake_set
        cache.get.side_effect = fake_get
        cache.keys.side_effect = fake_keys

        svc.register_order(
            owner_id,
            order_id,
            "254711371265",
            sample_order_fixture,
            business_name="Test Cafe",
        )
        svc.record_stk_context(
            owner_id,
            order_id,
            checkout_request_id=checkout_id,
            merchant_request_id=merchant_id,
            whatsapp_sender="254711371265",
            mpesa_phone="254797568564",
        )

        reg = svc.get_registered_order(owner_id, order_id)
        assert reg["whatsapp_sender"] == "254711371265"
        assert reg["customer_phone"] == "254711371265"
        assert reg["mpesa_phone"] == "254797568564"
        assert reg["stk_checkout_request_id"] == checkout_id
        assert reg["stk_initiated"] is True

        found = svc.find_order_by_stk_ids(owner_id, checkout_request_id=checkout_id)
        assert found is not None
        assert found["order_id"] == order_id

        found_m = svc.find_order_by_stk_ids(owner_id, merchant_request_id=merchant_id)
        assert found_m is not None


@pytest.mark.asyncio
async def test_notify_payment_received_prefers_whatsapp_sender(sample_order_fixture):
    from src.services.order_tracking_service import OrderTrackingService

    svc = OrderTrackingService()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-1"
    db = AsyncMock()
    order_id = sample_order_fixture["order_id"]

    registry = {
        "order_id": order_id,
        "whatsapp_sender": "254711371265",
        "customer_phone": "254711371265",
        "mpesa_phone": "254797568564",
        "business_name": "Test Cafe",
        "currency": "KES",
        "order": sample_order_fixture,
        "payment_notified": False,
    }

    with patch("src.services.order_tracking_service.cache_service") as cache, \
         patch.object(svc, "_get_whatsapp_config", new_callable=AsyncMock) as wa_cfg, \
         patch.object(svc, "_generate_receipt_pdf_bytes", new_callable=AsyncMock) as gen_pdf, \
         patch("src.services.whatsapp_service.WhatsAppService") as WaCls:

        cache.get.return_value = registry
        wa_cfg.return_value = {"access_token": "tok", "phone_number_id": "pnid"}
        gen_pdf.return_value = b"%PDF-PAID"

        wa = WaCls.return_value
        wa.upload_and_send_document = AsyncMock(return_value={"success": True})

        await svc.notify_payment_received(
            user=mock_user,
            db=db,
            order_id=order_id,
            mpesa_receipt="QHX111",
            amount_paid=500,
            customer_phone="254797568564",
        )

        call_kwargs = wa.upload_and_send_document.call_args.kwargs
        assert call_kwargs["to_number"] == "254711371265"
