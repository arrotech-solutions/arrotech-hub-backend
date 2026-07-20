"""Tests for src/services/invoice_service.py"""
import pytest

class TestInvoiceService:
    def test_import(self):
        from src.services.invoice_service import InvoiceService
        svc = InvoiceService()
        assert svc is not None
