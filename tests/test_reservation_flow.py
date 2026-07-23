"""Tests for the create_reservation sub-tool confirmation gate and record shape."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.conversational_agent_service import ConversationalAgentService
from src.services.conversation_context_manager import ConversationSession, context_manager


def _make_session(session_key, metadata=None):
    return ConversationSession(
        session_key=session_key,
        platform="whatsapp",
        owner_user_id="user-uuid-1",
        sender_id="254700000000",
        messages=[],
        metadata=metadata or {},
    )


@pytest.mark.asyncio
async def test_reservation_requires_confirmation_first():
    agent = ConversationalAgentService()
    session_key = "ccm:whatsapp:user-uuid-1:254700000000"
    session = _make_session(session_key)

    async def fake_get_session_by_key(key):
        return session

    async def fake_update_metadata(key, updates):
        session.metadata.update(updates)

    with patch.object(context_manager, "get_session_by_key", fake_get_session_by_key), \
         patch.object(context_manager, "update_session_metadata", fake_update_metadata):
        result = await agent._sub_create_reservation(
            arguments={
                "customer_name": "Asha",
                "customer_phone": "254700000000",
                "reservation_date": "2026-07-25",
                "reservation_time": "19:30",
                "party_size": 4,
            },
            business_name="Mama's Kitchen",
            storage_config={"provider": "none"},
            user=MagicMock(),
            db=AsyncMock(),
            session_key=session_key,
            user_message="I'd like to book a table",
        )

    assert result["success"] is False
    assert result["error"] == "RESERVATION_NOT_CONFIRMED"
    # pending reservation stored for the confirmation turn
    assert session.metadata.get("pending_reservation", {}).get("customer_name") == "Asha"
    assert session.metadata.get("awaiting_reservation_confirmation") is True


@pytest.mark.asyncio
async def test_reservation_incomplete_asks_for_missing():
    agent = ConversationalAgentService()
    session_key = "ccm:whatsapp:user-uuid-1:254700000000"
    session = _make_session(session_key)

    async def fake_get_session_by_key(key):
        return session

    async def fake_update_metadata(key, updates):
        session.metadata.update(updates)

    with patch.object(context_manager, "get_session_by_key", fake_get_session_by_key), \
         patch.object(context_manager, "update_session_metadata", fake_update_metadata):
        result = await agent._sub_create_reservation(
            arguments={"customer_name": "Asha", "customer_phone": "254700000000"},
            business_name="Mama's Kitchen",
            storage_config={"provider": "none"},
            user=MagicMock(),
            db=AsyncMock(),
            session_key=session_key,
            user_message="book a table",
        )

    assert result["success"] is False
    assert result["error"] == "RESERVATION_INCOMPLETE"


@pytest.mark.asyncio
async def test_reservation_created_on_yes_with_pending():
    agent = ConversationalAgentService()
    session_key = "ccm:whatsapp:user-uuid-1:254700000000"
    session = _make_session(
        session_key,
        metadata={
            "pending_reservation": {
                "customer_name": "Asha",
                "customer_phone": "254700000000",
                "reservation_date": "2026-07-25",
                "reservation_time": "19:30",
                "party_size": 4,
            },
            "awaiting_reservation_confirmation": True,
        },
    )

    async def fake_get_session_by_key(key):
        return session

    async def fake_update_metadata(key, updates):
        session.metadata.update(updates)

    with patch.object(context_manager, "get_session_by_key", fake_get_session_by_key), \
         patch.object(context_manager, "update_session_metadata", fake_update_metadata), \
         patch.object(agent, "_persist_reservation_to_storage", new_callable=AsyncMock) as persist:
        result = await agent._sub_create_reservation(
            arguments={},
            business_name="Mama's Kitchen",
            storage_config={"provider": "google_sheets", "spreadsheet_id": "sheet123"},
            user=MagicMock(),
            db=AsyncMock(),
            session_key=session_key,
            user_message="yes",
        )

    assert result["success"] is True
    assert result["reservation_id"].startswith("RES-")
    assert "confirm" in result["reservation_notification"].lower()
    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_deterministic_flow_walks_and_creates_without_hallucination():
    """Full booking wizard: intent → date → time → party → summary → YES.

    The summary and created booking must contain the EXACT values the customer
    typed, never anything the model could have invented.
    """
    agent = ConversationalAgentService()
    session_key = "ccm:whatsapp:user-uuid-1:254711371265"
    session = _make_session(session_key)

    async def fake_get_session_by_key(key):
        return session

    async def fake_update_metadata(key, updates):
        session.metadata.update(updates)

    async def run(msg):
        return await agent._handle_reservation_flow(
            session_key=session_key,
            user_message=msg,
            order_type="food",
            reservations_enabled=True,
            business_name="Tians Grill",
            customer_name="",
            customer_phone="254711371265",
            storage_config={"provider": "none"},
            preferred_language="en",
            user=MagicMock(),
            db=AsyncMock(),
        )

    with patch.object(context_manager, "get_session_by_key", fake_get_session_by_key), \
         patch.object(context_manager, "update_session_metadata", fake_update_metadata), \
         patch.object(context_manager, "is_human_handoff", MagicMock(return_value=False)), \
         patch.object(agent, "_save_to_ccm", new_callable=AsyncMock), \
         patch.object(agent, "_persist_reservation_to_storage", new_callable=AsyncMock):
        r1 = await run("I wanna book a reservation for two")
        assert "date" in r1["response_text"].lower()

        r2 = await run("24th July 2026")
        assert "time" in r2["response_text"].lower()

        # Party size was captured from the very first message ("for two"),
        # so after time the wizard should jump straight to the name.
        r3 = await run("10 p.m")
        assert "name" in r3["response_text"].lower()

        r4 = await run("Harun Gitundu")
        # Summary uses the customer's exact words, not invented values.
        assert "24th July 2026" in r4["response_text"]
        assert "10 p.m" in r4["response_text"]
        assert "Harun Gitundu" in r4["response_text"]
        assert "Party size: 2" in r4["response_text"]
        assert session.metadata.get("awaiting_reservation_confirmation") is True

        r5 = await run("YES")
        assert r5["order_created"] is True
        assert r5["order_notification"]
        assert "Harun Gitundu" in r5["order_notification"]
        assert session.metadata.get("awaiting_reservation_confirmation") is False


@pytest.mark.asyncio
async def test_deterministic_flow_ignored_for_non_food_business():
    agent = ConversationalAgentService()
    result = await agent._handle_reservation_flow(
        session_key="ccm:whatsapp:user-uuid-1:254700000000",
        user_message="I want to book a reservation",
        order_type="retail",
        reservations_enabled=True,
        business_name="Shop",
        customer_name="",
        customer_phone="254700000000",
        storage_config={"provider": "none"},
        preferred_language="en",
        user=MagicMock(),
        db=AsyncMock(),
    )
    assert result is None


@pytest.mark.asyncio
async def test_deterministic_flow_passes_through_without_intent():
    agent = ConversationalAgentService()
    session_key = "ccm:whatsapp:user-uuid-1:254700000000"
    session = _make_session(session_key)

    async def fake_get_session_by_key(key):
        return session

    with patch.object(context_manager, "get_session_by_key", fake_get_session_by_key), \
         patch.object(context_manager, "is_human_handoff", MagicMock(return_value=False)):
        result = await agent._handle_reservation_flow(
            session_key=session_key,
            user_message="Do you have chicken wings?",
            order_type="food",
            reservations_enabled=True,
            business_name="Tians Grill",
            customer_name="",
            customer_phone="254700000000",
            storage_config={"provider": "none"},
            preferred_language="en",
            user=MagicMock(),
            db=AsyncMock(),
        )
    assert result is None


@pytest.mark.asyncio
async def test_deterministic_flow_cancel_clears_state():
    agent = ConversationalAgentService()
    session_key = "ccm:whatsapp:user-uuid-1:254700000000"
    session = _make_session(
        session_key,
        metadata={"awaiting_reservation_confirmation": True, "pending_reservation": {"customer_name": "Asha"}},
    )

    async def fake_get_session_by_key(key):
        return session

    async def fake_update_metadata(key, updates):
        session.metadata.update(updates)

    with patch.object(context_manager, "get_session_by_key", fake_get_session_by_key), \
         patch.object(context_manager, "update_session_metadata", fake_update_metadata), \
         patch.object(context_manager, "is_human_handoff", MagicMock(return_value=False)), \
         patch.object(agent, "_save_to_ccm", new_callable=AsyncMock):
        result = await agent._handle_reservation_flow(
            session_key=session_key,
            user_message="cancel",
            order_type="food",
            reservations_enabled=True,
            business_name="Tians Grill",
            customer_name="",
            customer_phone="254700000000",
            storage_config={"provider": "none"},
            preferred_language="en",
            user=MagicMock(),
            db=AsyncMock(),
        )
    assert result is not None
    assert result["order_created"] is False
    assert session.metadata.get("awaiting_reservation_confirmation") is False
    assert session.metadata.get("pending_reservation") is None


def test_format_delivery_choices_lists_tenant_methods():
    choices = ConversationalAgentService._format_delivery_choices(
        ["delivery", "pickup", "dine_in"], "en"
    )
    assert "*delivery*" in choices
    assert "*pickup*" in choices
    assert "*dine-in*" in choices
    assert " or " in choices

    sw = ConversationalAgentService._format_delivery_choices(
        ["delivery", "dine_in"], "sw"
    )
    assert " au " in sw


def test_build_reservation_sheet_record_shape():
    reservation = {
        "reservation_id": "RES-20260725-ABC123",
        "status": "requested",
        "customer": {"name": "Asha", "phone": "254700000000"},
        "reservation_date": "2026-07-25",
        "reservation_time": "19:30",
        "party_size": 4,
        "notes": "Window seat",
        "created_at": "2026-07-22T10:00:00",
    }
    record = ConversationalAgentService._build_reservation_sheet_record(reservation)
    assert record["Reservation ID"] == "RES-20260725-ABC123"
    assert record["Status"] == "requested"
    assert record["Customer Name"] == "Asha"
    assert record["Customer Phone"] == "'254700000000"
    assert record["Date"] == "2026-07-25"
    assert record["Time"] == "19:30"
    assert record["Party Size"] == "4"
    assert record["Notes"] == "Window seat"
