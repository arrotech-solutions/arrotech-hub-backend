"""Tests for src/services/airtable_service.py"""
import pytest

class TestAirtableService:
    def test_import(self):
        from src.services.airtable_service import AirtableService
        svc = AirtableService()
        assert svc is not None
