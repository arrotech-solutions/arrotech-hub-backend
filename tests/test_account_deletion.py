"""Tests for GDPR account erasure (DELETE /auth/me)."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Conversation, Message, User, UserSettings
from src.services.account_deletion_service import erase_user_account


@pytest.mark.asyncio
async def test_erase_user_account_with_conversation_children(
    db_session: AsyncSession,
    test_user: User,
):
    """Bulk delete used to fail when Message rows still referenced Conversation."""
    conv = Conversation(user_id=test_user.id, title="To erase")
    db_session.add(conv)
    await db_session.flush()

    db_session.add(
        Message(
            conversation_id=conv.id,
            role="user",
            content="hello",
        )
    )
    db_session.add(UserSettings(user_id=test_user.id))
    await db_session.commit()

    user = (
        await db_session.execute(select(User).where(User.id == test_user.id))
    ).scalar_one()

    await erase_user_account(db_session, user)
    await db_session.commit()

    remaining = (
        await db_session.execute(select(User).where(User.id == test_user.id))
    ).scalar_one_or_none()
    assert remaining is None

    msgs = (
        await db_session.execute(select(Message).where(Message.conversation_id == conv.id))
    ).scalars().all()
    assert msgs == []


@pytest.mark.asyncio
async def test_delete_account_endpoint_requires_confirmation(
    client: AsyncClient,
    auth_headers,
):
    response = await client.delete("/auth/me?confirmation=WRONG", headers=auth_headers)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_delete_account_endpoint_success(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    test_user: User,
):
    conv = Conversation(user_id=test_user.id, title="Wipe me")
    db_session.add(conv)
    await db_session.flush()
    db_session.add(
        Message(conversation_id=conv.id, role="assistant", content="bye")
    )
    await db_session.commit()

    response = await client.delete(
        "/auth/me?confirmation=DELETE",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("success") is True

    remaining = (
        await db_session.execute(select(User).where(User.id == test_user.id))
    ).scalar_one_or_none()
    assert remaining is None
