"""Tests for src/services/clickup_service.py"""
import pytest

class TestClickUpService:
    def test_import(self):
        from src.services.clickup_service import ClickUpService
        svc = ClickUpService()
        assert svc is not None
