"""Tests for src/services/accounting_service.py"""
import pytest


class TestAccountingService:
    def test_import(self):
        from src.services.accounting_service import AccountingService
        svc = AccountingService()
        assert svc is not None

    @pytest.mark.asyncio
    async def test_validate_pin_valid(self):
        from src.services.accounting_service import AccountingService
        svc = AccountingService()
        result = await svc.handle_operation("kra", "validate_pin", pin="A123456789Z")
        assert result["success"] is True
        assert result["is_valid"] is True

    @pytest.mark.asyncio
    async def test_validate_pin_invalid(self):
        from src.services.accounting_service import AccountingService
        svc = AccountingService()
        result = await svc.handle_operation("kra", "validate_pin", pin="123")
        assert result["success"] is True
        assert result["is_valid"] is False

    @pytest.mark.asyncio
    async def test_validate_pin_missing(self):
        from src.services.accounting_service import AccountingService
        svc = AccountingService()
        result = await svc.handle_operation("kra", "validate_pin")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_check_compliance(self):
        from src.services.accounting_service import AccountingService
        svc = AccountingService()
        result = await svc.handle_operation("kra", "check_compliance")
        assert result["success"] is True
        assert result["compliant"] is True

    @pytest.mark.asyncio
    async def test_sync_invoices(self):
        from src.services.accounting_service import AccountingService
        svc = AccountingService()
        result = await svc.handle_operation("quickbooks", "sync_invoices")
        assert result["success"] is True
        assert result["synced_count"] == 12

    @pytest.mark.asyncio
    async def test_get_profit_loss(self):
        from src.services.accounting_service import AccountingService
        svc = AccountingService()
        result = await svc.handle_operation("xero", "get_profit_loss")
        assert result["success"] is True
        assert result["profit"] == 35000

    @pytest.mark.asyncio
    async def test_unsupported_operation(self):
        from src.services.accounting_service import AccountingService
        svc = AccountingService()
        result = await svc.handle_operation("kra", "unknown_op")
        assert result["success"] is False

    def test_global_instance(self):
        from src.services.accounting_service import accounting_service
        assert accounting_service is not None
