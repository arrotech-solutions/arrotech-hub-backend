"""Tests for src/services/telegram_workflow_trigger.py"""
import pytest

class TestTelegramWorkflowTrigger:
    def test_import(self):
        from src.services.telegram_workflow_trigger import TelegramWorkflowTrigger
        assert TelegramWorkflowTrigger is not None
