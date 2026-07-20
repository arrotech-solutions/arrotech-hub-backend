"""Tests for WhatsApp contact delete and bulk delete."""

import uuid

import pytest
from sqlalchemy import select

from src.models import (
    User,
    WhatsAppBroadcast,
    WhatsAppBroadcastRecipient,
    WhatsAppContact,
    WhatsAppMessage,
    WhatsAppMessageDirection,
    WhatsAppMessageStatus,
)
from src.services.whatsapp_contact_service import (
    bulk_delete_contacts,
    delete_contact_and_related,
)


@pytest.mark.asyncio
async def test_delete_contact_removes_messages(db_session):
    user = User(
        id=uuid.uuid4(),
        email="wa-delete@test.com",
        name="WA User",
        password_hash="hash",
    )
    db_session.add(user)
    await db_session.flush()

    contact = WhatsAppContact(
        user_id=user.id,
        phone_number="254700000001",
        name="Test Contact",
        message_count=1,
    )
    db_session.add(contact)
    await db_session.flush()

    msg = WhatsAppMessage(
        user_id=user.id,
        contact_id=contact.id,
        direction=WhatsAppMessageDirection.INCOMING,
        content="Hello",
        status=WhatsAppMessageStatus.DELIVERED,
    )
    db_session.add(msg)
    await db_session.commit()

    await delete_contact_and_related(db_session, contact)
    await db_session.commit()

    remaining_msgs = await db_session.execute(select(WhatsAppMessage))
    assert remaining_msgs.scalars().all() == []

    remaining_contacts = await db_session.execute(select(WhatsAppContact))
    assert remaining_contacts.scalars().all() == []


@pytest.mark.asyncio
async def test_delete_contact_removes_broadcast_recipients(db_session):
    user = User(
        id=uuid.uuid4(),
        email="wa-broadcast@test.com",
        name="WA User",
        password_hash="hash",
    )
    db_session.add(user)
    await db_session.flush()

    contact = WhatsAppContact(
        user_id=user.id,
        phone_number="254700000002",
        name="Broadcast Contact",
    )
    db_session.add(contact)
    await db_session.flush()

    broadcast = WhatsAppBroadcast(
        user_id=user.id,
        name="Promo",
        message_type="text",
        text_content="Hi",
    )
    db_session.add(broadcast)
    await db_session.flush()

    recipient = WhatsAppBroadcastRecipient(
        broadcast_id=broadcast.id,
        contact_id=contact.id,
        status="pending",
    )
    db_session.add(recipient)
    await db_session.commit()

    await delete_contact_and_related(db_session, contact)
    await db_session.commit()

    remaining = await db_session.execute(select(WhatsAppBroadcastRecipient))
    assert remaining.scalars().all() == []


@pytest.mark.asyncio
async def test_bulk_delete_skips_foreign_contacts(db_session):
    owner = User(
        id=uuid.uuid4(),
        email="owner@test.com",
        name="Owner",
        password_hash="hash",
    )
    other = User(
        id=uuid.uuid4(),
        email="other@test.com",
        name="Other",
        password_hash="hash",
    )
    db_session.add_all([owner, other])
    await db_session.flush()

    mine = WhatsAppContact(
        user_id=owner.id,
        phone_number="254700000003",
        name="Mine",
    )
    theirs = WhatsAppContact(
        user_id=other.id,
        phone_number="254700000004",
        name="Theirs",
    )
    db_session.add_all([mine, theirs])
    await db_session.commit()

    deleted, failed = await bulk_delete_contacts(
        db_session,
        user_id=owner.id,
        contact_ids=[mine.id, theirs.id, uuid.uuid4()],
    )
    await db_session.commit()

    assert deleted == 1
    assert len(failed) == 2
    reasons = {f["reason"] for f in failed}
    assert "not_found" in reasons

    remaining = await db_session.execute(
        select(WhatsAppContact).where(WhatsAppContact.user_id == other.id)
    )
    assert len(remaining.scalars().all()) == 1


@pytest.mark.asyncio
async def test_bulk_delete_rejects_over_limit(db_session):
    user = User(
        id=uuid.uuid4(),
        email="limit@test.com",
        name="Limit",
        password_hash="hash",
    )
    db_session.add(user)
    await db_session.commit()

    with pytest.raises(ValueError, match="50"):
        await bulk_delete_contacts(
            db_session,
            user_id=user.id,
            contact_ids=[uuid.uuid4() for _ in range(51)],
        )
