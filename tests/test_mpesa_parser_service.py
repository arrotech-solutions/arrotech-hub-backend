"""Tests for src/services/mpesa_parser_service.py"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

class TestMpesaParserService:
    def test_import(self):
        from src.services.mpesa_parser_service import MpesaParserService
        svc = MpesaParserService()
        assert svc is not None

    def test_clean_reference(self):
        from src.services.mpesa_parser_service import MpesaParserService
        svc = MpesaParserService()
        assert svc.clean_reference("") == ""
        assert svc.clean_reference(" abc ") == "ABC"
        assert svc.clean_reference("0lO") == "0LO"

    def test_parse_sms_received(self):
        from src.services.mpesa_parser_service import MpesaParserService
        svc = MpesaParserService()
        # Invalid SMS
        assert svc.parse_sms("") is None
        assert svc.parse_sms("Invalid text without start code") is None
        
        # Valid SMS
        sample_sms = "QG442342XX Confirmed. On 28/4/23 at 5:30 PM Ksh1,500.00 received from JOHN DOE 0712345678. New M-PESA Balance is Ksh5,000.00"
        result = svc.parse_sms(sample_sms)
        assert result is not None
        assert result["transaction_id"] == "QG442342XX"
        assert result["amount"] == 1500.0
        assert result["sender_name"] == "JOHN DOE"
        assert result["phone_number"] == "0712345678"
        assert result["type"] == "C2B"

    def test_parse_sms_sent(self):
        from src.services.mpesa_parser_service import MpesaParserService
        svc = MpesaParserService()
        
        sample_sms = "QG442342XX Confirmed. Ksh1,500.00 sent to PAYMENT SERVICES on 28/4/23 at 5:30 PM. New M-PESA Balance is Ksh5,000.00"
        result = svc.parse_sms(sample_sms)
        assert result is not None
        assert result["transaction_id"] == "QG442342XX"
        assert result["amount"] == 1500.0
        assert result["type"] == "C2B"


