"""Tests for STK payment poll fallback."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_poll_stk_finalizes_when_query_returns_success():
    from src.services.order_stk_payment_service import poll_stk_and_finalize_order_payment

    owner_id = "f90eb4b7-f155-49ce-b76f-518f8ca9b673"
    order_id = "ORD-TEST-001"
    checkout_id = "ws_CO_POLL123"

    registry = {
        "order_id": order_id,
        "whatsapp_sender": "254711371265",
        "customer_phone": "254711371265",
        "mpesa_phone": "254797568564",
        "platform": "whatsapp",
        "storage_config": {"provider": "none"},
        "amount": 500,
        "payment_notified": False,
    }

    mock_db = AsyncMock()
    mock_session_maker = MagicMock()
    mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "src.services.order_stk_payment_service.order_tracking_service"
    ) as track, patch(
        "src.services.order_stk_payment_service.DarajaService"
    ) as DarajaCls, patch(
        "src.services.order_stk_payment_service.asyncio.sleep", new_callable=AsyncMock
    ), patch(
        "src.database.get_session_maker",
        return_value=mock_session_maker,
    ), patch(
        "src.services.order_stk_payment_service.finalize_order_stk_payment",
        new_callable=AsyncMock,
    ) as finalize:

        track.get_registered_order.return_value = registry
        track.resolve_stk_notify_context.return_value = None
        daraja = DarajaCls.return_value
        daraja.stk_push_query = AsyncMock(
            return_value={
                "success": True,
                "result_code": "0",
                "result_desc": "The service request is processed successfully.",
            }
        )

        await poll_stk_and_finalize_order_payment(
            owner_user_id=owner_id,
            order_id=order_id,
            checkout_request_id=checkout_id,
            amount=500,
            daraja_environment="sandbox",
            consumer_key="key",
            consumer_secret="secret",
            short_code="174379",
            passkey="pass",
            initial_delay_seconds=0,
            poll_interval_seconds=0,
            max_wait_seconds=5,
        )

        finalize.assert_called_once()
        assert finalize.call_args.kwargs["is_paid"] is True
        assert finalize.call_args.kwargs["whatsapp_sender"] == "254711371265"


@pytest.mark.asyncio
async def test_poll_stk_skips_if_already_notified():
    from src.services.order_stk_payment_service import poll_stk_and_finalize_order_payment

    with patch(
        "src.services.order_stk_payment_service.order_tracking_service"
    ) as track, patch(
        "src.services.order_stk_payment_service.DarajaService"
    ) as DarajaCls, patch(
        "src.services.order_stk_payment_service.asyncio.sleep", new_callable=AsyncMock
    ), patch(
        "src.services.order_stk_payment_service.finalize_order_stk_payment",
        new_callable=AsyncMock,
    ) as finalize:

        track.get_registered_order.return_value = {
            "order_id": "ORD-X",
            "payment_notified": True,
        }
        DarajaCls.return_value.stk_push_query = AsyncMock()

        await poll_stk_and_finalize_order_payment(
            owner_user_id="user-1",
            order_id="ORD-X",
            checkout_request_id="ws_CO_X",
            daraja_environment="sandbox",
            consumer_key="k",
            consumer_secret="s",
            short_code="174379",
            passkey="p",
            initial_delay_seconds=0,
            poll_interval_seconds=0,
            max_wait_seconds=5,
        )

        finalize.assert_not_called()
        DarajaCls.return_value.stk_push_query.assert_not_called()
