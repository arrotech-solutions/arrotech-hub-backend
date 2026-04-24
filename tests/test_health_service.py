"""Tests for src/services/health_service.py"""
import pytest

class TestHealthService:
    def test_import(self):
        from src.services.health_service import HealthService
        svc = HealthService()
        assert svc is not None
