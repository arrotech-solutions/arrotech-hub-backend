"""Tests for src/services/mpesa_reconciliation_service.py"""
import pytest

class TestMpesaReconciliationService:
    def test_import(self):
        from src.services.mpesa_reconciliation_service import MpesaReconciliationService
        svc = MpesaReconciliationService()
        assert svc is not None
