"""Tests for the manual M-Pesa payment fallback (no STK).

Covers the gating helpers, bilingual instruction builder, the manual branch in
_sub_initiate_mpesa_payment, and the customer payment-reporting flow that writes
the reported code to the merchant's Sheet/Airtable.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.manual_payment_helpers import (
    build_manual_payment_message,
    manual_payment_configured,
    stk_credentials_ready,
)
from src.services.whatsapp_ordering_helpers import (
    REPORTED_PAID_AGENT_PREFIX,
    extract_mpesa_code,
)


def _cfg(**overrides):
    base = dict(
        webhook_secret=None,
        daraja_shortcode=None,
        daraja_passkey=None,
        manual_payment_enabled=False,
        manual_paybill_number=None,
        manual_paybill_account=None,
        manual_till_number=None,
        manual_pochi_number=None,
        manual_send_money_number=None,
        manual_recipient_name=None,
        manual_payment_note=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ── Gating helpers ────────────────────────────────────────────────────────

def test_stk_credentials_ready_full():
    cfg = _cfg(webhook_secret="wh", daraja_shortcode="174379", daraja_passkey="pk")
    decrypted = {"daraja_consumer_key": "ck", "daraja_consumer_secret": "cs"}
    assert stk_credentials_ready(cfg, decrypted) is True


@pytest.mark.parametrize(
    "cfg_kwargs,decrypted",
    [
        (dict(webhook_secret="", daraja_shortcode="1", daraja_passkey="p"), {"daraja_consumer_key": "k", "daraja_consumer_secret": "s"}),
        (dict(webhook_secret="wh", daraja_shortcode="", daraja_passkey="p"), {"daraja_consumer_key": "k", "daraja_consumer_secret": "s"}),
        (dict(webhook_secret="wh", daraja_shortcode="1", daraja_passkey=""), {"daraja_consumer_key": "k", "daraja_consumer_secret": "s"}),
        (dict(webhook_secret="wh", daraja_shortcode="1", daraja_passkey="p"), {"daraja_consumer_key": "", "daraja_consumer_secret": "s"}),
        (dict(webhook_secret="wh", daraja_shortcode="1", daraja_passkey="p"), {"daraja_consumer_key": "k", "daraja_consumer_secret": ""}),
    ],
)
def test_stk_credentials_ready_missing_any(cfg_kwargs, decrypted):
    assert stk_credentials_ready(_cfg(**cfg_kwargs), decrypted) is False


def test_stk_credentials_ready_none_cfg():
    assert stk_credentials_ready(None, {}) is False


def test_manual_payment_configured_requires_enabled_and_method():
    assert manual_payment_configured(_cfg(manual_payment_enabled=True, manual_paybill_number="400200")) is True
    assert manual_payment_configured(_cfg(manual_payment_enabled=True, manual_till_number="5203981")) is True
    assert manual_payment_configured(_cfg(manual_payment_enabled=True, manual_pochi_number="0712345678")) is True
    # Enabled but no method set
    assert manual_payment_configured(_cfg(manual_payment_enabled=True)) is False
    # Method set but not enabled
    assert manual_payment_configured(_cfg(manual_paybill_number="400200")) is False
    assert manual_payment_configured(None) is False


# ── Instruction builder ───────────────────────────────────────────────────

def test_build_manual_payment_message_paybill_uses_order_as_account():
    cfg = _cfg(manual_payment_enabled=True, manual_paybill_number="400200")
    msg = build_manual_payment_message(
        cfg, order_id="ORD-1", amount=1500, business_name="Test Cafe", currency="KES", lang="en"
    )
    assert "Pay Bill" in msg
    assert "400200" in msg
    assert "ORD-1" in msg  # account defaults to order id
    assert "KES 1,500" in msg


def test_build_manual_payment_message_fixed_account_and_all_methods():
    cfg = _cfg(
        manual_payment_enabled=True,
        manual_paybill_number="400200",
        manual_paybill_account="ACME",
        manual_till_number="5203981",
        manual_pochi_number="0712345678",
        manual_send_money_number="0722111222",
        manual_recipient_name="Acme Ltd",
    )
    msg = build_manual_payment_message(cfg, order_id="ORD-2", amount=200, business_name="Acme")
    assert "ACME" in msg
    assert "5203981" in msg
    assert "0712345678" in msg
    assert "0722111222" in msg
    assert "Acme Ltd" in msg
    # Prompts the customer to send the code afterwards
    assert "confirmation code" in msg.lower()


def test_build_manual_payment_message_swahili():
    cfg = _cfg(manual_payment_enabled=True, manual_till_number="5203981")
    msg = build_manual_payment_message(cfg, order_id="ORD-3", amount=50, business_name="Duka", lang="sw")
    assert "Buy Goods" in msg
    assert "5203981" in msg
    assert "PIN" in msg


# ── M-Pesa code extraction ─────────────────────────────────────────────────

@pytest.mark.parametrize(
    "text,expected",
    [
        ("QGR7XA12B9", "QGR7XA12B9"),
        ("my code is qgr7xa12b9 thanks", "QGR7XA12B9"),
        ("1234567890", None),  # digits only
        ("ABCDEFGHIJ", None),  # letters only
        ("hello there", None),
        ("", None),
    ],
)
def test_extract_mpesa_code(text, expected):
    assert extract_mpesa_code(text) == expected


# ── _sub_initiate_mpesa_payment manual branch ───────────────────────────────

@pytest.mark.asyncio
async def test_sub_initiate_returns_manual_when_no_stk_creds():
    from src.services.conversational_agent_service import ConversationalAgentService

    agent = ConversationalAgentService()
    user = MagicMock()
    user.id = "user-uuid-1"
    db = AsyncMock()

    cfg = _cfg(manual_payment_enabled=True, manual_paybill_number="400200")

    order_snapshot = {"order_id": "ORD-9", "subtotal": 500, "currency": "KES", "status": "pending"}

    with patch.object(agent, "_resolve_order_for_payment", new_callable=AsyncMock) as resolve, \
         patch("src.services.mpesa_reconciliation_service.MpesaReconciliationService") as ReconCls, \
         patch("src.services.daraja_service.DarajaService") as DarajaCls, \
         patch("src.services.order_tracking_service.order_tracking_service") as ots:

        resolve.return_value = (order_snapshot, 500)
        recon = ReconCls.return_value
        recon.decrypt_config_credentials.return_value = {}

        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = cfg
        db.execute = AsyncMock(return_value=mock_res)

        ots.owner_id_from_session_key.return_value = str(user.id)
        ots.get_registered_order.return_value = {}
        ots.is_stk_debounced.return_value = False

        result = await agent._sub_initiate_mpesa_payment(
            order_id="ORD-9",
            phone_number="254712345678",
            amount=500,
            description="Order ORD-9",
            session_key=f"ccm:whatsapp:{user.id}:254712345678",
            storage_config={"provider": "none"},
            business_name="Test Cafe",
            user=user,
            db=db,
        )

        assert result["success"] is True
        assert result["mode"] == "manual"
        assert "400200" in result["message"]
        DarajaCls.return_value.stk_push.assert_not_called()
        ots.mark_manual_payment.assert_called_once()


@pytest.mark.asyncio
async def test_sub_initiate_errors_when_neither_stk_nor_manual():
    from src.services.conversational_agent_service import ConversationalAgentService

    agent = ConversationalAgentService()
    user = MagicMock()
    user.id = "user-uuid-1"
    db = AsyncMock()

    cfg = _cfg()  # nothing configured

    with patch.object(agent, "_resolve_order_for_payment", new_callable=AsyncMock) as resolve, \
         patch("src.services.mpesa_reconciliation_service.MpesaReconciliationService") as ReconCls, \
         patch("src.services.order_tracking_service.order_tracking_service") as ots:

        resolve.return_value = ({"order_id": "ORD-9", "subtotal": 500}, 500)
        ReconCls.return_value.decrypt_config_credentials.return_value = {}

        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = cfg
        db.execute = AsyncMock(return_value=mock_res)

        ots.owner_id_from_session_key.return_value = str(user.id)
        ots.get_registered_order.return_value = {}
        ots.is_stk_debounced.return_value = False

        result = await agent._sub_initiate_mpesa_payment(
            order_id="ORD-9",
            phone_number="254712345678",
            amount=500,
            description="Order ORD-9",
            session_key=f"ccm:whatsapp:{user.id}:254712345678",
            storage_config={"provider": "none"},
            business_name="Test Cafe",
            user=user,
            db=db,
        )

        assert result["success"] is False
        assert "not configured" in result["error"].lower()


# ── Reported payment write to storage ───────────────────────────────────────

@pytest.mark.asyncio
async def test_record_reported_payment_marks_registry_not_paid():
    from src.services.order_tracking_service import OrderTrackingService

    svc = OrderTrackingService()
    stored = {}

    def fake_set(key, value, expire_seconds=3600):
        stored[key] = value
        return True

    def fake_get(key):
        return stored.get(key)

    with patch("src.services.order_tracking_service.cache_service") as cache:
        cache.set.side_effect = fake_set
        cache.get.side_effect = fake_get

        svc.record_reported_payment("owner-1", "ORD-5", "QGR7XA12B9")
        reg = svc.get_registered_order("owner-1", "ORD-5")

        assert reg["payment_reported"] is True
        assert reg["reported_code"] == "QGR7XA12B9"
        assert reg.get("payment_notified") is not True  # never auto-paid


@pytest.mark.asyncio
async def test_persist_reported_payment_writes_sheet_columns():
    from src.services.conversational_agent_service import ConversationalAgentService

    agent = ConversationalAgentService()
    user = MagicMock()
    user.id = "user-uuid-1"
    db = AsyncMock()

    with patch.object(agent, "_ensure_sheet_headers_with_fallback", new_callable=AsyncMock) as ensure, \
         patch.object(agent, "_upsert_order_row_in_google_sheets", new_callable=AsyncMock) as upsert, \
         patch("src.services.tool_executor.ToolExecutor"):

        ensure.return_value = {"sheet_name": "Orders", "headers": list_headers()}

        await agent.persist_reported_payment_to_storage(
            order_id="ORD-7",
            code="QGR7XA12B9",
            order_snapshot={"order_id": "ORD-7"},
            storage_config={"provider": "google_sheets", "spreadsheet_id": "sheet-1"},
            user=user,
            db=db,
        )

        upsert.assert_called_once()
        record = upsert.call_args.kwargs["order_record"]
        assert record["Payment Status"] == "reported"
        assert record["Payment Ref"] == "QGR7XA12B9"
        # Status left blank so the merchant's own status is preserved
        assert record["Status"] == ""


def list_headers():
    from src.services.conversational_agent_service import _ORDERS_SHEET_HEADERS

    return list(_ORDERS_SHEET_HEADERS)


@pytest.mark.asyncio
async def test_reported_paid_button_asks_for_code():
    from src.services.conversation_context_manager import ConversationSession, context_manager
    from src.services.conversational_agent_service import ConversationalAgentService

    agent = ConversationalAgentService()
    user = MagicMock()
    user.id = "user-uuid-1"
    db = AsyncMock()
    session_key = f"ccm:whatsapp:{user.id}:254711371265"
    msg = f"{REPORTED_PAID_AGENT_PREFIX}ORD-8"

    session = ConversationSession(
        session_key=session_key,
        platform="whatsapp",
        owner_user_id=str(user.id),
        sender_id="254711371265",
        messages=[],
        metadata={},
    )

    updates = []

    async def fake_get_session_by_key(key):
        return session

    async def fake_update_metadata(key, u):
        updates.append(u)
        session.metadata.update({k: v for k, v in u.items() if v is not None})

    with patch.object(context_manager, "get_session_by_key", fake_get_session_by_key), \
         patch.object(context_manager, "update_session_metadata", fake_update_metadata), \
         patch.object(context_manager, "maybe_expire_human_handoff", AsyncMock()), \
         patch.object(agent, "_cart_fast_path_result", new_callable=AsyncMock) as fast_path:

        fast_path.return_value = {"response_text": "send code"}

        await agent.execute(
            user_message=msg,
            session_key=session_key,
            business_config={"business_name": "Test Cafe", "customer_phone": "254711371265"},
            user=user,
            db=db,
        )

        assert any(u.get("awaiting_mpesa_code") == "ORD-8" for u in updates)
        fast_path.assert_called_once()


# ── Event-driven paid confirmation webhook ──────────────────────────────────

def _fake_request(body: bytes):
    req = SimpleNamespace()
    req.body = AsyncMock(return_value=body)
    return req


class _FakeSessionMaker:
    """Mimics get_session_maker() -> maker, then `async with maker() as db`."""

    def __init__(self, db):
        self._db = db

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_manual_payment_confirmed_queues_on_paid():
    import importlib
    mod = importlib.import_module("src.routers.mpesa_agent_router")

    with patch.object(mod.asyncio, "create_task") as create_task, \
         patch.object(mod, "_handle_manual_payment_confirmed_background") as bg:
        bg.return_value = MagicMock()  # avoid creating a real coroutine
        req = _fake_request(b'{"order_id":"ORD-1","status":"paid","mpesa_code":"QGR7X"}')

        res = await mod.manual_payment_confirmed("secret-abc", req)

        assert res["success"] is True
        assert res["queued"] is True
        create_task.assert_called_once()


@pytest.mark.asyncio
async def test_manual_payment_confirmed_skips_non_paid():
    import importlib
    mod = importlib.import_module("src.routers.mpesa_agent_router")

    with patch.object(mod.asyncio, "create_task") as create_task, \
         patch.object(mod, "_handle_manual_payment_confirmed_background") as bg:
        bg.return_value = MagicMock()
        req = _fake_request(b'{"order_id":"ORD-1","status":"pending"}')

        res = await mod.manual_payment_confirmed("secret-abc", req)

        assert res["skipped"] is True
        create_task.assert_not_called()


@pytest.mark.asyncio
async def test_manual_payment_confirmed_requires_order_id():
    import importlib

    from fastapi import HTTPException

    mod = importlib.import_module("src.routers.mpesa_agent_router")

    req = _fake_request(b'{"status":"paid"}')
    with pytest.raises(HTTPException) as exc:
        await mod.manual_payment_confirmed("secret-abc", req)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_manual_payment_confirmed_bg_sends_receipt():
    import importlib
    mod = importlib.import_module("src.routers.mpesa_agent_router")

    db = AsyncMock()
    cfg = SimpleNamespace(user_id="user-1", webhook_secret="secret-abc")
    user = SimpleNamespace(id="user-1")
    res_cfg = MagicMock(); res_cfg.scalar_one_or_none.return_value = cfg
    res_user = MagicMock(); res_user.scalar_one_or_none.return_value = user
    db.execute = AsyncMock(side_effect=[res_cfg, res_user])

    ots = MagicMock()
    ots.notify_payment_received = AsyncMock(return_value={"success": True})

    with patch("src.database.get_session_maker", return_value=_FakeSessionMaker(db)), \
         patch("src.services.order_tracking_service.order_tracking_service", ots), \
         patch.object(mod, "_record_manual_payment_in_storage", new_callable=AsyncMock) as writeback:
        await mod._handle_manual_payment_confirmed_background(
            webhook_secret="secret-abc",
            order_id="ORD-1",
            mpesa_code="QGR7XA12B9",
            amount=1500,
            customer_phone="254712345678",
        )

    ots.notify_payment_received.assert_awaited_once()
    kwargs = ots.notify_payment_received.call_args.kwargs
    assert kwargs["order_id"] == "ORD-1"
    assert kwargs["mpesa_receipt"] == "QGR7XA12B9"
    assert kwargs["amount_paid"] == 1500.0
    assert kwargs["customer_phone"] == "254712345678"
    # Fresh send -> storage write-back runs
    writeback.assert_awaited_once()


@pytest.mark.asyncio
async def test_manual_payment_confirmed_bg_skips_writeback_when_already_notified():
    import importlib
    mod = importlib.import_module("src.routers.mpesa_agent_router")

    db = AsyncMock()
    cfg = SimpleNamespace(user_id="user-1", webhook_secret="secret-abc")
    user = SimpleNamespace(id="user-1")
    res_cfg = MagicMock(); res_cfg.scalar_one_or_none.return_value = cfg
    res_user = MagicMock(); res_user.scalar_one_or_none.return_value = user
    db.execute = AsyncMock(side_effect=[res_cfg, res_user])

    ots = MagicMock()
    ots.notify_payment_received = AsyncMock(
        return_value={"success": True, "skipped": True, "reason": "already_notified"}
    )

    with patch("src.database.get_session_maker", return_value=_FakeSessionMaker(db)), \
         patch("src.services.order_tracking_service.order_tracking_service", ots), \
         patch.object(mod, "_record_manual_payment_in_storage", new_callable=AsyncMock) as writeback:
        await mod._handle_manual_payment_confirmed_background(
            webhook_secret="secret-abc",
            order_id="ORD-1",
            mpesa_code="QGR7XA12B9",
            amount=1500,
        )

    # Idempotent skip -> no duplicate Transactions row / Receipt Sent write
    writeback.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_manual_payment_in_storage_writes_tx_and_receipt():
    import importlib
    mod = importlib.import_module("src.routers.mpesa_agent_router")

    db = AsyncMock()
    user = SimpleNamespace(id="user-1")

    ots = MagicMock()
    ots.get_registered_order.return_value = {
        "storage_config": {"provider": "google_sheets", "spreadsheet_id": "sheet-1"},
        "currency": "KES",
        "whatsapp_sender": "254712345678",
    }

    conv = MagicMock()
    conv.persist_payment_transaction_to_storage = AsyncMock()
    conv.mark_receipt_sent_in_storage = AsyncMock()

    with patch("src.services.order_tracking_service.order_tracking_service", ots), \
         patch("src.services.conversational_agent_service.ConversationalAgentService", return_value=conv):
        await mod._record_manual_payment_in_storage(
            db=db,
            user=user,
            owner_user_id="user-1",
            order_id="ORD-1",
            mpesa_code="QGR7XA12B9",
            amount_paid=1500.0,
            customer_phone="254712345678",
        )

    conv.persist_payment_transaction_to_storage.assert_awaited_once()
    tx = conv.persist_payment_transaction_to_storage.call_args.kwargs
    assert tx["transaction_data"]["source"] == "manual_mpesa"
    assert tx["transaction_data"]["transaction_id"] == "QGR7XA12B9"
    assert tx["transaction_data"]["amount"] == 1500.0
    assert tx["order_data"] is None  # do not re-touch merchant's Orders Status
    conv.mark_receipt_sent_in_storage.assert_awaited_once()
    assert conv.mark_receipt_sent_in_storage.call_args.kwargs["order_id"] == "ORD-1"


@pytest.mark.asyncio
async def test_record_manual_payment_in_storage_noop_without_storage():
    import importlib
    mod = importlib.import_module("src.routers.mpesa_agent_router")

    db = AsyncMock()
    user = SimpleNamespace(id="user-1")

    ots = MagicMock()
    ots.get_registered_order.return_value = {}  # registry expired / no storage

    conv = MagicMock()
    conv.persist_payment_transaction_to_storage = AsyncMock()
    conv.mark_receipt_sent_in_storage = AsyncMock()

    with patch("src.services.order_tracking_service.order_tracking_service", ots), \
         patch("src.services.conversational_agent_service.ConversationalAgentService", return_value=conv):
        await mod._record_manual_payment_in_storage(
            db=db,
            user=user,
            owner_user_id="user-1",
            order_id="ORD-1",
            mpesa_code="QGR7XA12B9",
            amount_paid=1500.0,
            customer_phone="254712345678",
        )

    conv.persist_payment_transaction_to_storage.assert_not_awaited()
    conv.mark_receipt_sent_in_storage.assert_not_awaited()


# ── Receipt Sent write-back helpers ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_receipt_sent_in_storage_google_dispatch():
    from src.services.conversational_agent_service import ConversationalAgentService

    agent = ConversationalAgentService()
    user = MagicMock(); user.id = "user-1"
    db = AsyncMock()

    with patch.object(agent, "_update_order_fields_in_google_sheets", new_callable=AsyncMock) as upd, \
         patch("src.services.tool_executor.ToolExecutor"):
        await agent.mark_receipt_sent_in_storage(
            order_id="ORD-1",
            storage_config={"provider": "google_sheets", "spreadsheet_id": "sheet-1"},
            user=user,
            db=db,
        )

    upd.assert_awaited_once()
    fields = upd.call_args.kwargs["fields"]
    assert fields["Receipt Sent"] == "yes"
    assert fields["Receipt Sent At"]  # timestamp present


@pytest.mark.asyncio
async def test_mark_receipt_sent_in_storage_noop_when_no_provider():
    from src.services.conversational_agent_service import ConversationalAgentService

    agent = ConversationalAgentService()
    user = MagicMock(); user.id = "user-1"
    db = AsyncMock()

    with patch.object(agent, "_update_order_fields_in_google_sheets", new_callable=AsyncMock) as upd, \
         patch.object(agent, "_update_order_fields_in_airtable", new_callable=AsyncMock) as upd_air:
        await agent.mark_receipt_sent_in_storage(
            order_id="ORD-1",
            storage_config={"provider": "none"},
            user=user,
            db=db,
        )

    upd.assert_not_awaited()
    upd_air.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_order_fields_in_google_sheets_updates_matching_row():
    from src.services.conversational_agent_service import ConversationalAgentService

    agent = ConversationalAgentService()
    user = MagicMock(); user.id = "user-1"
    db = AsyncMock()

    headers = list_headers()
    order_idx = headers.index("Order ID")
    receipt_idx = headers.index("Receipt Sent")

    existing_row = [""] * len(headers)
    existing_row[order_idx] = "ORD-1"

    written = {}

    async def fake_execute(tool_name, args, u, d):
        if args.get("operation") == "read_range":
            return {"success": True, "values": [headers, existing_row]}
        if args.get("operation") == "write_range":
            written["range"] = args.get("range_name")
            written["values"] = args.get("values")
            return {"success": True}
        return {"success": True}

    executor = MagicMock()
    executor.execute_tool = AsyncMock(side_effect=fake_execute)

    with patch.object(
        agent, "_ensure_sheet_headers_with_fallback", new_callable=AsyncMock
    ) as ensure:
        ensure.return_value = {"sheet_name": "Orders", "headers": headers}
        await agent._update_order_fields_in_google_sheets(
            executor=executor,
            order_id="ORD-1",
            fields={"Receipt Sent": "yes", "Receipt Sent At": "2026-07-09T12:00:00"},
            storage_config={"provider": "google_sheets", "spreadsheet_id": "sheet-1"},
            user=user,
            db=db,
        )

    assert written, "write_range should have been called"
    assert written["values"][0][receipt_idx] == "yes"
    # Existing Order ID preserved in the rewritten row
    assert written["values"][0][order_idx] == "ORD-1"


@pytest.mark.asyncio
async def test_update_order_fields_in_google_sheets_noop_when_row_missing():
    from src.services.conversational_agent_service import ConversationalAgentService

    agent = ConversationalAgentService()
    user = MagicMock(); user.id = "user-1"
    db = AsyncMock()

    headers = list_headers()

    calls = []

    async def fake_execute(tool_name, args, u, d):
        calls.append(args.get("operation"))
        if args.get("operation") == "read_range":
            return {"success": True, "values": [headers]}  # header only, no data rows
        return {"success": True}

    executor = MagicMock()
    executor.execute_tool = AsyncMock(side_effect=fake_execute)

    with patch.object(
        agent, "_ensure_sheet_headers_with_fallback", new_callable=AsyncMock
    ) as ensure:
        ensure.return_value = {"sheet_name": "Orders", "headers": headers}
        await agent._update_order_fields_in_google_sheets(
            executor=executor,
            order_id="ORD-DOES-NOT-EXIST",
            fields={"Receipt Sent": "yes"},
            storage_config={"provider": "google_sheets", "spreadsheet_id": "sheet-1"},
            user=user,
            db=db,
        )

    # No write attempted for a missing order row
    assert "write_range" not in calls


@pytest.mark.asyncio
async def test_manual_payment_confirmed_bg_ignores_bad_secret():
    import importlib
    mod = importlib.import_module("src.routers.mpesa_agent_router")

    db = AsyncMock()
    res_cfg = MagicMock(); res_cfg.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=res_cfg)

    ots = MagicMock()
    ots.notify_payment_received = AsyncMock()

    with patch("src.database.get_session_maker", return_value=_FakeSessionMaker(db)), \
         patch("src.services.order_tracking_service.order_tracking_service", ots):
        await mod._handle_manual_payment_confirmed_background(
            webhook_secret="wrong-secret",
            order_id="ORD-1",
        )

    ots.notify_payment_received.assert_not_awaited()
