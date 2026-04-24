"""Tests for src/services/kb_autopilot_service.py"""
import pytest

class TestKBAutopilotService:
    def test_import(self):
        from src.services.kb_autopilot_service import KBAutopilotService
        svc = KBAutopilotService()
        assert svc is not None

    def test_instantiate(self):
        from src.services.kb_autopilot_service import KBAutopilotService
        svc = KBAutopilotService()
        assert hasattr(svc, '__class__')
