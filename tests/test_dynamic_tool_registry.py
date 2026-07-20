"""Tests for src/services/dynamic_tool_registry.py"""
import pytest

class TestDynamicToolRegistry:
    def test_import(self):
        from src.services.dynamic_tool_registry import DynamicToolRegistry
        svc = DynamicToolRegistry()
        assert svc is not None

    def test_instantiate(self):
        from src.services.dynamic_tool_registry import DynamicToolRegistry
        svc = DynamicToolRegistry()
        assert hasattr(svc, '__class__')
