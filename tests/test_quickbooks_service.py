"""Tests for src/services/quickbooks_service.py"""
import pytest

class TestQuickBooksService:
    def test_import(self):
        from src.services.quickbooks_service import QuickBooksService
        svc = QuickBooksService()
        assert svc is not None
