"""Tests for src/services/assistant_kb_service.py"""
import pytest

class TestAssistantKBService:
    def test_import(self):
        from src.services.assistant_kb_service import AssistantKBService
        svc = AssistantKBService()
        assert svc is not None

    def test_instantiate(self):
        from src.services.assistant_kb_service import AssistantKBService
        svc = AssistantKBService()
        assert hasattr(svc, '__class__')
