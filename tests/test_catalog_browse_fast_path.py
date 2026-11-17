"""Deterministic browse catalog fast-path (no LLM handoff)."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.models import User
from src.services.conversation_context_manager import (
    ConversationSession,
    context_manager,
)


def _user(email: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        name="Merchant",
        password_hash="hash",
    )


@pytest.mark.asyncio
async def test_browse_catalog_fast_path_sends_cards(db_session, monkeypatch):
    from src.services.catalog_service import CatalogService
    from src.services.conversational_agent_service import ConversationalAgentService

    user = _user("browse-fast@test.com")
    db_session.add(user)
    await db_session.commit()

    await CatalogService().create_product(
        db_session,
        user.id,
        {"name": "Nike Air Max", "Price": "8500", "Category": "Footwear", "SKU": "NIKE-1"},
    )

    agent = ConversationalAgentService()
    agent._sub_display_product_cards = AsyncMock(
        return_value={"success": True, "cards": [{"id": "NIKE-1"}], "cards_sent": 1}
    )
    agent._save_to_ccm = AsyncMock()

    result = await agent._browse_catalog_fast_path(
        session_key=f"ccm:whatsapp:{user.id}:254700000000",
        user_message="I'd like to browse your catalog/products. Please show me what you have.",
        catalog_word="catalog",
        currency="KES",
        business_name="Arrotech Shop",
        order_type="ecommerce",
        user=user,
        db=db_session,
    )

    assert result["human_handoff"] is False
    assert "Here's what we have" in result["response_text"]
    assert result["cards"]
    agent._sub_display_product_cards.assert_awaited_once()


@pytest.mark.asyncio
async def test_browse_catalog_fast_path_empty_catalog_is_honest(db_session):
    from src.services.conversational_agent_service import ConversationalAgentService

    user = _user("browse-empty@test.com")
    db_session.add(user)
    await db_session.commit()

    agent = ConversationalAgentService()
    agent._save_to_ccm = AsyncMock()

    result = await agent._browse_catalog_fast_path(
        session_key=f"ccm:whatsapp:{user.id}:254700000001",
        user_message="browse catalog",
        catalog_word="catalog",
        currency="KES",
        business_name="Arrotech Shop",
        order_type="ecommerce",
        user=user,
        db=db_session,
    )

    assert result["human_handoff"] is False
    assert "empty" in result["response_text"].lower()
    assert result["cards"] == []


@pytest.mark.asyncio
async def test_browse_fast_path_cards_skip_unsellable(db_session):
    """Browse cards include in-stock qty and omit qty 0 and out-of-stock."""
    from src.services.catalog_service import CatalogService
    from src.services.conversational_agent_service import ConversationalAgentService

    user = _user("browse-sellable@test.com")
    db_session.add(user)
    await db_session.commit()
    svc = CatalogService()
    await svc.create_product(
        db_session,
        user.id,
        {
            "name": "Nike Air Max",
            "Price": "8500",
            "Category": "Footwear",
            "SKU": "SELL-1",
            "Availability": "in_stock",
            "quantity": "3",
        },
    )
    await svc.create_product(
        db_session,
        user.id,
        {
            "name": "Zero Stock Samba",
            "Price": "7200",
            "Category": "Footwear",
            "SKU": "ZERO-1",
            "Availability": "in_stock",
            "quantity": "0",
        },
    )
    await svc.create_product(
        db_session,
        user.id,
        {
            "name": "Sold Out Puma",
            "Price": "6000",
            "Category": "Footwear",
            "SKU": "OOS-1",
            "Availability": "out_of_stock",
            "quantity": "4",
        },
    )

    agent = ConversationalAgentService()
    agent._save_to_ccm = AsyncMock()

    async def _display(*, products, **_kwargs):
        return {
            "success": True,
            "cards": [{"id": product["id"]} for product in products],
            "cards_sent": len(products),
        }

    agent._sub_display_product_cards = _display

    result = await agent._browse_catalog_fast_path(
        session_key=f"ccm:whatsapp:{user.id}:254700000002",
        user_message="I'd like to browse your catalog/products. Please show me what you have.",
        catalog_word="catalog",
        currency="KES",
        business_name="Arrotech Shop",
        order_type="ecommerce",
        user=user,
        db=db_session,
    )

    assert [card["id"] for card in result["cards"]] == ["SELL-1"]
    assert "empty" not in result["response_text"].lower()


@pytest.mark.asyncio
async def test_browse_fast_path_unsellable_only_is_empty(db_session):
    """A successful browse of only unsellable rows says the catalog is empty."""
    from src.services.catalog_service import CatalogService
    from src.services.conversational_agent_service import ConversationalAgentService

    user = _user("browse-unsellable-only@test.com")
    db_session.add(user)
    await db_session.commit()
    await CatalogService().create_product(
        db_session,
        user.id,
        {
            "name": "Sold Out Puma",
            "Price": "6000",
            "Category": "Footwear",
            "SKU": "OOS-1",
            "Availability": "out_of_stock",
            "quantity": "4",
        },
    )

    agent = ConversationalAgentService()
    agent._save_to_ccm = AsyncMock()
    agent._sub_display_product_cards = AsyncMock(
        return_value={"success": True, "cards": [{"id": "OOS-1"}], "cards_sent": 1}
    )

    result = await agent._browse_catalog_fast_path(
        session_key=f"ccm:whatsapp:{user.id}:254700000003",
        user_message="browse catalog",
        catalog_word="catalog",
        currency="KES",
        business_name="Arrotech Shop",
        order_type="ecommerce",
        user=user,
        db=db_session,
    )

    assert "empty" in result["response_text"].lower()
    assert result["cards"] == []
    agent._sub_display_product_cards.assert_not_called()


@pytest.mark.asyncio
async def test_browse_fast_path_search_error_is_not_empty_catalog(db_session):
    """A failed browse search must not claim the catalog is empty."""
    from src.services.conversational_agent_service import ConversationalAgentService

    user = _user("browse-error@test.com")
    agent = ConversationalAgentService()
    agent._save_to_ccm = AsyncMock()
    agent._search_arrotech_catalog_products = AsyncMock(
        return_value={"success": False, "result": "Search error: db down"}
    )

    result = await agent._browse_catalog_fast_path(
        session_key=f"ccm:whatsapp:{user.id}:254700000004",
        user_message="browse catalog",
        catalog_word="catalog",
        currency="KES",
        business_name="Arrotech Shop",
        order_type="ecommerce",
        user=user,
        db=db_session,
    )

    text = result["response_text"].lower()
    assert "empty" not in text
    assert "nothing is listed" not in text
    assert "try again" in text
    assert result["cards"] == []
    assert result["human_handoff"] is False
    assert result["actions_taken"] == [
        {"tool": "search_products", "result_summary": "browse_error"}
    ]


@pytest.mark.asyncio
async def test_browse_fast_path_search_exception_is_not_empty_catalog(db_session):
    """An exception from browse search uses the error reply, not the empty reply."""
    from src.services.conversational_agent_service import ConversationalAgentService

    user = _user("browse-raise@test.com")
    agent = ConversationalAgentService()
    agent._save_to_ccm = AsyncMock()
    agent._search_arrotech_catalog_products = AsyncMock(
        side_effect=RuntimeError("catalog db unavailable")
    )

    result = await agent._browse_catalog_fast_path(
        session_key=f"ccm:whatsapp:{user.id}:254700000005",
        user_message="browse catalog",
        catalog_word="catalog",
        currency="KES",
        business_name="Arrotech Shop",
        order_type="ecommerce",
        user=user,
        db=db_session,
    )

    text = result["response_text"].lower()
    assert "empty" not in text
    assert "try again" in text
    assert result["cards"] == []
    assert result["actions_taken"][0]["result_summary"] == "browse_error"


@pytest.mark.asyncio
async def test_search_arrotech_catalog_no_match_forbids_escalation(db_session, monkeypatch):
    from src.services.catalog_service import CatalogService
    from src.services.conversational_agent_service import ConversationalAgentService

    user = _user("nomatch@test.com")
    db_session.add(user)
    await db_session.commit()

    await CatalogService().create_product(
        db_session,
        user.id,
        {"name": "Coca-Cola 500ml", "Price": "80", "Category": "Drinks"},
    )

    agent = ConversationalAgentService()
    result = await agent._search_arrotech_catalog_products(
        "xyzzy-no-match-product", user, db_session
    )

    assert result["success"] is True
    assert result["data"]["empty"] is True
    assert "CATALOG_NO_MATCH" in result["result"]
    assert "escalate_to_human" in result["result"]


def _session(session_key: str, owner: str, phone: str) -> ConversationSession:
    return ConversationSession(
        session_key=session_key,
        platform="whatsapp",
        owner_user_id=owner,
        sender_id=phone,
        messages=[],
        metadata={"preferred_language": "en"},
    )


@pytest.mark.asyncio
async def test_execute_browse_all_sends_cards_before_llm(db_session):
    """Browse-all returns product cards from execute without calling the LLM."""
    from src.services.catalog_service import CatalogService
    from src.services.conversational_agent_service import ConversationalAgentService

    user = _user("browse-execute@test.com")
    db_session.add(user)
    await db_session.commit()

    await CatalogService().create_product(
        db_session,
        user.id,
        {"name": "Nike Air Max", "Price": "8500", "Category": "Footwear", "SKU": "NIKE-1"},
    )

    phone = "254700000099"
    session_key = f"ccm:whatsapp:{user.id}:{phone}"
    session = _session(session_key, str(user.id), phone)

    async def fake_get(key):
        return session if key == session.session_key else None

    async def fake_update(key, updates):
        if key == session.session_key:
            session.metadata.update(updates)

    async def fake_save(_sess):
        return None

    agent = ConversationalAgentService()
    agent._save_to_ccm = AsyncMock()
    agent._sub_display_product_cards = AsyncMock(
        return_value={"success": True, "cards": [{"id": "NIKE-1"}], "cards_sent": 1}
    )

    class _LlmTurn:
        error = None
        content = "LLM should not answer a browse-all catalog request."
        tools_called = []

    with (
        patch.object(context_manager, "get_session_by_key", fake_get),
        patch.object(context_manager, "update_session_metadata", fake_update),
        patch.object(context_manager, "save_session", fake_save),
        patch.object(agent, "_detect_language_llm", new=AsyncMock(return_value=None)),
        patch.object(agent, "_maybe_send_welcome_quick_replies", new=AsyncMock()),
        patch.object(agent.llm_service, "chat_completion", new=AsyncMock(return_value=_LlmTurn())) as chat,
    ):
        result = await agent.execute(
            user_message=(
                "I'd like to browse your catalog/products. Please show me what you have."
            ),
            session_key=session_key,
            business_config={
                "order_type": "ecommerce",
                "business_name": "Arrotech Shop",
                "currency": "KES",
                "commerce_rails_enabled": False,
            },
            user=user,
            db=db_session,
        )

    assert result["human_handoff"] is False
    assert "Here's what we have" in result["response_text"]
    assert result["cards"]
    chat.assert_not_called()


@pytest.mark.asyncio
async def test_catalog_search_hit_displays_cards_when_model_omits_display(db_session):
    """A catalog hit is shown as cards even when the model never calls display.

    Fails if search_products returning Jordan sneakers (READY_TO_DISPLAY_PRODUCTS)
    does not invoke the card path with id JORDAN-1 before the text-only reply.
    """
    from src.services.catalog_service import CatalogService
    from src.services.conversational_agent_service import ConversationalAgentService

    user = _user("search-force-display@test.com")
    db_session.add(user)
    await db_session.commit()

    await CatalogService().create_product(
        db_session,
        user.id,
        {
            "name": "Jordan sneakers",
            "Price": "9000",
            "Category": "Street",
            "SKU": "JORDAN-1",
            "Availability": "in_stock",
        },
    )

    phone = "254700000088"
    session_key = f"ccm:whatsapp:{user.id}:{phone}"
    session = _session(session_key, str(user.id), phone)

    async def fake_get(key):
        return session if key == session.session_key else None

    async def fake_update(key, updates):
        if key == session.session_key:
            session.metadata.update(updates)

    async def fake_save(_sess):
        return None

    agent = ConversationalAgentService()
    agent._save_to_ccm = AsyncMock()

    class _SearchTurn:
        error = None
        content = ""
        tools_called = [
            {"name": "search_products", "arguments": {"query": "Jordan sneakers"}}
        ]

    class _OmitTurn:
        error = None
        content = "Let me know if you need anything else."
        tools_called = []

    search_turn = _SearchTurn()
    omit_turn = _OmitTurn()

    with (
        patch.object(context_manager, "get_session_by_key", fake_get),
        patch.object(context_manager, "update_session_metadata", fake_update),
        patch.object(context_manager, "save_session", fake_save),
        patch.object(agent, "_detect_language_llm", new=AsyncMock(return_value=None)),
        patch.object(agent, "_maybe_send_welcome_quick_replies", new=AsyncMock()),
        patch.object(
            agent.llm_service, "chat_completion", new=AsyncMock(side_effect=[search_turn, omit_turn])
        ) as chat,
    ):
        result = await agent.execute(
            user_message="Do you have Jordan sneakers?",
            session_key=session_key,
            business_config={
                "order_type": "ecommerce",
                "business_name": "Arrotech Shop",
                "currency": "KES",
                "commerce_rails_enabled": False,
                "kb_id": "",
            },
            user=user,
            db=db_session,
        )

    assert chat.await_count == 2
    assert search_turn.tools_called[0]["name"] == "search_products"
    assert omit_turn.tools_called == []
    assert [card.get("id") for card in result["cards"]] == ["JORDAN-1"]
    assert result["human_handoff"] is False
