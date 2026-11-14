"""CommerceStorageService order and reservation persistence."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.models import CommerceOrder, User


def _user(email: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        name="Merchant",
        password_hash="hash",
    )


@pytest.mark.asyncio
async def test_upsert_order_and_mark_paid(db_session):
    """Upsert stores one order row; mark_order_paid sets paid + receipt.

    Fails if a second upsert inserts a duplicate, payment_status stays pending,
    the receipt is dropped, or another user's get/list can see the row.
    """
    from src.services.commerce_storage_service import CommerceStorageService

    user = _user("orders-owner@test.com")
    other = _user("orders-other@test.com")
    db_session.add_all([user, other])
    await db_session.commit()

    svc = CommerceStorageService()
    payload = {
        "order_id": "ORD-20261113-A1B2C3",
        "customer_name": "Amina Wanjiku",
        "customer_phone": "+254712345678",
        "status": "pending",
        "delivery_method": "delivery",
        "delivery_address": "Kilimani, Nairobi",
        "total": "450.00",
        "items": [
            {"name": "Simba Chips", "qty": 2, "price": "120.00"},
            {"name": "Coca-Cola 500ml", "qty": 1, "price": "80.00"},
        ],
        "notes": "Leave at the gate",
    }

    created = await svc.upsert_order(db_session, user.id, payload)
    assert created.user_id == user.id
    assert created.external_order_id == "ORD-20261113-A1B2C3"
    assert created.customer_name == "Amina Wanjiku"
    assert created.customer_phone == "+254712345678"
    assert created.status == "pending"
    assert created.payment_status == "pending"
    assert created.currency == "KES"
    assert Decimal(created.total) == Decimal("450.00")
    assert created.line_items == payload["items"]
    assert created.delivery_method == "delivery"
    assert created.raw_snapshot == payload

    updated = await svc.upsert_order(
        db_session,
        user.id,
        {**payload, "notes": "Call on arrival", "customer_name": "Amina W."},
    )
    assert updated.id == created.id
    assert updated.customer_name == "Amina W."
    assert updated.notes == "Call on arrival"

    rows = (
        await db_session.execute(
            select(CommerceOrder).where(CommerceOrder.user_id == user.id)
        )
    ).scalars().all()
    assert len(rows) == 1

    assert await svc.get_order(db_session, other.id, "ORD-20261113-A1B2C3") is None
    assert await svc.list_orders(db_session, other.id) == []

    paid = await svc.mark_order_paid(
        db_session,
        user.id,
        "ORD-20261113-A1B2C3",
        mpesa_receipt="QK123XYZ",
    )
    assert paid.id == created.id
    assert paid.payment_status == "paid"
    assert paid.mpesa_receipt == "QK123XYZ"

    fetched = await svc.get_order(db_session, user.id, "ORD-20261113-A1B2C3")
    assert fetched is not None
    assert fetched.payment_status == "paid"
    assert fetched.mpesa_receipt == "QK123XYZ"


@pytest.mark.asyncio
async def test_upsert_reservation(db_session):
    """Upsert stores a reservation that list_reservations returns for that user only.

    Fails if reservation_id is not mapped, a second upsert duplicates the row,
    or another user's list can see it.
    """
    from src.services.commerce_storage_service import CommerceStorageService

    user = _user("res-owner@test.com")
    other = _user("res-other@test.com")
    db_session.add_all([user, other])
    await db_session.commit()

    svc = CommerceStorageService()
    payload = {
        "reservation_id": "RES-20261113-F4E5D6",
        "customer_name": "Brian Otieno",
        "customer_phone": "+254700111222",
        "reservation_date": "2026-11-20",
        "reservation_time": "19:30",
        "party_size": 4,
        "notes": "Window table",
    }

    created = await svc.upsert_reservation(db_session, user.id, payload)
    assert created.user_id == user.id
    assert created.external_reservation_id == "RES-20261113-F4E5D6"
    assert created.customer_name == "Brian Otieno"
    assert created.customer_phone == "+254700111222"
    assert created.reservation_date == "2026-11-20"
    assert created.reservation_time == "19:30"
    assert created.party_size == 4
    assert created.status == "confirmed"
    assert created.raw_snapshot == payload

    listed = await svc.list_reservations(db_session, user.id)
    assert [r.id for r in listed] == [created.id]
    assert listed[0].external_reservation_id == "RES-20261113-F4E5D6"

    assert await svc.list_reservations(db_session, other.id) == []

    updated = await svc.upsert_reservation(
        db_session,
        user.id,
        {**payload, "party_size": 6, "notes": "High chair"},
    )
    assert updated.id == created.id
    assert updated.party_size == 6
    relisted = await svc.list_reservations(db_session, user.id)
    assert [r.id for r in relisted] == [created.id]
    assert relisted[0].party_size == 6


@pytest.mark.asyncio
async def test_update_order_status_rejects_invalid(db_session):
    """A status not in ORDER_STATUSES is rejected and the row is unchanged.

    Fails if an invalid status is persisted or a missing order is inserted.
    """
    from src.services.commerce_storage_service import CommerceStorageService

    user = _user("status-owner@test.com")
    db_session.add(user)
    await db_session.commit()

    svc = CommerceStorageService()
    payload = {
        "order_id": "ORD-20261113-STAT",
        "customer_name": "Amina Wanjiku",
        "customer_phone": "+254712345678",
        "status": "pending",
        "delivery_method": "pickup",
        "total": "80.00",
        "items": [{"name": "Coca-Cola 500ml", "qty": 1, "price": "80.00"}],
    }
    created = await svc.upsert_order(db_session, user.id, payload)

    with pytest.raises(ValueError):
        await svc.update_order_status(
            db_session, user.id, "ORD-20261113-STAT", "not_a_status"
        )

    fetched = await svc.get_order(db_session, user.id, "ORD-20261113-STAT")
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.status == "pending"

    with pytest.raises(LookupError):
        await svc.update_order_status(db_session, user.id, "ORD-MISSING", "confirmed")
    assert await svc.get_order(db_session, user.id, "ORD-MISSING") is None
