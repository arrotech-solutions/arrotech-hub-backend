"""Commerce-context payload used by the Conversations handoff panel."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import CommerceComplaint, CommerceReturn, User, WhatsAppContact
from src.services.commerce_policy import upsert_policy
from src.services.conversation_context_manager import ConversationSession


@pytest.mark.asyncio
async def test_commerce_context_includes_handoff_packet(
    client: AsyncClient,
    auth_headers,
    db_session: AsyncSession,
    test_user: User,
    test_user_2: User,
):
    """Handoff context names this contact's returns, complaints, phase, and sell modes."""
    contact = WhatsAppContact(
        user_id=test_user.id,
        phone_number="254711000111",
        name="Amina",
        tags=["human_handoff"],
    )
    own_return = CommerceReturn(
        user_id=test_user.id,
        external_return_id="RET-HANDOFF-1",
        order_external_id="ORD-1",
        customer_phone="+254711000111",
        reason_code="damaged",
        amount=Decimal("500.00"),
        currency="KES",
        status="requested",
    )
    other_phone_return = CommerceReturn(
        user_id=test_user.id,
        external_return_id="RET-OTHER-PHONE",
        order_external_id="ORD-2",
        customer_phone="254700000099",
        reason_code="wrong_item",
        amount=Decimal("100.00"),
        currency="KES",
        status="requested",
    )
    other_tenant_return = CommerceReturn(
        user_id=test_user_2.id,
        external_return_id="RET-OTHER-TENANT",
        order_external_id="ORD-3",
        customer_phone="254711000111",
        reason_code="damaged",
        amount=Decimal("50.00"),
        currency="KES",
        status="requested",
    )
    complaint = CommerceComplaint(
        user_id=test_user.id,
        external_complaint_id="CMP-HANDOFF-1",
        order_external_id="ORD-1",
        customer_phone="254711000111",
        category="payment_dispute",
        status="handed_off",
    )
    db_session.add_all(
        [contact, own_return, other_phone_return, other_tenant_return, complaint]
    )
    await db_session.commit()
    await upsert_policy(
        db_session,
        test_user.id,
        {"sell_modes": ["pharmacy", "grocery"]},
    )

    session = ConversationSession(
        session_key=f"ccm:whatsapp:{test_user.id}:254711000111",
        platform="whatsapp",
        owner_user_id=str(test_user.id),
        sender_id="254711000111",
        metadata={
            "commerce_rails_state": {"phase": "awaiting_payment", "cart_lines": []},
        },
    )

    with patch(
        "src.services.whatsapp_commerce_context.context_manager.get_session_by_key",
        new=AsyncMock(return_value=session),
    ):
        response = await client.get(
            f"/api/whatsapp/contacts/{contact.id}/commerce-context",
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["return_ids"] == [str(own_return.id)]
    assert data["complaint_ids"] == [str(complaint.id)]
    assert data["commerce_phase"] == "awaiting_payment"
    assert data["policy_sell_modes"] == ["pharmacy", "grocery"]
