"""Tests for src/services/payment_service.py"""
import pytest

class TestPaymentService:
    @pytest.mark.asyncio
    async def test_payment_service_initialization(self):
        from src.services.payment_service import PaymentService
        service = PaymentService()
        assert service is not None

    @pytest.mark.asyncio
    async def test_mpesa_initialization(self):
        from src.services.payment_service import PaymentService
        service = PaymentService()
        assert service is not None
