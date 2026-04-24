"""Tests for src/services/autonomous_agent_service.py"""
import pytest

class TestAutonomousAgentService:
    def test_import(self):
        from src.services.autonomous_agent_service import AutonomousAgentService
        svc = AutonomousAgentService()
        assert svc is not None

    def test_instantiate(self):
        from src.services.autonomous_agent_service import AutonomousAgentService
        svc = AutonomousAgentService()
        assert hasattr(svc, '__class__')
