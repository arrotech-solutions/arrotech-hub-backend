"""Returns, complaints, and refund payout rails.

Review focus:
- Approve without Daraja payout creds stays refund_pending, never refunded.
- Auto-approve over the cap or outside the window stays Hub-pending with no payout.
- Approve with a mocked B2C payout that includes a receipt becomes refunded.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    CommerceOrder,
    CommerceRefundAttempt,
    CommerceReturn,
    User,
)
from src.services.commerce_policy import upsert_policy
from src.services.commerce_refund_service import (
    execute_refund,
    mark_settled_offline,
    payout_credentials_configured,
)
from src.services.commerce_returns_service import (
    apply_aftersale_command,
    approve_return,
    deny_return,
    evaluate_auto_approve,
    request_complaint,
    request_return,
)
from src.services.commerce_runtime import CommerceRuntime, CommerceState
from src.services.daraja_service import DarajaService


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _make_order(
    db: AsyncSession,
    user: User,
    *,
    external_id: str = "ORD-RET-1",
    total: str = "1500.00",
    created_at: datetime | None = None,
    phone: str = "0712345678",
    notes: str | None = None,
) -> CommerceOrder:
    order = CommerceOrder(
        user_id=user.id,
        external_order_id=external_id,
        customer_name="Amina",
        customer_phone=phone,
        status="delivered",
        payment_status="paid",
        payment_method="mpesa",
        currency="KES",
        total=Decimal(total),
        line_items=[
            {
                "product_id": "sku-1",
                "qty": 1,
                "name": "Rice",
                "unit_price": total,
            }
        ],
        delivery_method="delivery",
        notes=notes,
        created_at=created_at or _now(),
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


def _message(row: CommerceReturn) -> str:
    snapshot = row.raw_snapshot or {}
    return str(snapshot.get("customer_message") or "")


async def _attempts(db: AsyncSession, return_id) -> list[CommerceRefundAttempt]:
    result = await db.execute(
        select(CommerceRefundAttempt).where(
            CommerceRefundAttempt.return_id == return_id
        )
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_approve_without_payout_creds_is_pending_not_refunded(
    db_session: AsyncSession,
    test_user: User,
):
    """No Daraja payout creds: approval records an offline attempt and does not say refunded."""
    assert payout_credentials_configured() is False
    await _make_order(db_session, test_user, total="800.00")
    row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-RET-1",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("800.00"),
    )
    assert row.status == "pending_approval"
    assert await _attempts(db_session, row.id) == []

    approved = await approve_return(
        db_session, test_user.id, row.id, actor_user_id=test_user.id
    )

    assert approved.status == "refund_pending"
    assert approved.status != "refunded"
    message = _message(approved)
    assert "offline" in message.lower()
    assert "refunded" not in message.lower()
    attempts = await _attempts(db_session, approved.id)
    assert len(attempts) == 1
    assert attempts[0].method == "offline"
    assert attempts[0].status == "pending"
    assert attempts[0].mpesa_receipt is None


@pytest.mark.asyncio
async def test_auto_approve_over_cap_stays_pending_without_payout(
    db_session: AsyncSession,
    test_user: User,
):
    await upsert_policy(
        db_session,
        test_user.id,
        {"auto_approve_enabled": True, "auto_approve_max_amount_kes": 500},
    )
    order = await _make_order(db_session, test_user, total="2000.00")
    row = await request_return(
        db_session,
        test_user.id,
        order_external_id=order.external_order_id,
        phone=order.customer_phone,
        reason_code="changed_mind",
        amount=Decimal("900.00"),
    )

    assert evaluate_auto_approve(
        {
            "auto_approve_enabled": True,
            "auto_approve_max_amount_kes": 500,
            "return_window_days": 7,
            "return_reason_codes": ["changed_mind"],
        },
        row,
        order,
    ) is False
    assert row.status == "pending_approval"
    assert row.auto_approved is False
    assert await _attempts(db_session, row.id) == []


@pytest.mark.asyncio
async def test_auto_approve_outside_window_stays_pending_without_payout(
    db_session: AsyncSession,
    test_user: User,
):
    await upsert_policy(
        db_session,
        test_user.id,
        {
            "auto_approve_enabled": True,
            "auto_approve_max_amount_kes": 5000,
            "return_window_days": 7,
        },
    )
    order = await _make_order(
        db_session,
        test_user,
        external_id="ORD-OLD",
        total="400.00",
        created_at=_now() - timedelta(days=30),
    )
    row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-OLD",
        phone=order.customer_phone,
        reason_code="wrong_item",
        amount=Decimal("400.00"),
    )

    assert row.status == "pending_approval"
    assert row.auto_approved is False
    assert await _attempts(db_session, row.id) == []


@pytest.mark.asyncio
async def test_auto_approve_within_cap_and_window_without_creds_is_not_refunded(
    db_session: AsyncSession,
    test_user: User,
):
    await upsert_policy(
        db_session,
        test_user.id,
        {"auto_approve_enabled": True, "auto_approve_max_amount_kes": 1000},
    )
    order = await _make_order(
        db_session,
        test_user,
        external_id="ORD-AUTO",
        total="600.00",
    )
    row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-AUTO",
        phone=order.customer_phone,
        reason_code="not_as_described",
        amount=Decimal("600.00"),
    )

    assert evaluate_auto_approve(
        {
            "auto_approve_enabled": True,
            "auto_approve_max_amount_kes": 1000,
            "return_window_days": 7,
            "return_reason_codes": ["not_as_described"],
        },
        row,
        order,
    ) is True
    assert row.auto_approved is True
    assert row.status == "refund_pending"
    assert "refunded" not in _message(row).lower()
    attempts = await _attempts(db_session, row.id)
    assert len(attempts) == 1
    assert attempts[0].method == "offline"
    assert attempts[0].status == "pending"


@pytest.mark.asyncio
async def test_approve_with_mocked_b2c_success_marks_refunded(
    db_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    await _make_order(db_session, test_user, external_id="ORD-B2C", total="250.00")
    row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-B2C",
        phone="254712345678",
        reason_code="damaged",
        amount=Decimal("250.00"),
    )
    b2c = AsyncMock(
        return_value={
            "success": True,
            "receipt": "RFD123456",
            "conversation_id": "AG_20261114_1",
        }
    )
    monkeypatch.setattr(
        "src.services.commerce_refund_service.payout_credentials_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "src.services.commerce_refund_service.send_b2c_payout",
        b2c,
    )

    approved = await approve_return(
        db_session, test_user.id, row.id, actor_user_id=test_user.id
    )

    assert approved.status == "refunded"
    assert "RFD123456" in _message(approved)
    assert "refunded" in _message(approved).lower()
    attempts = await _attempts(db_session, approved.id)
    assert len(attempts) == 1
    assert attempts[0].method == "mpesa_b2c"
    assert attempts[0].status == "success"
    assert attempts[0].mpesa_receipt == "RFD123456"
    b2c.assert_awaited_once()
    assert b2c.await_args.kwargs["phone_number"] == "254712345678"
    assert b2c.await_args.kwargs["amount"] == 250

    again = await execute_refund(db_session, approved)
    assert again.id == attempts[0].id
    assert b2c.await_count == 1


@pytest.mark.asyncio
async def test_b2c_accept_without_receipt_stays_refund_pending(
    db_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    """Daraja accept (no receipt) is not payout success, so the return is not refunded."""
    await _make_order(db_session, test_user, external_id="ORD-ACCEPT", total="100.00")
    row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-ACCEPT",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("100.00"),
    )
    monkeypatch.setattr(
        "src.services.commerce_refund_service.payout_credentials_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "src.services.commerce_refund_service.send_b2c_payout",
        AsyncMock(
            return_value={
                "success": True,
                "accepted": True,
                "receipt": None,
                "conversation_id": "AG_PENDING",
            }
        ),
    )

    approved = await approve_return(
        db_session, test_user.id, row.id, actor_user_id=test_user.id
    )

    assert approved.status == "refund_pending"
    assert "refunded" not in _message(approved).lower()
    attempts = await _attempts(db_session, approved.id)
    assert attempts[0].method == "mpesa_b2c"
    assert attempts[0].status == "pending"
    assert attempts[0].mpesa_receipt is None


@pytest.mark.asyncio
async def test_b2c_failure_does_not_mark_refunded(
    db_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    await _make_order(db_session, test_user, external_id="ORD-FAIL", total="100.00")
    row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-FAIL",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("100.00"),
    )
    monkeypatch.setattr(
        "src.services.commerce_refund_service.payout_credentials_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "src.services.commerce_refund_service.send_b2c_payout",
        AsyncMock(return_value={"success": False, "error": "Daraja rejected"}),
    )

    approved = await approve_return(
        db_session, test_user.id, row.id, actor_user_id=test_user.id
    )

    assert approved.status == "failed"
    assert approved.status != "refunded"
    assert "refunded" not in _message(approved).lower()
    attempts = await _attempts(db_session, approved.id)
    assert attempts[0].status == "failed"
    assert "Daraja rejected" in (attempts[0].error or "")


@pytest.mark.asyncio
async def test_mark_settled_offline_is_terminal_without_claiming_refunded(
    db_session: AsyncSession,
    test_user: User,
):
    order = await _make_order(
        db_session,
        test_user,
        external_id="ORD-OFF",
        total="300.00",
        notes="Leave at gate",
    )
    row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-OFF",
        phone=order.customer_phone,
        reason_code="damaged",
        amount=Decimal("300.00"),
    )
    pending = await approve_return(
        db_session, test_user.id, row.id, actor_user_id=test_user.id
    )
    assert pending.status == "refund_pending"

    settled = await mark_settled_offline(
        db_session,
        test_user.id,
        pending.id,
        actor_user_id=test_user.id,
        note="Paid cash in shop",
    )

    assert settled.status == "settled_offline"
    assert settled.status != "refunded"
    assert "offline" in _message(settled).lower()
    assert "refunded" not in _message(settled).lower()
    await db_session.refresh(order)
    assert order.payment_status == "paid"
    assert "settled offline" in (order.notes or "").lower()
    assert "Leave at gate" in (order.notes or "")
    attempts = await _attempts(db_session, settled.id)
    assert attempts[0].method == "offline"
    assert attempts[0].status == "success"


@pytest.mark.asyncio
async def test_deny_return_does_not_create_refund_attempt(
    db_session: AsyncSession,
    test_user: User,
):
    await _make_order(db_session, test_user, external_id="ORD-DENY", total="90.00")
    row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-DENY",
        phone="0712345678",
        reason_code="changed_mind",
        amount=Decimal("90.00"),
    )

    denied = await deny_return(
        db_session,
        test_user.id,
        row.id,
        actor_user_id=test_user.id,
        reason="Outside policy photos",
    )

    assert denied.status == "denied"
    assert await _attempts(db_session, denied.id) == []
    assert (denied.raw_snapshot or {}).get("denied_by") == str(test_user.id)


@pytest.mark.asyncio
async def test_request_complaint_self_serve_resolves_and_dispute_hands_off(
    db_session: AsyncSession,
    test_user: User,
):
    resolved, resolved_result = await request_complaint(
        db_session,
        test_user.id,
        phone="0712345678",
        category="where_is_my_order",
        order_external_id="ORD-RET-1",
    )
    dispute, dispute_result = await request_complaint(
        db_session,
        test_user.id,
        phone="0712345678",
        category="payment_dispute",
        order_external_id="ORD-RET-1",
    )

    assert resolved.status == "resolved_self_serve"
    assert resolved_result["effects"] == []
    assert dispute.status == "handed_off"
    assert dispute_result["effects"] == [
        {"type": "handoff", "complaint_id": str(dispute.id)}
    ]


@pytest.mark.asyncio
async def test_aftersale_wrapper_handles_return_core_runtime_does_not(
    db_session: AsyncSession,
    test_user: User,
):
    await _make_order(db_session, test_user, external_id="ORD-WRAP", total="50.00")
    state = CommerceState(cart_lines=[])
    state, result = await apply_aftersale_command(
        db_session,
        test_user.id,
        state,
        {
            "type": "request_return",
            "order_external_id": "ORD-WRAP",
            "phone": "0712345678",
            "reason_code": "damaged",
            "amount": "50.00",
        },
    )

    assert result["ok"] is True
    assert result["effects"][0]["type"] == "persist_return"
    assert result["effects"][0]["status"] == "pending_approval"
    assert state.phase == "cart"

    runtime = CommerceRuntime(policy={}, catalog_port=None, order_port=None)
    _, core = await runtime.apply(state, {"type": "request_return"})
    assert core["ok"] is False
    assert core["error_code"] == "unknown_command"

    _, complaint = await apply_aftersale_command(
        db_session,
        test_user.id,
        state,
        {
            "type": "request_complaint",
            "phone": "0712345678",
            "category": "abuse",
        },
    )
    assert complaint["ok"] is True
    assert complaint["effects"][0]["type"] == "handoff"


@pytest.mark.asyncio
async def test_b2c_payment_success_requires_receipt(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    class _Response:
        status = 200

        async def json(self, content_type=None):
            return {
                "ResponseCode": "0",
                "ResponseDescription": "Accept the service request successfully.",
                "ConversationID": "AG_1",
                "OriginatorConversationID": "orig-1",
                "TransactionReceipt": "RCPT9",
            }

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class _Session:
        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["payload"] = json
            captured["headers"] = headers
            return _Response()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        "src.services.daraja_service.aiohttp.ClientSession",
        lambda: _Session(),
    )
    service = DarajaService(environment="sandbox")
    monkeypatch.setattr(service, "_get_access_token", AsyncMock(return_value="token"))

    result = await service.b2c_payment(
        phone_number="0712345678",
        amount=250,
        remarks="Refund RET-1",
        initiator_name="testapi",
        security_credential="sec",
        short_code="600000",
        consumer_key="key",
        consumer_secret="secret",
        result_url="https://example.test/result",
        timeout_url="https://example.test/timeout",
    )

    assert result["success"] is True
    assert result["receipt"] == "RCPT9"
    assert result["conversation_id"] == "AG_1"
    assert captured["payload"]["CommandID"] == "BusinessPayment"
    assert captured["payload"]["PartyA"] == "600000"
    assert captured["payload"]["PartyB"] == "254712345678"
    assert captured["payload"]["Amount"] == 250
    assert captured["url"].endswith("/mpesa/b2c/v1/paymentrequest")

    missing = await service.b2c_payment(
        phone_number="0712345678",
        amount=10,
        remarks="Refund",
        short_code="600000",
    )
    assert missing["success"] is False
    assert "credential" in missing["error"].lower()


@pytest.mark.asyncio
async def test_returns_router_lists_approves_denies_and_settles(
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_user: User,
):
    await _make_order(db_session, test_user, external_id="ORD-API", total="120.00")
    created = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-API",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("120.00"),
    )

    listed = await client.get("/api/commerce/returns", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["success"] is True
    ids = [item["id"] for item in body["data"]["returns"]]
    assert str(created.id) in ids

    detail = await client.get(
        f"/api/commerce/returns/{created.id}",
        headers=auth_headers,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["status"] == "pending_approval"

    approved = await client.post(
        f"/api/commerce/returns/{created.id}/approve",
        headers=auth_headers,
    )
    assert approved.status_code == 200, approved.text
    approved_data = approved.json()["data"]
    assert approved_data["status"] == "refund_pending"
    assert "refunded" not in approved_data["customer_message"].lower()
    assert approved_data["refund_attempts"][0]["method"] == "offline"

    await _make_order(db_session, test_user, external_id="ORD-API-2", total="40.00")
    denied_row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-API-2",
        phone="0712345678",
        reason_code="changed_mind",
        amount=Decimal("40.00"),
    )
    denied = await client.post(
        f"/api/commerce/returns/{denied_row.id}/deny",
        headers=auth_headers,
        json={"reason": "No photo"},
    )
    assert denied.status_code == 200, denied.text
    assert denied.json()["data"]["status"] == "denied"

    settled = await client.post(
        f"/api/commerce/returns/{created.id}/settle-offline",
        headers=auth_headers,
        json={"note": "Paid on till"},
    )
    assert settled.status_code == 200, settled.text
    settled_data = settled.json()["data"]
    assert settled_data["status"] == "settled_offline"
    assert settled_data["status"] != "refunded"
    assert "refunded" not in settled_data["customer_message"].lower()


def _b2c_result(code: int, *, originator: str, conversation: str, receipt: str | None = None, desc: str = "ok") -> dict:
    result = {
        "ResultCode": code,
        "ResultDesc": desc,
        "OriginatorConversationID": originator,
        "ConversationID": conversation,
    }
    if receipt:
        result["TransactionID"] = receipt
        result["ResultParameters"] = {
            "ResultParameter": [{"Key": "TransactionReceipt", "Value": receipt}]
        }
    return {"Result": result}


@pytest.mark.asyncio
async def test_b2c_pending_row_is_committed_before_http_and_timeout_is_not_retried(
    db_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    """A pending attempt exists before Daraja is called. Timeout leaves it pending."""
    await _make_order(db_session, test_user, external_id="ORD-TIMEOUT", total="80.00")
    row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-TIMEOUT",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("80.00"),
    )
    seen: dict = {}

    async def timeout_after_pending(**kwargs):
        attempts = await _attempts(db_session, row.id)
        seen["count_during_call"] = len(attempts)
        seen["status_during_call"] = attempts[0].status if attempts else None
        raise TimeoutError("daraja timeout")

    monkeypatch.setattr(
        "src.services.commerce_refund_service.payout_credentials_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "src.services.commerce_refund_service.send_b2c_payout",
        timeout_after_pending,
    )

    approved = await approve_return(
        db_session, test_user.id, row.id, actor_user_id=test_user.id
    )

    assert seen["count_during_call"] == 1
    assert seen["status_during_call"] == "pending"
    assert approved.status == "refund_pending"
    assert "refunded" not in _message(approved).lower()
    attempts = await _attempts(db_session, approved.id)
    assert len(attempts) == 1
    assert attempts[0].status == "pending"
    assert attempts[0].method == "mpesa_b2c"

    again = await execute_refund(db_session, approved)
    assert again.id == attempts[0].id
    assert again.status == "pending"
    approved_again = await approve_return(
        db_session, test_user.id, approved.id, actor_user_id=test_user.id
    )
    assert approved_again.status == "refund_pending"
    assert len(await _attempts(db_session, approved.id)) == 1


@pytest.mark.asyncio
async def test_failed_b2c_is_not_auto_retried(
    db_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    await _make_order(db_session, test_user, external_id="ORD-NORETRY", total="70.00")
    row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-NORETRY",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("70.00"),
    )
    calls = {"n": 0}

    async def reject(**kwargs):
        calls["n"] += 1
        return {"success": False, "error": "Daraja rejected"}

    monkeypatch.setattr(
        "src.services.commerce_refund_service.payout_credentials_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "src.services.commerce_refund_service.send_b2c_payout",
        reject,
    )

    failed = await approve_return(
        db_session, test_user.id, row.id, actor_user_id=test_user.id
    )
    assert failed.status == "failed"
    assert calls["n"] == 1

    again = await approve_return(
        db_session, test_user.id, failed.id, actor_user_id=test_user.id
    )
    assert again.status == "failed"
    assert calls["n"] == 1
    assert len(await _attempts(db_session, failed.id)) == 1

    same = await execute_refund(db_session, again)
    assert same.status == "failed"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_retry_refund_creates_a_new_pending_only_after_failure(
    db_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    from src.services.commerce_refund_service import retry_refund

    await _make_order(db_session, test_user, external_id="ORD-RETRY", total="55.00")
    row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-RETRY",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("55.00"),
    )
    calls = {"n": 0}

    async def payout(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"success": False, "error": "Daraja rejected"}
        attempts = await _attempts(db_session, row.id)
        pending = [item for item in attempts if item.status == "pending"]
        failed = [item for item in attempts if item.status == "failed"]
        assert len(failed) == 1
        assert len(pending) == 1
        return {
            "success": True,
            "receipt": "RFDRETRY",
            "conversation_id": "AG_RETRY",
            "originator_conversation_id": "orig-retry",
        }

    monkeypatch.setattr(
        "src.services.commerce_refund_service.payout_credentials_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "src.services.commerce_refund_service.send_b2c_payout",
        payout,
    )

    failed = await approve_return(
        db_session, test_user.id, row.id, actor_user_id=test_user.id
    )
    assert failed.status == "failed"
    assert calls["n"] == 1

    retried = await retry_refund(
        db_session, test_user.id, failed.id, actor_user_id=test_user.id
    )
    assert retried.status == "refunded"
    assert calls["n"] == 2
    attempts = await _attempts(db_session, failed.id)
    assert [item.status for item in attempts] == ["failed", "success"]
    assert attempts[1].mpesa_receipt == "RFDRETRY"


@pytest.mark.asyncio
async def test_b2c_result_callback_receipt_marks_refunded_and_failure_allows_settle(
    db_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    from src.services.commerce_refund_service import apply_b2c_result

    await _make_order(db_session, test_user, external_id="ORD-CB-OK", total="40.00")
    ok_row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-CB-OK",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("40.00"),
    )
    monkeypatch.setattr(
        "src.services.commerce_refund_service.payout_credentials_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "src.services.commerce_refund_service.send_b2c_payout",
        AsyncMock(
            return_value={
                "success": True,
                "accepted": True,
                "receipt": None,
                "conversation_id": "AG_OK",
                "originator_conversation_id": "orig-ok",
            }
        ),
    )
    pending = await approve_return(
        db_session, test_user.id, ok_row.id, actor_user_id=test_user.id
    )
    assert pending.status == "refund_pending"

    completed = await apply_b2c_result(
        db_session,
        _b2c_result(0, originator="orig-ok", conversation="AG_OK", receipt="RCPT-OK"),
        user_id=test_user.id,
    )
    assert completed is not None
    assert completed.status == "refunded"
    assert "RCPT-OK" in _message(completed)
    ok_attempts = await _attempts(db_session, completed.id)
    assert ok_attempts[0].status == "success"
    assert ok_attempts[0].mpesa_receipt == "RCPT-OK"

    again = await apply_b2c_result(
        db_session,
        _b2c_result(0, originator="orig-ok", conversation="AG_OK", receipt="RCPT-OK"),
        user_id=test_user.id,
    )
    assert again.status == "refunded"
    assert len(await _attempts(db_session, completed.id)) == 1

    await _make_order(db_session, test_user, external_id="ORD-CB-BAD", total="30.00")
    bad_row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-CB-BAD",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("30.00"),
    )
    monkeypatch.setattr(
        "src.services.commerce_refund_service.send_b2c_payout",
        AsyncMock(
            return_value={
                "success": True,
                "accepted": True,
                "receipt": None,
                "conversation_id": "AG_BAD",
                "originator_conversation_id": "orig-bad",
            }
        ),
    )
    waiting = await approve_return(
        db_session, test_user.id, bad_row.id, actor_user_id=test_user.id
    )
    failed = await apply_b2c_result(
        db_session,
        _b2c_result(2001, originator="orig-bad", conversation="AG_BAD", desc="Rejected"),
        user_id=test_user.id,
    )
    assert failed.status == "failed"
    assert (await _attempts(db_session, waiting.id))[0].status == "failed"
    settled = await mark_settled_offline(
        db_session, test_user.id, waiting.id, actor_user_id=test_user.id, note="Cash"
    )
    assert settled.status == "settled_offline"
    assert "refunded" not in _message(settled).lower()


@pytest.mark.asyncio
async def test_explicit_settle_offline_while_b2c_pending_does_not_claim_refunded(
    db_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    await _make_order(db_session, test_user, external_id="ORD-SETTLE-PENDING", total="25.00")
    row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-SETTLE-PENDING",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("25.00"),
    )
    monkeypatch.setattr(
        "src.services.commerce_refund_service.payout_credentials_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "src.services.commerce_refund_service.send_b2c_payout",
        AsyncMock(
            return_value={
                "success": True,
                "accepted": True,
                "receipt": None,
                "conversation_id": "AG_WAIT",
                "originator_conversation_id": "orig-wait",
            }
        ),
    )
    pending = await approve_return(
        db_session, test_user.id, row.id, actor_user_id=test_user.id
    )
    assert pending.status == "refund_pending"

    from src.services.commerce_refund_service import CommerceReturnError

    with pytest.raises(CommerceReturnError) as exc:
        await mark_settled_offline(
            db_session,
            test_user.id,
            pending.id,
            actor_user_id=test_user.id,
            note="Paid cash while M-Pesa is still pending",
        )
    assert exc.value.code == "payout_in_flight"
    await db_session.refresh(pending)
    assert pending.status == "refund_pending"
    assert pending.status != "settled_offline"


@pytest.mark.asyncio
async def test_second_full_return_is_rejected_when_money_is_reserved(
    db_session: AsyncSession,
    test_user: User,
):
    from src.services.commerce_returns_service import CommerceReturnError

    await _make_order(db_session, test_user, external_id="ORD-CAP", total="1000.00")
    first = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-CAP",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("1000.00"),
    )
    assert first.status == "pending_approval"

    same = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-CAP",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("1000.00"),
    )
    assert same.id == first.id

    with pytest.raises(CommerceReturnError) as exc:
        await request_return(
            db_session,
            test_user.id,
            order_external_id="ORD-CAP",
            phone="0712345678",
            reason_code="wrong_item",
            amount=Decimal("1000.00"),
        )
    assert exc.value.code == "amount_exceeds_order"

    await _make_order(db_session, test_user, external_id="ORD-PART", total="1000.00")
    await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-PART",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("600.00"),
    )
    with pytest.raises(CommerceReturnError):
        await request_return(
            db_session,
            test_user.id,
            order_external_id="ORD-PART",
            phone="0712345678",
            reason_code="wrong_item",
            amount=Decimal("500.00"),
        )
    second = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-PART",
        phone="0712345678",
        reason_code="changed_mind",
        amount=Decimal("400.00"),
    )
    assert second.amount == Decimal("400.00")
    assert second.id != first.id


@pytest.mark.asyncio
async def test_overlapping_execute_refund_sends_b2c_once(
    async_engine,
    db_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    await _make_order(db_session, test_user, external_id="ORD-RACE", total="15.00")
    row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-RACE",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("15.00"),
    )
    calls = {"n": 0}

    async def slow_success(**kwargs):
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return {
            "success": True,
            "receipt": "RACE1",
            "conversation_id": "AG_RACE",
            "originator_conversation_id": "orig-race",
        }

    monkeypatch.setattr(
        "src.services.commerce_refund_service.payout_credentials_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "src.services.commerce_refund_service.send_b2c_payout",
        slow_success,
    )

    maker = async_sessionmaker(async_engine, expire_on_commit=False)
    async with maker() as left, maker() as right:
        left_row = await left.get(CommerceReturn, row.id)
        right_row = await right.get(CommerceReturn, row.id)
        await asyncio.gather(
            execute_refund(left, left_row),
            execute_refund(right, right_row),
        )

    assert calls["n"] == 1
    attempts = await _attempts(db_session, row.id)
    assert len(attempts) == 1
    assert attempts[0].status == "success"
    assert attempts[0].mpesa_receipt == "RACE1"


@pytest.mark.asyncio
async def test_b2c_result_url_posts_to_tenant_callback_and_route_completes_return(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    """ResultURL is the tenant Daraja callback, and that HTTP route applies the result."""
    from src.models import MpesaAgentConfig

    secret = "tenant-b2c-secret"
    db_session.add(
        MpesaAgentConfig(
            user_id=test_user.id,
            webhook_secret=secret,
            daraja_shortcode="600000",
        )
    )
    await db_session.commit()
    monkeypatch.setattr(
        "src.services.commerce_refund_service.settings.API_BASE_URL",
        "https://hub.test",
    )
    monkeypatch.setattr(
        "src.services.commerce_refund_service.payout_credentials_configured",
        lambda: True,
    )
    captured: dict = {}

    async def accept(**kwargs):
        captured.update(kwargs)
        return {
            "success": True,
            "accepted": True,
            "receipt": None,
            "conversation_id": "AG_HTTP",
            "originator_conversation_id": "orig-http",
        }

    monkeypatch.setattr(
        "src.services.commerce_refund_service.send_b2c_payout",
        accept,
    )
    await _make_order(db_session, test_user, external_id="ORD-HTTP", total="18.00")
    row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-HTTP",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("18.00"),
    )
    pending = await approve_return(
        db_session, test_user.id, row.id, actor_user_id=test_user.id
    )
    assert pending.status == "refund_pending"
    expected = f"https://hub.test/api/agents/daraja/callback/{secret}"
    assert captured["result_url"] == expected
    assert captured["timeout_url"] == expected
    assert "/payments/mpesa/callback" not in captured["result_url"]

    response = await client.post(
        f"/api/agents/daraja/callback/{secret}",
        json=_b2c_result(0, originator="orig-http", conversation="AG_HTTP", receipt="RCPT-HTTP"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["ResultCode"] == 0
    await db_session.refresh(pending)
    assert pending.status == "refunded"
    assert (await _attempts(db_session, pending.id))[0].mpesa_receipt == "RCPT-HTTP"

    await _make_order(db_session, test_user, external_id="ORD-HTTP-FAIL", total="9.00")
    fail_row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-HTTP-FAIL",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("9.00"),
    )

    async def accept_fail(**kwargs):
        return {
            "success": True,
            "accepted": True,
            "receipt": None,
            "conversation_id": "AG_HTTP_FAIL",
            "originator_conversation_id": "orig-http-fail",
        }

    monkeypatch.setattr(
        "src.services.commerce_refund_service.send_b2c_payout",
        accept_fail,
    )
    waiting = await approve_return(
        db_session, test_user.id, fail_row.id, actor_user_id=test_user.id
    )
    fail_response = await client.post(
        f"/api/agents/daraja/callback/{secret}",
        json=_b2c_result(
            2001,
            originator="orig-http-fail",
            conversation="AG_HTTP_FAIL",
            desc="Rejected",
        ),
    )
    assert fail_response.status_code == 200, fail_response.text
    await db_session.refresh(waiting)
    assert waiting.status == "failed"
    settled = await mark_settled_offline(
        db_session, test_user.id, waiting.id, actor_user_id=test_user.id
    )
    assert settled.status == "settled_offline"


@pytest.mark.asyncio
async def test_late_b2c_success_does_not_flip_settled_offline(
    db_session: AsyncSession,
    test_user: User,
    caplog,
):
    import logging

    from src.services.commerce_refund_service import _apply_b2c_accept, apply_b2c_result

    await _make_order(db_session, test_user, external_id="ORD-LATE", total="12.00")
    row = await request_return(
        db_session,
        test_user.id,
        order_external_id="ORD-LATE",
        phone="0712345678",
        reason_code="damaged",
        amount=Decimal("12.00"),
    )
    row.status = "settled_offline"
    await db_session.commit()
    from src.models import CommerceRefundAttempt

    attempt = CommerceRefundAttempt(
        return_id=row.id,
        method="mpesa_b2c",
        status="pending",
        amount=row.amount,
        conversation_id="AG_LATE",
        originator_conversation_id="orig-late",
    )
    db_session.add(attempt)
    await db_session.commit()

    with caplog.at_level(logging.WARNING):
        updated = await apply_b2c_result(
            db_session,
            _b2c_result(0, originator="orig-late", conversation="AG_LATE", receipt="RCPT-LATE"),
            user_id=test_user.id,
        )
    assert updated.status == "settled_offline"
    await db_session.refresh(attempt)
    assert attempt.mpesa_receipt == "RCPT-LATE"
    assert "settled offline" in caplog.text.lower()

    row.status = "settled_offline"
    await db_session.commit()
    with caplog.at_level(logging.WARNING):
        await _apply_b2c_accept(
            db_session,
            row,
            attempt,
            {
                "success": True,
                "receipt": "RCPT-ACCEPT",
                "conversation_id": "AG_LATE",
                "originator_conversation_id": "orig-late",
            },
            row,
        )
    assert row.status == "settled_offline"
    assert attempt.mpesa_receipt == "RCPT-ACCEPT"
    assert "refunded" not in (row.status or "")
