"""Tests for agent_intelligence_service — multilingual & escalation."""
import pytest


class TestAgentIntelligenceService:
    def test_import(self):
        from src.services.agent_intelligence_service import agent_intelligence
        assert agent_intelligence is not None

    def test_detect_swahili(self):
        from src.services.agent_intelligence_service import agent_intelligence
        result = agent_intelligence.detect_language(
            "Habari, nataka kuagiza chakula leo", supported=["en", "sw"]
        )
        assert result["language_code"] == "sw"
        assert result["confidence"] >= 0.5

    def test_detect_english(self):
        from src.services.agent_intelligence_service import agent_intelligence
        result = agent_intelligence.detect_language(
            "Hello, I would like to place an order please", supported=["en", "sw"]
        )
        assert result["language_code"] == "en"

    def test_detect_arabic_script(self):
        from src.services.agent_intelligence_service import agent_intelligence
        result = agent_intelligence.detect_language(
            "مرحبا أريد طلب طعام", supported=["en", "ar"]
        )
        assert result["language_code"] == "ar"

    def test_wants_human_agent(self):
        from src.services.agent_intelligence_service import agent_intelligence
        assert agent_intelligence.wants_human_agent("I need to speak to a human please")
        assert agent_intelligence.wants_human_agent("Nataka kuongea na mtu")
        assert not agent_intelligence.wants_human_agent("Show me the menu")

    def test_auto_escalate_frustration(self):
        from src.services.agent_intelligence_service import agent_intelligence
        should, reason = agent_intelligence.should_auto_escalate(
            "This is ridiculous and unacceptable!!!",
            {},
            frustration_threshold=0.5,
        )
        assert should is True
        assert reason == "high_frustration"

    def test_auto_escalate_human_request(self):
        from src.services.agent_intelligence_service import agent_intelligence
        should, reason = agent_intelligence.should_auto_escalate(
            "Can I talk to a manager?",
            {},
        )
        assert should is True
        assert reason == "customer_requested_human"

    def test_no_escalate_when_handoff_active(self):
        from src.services.agent_intelligence_service import agent_intelligence
        should, _ = agent_intelligence.should_auto_escalate(
            "I want a human!!!",
            {"human_handoff": True},
        )
        assert should is False

    def test_language_instruction_swahili(self):
        from src.services.agent_intelligence_service import agent_intelligence
        block = agent_intelligence.build_language_instruction("sw")
        assert "Swahili" in block
        assert "CRITICAL" in block

    def test_handoff_messages_exist(self):
        from src.services.agent_intelligence_service import agent_intelligence
        msg = agent_intelligence.get_handoff_customer_message("sw")
        assert "timu" in msg.lower() or "agent" in msg.lower()

    def test_release_bot_command(self):
        from src.services.agent_intelligence_service import agent_intelligence
        assert agent_intelligence.is_release_bot_command("/bot")
        assert not agent_intelligence.is_release_bot_command("hello")
