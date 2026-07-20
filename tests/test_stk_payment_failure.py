"""Tests for M-Pesa STK payment failure handling and retry."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.stk_result_messages import (
    STK_TERMINAL_FAILURE_CODES,
    stk_api_error_message,
    stk_customer_message,
    stk_inconclusive_message,
)


def test_stk_customer_message_insufficient_funds():
    msg = stk_customer_message("1", lang="en")
    assert "balance" in msg.lower() or "low" in msg.lower()


def test_stk_customer_message_wrong_pin_swahili():
    msg = stk_customer_message("2001", lang="sw")
    assert "PIN" in msg or "pin" in msg.lower()


def test_stk_customer_message_cancelled():
    msg = stk_customer_message("1032", lang="en")
    assert "cancel" in msg.lower()


def test_terminal_failure_codes_include_common_cases():
    assert "1" in STK_TERMINAL_FAILURE_CODES
    assert "1032" in STK_TERMINAL_FAILURE_CODES
    assert "2001" in STK_TERMINAL_FAILURE_CODES


def test_inconclusive_and_api_messages():
    assert stk_inconclusive_message(lang="en")
    assert stk_api_error_message(lang="sw")


@pytest.mark.asyncio
async def test_finalize_failure_sends_retry_buttons():
    from src.services.order_stk_payment_service import finalize_order_stk_payment

    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "f90eb4b7-f155-49ce-b76f-518f8ca9b673"

    with patch(
        "src.services.order_stk_payment_service.select"
    ) as mock_select, patch(
        "src.services.order_stk_payment_service.order_tracking_service"
    ) as track, patch(
        "src.services.order_stk_payment_service.cache_service"
    ) as cache:

        cache.get.return_value = None
        track.get_registered_order.return_value = {
            "order_id": "ORD-1",
            "payment_notified": False,
            "amount": 100,
        }
        track.record_payment_failure_metadata.return_value = 1
        track.send_payment_retry_buttons = AsyncMock(return_value={"success": True})
        track.record_payment_attempt = AsyncMock()
        track.maybe_alert_business_payment_failures = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        await finalize_order_stk_payment(
            db=mock_db,
            owner_user_id=str(mock_user.id),
            order_id="ORD-1",
            whatsapp_sender="254711371265",
            mpesa_phone="254711371265",
            platform="whatsapp",
            storage_config={"provider": "none"},
            is_paid=False,
            result_code="1032",
            result_desc="Request cancelled by user",
            checkout_request_id="ws_CO_FAIL123",
        )

        track.send_payment_retry_buttons.assert_awaited_once()
        cache.set.assert_called()
        track.record_payment_failure_metadata.assert_called_once()


@pytest.mark.asyncio
async def test_finalize_failure_idempotent_per_checkout():
    from src.services.order_stk_payment_service import finalize_order_stk_payment

    with patch(
        "src.services.order_stk_payment_service.cache_service"
    ) as cache, patch(
        "src.services.order_stk_payment_service.order_tracking_service"
    ) as track:

        cache.get.return_value = True
        track.get_registered_order.return_value = {"payment_notified": False}

        await finalize_order_stk_payment(
            db=AsyncMock(),
            owner_user_id="owner-1",
            order_id="ORD-1",
            whatsapp_sender="254711371265",
            mpesa_phone="254711371265",
            platform="whatsapp",
            storage_config={},
            is_paid=False,
            result_code="1",
            checkout_request_id="ws_CO_DUP",
        )

        track.send_payment_retry_buttons.assert_not_called()


@pytest.mark.asyncio
async def test_initiate_mpesa_blocks_already_paid():
    from src.services.conversational_agent_service import ConversationalAgentService

    svc = ConversationalAgentService()
    user = MagicMock()
    user.id = "f90eb4b7-f155-49ce-b76f-518f8ca9b673"

    with patch(
        "src.services.order_tracking_service.order_tracking_service"
    ) as track:
        track.owner_id_from_session_key.return_value = str(user.id)
        track.get_registered_order.return_value = {"payment_notified": True}

        res = await svc._sub_initiate_mpesa_payment(
            order_id="ORD-PAID",
            phone_number="254711371265",
            amount=100,
            description="test",
            session_key="ccm:whatsapp:u:254711371265",
            storage_config={},
            business_name="Test",
            user=user,
            db=AsyncMock(),
        )

    assert res["success"] is False
    assert "paid" in res["error"].lower()


@pytest.mark.asyncio
async def test_initiate_mpesa_debounce_blocks_rapid_retry():
    from src.services.conversational_agent_service import ConversationalAgentService

    svc = ConversationalAgentService()
    user = MagicMock()
    user.id = "f90eb4b7-f155-49ce-b76f-518f8ca9b673"

    with patch(
        "src.services.order_tracking_service.order_tracking_service"
    ) as track:
        track.owner_id_from_session_key.return_value = str(user.id)
        track.get_registered_order.return_value = {"payment_notified": False}
        track.is_stk_debounced.return_value = True

        res = await svc._sub_initiate_mpesa_payment(
            order_id="ORD-1",
            phone_number="254711371265",
            amount=100,
            description="test",
            session_key="ccm:whatsapp:u:254711371265",
            storage_config={},
            business_name="Test",
            user=user,
            db=AsyncMock(),
        )

    assert res["success"] is False
    assert "wait" in res["error"].lower()
