"""Tests for src/services/intent_processor.py"""
import pytest

class TestIntentProcessor:
    def test_import(self):
        from src.services.intent_processor import IntentProcessor
        assert IntentProcessor is not None

    def test_instantiate(self):
        from src.services.intent_processor import IntentProcessor
        from unittest.mock import MagicMock
        svc = IntentProcessor(user=MagicMock(), db=MagicMock())
        assert hasattr(svc, '__class__')
