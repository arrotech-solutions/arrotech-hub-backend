"""Regression tests for checkout confirmation gates."""

import pytest

from src.services.whatsapp_ordering_helpers import is_order_confirmation_message


def test_confirmation_words_strict():
    assert is_order_confirmation_message("yes")
    assert is_order_confirmation_message("Ndio")
    assert is_order_confirmation_message("CONFIRM")
    assert not is_order_confirmation_message("ok")
    assert not is_order_confirmation_message("sure")
    assert not is_order_confirmation_message("okay")
    assert not is_order_confirmation_message("I want chicken")


@pytest.mark.asyncio
async def test_mark_order_confirmed_requires_pending(monkeypatch):
    from src.services.conversation_context_manager import (
        ConversationSession,
        context_manager,
    )

    saved = {}

    async def fake_get_session_by_key(session_key):
        return ConversationSession(
            session_key=session_key,
            platform="whatsapp",
            owner_user_id="u1",
            sender_id="254700",
            messages=[],
            metadata=saved,
        )

    async def fake_save_session(session):
        saved.update(session.metadata)

    monkeypatch.setattr(
        context_manager, "get_session_by_key", fake_get_session_by_key
    )
    monkeypatch.setattr(context_manager, "save_session", fake_save_session)

    await context_manager.mark_order_confirmed("ccm:whatsapp:u1:254700")
    assert "order_confirmed" not in saved

    saved["pending_confirmation"] = {"items": [], "at": 1.0}
    await context_manager.mark_order_confirmed("ccm:whatsapp:u1:254700")
    assert saved.get("order_confirmed") is True
