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
