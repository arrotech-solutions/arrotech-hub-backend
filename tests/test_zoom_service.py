"""Tests for src/services/zoom_service.py"""
import pytest

class TestZoomService:
    def test_import(self):
        from src.services.zoom_service import ZoomService
        svc = ZoomService()
        assert svc is not None
