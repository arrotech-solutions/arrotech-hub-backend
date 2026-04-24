"""Tests for src/services/intent_processor.py"""
import pytest

class TestIntentProcessor:
    def test_import(self):
        from src.services.intent_processor import IntentProcessor
        svc = IntentProcessor()
        assert svc is not None

    def test_instantiate(self):
        from src.services.intent_processor import IntentProcessor
        svc = IntentProcessor()
        assert hasattr(svc, '__class__')
