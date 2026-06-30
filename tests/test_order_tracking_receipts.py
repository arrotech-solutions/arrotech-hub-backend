"""Tests for WhatsApp order PDF receipt delivery."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.order_tracking_service import OrderTrackingService


@pytest.fixture
def tracking_service():
    return OrderTrackingService()


@pytest.fixture
def sample_order():
    return {
        "order_id": "ORD-20250626-ABC123",
        "customer_name": "Jane Doe",
        "customer_phone": "254712345678",
        "items": [
            {"name": "Burger", "quantity": 2, "unit_price": 500, "total": 1000},
        ],
        "subtotal": 1000,
        "delivery_method": "pickup",
        "status": "pending",
    }


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = "user-uuid-1"
    return user


def test_build_receipt_data_pending_vs_paid(tracking_service, sample_order):
    pending = tracking_service._build_receipt_data(
        order=sample_order,
        order_id=sample_order["order_id"],
        business_name="Test Cafe",
        business_phone="254700000000",
        mpesa_receipt="",
        amount=1000,
        currency="KES",
        payment_status="pending",
    )
    paid = tracking_service._build_receipt_data(
        order=sample_order,
        order_id=sample_order["order_id"],
        business_name="Test Cafe",
        business_phone="254700000000",
        mpesa_receipt="QHX123",
        amount=1000,
        currency="KES",
        payment_status="paid",
    )

    assert pending["payment_status"] == "pending"
    assert paid["payment_status"] == "paid"
    assert paid["mpesa_receipt"] == "QHX123"
    assert pending["items"][0]["name"] == "Burger"


@pytest.mark.asyncio
async def test_generate_order_receipt_pdf_produces_valid_pdf(sample_order):
    from src.services.file_management_service import FileManagementService

    fms = FileManagementService()
    data = {
        "order_id": sample_order["order_id"],
        "business_name": "ATC Collections",
        "business_phone": "254711371265",
        "customer_name": "Jane Doe",
        "customer_phone": sample_order["customer_phone"],
        "delivery_method": "pickup",
        "items": [{"name": "Coca-Cola", "quantity": 1, "unit_price": 1, "total": 1}],
        "currency": "KES",
        "amount": 1,
        "payment_status": "pending",
        "issued_at": "30 Jun 2026, 11:55 UTC",
    }
    result = await fms.generate_order_receipt_pdf(data, filename="test_receipt.pdf")

    assert result["success"] is True
    assert result["method"] == "reportlab_receipt"
    raw = base64.b64decode(result["content"])
    assert raw.startswith(b"%PDF")
    assert b"font-family" not in raw
    assert b"ORDER RECEIVED" not in raw  # text is compressed/encoded in PDF stream


def test_order_amount_sums_line_items_when_subtotal_missing(tracking_service):
    order = {
        "items": [
            {"name": "Coca-Cola", "quantity": 1, "price": 1, "total": 1},
        ],
    }
    assert tracking_service._order_amount(order) == 1.0


def test_order_amount_uses_price_when_unit_price_missing(tracking_service):
    order = {
        "subtotal": 0,
        "items": [{"name": "Snack", "quantity": 2, "price": 50}],
    }
    assert tracking_service._order_amount(order) == 100.0


@pytest.mark.asyncio
async def test_resolve_order_for_payment_from_session_metadata(sample_order):
    from src.services.conversational_agent_service import ConversationalAgentService
    from src.services.conversation_context_manager import (
        ConversationSession,
        context_manager,
    )

    agent = ConversationalAgentService()
    user = MagicMock()
    user.id = "f90eb4b7-f155-49ce-b76f-518f8ca9b673"
    session_key = f"ccm:whatsapp:{user.id}:254711371265"

    async def fake_get_session_by_key(key):
        return ConversationSession(
            session_key=key,
            platform="whatsapp",
            owner_user_id=str(user.id),
            sender_id="254711371265",
            messages=[],
            metadata={
                "orders_by_id": {
                    sample_order["order_id"]: sample_order,
                }
            },
        )

    with patch.object(
        context_manager, "get_session_by_key", fake_get_session_by_key
    ), patch(
        "src.services.order_tracking_service.cache_service"
    ) as cache:
        cache.get.return_value = None
        cache.redis_client = None

        order, amount = await agent._resolve_order_for_payment(
            order_id=sample_order["order_id"],
            user=user,
            db=AsyncMock(),
            session_key=session_key,
            storage_config={"provider": "none"},
            amount_hint=0,
        )

    assert order is not None
    assert amount == 1000.0


def test_register_order_preserves_existing_flags(tracking_service, sample_order):
    with patch("src.services.order_tracking_service.cache_service") as cache:
        cache.redis_client = MagicMock()
        cache.get.side_effect = [
            {
                "placement_notified": True,
                "stk_initiated": True,
                "payment_notified": False,
            },
            {"order_id": sample_order["order_id"]},
        ]
        cache.set.return_value = True
        tracking_service.register_order(
            "user-1",
            sample_order["order_id"],
            sample_order["customer_phone"],
            sample_order,
            business_name="Test Cafe",
        )
        cache.set.assert_called_once()
        payload = cache.set.call_args[0][1]
        assert payload["stk_initiated"] is True
        assert payload["placement_notified"] is True


@pytest.mark.asyncio
async def test_notify_order_placed_sends_pdf(
    tracking_service, sample_order, mock_user
):
    db = AsyncMock()
    pdf_content = base64.b64encode(b"%PDF-1.4 fake").decode()

    with patch("src.services.order_tracking_service.cache_service") as cache, \
         patch.object(tracking_service, "_get_whatsapp_config", new_callable=AsyncMock) as wa_cfg, \
         patch.object(tracking_service.order_service, "format_order_receipt", new_callable=AsyncMock) as fmt, \
         patch.object(tracking_service, "_generate_receipt_pdf_bytes", new_callable=AsyncMock) as gen_pdf, \
         patch("src.services.whatsapp_service.WhatsAppService") as WaCls:

        cache.get.return_value = {}
        wa_cfg.return_value = {"access_token": "tok", "phone_number_id": "pnid"}
        fmt.return_value = {"success": True, "message": "text receipt"}
        gen_pdf.return_value = base64.b64decode(pdf_content)

        wa = WaCls.return_value
        wa.send_message = AsyncMock(return_value={"success": True})
        wa.upload_and_send_document = AsyncMock(return_value={"success": True})
        wa.send_quick_reply_buttons = AsyncMock(return_value={"success": True})

        result = await tracking_service.notify_order_placed(
            user=mock_user,
            db=db,
            customer_phone=sample_order["customer_phone"],
            order_data={"order": sample_order},
            business_name="Test Cafe",
        )

        assert result["success"] is True
        wa.upload_and_send_document.assert_called_once()
        wa.send_message.assert_called_once()
        assert "customer_receipt" in result["sent"]
        assert "receipt" not in result["sent"]


@pytest.mark.asyncio
async def test_notify_order_placed_idempotent(
    tracking_service, sample_order, mock_user
):
    db = AsyncMock()

    with patch("src.services.order_tracking_service.cache_service") as cache:
        cache.get.return_value = {"placement_notified": True}

        result = await tracking_service.notify_order_placed(
            user=mock_user,
            db=db,
            customer_phone=sample_order["customer_phone"],
            order_data={"order": sample_order},
            business_name="Test Cafe",
        )

        assert result["skipped"] is True
        assert result["reason"] == "placement_already_notified"


@pytest.mark.asyncio
async def test_notify_order_placed_skips_payment_prompt_when_stk_initiated(
    tracking_service, sample_order, mock_user
):
    db = AsyncMock()

    with patch("src.services.order_tracking_service.cache_service") as cache, \
         patch.object(tracking_service, "_get_whatsapp_config", new_callable=AsyncMock) as wa_cfg, \
         patch.object(tracking_service.order_service, "format_order_receipt", new_callable=AsyncMock) as fmt, \
         patch.object(tracking_service, "_generate_receipt_pdf_bytes", new_callable=AsyncMock) as gen_pdf, \
         patch("src.services.whatsapp_service.WhatsAppService") as WaCls:

        cache.get.return_value = {"stk_initiated": True}
        wa_cfg.return_value = {"access_token": "tok", "phone_number_id": "pnid"}
        fmt.return_value = {"success": True, "message": "text receipt"}
        gen_pdf.return_value = b"%PDF"

        wa = WaCls.return_value
        wa.send_message = AsyncMock(return_value={"success": True})
        wa.upload_and_send_document = AsyncMock(return_value={"success": True})
        wa.send_quick_reply_buttons = AsyncMock(return_value={"success": True})

        result = await tracking_service.notify_order_placed(
            user=mock_user,
            db=db,
            customer_phone=sample_order["customer_phone"],
            order_data={"order": sample_order},
            business_name="Test Cafe",
        )

        wa.send_quick_reply_buttons.assert_not_called()
        assert "payment_prompt_skipped" in result["sent"]


@pytest.mark.asyncio
async def test_notify_payment_received_after_sync_register(
    tracking_service, sample_order, mock_user
):
    db = AsyncMock()
    registry = {
        "order_id": sample_order["order_id"],
        "customer_phone": sample_order["customer_phone"],
        "business_name": "Test Cafe",
        "business_phone": "254711111111",
        "currency": "KES",
        "order": sample_order,
        "payment_notified": False,
    }

    with patch("src.services.order_tracking_service.cache_service") as cache, \
         patch.object(tracking_service, "_get_whatsapp_config", new_callable=AsyncMock) as wa_cfg, \
         patch.object(tracking_service, "_generate_receipt_pdf_bytes", new_callable=AsyncMock) as gen_pdf, \
         patch("src.services.whatsapp_service.WhatsAppService") as WaCls:

        cache.get.return_value = registry
        wa_cfg.return_value = {"access_token": "tok", "phone_number_id": "pnid"}
        gen_pdf.return_value = b"%PDF-PAID"

        wa = WaCls.return_value
        wa.upload_and_send_document = AsyncMock(return_value={"success": True})

        result = await tracking_service.notify_payment_received(
            user=mock_user,
            db=db,
            order_id=sample_order["order_id"],
            mpesa_receipt="QHX999",
            amount_paid=1000,
        )

        assert result["success"] is True
        assert "customer_receipt" in result["sent"]
        call_kwargs = wa.upload_and_send_document.call_args.kwargs
        assert call_kwargs["filename"] == f"Receipt-{sample_order['order_id']}-PAID.pdf"


@pytest.mark.asyncio
async def test_notify_payment_received_idempotent(
    tracking_service, sample_order, mock_user
):
    db = AsyncMock()

    with patch("src.services.order_tracking_service.cache_service") as cache:
        cache.get.return_value = {"payment_notified": True}

        result = await tracking_service.notify_payment_received(
            user=mock_user,
            db=db,
            order_id=sample_order["order_id"],
            mpesa_receipt="QHX999",
            amount_paid=1000,
        )

        assert result["skipped"] is True


@pytest.mark.asyncio
async def test_whatsapp_send_message_empty_skips():
    from src.services.tool_executor import ToolExecutor

    svc = ToolExecutor()
    user = MagicMock()
    user.id = "user-1"
    db = AsyncMock()

    connection = MagicMock()
    connection.config = {
        "access_token": "tok",
        "phone_number_id": "pnid",
    }

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = connection
    db.execute = AsyncMock(return_value=result_mock)

    result = await svc._execute_whatsapp_tool(
        "whatsapp_send_message",
        {
            "operation": "send_message",
            "to_number": "254712345678",
            "message": "",
        },
        user,
        db,
    )

    assert result["success"] is True
    assert result.get("skipped") is True
    assert result.get("reason") == "empty_message"
