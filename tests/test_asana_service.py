"""Tests for src/services/asana_service.py"""
import pytest

class TestAsanaService:
    def test_import(self):
        from src.services.asana_service import AsanaService
        svc = AsanaService()
        assert svc is not None
