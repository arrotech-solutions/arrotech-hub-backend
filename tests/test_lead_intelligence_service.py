"""Tests for src/services/lead_intelligence_service.py"""
import pytest

class TestLeadIntelligenceService:
    def test_import(self):
        from src.services.lead_intelligence_service import LeadIntelligenceService
        assert LeadIntelligenceService is not None
