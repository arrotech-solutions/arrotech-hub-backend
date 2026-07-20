"""Tests for src/services/platform_registry.py"""
import pytest

class TestPlatformRegistry:
    def test_import(self):
        from src.services.platform_registry import PlatformRegistry
        svc = PlatformRegistry()
        assert svc is not None

    def test_instantiate(self):
        from src.services.platform_registry import PlatformRegistry
        svc = PlatformRegistry()
        assert hasattr(svc, '__class__')
