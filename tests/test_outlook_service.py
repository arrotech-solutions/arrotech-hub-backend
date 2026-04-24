"""Tests for src/services/outlook_service.py"""
import pytest

class TestOutlookService:
    def test_import(self):
        from src.services.outlook_service import OutlookService
        svc = OutlookService()
        assert svc is not None
