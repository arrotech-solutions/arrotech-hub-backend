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
