"""Tests for src/services/daraja_service.py"""
import pytest

class TestDarajaService:
    def test_import(self):
        from src.services.daraja_service import DarajaService
        svc = DarajaService()
        assert svc is not None
