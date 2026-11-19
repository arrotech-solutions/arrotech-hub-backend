"""STK finalize sessions must set RLS tenant context; reconcile failures must rollback."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_poll_sets_tenant_context_before_paid_finalize():
    from src.services.order_stk_payment_service import poll_stk_and_finalize_order_payment

    owner_id = "f90eb4b7-f155-49ce-b76f-518f8ca9b673"
    order_id = "ORD-RLS-001"
    checkout_id = "ws_CO_RLS123"

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
    set_tenant = AsyncMock()
    call_order = []

    async def _set_tenant(db, user_id):
        call_order.append(("set_tenant", str(user_id)))
        await set_tenant(db, user_id)

    async def _finalize(**kwargs):
        call_order.append(("finalize", kwargs.get("owner_user_id")))

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
        "src.database.set_tenant_context",
        side_effect=_set_tenant,
    ), patch(
        "src.services.order_stk_payment_service.finalize_order_stk_payment",
        side_effect=_finalize,
    ):
        track.get_registered_order.return_value = registry
        track.resolve_stk_notify_context.return_value = {
            "order_id": order_id,
            "whatsapp_sender": "254711371265",
            "mpesa_phone": "254797568564",
            "platform": "whatsapp",
            "storage_config": {"provider": "none"},
            "amount": 500,
        }
        DarajaCls.return_value.stk_push_query = AsyncMock(
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

    assert ("set_tenant", owner_id) in call_order
    assert ("finalize", owner_id) in call_order
    assert call_order.index(("set_tenant", owner_id)) < call_order.index(("finalize", owner_id))
    set_tenant.assert_awaited()


@pytest.mark.asyncio
async def test_reconcile_failure_rolls_back_then_paid_notify_still_runs():
    """RLS poison must not skip customer notify after Daraja confirmed paid."""
    from src.services.order_stk_payment_service import finalize_order_stk_payment

    owner_id = "f90eb4b7-f155-49ce-b76f-518f8ca9b673"
    order_id = "ORD-RLS-002"
    mock_db = AsyncMock()
    mock_db.rollback = AsyncMock()
    owner = MagicMock()
    owner.id = owner_id

    owner_result = MagicMock()
    owner_result.scalar_one_or_none.return_value = owner
    mock_db.execute = AsyncMock(return_value=owner_result)

    registry = {
        "order_id": order_id,
        "payment_notified": False,
        "whatsapp_sender": "254711371265",
        "order": {"customer_phone": "254711371265", "total": 100, "items": []},
    }

    with patch(
        "src.services.order_stk_payment_service.order_tracking_service"
    ) as track, patch(
        "src.services.order_stk_payment_service.CommerceStorageService",
        create=True,
    ), patch(
        "src.services.commerce_storage_service.CommerceStorageService"
    ) as StorageCls, patch(
        "src.services.whatsapp_service.WhatsAppService"
    ) as WaCls:
        track.get_registered_order.return_value = registry
        track._get_whatsapp_config = AsyncMock(
            return_value={"access_token": "tok", "phone_number_id": "pnid"}
        )
        track.notify_payment_received = AsyncMock()
        track.record_payment_attempt = AsyncMock()

        storage = StorageCls.return_value
        storage.get_order = AsyncMock(side_effect=Exception("RLS blocked commerce_orders"))
        storage.upsert_order = AsyncMock()
        storage.mark_order_paid = AsyncMock()

        wa = WaCls.return_value
        wa.send_message = AsyncMock(return_value={"success": True})

        await finalize_order_stk_payment(
            db=mock_db,
            owner_user_id=owner_id,
            order_id=order_id,
            whatsapp_sender="254711371265",
            mpesa_phone="254797568564",
            platform="whatsapp",
            storage_config={"provider": "none"},
            is_paid=True,
            mpesa_receipt="QHXRLS1",
            amount_paid=100,
            checkout_request_id="ws_CO_RLS2",
        )

    mock_db.rollback.assert_awaited()
    wa.send_message.assert_awaited()
    track.notify_payment_received.assert_awaited()


@pytest.mark.asyncio
async def test_callback_background_sets_tenant_before_finalize():
    from src.routers.mpesa_agent_router import _handle_mpesa_callback_background

    owner_id = "f90eb4b7-f155-49ce-b76f-518f8ca9b673"
    webhook_secret = "secret-rls-test"
    body = (
        b'{"Body":{"stkCallback":{"CheckoutRequestID":"ws_CO_CB1",'
        b'"MerchantRequestID":"mr_CB1","ResultCode":0,'
        b'"ResultDesc":"The service request is processed successfully.",'
        b'"CallbackMetadata":{"Item":['
        b'{"Name":"Amount","Value":100},'
        b'{"Name":"MpesaReceiptNumber","Value":"QHXCB1"},'
        b'{"Name":"PhoneNumber","Value":254797568564}'
        b"]}}}}"
    )

    mock_db = AsyncMock()
    mock_session_maker = MagicMock()
    mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

    config = MagicMock()
    config.user_id = owner_id
    config.webhook_secret = webhook_secret

    cfg_result = MagicMock()
    cfg_result.scalar_one_or_none.return_value = config
    mock_db.execute = AsyncMock(return_value=cfg_result)

    set_tenant = AsyncMock()
    call_order = []

    async def _set_tenant(db, user_id):
        call_order.append(("set_tenant", str(user_id)))
        await set_tenant(db, user_id)

    async def _finalize(**kwargs):
        call_order.append(("finalize", kwargs.get("owner_user_id")))

    with patch(
        "src.database.get_session_maker",
        return_value=mock_session_maker,
    ), patch(
        "src.database.set_tenant_context",
        side_effect=_set_tenant,
    ), patch(
        "src.routers.mpesa_agent_router.MpesaReconciliationService"
    ) as RecoCls, patch(
        "src.services.order_tracking_service.order_tracking_service"
    ) as track, patch(
        "src.services.order_stk_payment_service.finalize_order_stk_payment",
        side_effect=_finalize,
    ), patch(
        "src.routers.mpesa_agent_router.cache_service"
    ):
        reco = RecoCls.return_value
        reco._parse_stk_callback.return_value = {
            "checkout_request_id": "ws_CO_CB1",
            "merchant_request_id": "mr_CB1",
            "result_code": "0",
            "result_desc": "ok",
            "transaction_id": "QHXCB1",
            "amount": 100,
        }
        reco.process_stk_callback = AsyncMock(return_value=MagicMock())
        track.resolve_stk_notify_context.return_value = {
            "order_id": "ORD-CB-1",
            "whatsapp_sender": "254711371265",
            "mpesa_phone": "254797568564",
            "platform": "whatsapp",
            "storage_config": {"provider": "none"},
            "amount": 100,
            "currency": "KES",
        }

        await _handle_mpesa_callback_background(webhook_secret, body)

    assert ("set_tenant", owner_id) in call_order
    assert ("finalize", owner_id) in call_order
    assert call_order.index(("set_tenant", owner_id)) < call_order.index(("finalize", owner_id))
