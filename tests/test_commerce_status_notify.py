"""Hub order status changes notify the customer on WhatsApp.

PATCH persists first. A failed WhatsApp send is logged and does not
roll the status back.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Connection, MessagingConversation, User
from src.services.commerce_storage_service import CommerceStorageService

ORDER_ID = "ORD-STATUS-READY-1"
CUSTOMER_PHONE = "+254712345678"


def _order_payload(**overrides):
    data = {
        "order_id": ORDER_ID,
        "customer_name": "Amina Wanjiku",
        "customer_phone": CUSTOMER_PHONE,
        "status": "preparing",
        "delivery_method": "delivery",
        "total": "450.00",
        "items": [{"name": "Simba Chips", "qty": 1, "price": "450.00"}],
    }
    data.update(overrides)
    return data


def _sent(mock: AsyncMock):
    assert mock.await_count == 1
    args, kwargs = mock.await_args
    if args and not isinstance(args[0], str):
        args = args[1:]
    to_number = kwargs.get("to_number", args[0] if args else "")
    message = kwargs.get("message", args[1] if len(args) > 1 else "")
    return str(to_number), str(message)


async def _seed_preparing_order(db_session: AsyncSession, user: User, **overrides):
    await CommerceStorageService().upsert_order(
        db_session, user.id, _order_payload(**overrides)
    )
    connection = Connection(
        user_id=user.id,
        platform="whatsapp",
        name="Test WhatsApp",
        status="active",
        config={"access_token": "test-token", "phone_number_id": "123456"},
    )
    db_session.add(connection)
    await db_session.commit()


@pytest.mark.asyncio
async def test_patch_ready_sends_whatsapp_once_after_persist(
    client: AsyncClient,
    auth_headers,
    test_user: User,
    db_session: AsyncSession,
):
    """PATCH preparing→ready sends one WhatsApp text after the status commit.

    Fails if send is skipped, called before commit, or omits the order id
    and new status. English is the default when no customer language is known.
    """
    await _seed_preparing_order(db_session, test_user)
    events: list[str] = []
    original_commit = db_session.commit

    async def tracking_commit(*args, **kwargs):
        result = await original_commit(*args, **kwargs)
        events.append("commit")
        return result

    db_session.commit = tracking_commit

    async def fake_send(*args, **kwargs):
        assert "commit" in events, "WhatsApp send ran before the status commit"
        events.append("send")
        return {"success": True}

    with patch(
        "src.services.whatsapp_service.WhatsAppService.send_message",
        new=AsyncMock(side_effect=fake_send),
    ) as send:
        patched = await client.patch(
            f"/api/commerce/orders/{ORDER_ID}",
            headers=auth_headers,
            json={"status": "ready"},
        )

    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body.get("success") is True
    assert (body.get("data") or {}).get("status") == "ready"
    phone, message = _sent(send)
    assert CUSTOMER_PHONE in phone or "254712345678" in phone
    assert ORDER_ID in message
    assert "ready" in message.lower()
    assert "oda yako" not in message.lower()
    assert events == ["commit", "send"]


@pytest.mark.asyncio
async def test_whatsapp_send_failure_does_not_roll_back_ready_status(
    client: AsyncClient,
    auth_headers,
    test_user: User,
    db_session: AsyncSession,
):
    """A raising WhatsApp send leaves the persisted ready status in place.

    Fails if the PATCH returns an error or a later read shows preparing.
    """
    await _seed_preparing_order(db_session, test_user)

    with patch(
        "src.services.whatsapp_service.WhatsAppService.send_message",
        new=AsyncMock(side_effect=RuntimeError("meta down")),
    ) as send:
        patched = await client.patch(
            f"/api/commerce/orders/{ORDER_ID}",
            headers=auth_headers,
            json={"status": "ready"},
        )

    assert send.await_count == 1
    assert patched.status_code == 200, patched.text
    assert (patched.json().get("data") or {}).get("status") == "ready"

    listed = await client.get("/api/commerce/orders", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    orders = (listed.json().get("data") or {}).get("orders") or []
    match = next(
        item
        for item in orders
        if (item.get("external_order_id") or item.get("order_id")) == ORDER_ID
    )
    assert match.get("status") == "ready"


@pytest.mark.asyncio
async def test_known_swahili_customer_gets_swahili_status_text(
    client: AsyncClient,
    auth_headers,
    test_user: User,
    db_session: AsyncSession,
):
    """Customer preferred_language sw produces Swahili copy with id and status.

    Fails if the text stays English or drops the order id / ready status.
    """
    await _seed_preparing_order(db_session, test_user)
    db_session.add(
        MessagingConversation(
            owner_user_id=test_user.id,
            platform="whatsapp",
            sender_id="254712345678",
            session_key=f"ccm:whatsapp:{test_user.id}:254712345678",
            metadata_={"preferred_language": "sw"},
        )
    )
    await db_session.commit()

    with patch(
        "src.services.whatsapp_service.WhatsAppService.send_message",
        new=AsyncMock(return_value={"success": True}),
    ) as send:
        patched = await client.patch(
            f"/api/commerce/orders/{ORDER_ID}",
            headers=auth_headers,
            json={"status": "ready"},
        )

    assert patched.status_code == 200, patched.text
    _phone, message = _sent(send)
    assert ORDER_ID in message
    assert "ready" in message.lower()
    assert "oda yako" in message.lower()
