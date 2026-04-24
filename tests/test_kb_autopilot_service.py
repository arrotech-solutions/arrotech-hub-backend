"""Tests for src/services/kb_autopilot_service.py"""
import pytest

class TestKBAutopilotService:
    def test_import(self):
        from src.services.kb_autopilot_service import KBAutopilotService
        assert KBAutopilotService is not None

    def test_instantiate(self):
        from src.services.kb_autopilot_service import KBAutopilotService
        from unittest.mock import MagicMock
        svc = KBAutopilotService(zoho_service=MagicMock())
        assert hasattr(svc, '__class__')
