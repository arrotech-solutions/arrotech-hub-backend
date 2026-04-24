"""Tests for src/services/zoho_service.py"""
import pytest

class TestZohoService:
    def test_import(self):
        from src.services.zoho_service import ZohoService
        svc = ZohoService()
        assert svc is not None
