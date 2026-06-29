"""Tests for src/services/whatsapp_workflow_trigger.py"""
import pytest
from types import SimpleNamespace


class TestWhatsAppWorkflowTrigger:
    def test_import(self):
        from src.services.whatsapp_workflow_trigger import WhatsAppWorkflowTrigger
        assert WhatsAppWorkflowTrigger is not None

    def test_pick_support_workflow_for_general_question(self):
        from src.services.whatsapp_workflow_trigger import (
            _pick_whatsapp_inbound_workflow,
            _prefer_ordering_workflow_for_message,
        )

        ordering = SimpleNamespace(
            name="Ordering Agent",
            steps=[SimpleNamespace(tool_name="conversational_agent")],
            variables={"template_id": "whatsapp_ordering_agent"},
            workflow_metadata={},
        )
        support = SimpleNamespace(
            name="Support Agent",
            steps=[
                SimpleNamespace(tool_name="rag_search"),
                SimpleNamespace(tool_name="ai_text_generation"),
                SimpleNamespace(tool_name="whatsapp_send_message"),
            ],
            variables={"template_id": "whatsapp_support_agent"},
            workflow_metadata={},
        )

        wa_general = [(ordering, "whatsapp_message_received"), (support, "whatsapp_message_received")]
        picked = _pick_whatsapp_inbound_workflow(wa_general, "What are your opening hours?")
        assert picked.name == "Support Agent"
        assert not _prefer_ordering_workflow_for_message("What are your opening hours?")

    def test_pick_ordering_workflow_for_cart_message(self):
        from src.services.whatsapp_workflow_trigger import _pick_whatsapp_inbound_workflow

        ordering = SimpleNamespace(
            name="Ordering Agent",
            steps=[SimpleNamespace(tool_name="conversational_agent")],
            variables={},
            workflow_metadata={},
        )
        support = SimpleNamespace(
            name="Support Agent",
            steps=[
                SimpleNamespace(tool_name="rag_search"),
                SimpleNamespace(tool_name="ai_text_generation"),
            ],
            variables={"template_id": "whatsapp_support_agent"},
            workflow_metadata={},
        )

        wa_general = [(ordering, "whatsapp_message_received"), (support, "whatsapp_message_received")]
        picked = _pick_whatsapp_inbound_workflow(wa_general, "I want to order from the menu")
        assert picked.name == "Ordering Agent"
