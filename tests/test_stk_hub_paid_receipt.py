"""STK success writes Hub paid state and does not claim a receipt that was not sent."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.models import CommerceOrder, StkOrderMapping
from src.services.cache_service import cache_service
from src.services.commerce_storage_service import CommerceStorageService
from src.services.order_tracking_service import OrderTrackingService, order_tracking_service


def _payload(order_id: str) -> dict:
    return {
        "order_id": order_id,
        "customer_name": "Asha",
        "customer_phone": "254711000701",
        "status": "pending",
        "delivery_method": "pickup",
        "total": "100.00",
        "items": [{"name": "Tea", "quantity": 1, "unit_price": 100, "total": 100}],
    }


def _registry(order_id: str) -> dict:
    order = _payload(order_id)
    return {
        "order_id": order_id,
        "customer_phone": "254711000701",
        "whatsapp_sender": "254711000701",
        "mpesa_phone": "254711000701",
        "business_name": "Shop",
        "business_phone": "",
        "currency": "KES",
        "platform": "whatsapp",
        "storage_config": {"provider": "none"},
        "amount": 100,
        "order": order,
        "payment_notified": False,
    }


class _MemoryCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, expire_seconds=3600):
        self.store[key] = value
        return True

    def delete(self, key):
        self.store.pop(key, None)
        return True

    def keys(self, pattern):
        return []


def _patch_cache(memory: _MemoryCache):
    return patch.multiple(
        cache_service,
        get=memory.get,
        set=memory.set,
        delete=memory.delete,
        keys=memory.keys,
    )


def _patch_whatsapp(upload_result, send_result):
    wa = AsyncMock()
    wa.upload_and_send_document = AsyncMock(return_value=upload_result)
    wa.send_message = AsyncMock(return_value=send_result)
    return patch("src.services.whatsapp_service.WhatsAppService", return_value=wa), wa


async def _hub_row(db, user_id, order_id):
    result = await db.execute(
        select(CommerceOrder).where(
            CommerceOrder.user_id == user_id,
            CommerceOrder.external_order_id == order_id,
        )
    )
    return result.scalar_one_or_none()


@pytest.mark.asyncio
async def test_stk_success_marks_hub_paid_from_stk_mapping_when_order_id_blank(
    db_session, test_user
):
    """A paid STK callback with no order id still marks the mapped Hub row paid.

    Breaks if finalize returns before reading StkOrderMapping.
    """
    order_id = "ORD-MAP-1"
    await CommerceStorageService().upsert_order(db_session, test_user.id, _payload(order_id))
    db_session.add(
        StkOrderMapping(
            user_id=test_user.id,
            order_id=order_id,
            checkout_request_id="ws_CO_MAP1",
            whatsapp_sender="254711000701",
            mpesa_phone="254711000701",
            platform="whatsapp",
            storage_config={"provider": "none"},
            amount=100,
            currency="KES",
        )
    )
    await db_session.commit()

    from src.services.order_stk_payment_service import finalize_order_stk_payment

    memory = _MemoryCache()
    wa_patch, wa = _patch_whatsapp({"success": True}, {"success": True})
    with _patch_cache(memory), wa_patch, patch.object(
        OrderTrackingService,
        "_get_whatsapp_config",
        new_callable=AsyncMock,
        return_value={"access_token": "tok", "phone_number_id": "pnid"},
    ), patch.object(
        OrderTrackingService,
        "_generate_receipt_pdf_bytes",
        new_callable=AsyncMock,
        return_value=b"%PDF",
    ):
        await finalize_order_stk_payment(
            db=db_session,
            owner_user_id=str(test_user.id),
            order_id="",
            whatsapp_sender="254711000701",
            mpesa_phone="254711000701",
            platform="whatsapp",
            storage_config={"provider": "none"},
            is_paid=True,
            mpesa_receipt="QHXMAP1",
            amount_paid=100,
            checkout_request_id="ws_CO_MAP1",
            merchant_request_id="mr-map-1",
        )

    row = await _hub_row(db_session, test_user.id, order_id)
    assert row is not None
    assert row.payment_status == "paid"
    assert row.mpesa_receipt == "QHXMAP1"
    wa.upload_and_send_document.assert_awaited()


@pytest.mark.asyncio
async def test_stk_success_marks_hub_paid_from_redis_when_callback_order_id_misses(
    db_session, test_user
):
    """Redis checkout context wins when the callback order id is not the Hub row.

    Breaks if reconcile gives up after get_order misses the bad id.
    """
    order_id = "ORD-REDIS-1"
    await CommerceStorageService().upsert_order(db_session, test_user.id, _payload(order_id))
    checkout = "ws_CO_REDIS1"
    memory = _MemoryCache()
    memory.store[f"mpesa:stk:checkout:{checkout}"] = {
        "order_id": order_id,
        "whatsapp_sender": "254711000701",
        "mpesa_phone": "254711000701",
        "platform": "whatsapp",
        "storage_config": {"provider": "none"},
        "amount": 100,
        "currency": "KES",
    }

    from src.services.order_stk_payment_service import finalize_order_stk_payment

    wa_patch, _wa = _patch_whatsapp({"success": True}, {"success": True})
    with _patch_cache(memory), wa_patch, patch.object(
        OrderTrackingService,
        "_get_whatsapp_config",
        new_callable=AsyncMock,
        return_value={"access_token": "tok", "phone_number_id": "pnid"},
    ), patch.object(
        OrderTrackingService,
        "_generate_receipt_pdf_bytes",
        new_callable=AsyncMock,
        return_value=b"%PDF",
    ):
        await finalize_order_stk_payment(
            db=db_session,
            owner_user_id=str(test_user.id),
            order_id="ORD-WRONG",
            whatsapp_sender="254711000701",
            mpesa_phone="254711000701",
            platform="whatsapp",
            storage_config={"provider": "none"},
            is_paid=True,
            mpesa_receipt="QHXREDIS",
            amount_paid=100,
            checkout_request_id=checkout,
        )

    missed = await _hub_row(db_session, test_user.id, order_id)
    assert missed is not None
    assert missed.payment_status == "paid"
    assert missed.mpesa_receipt == "QHXREDIS"
    assert await _hub_row(db_session, test_user.id, "ORD-WRONG") is None


@pytest.mark.asyncio
async def test_stk_success_creates_hub_row_from_registry_when_commerce_row_missing(
    db_session, test_user
):
    """Registry snapshot is enough to create the Hub row and mark it paid.

    Breaks if a missing commerce_orders row makes STK success a no-op.
    """
    order_id = "ORD-REG-1"
    memory = _MemoryCache()
    memory.store[order_tracking_service._tracking_key(str(test_user.id), order_id)] = _registry(
        order_id
    )

    from src.services.order_stk_payment_service import finalize_order_stk_payment

    wa_patch, _wa = _patch_whatsapp({"success": True}, {"success": True})
    with _patch_cache(memory), wa_patch, patch.object(
        OrderTrackingService,
        "_get_whatsapp_config",
        new_callable=AsyncMock,
        return_value={"access_token": "tok", "phone_number_id": "pnid"},
    ), patch.object(
        OrderTrackingService,
        "_generate_receipt_pdf_bytes",
        new_callable=AsyncMock,
        return_value=b"%PDF",
    ):
        await finalize_order_stk_payment(
            db=db_session,
            owner_user_id=str(test_user.id),
            order_id=order_id,
            whatsapp_sender="254711000701",
            mpesa_phone="254711000701",
            platform="whatsapp",
            storage_config={"provider": "none"},
            is_paid=True,
            mpesa_receipt="QHXREG1",
            amount_paid=100,
            checkout_request_id="ws_CO_REG1",
        )

    row = await _hub_row(db_session, test_user.id, order_id)
    assert row is not None
    assert row.payment_status == "paid"
    assert row.mpesa_receipt == "QHXREG1"
    assert row.customer_name == "Asha"


@pytest.mark.asyncio
async def test_stk_success_retries_receipt_after_send_failure(db_session, test_user):
    """Hub is paid on the first success; a failed receipt stays retryable.

    Breaks if payment_notified is set before WhatsApp accepts the receipt,
    because the next callback then skips the send.
    """
    order_id = "ORD-RETRY-1"
    await CommerceStorageService().upsert_order(db_session, test_user.id, _payload(order_id))
    memory = _MemoryCache()
    memory.store[order_tracking_service._tracking_key(str(test_user.id), order_id)] = _registry(
        order_id
    )

    from src.services.order_stk_payment_service import finalize_order_stk_payment

    wa = AsyncMock()
    wa.upload_and_send_document = AsyncMock(
        side_effect=[
            {"success": False, "error": "meta down"},
            {"success": True},
        ]
    )
    wa.send_message = AsyncMock(return_value={"success": False, "error": "meta down"})

    with _patch_cache(memory), patch(
        "src.services.whatsapp_service.WhatsAppService", return_value=wa
    ), patch.object(
        OrderTrackingService,
        "_get_whatsapp_config",
        new_callable=AsyncMock,
        return_value={"access_token": "tok", "phone_number_id": "pnid"},
    ), patch.object(
        OrderTrackingService,
        "_generate_receipt_pdf_bytes",
        new_callable=AsyncMock,
        return_value=b"%PDF",
    ), patch.object(
        order_tracking_service.order_service,
        "format_order_receipt",
        new_callable=AsyncMock,
        return_value={"success": True, "message": "Tea receipt"},
    ):
        await finalize_order_stk_payment(
            db=db_session,
            owner_user_id=str(test_user.id),
            order_id=order_id,
            whatsapp_sender="254711000701",
            mpesa_phone="254711000701",
            platform="whatsapp",
            storage_config={"provider": "none"},
            is_paid=True,
            mpesa_receipt="QHXRETRY",
            amount_paid=100,
            checkout_request_id="ws_CO_RETRY",
        )
        row = await _hub_row(db_session, test_user.id, order_id)
        saved = memory.store[order_tracking_service._tracking_key(str(test_user.id), order_id)]
        assert row.payment_status == "paid"
        assert row.mpesa_receipt == "QHXRETRY"
        assert saved["payment_notified"] is False
        assert saved["receipt_send_status"] == "failed"

        wa.send_message.return_value = {"success": True}
        await finalize_order_stk_payment(
            db=db_session,
            owner_user_id=str(test_user.id),
            order_id=order_id,
            whatsapp_sender="254711000701",
            mpesa_phone="254711000701",
            platform="whatsapp",
            storage_config={"provider": "none"},
            is_paid=True,
            mpesa_receipt="QHXRETRY",
            amount_paid=100,
            checkout_request_id="ws_CO_RETRY",
        )

    saved = memory.store[order_tracking_service._tracking_key(str(test_user.id), order_id)]
    assert saved["payment_notified"] is True
    assert saved["receipt_send_status"] == "sent"
    assert wa.upload_and_send_document.await_count == 2


def test_paid_order_with_failed_receipt_is_not_unpaid_expiry():
    """A paid order waiting on a receipt retry must not be cancelled as unpaid."""
    svc = OrderTrackingService()
    assert (
        svc.should_expire_unpaid(
            {
                "status": "paid",
                "payment_notified": False,
                "receipt_send_status": "failed",
            }
        )
        is False
    )
    assert svc.should_expire_unpaid({"status": "pending", "payment_notified": False}) is True
    assert svc.should_expire_unpaid({"payment_notified": True, "status": "pending"}) is False
