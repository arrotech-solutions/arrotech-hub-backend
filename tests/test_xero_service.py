"""Tests for src/services/xero_service.py"""
import pytest

class TestXeroService:
    def test_import(self):
        from src.services.xero_service import XeroService
        svc = XeroService()
        assert svc is not None
