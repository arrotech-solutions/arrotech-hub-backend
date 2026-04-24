"""Tests for src/services/instagram_service.py"""
import pytest

class TestInstagramService:
    def test_import(self):
        from src.services.instagram_service import InstagramService
        svc = InstagramService()
        assert svc is not None
