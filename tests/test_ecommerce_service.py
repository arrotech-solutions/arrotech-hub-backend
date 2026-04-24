"""Tests for src/services/ecommerce_service.py"""
import pytest

class TestEcommerceService:
    def test_import(self):
        from src.services.ecommerce_service import EcommerceService
        assert EcommerceService is not None
