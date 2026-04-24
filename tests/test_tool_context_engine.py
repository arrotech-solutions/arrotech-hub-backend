"""Tests for src/services/tool_context_engine.py"""
import pytest

class TestToolContextEngine:
    def test_import(self):
        from src.services.tool_context_engine import ToolContextEngine
        svc = ToolContextEngine()
        assert svc is not None

    def test_instantiate(self):
        from src.services.tool_context_engine import ToolContextEngine
        svc = ToolContextEngine()
        assert hasattr(svc, '__class__')
