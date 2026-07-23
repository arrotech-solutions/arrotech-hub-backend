"""Tests for the stateless ReservationService."""

import pytest

from src.services.reservation_service import ReservationService


@pytest.fixture
def service():
    return ReservationService()


@pytest.mark.asyncio
async def test_create_reservation_success(service):
    result = await service.create_reservation(
        customer_name="Asha",
        customer_phone="254700000000",
        reservation_date="2026-07-25",
        reservation_time="19:30",
        party_size=4,
        notes="Window seat",
    )
    assert result["success"] is True
    res = result["reservation"]
    assert res["reservation_id"].startswith("RES-")
    assert res["status"] == "requested"
    assert res["party_size"] == 4
    assert res["customer"]["name"] == "Asha"
    assert res["customer"]["phone"] == "254700000000"


@pytest.mark.asyncio
async def test_create_reservation_missing_fields(service):
    result = await service.create_reservation(
        customer_name="Asha",
        customer_phone="254700000000",
        reservation_date="",
        reservation_time="",
        party_size=None,
    )
    assert result["success"] is False
    assert "date" in result["missing"]
    assert "time" in result["missing"]
    assert "party size" in result["missing"]


@pytest.mark.asyncio
async def test_create_reservation_coerces_party_size_from_text(service):
    result = await service.create_reservation(
        customer_name="Asha",
        customer_phone="254700000000",
        reservation_date="Friday",
        reservation_time="7pm",
        party_size="4 people",
    )
    assert result["success"] is True
    assert result["reservation"]["party_size"] == 4


def test_format_reservation_confirmation_has_details():
    msg = ReservationService.format_reservation_confirmation(
        customer_name="Asha",
        customer_phone="254700000000",
        reservation_date="2026-07-25",
        reservation_time="19:30",
        party_size=4,
        business_name="Mama's Kitchen",
    )
    assert "Asha" in msg
    assert "2026-07-25" in msg
    assert "19:30" in msg
    assert "4" in msg
    assert "YES" in msg


def test_format_business_notification_confirm_decline_framing():
    reservation = {
        "reservation_id": "RES-20260725-ABC123",
        "status": "requested",
        "customer": {"name": "Asha", "phone": "254700000000"},
        "reservation_date": "2026-07-25",
        "reservation_time": "19:30",
        "party_size": 4,
        "notes": "",
    }
    msg = ReservationService.format_reservation_business_notification(
        reservation, business_name="Mama's Kitchen"
    )
    assert "RES-20260725-ABC123" in msg
    assert "confirm" in msg.lower()
    assert "decline" in msg.lower()
