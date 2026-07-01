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
    
    # Check that text contains key fields
    assert "B2" in res
    assert "Jane Doe" in res
    assert "20,000" in res
    assert "1,500" in res
    assert "2,000" in res
    assert "300" in res
    assert "5,000" in res
    assert "28,800" in res # Total
    assert "05 Aug" in res or "2026-08-05" in res

@pytest.mark.asyncio
async def test_process_partial_payment(rent_service):
    res = await rent_service.handle_operation(
        operation="process_partial_payment",
        tenant_name="Jane Doe",
        total_amount=28800,
        paid_amount=10000
    )
    
    assert "10,000" in res
    assert "18,800" in res # Balance
    assert "Thank you" in res

@pytest.mark.asyncio
async def test_calculate_utility_charges_metered(rent_service):
    res = await rent_service.handle_operation(
        operation="calculate_utility_charges",
        utility_type="water",
        meter_reading_previous=100,
        meter_reading_current=115,
        rate_per_unit=120
    )
    
    assert "15" in res # Units
    assert "1,800" in res # Amount (15 * 120)

@pytest.mark.asyncio
async def test_classify_tenant_intent(rent_service):
    res = await rent_service.handle_operation(
        operation="classify_tenant_intent",
        message="how much is my water bill?"
    )
    assert res == "utility_query"

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
    
    assert "Sunset Apartments" in res
    assert "August 2026" in res
    assert "90.0%" in res # Collection rate

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
    
    assert "found" in res
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
