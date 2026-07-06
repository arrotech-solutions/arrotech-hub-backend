import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.rent_tenant_storage_service import (
    RentTenantStorageService,
    _rows_to_tenants,
    storage_config_from_business,
)


def test_storage_config_from_business():
    cfg = storage_config_from_business({
        "storage_spreadsheet_id": "abc123",
        "storage_tenants_sheet_name": "Tenants",
        "storage_payments_sheet_name": "Payments",
    })
    assert cfg["spreadsheet_id"] == "abc123"
    assert cfg["tenants_sheet_name"] == "Tenants"


def test_rows_to_tenants_parses_headers():
    rows = [
        ["name", "phone", "unit", "rent_amount"],
        ["Jane", "254712345678", "A12", "15000"],
    ]
    tenants = _rows_to_tenants(rows)
    assert len(tenants) == 1
    assert tenants[0]["name"] == "Jane"
    assert tenants[0]["unit"] == "A12"


@pytest.mark.asyncio
async def test_load_tenants_uses_cache():
    service = RentTenantStorageService()
    user = MagicMock()
    user.id = "user-1"
    business_config = {"storage_spreadsheet_id": "sheet-1"}

    with patch("src.services.rent_tenant_storage_service.cache_service") as mock_cache:
        mock_cache.get.return_value = [{"name": "Cached", "unit": "B1"}]
        tenants = await service.load_tenants(user, business_config, AsyncMock())
        assert tenants[0]["name"] == "Cached"
        mock_cache.get.assert_called_once()


@pytest.mark.asyncio
async def test_load_tenants_empty_without_spreadsheet():
    service = RentTenantStorageService()
    user = MagicMock()
    user.id = "user-1"
    tenants = await service.load_tenants(user, {}, AsyncMock())
    assert tenants == []
