"""Tests for src/services/tiktok_service.py"""
import pytest

class TestTikTokService:
    def test_import(self):
        from src.services.tiktok_service import TikTokService
        svc = TikTokService()
        assert svc is not None
