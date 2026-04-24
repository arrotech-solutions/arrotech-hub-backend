"""Tests for src/services/hr_service.py"""
import pytest

class TestHRService:
    def test_import(self):
        from src.services.hr_service import HRService
        svc = HRService()
        assert svc is not None
