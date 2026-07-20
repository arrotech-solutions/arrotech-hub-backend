import pytest
from unittest.mock import MagicMock
from src.services.rent_collection_service import RentCollectionService

@pytest.fixture
def rent_service():
    return RentCollectionService()

@pytest.mark.asyncio
async def test_generate_consolidated_invoice(rent_service):
    res = await rent_service.handle_operation(
        operation="generate_consolidated_invoice",
        tenant_name="Jane Doe",
        unit="B2",
        rent_amount=20000,
        water_amount=1500,
        electricity_amount=2000,
        garbage_amount=300,
        previous_balance=5000,
        due_date="2026-08-05"
    )
    
    message = res.get("message", "")
    assert res.get("success") is True
    assert "B2" in message
    assert "Jane Doe" in message
    assert "20,000" in message
    assert "1,500" in message
    assert "2,000" in message
    assert "300" in message
    assert "5,000" in message
    assert "28,800" in message
    assert res.get("grand_total") == 28800

@pytest.mark.asyncio
async def test_process_partial_payment(rent_service):
    res = await rent_service.handle_operation(
        operation="process_partial_payment",
        tenant_name="Jane Doe",
        total_amount=28800,
        paid_amount=10000
    )
    
    message = res.get("message", "")
    assert res.get("success") is True
    assert "10,000" in message
    assert "18,800" in message
    assert "Thank you" in message
    assert res.get("balance") == 18800

@pytest.mark.asyncio
async def test_calculate_utility_charges_metered(rent_service):
    res = await rent_service.handle_operation(
        operation="calculate_utility_charges",
        utility_type="water",
        meter_reading_previous=100,
        meter_reading_current=115,
        rate_per_unit=120
    )
    
    assert res.get("success") is True
    assert res.get("units_consumed") == 15
    assert res.get("amount") == 1800
    assert "1,800" in res.get("message", "")

@pytest.mark.asyncio
async def test_classify_tenant_intent(rent_service):
    res = await rent_service.handle_operation(
        operation="classify_tenant_intent",
        message="how much is my water bill?"
    )
    assert res.get("success") is True
    assert res.get("primary_intent") in ("pay_water", "check_balance")

@pytest.mark.asyncio
async def test_generate_collection_summary(rent_service):
    res = await rent_service.handle_operation(
        operation="generate_collection_summary",
        property_name="Sunset Apartments",
        period="August 2026",
        total_units=20,
        occupied_units=18,
        total_expected=500000,
        total_collected=450000
    )
    
    message = res.get("message", "")
    assert res.get("success") is True
    assert "Sunset Apartments" in message
    assert "August 2026" in message
    assert "90%" in message

@pytest.mark.asyncio
async def test_lookup_tenant_found(rent_service):
    mock_data = [
        {"name": "John Doe", "phone": "254700000000", "unit": "A1"},
        {"name": "Jane Doe", "phone": "254711111111", "unit": "B2"}
    ]
    res = await rent_service.handle_operation(
        operation="lookup_tenant",
        phone_number="254711111111",
        tenants_data=mock_data
    )
    
    assert res.get("found") is True
    assert res["tenant"]["name"] == "Jane Doe"

@pytest.mark.asyncio
async def test_lookup_tenant_not_found(rent_service):
    mock_data = [
        {"name": "John Doe", "phone": "254700000000", "unit": "A1"}
    ]
    res = await rent_service.handle_operation(
        operation="lookup_tenant",
        phone_number="254799999999",
        tenants_data=mock_data
    )
    
    assert res.get("found") is False
