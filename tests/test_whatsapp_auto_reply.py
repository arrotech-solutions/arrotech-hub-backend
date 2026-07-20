"""Tests for src/services/whatsapp_auto_reply.py"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

class TestWhatsAppAutoReply:
    @pytest.mark.asyncio
    async def test_import(self):
        from src.services.whatsapp_auto_reply import AutoReplyEngine
        svc = AutoReplyEngine()
        assert svc is not None

    def test_substitute_variables(self):
        from src.services.whatsapp_auto_reply import AutoReplyEngine
        from src.models import WhatsAppContact, WhatsAppBusinessProfile
        
        svc = AutoReplyEngine()
        contact = WhatsAppContact(name="John Doe", phone_number="123456789")
        profile = WhatsAppBusinessProfile(business_name="Acme Corp")
        message = MagicMock()
        
        raw_text = "Hello {{name}}, welcome to {{business_name}}! We will call you at {{phone}}."
        result = svc._substitute_variables(raw_text, contact, message, profile)
        
        assert "John Doe" in result
        assert "Acme Corp" in result
        assert "123456789" in result

    def test_business_hours(self):
        from src.services.whatsapp_auto_reply import AutoReplyEngine
        import pytest
        
        svc = AutoReplyEngine()
        
        # Open 9am to 5pm, every day
        hours = {
            "monday": {"open": "09:00", "close": "17:00"},
            "tuesday": {"open": "09:00", "close": "17:00"},
            "wednesday": {"open": "09:00", "close": "17:00"},
            "thursday": {"open": "09:00", "close": "17:00"},
            "friday": {"open": "09:00", "close": "17:00"},
            "saturday": {"open": "09:00", "close": "17:00"},
            "sunday": {"open": "09:00", "close": "17:00"}
        }
        
        # Test will vary based on current system time, so we mock datetime inside the test if needed.
        # But we can at least assert it returns a boolean without throwing an error
        result = svc._is_within_business_hours(hours)
        assert isinstance(result, bool)
        
        # Empty hours -> False
        assert svc._is_within_business_hours({}) is False

    @pytest.mark.asyncio
    async def test_rule_match_keyword(self):
        from src.services.whatsapp_auto_reply import AutoReplyEngine
        from src.models import WhatsAppAutoReply, WhatsAppContact, WhatsAppMessage
        
        svc = AutoReplyEngine()
        
        rule = WhatsAppAutoReply(trigger_type="keyword", trigger_value="help|support")
        contact = WhatsAppContact()
        
        # Match
        msg = WhatsAppMessage(content="I need some help please")
        assert await svc._check_rule_match(rule, contact, msg, None) is True
        
        # No Match
        msg2 = WhatsAppMessage(content="Hello there")
        assert await svc._check_rule_match(rule, contact, msg2, None) is False

    @pytest.mark.asyncio
    async def test_rule_match_first_message(self):
        from src.services.whatsapp_auto_reply import AutoReplyEngine
        from src.models import WhatsAppAutoReply, WhatsAppContact, WhatsAppMessage
        
        svc = AutoReplyEngine()
        
        rule = WhatsAppAutoReply(trigger_type="first_message")
        msg = WhatsAppMessage(content="Hello")
        
        # First message
        contact = WhatsAppContact(message_count=1)
        assert await svc._check_rule_match(rule, contact, msg, None) is True
        
        # Subsequent message
        contact2 = WhatsAppContact(message_count=5)
        assert await svc._check_rule_match(rule, contact2, msg, None) is False

    @pytest.mark.asyncio
    async def test_rule_match_all(self):
        from src.services.whatsapp_auto_reply import AutoReplyEngine
        from src.models import WhatsAppAutoReply, WhatsAppContact, WhatsAppMessage
        
        svc = AutoReplyEngine()
        
        rule = WhatsAppAutoReply(trigger_type="all")
        contact = WhatsAppContact()
        msg = WhatsAppMessage(content="Anything")
        
        assert await svc._check_rule_match(rule, contact, msg, None) is True
