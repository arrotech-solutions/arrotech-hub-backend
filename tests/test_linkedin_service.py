"""Tests for src/services/linkedin_service.py"""
import pytest

class TestLinkedinService:
    def test_import(self):
        from src.services.linkedin_service import LinkedinService
        svc = LinkedinService()
        assert svc is not None
