"""Tests for src/services/scheduling_service.py"""
import pytest

class TestSchedulingService:
    def test_import(self):
        from src.services.scheduling_service import SchedulingService
        svc = SchedulingService()
        assert svc is not None
