"""Tests for src/services/whatsapp_workflow_trigger.py"""
import pytest

class TestWhatsAppWorkflowTrigger:
    def test_import(self):
        from src.services.whatsapp_workflow_trigger import WhatsAppWorkflowTrigger
        assert WhatsAppWorkflowTrigger is not None
