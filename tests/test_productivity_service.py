"""Tests for src/services/productivity_service.py"""
import pytest

class TestProductivityService:
    def test_import(self):
        from src.services.productivity_service import ProductivityService
        svc = ProductivityService()
        assert svc is not None
