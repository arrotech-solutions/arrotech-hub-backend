"""Tests for src/services/google_workspace/analytics_service.py"""
import pytest

class TestGoogleAnalyticsService:
    def test_import(self):
        try:
            from src.services.google_workspace.analytics_service import AnalyticsService
            assert AnalyticsService is not None
        except ImportError:
            pytest.skip("Google Analytics dependencies not installed")
