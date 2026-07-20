"""Tests for src/services/kra_service.py"""
import pytest

class TestKraService:
    def test_import(self):
        from src.services.kra_service import KraService
        svc = KraService()
        assert svc is not None
