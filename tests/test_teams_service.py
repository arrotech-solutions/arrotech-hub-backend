"""Tests for src/services/teams_service.py"""
import pytest

class TestTeamsService:
    def test_import(self):
        from src.services.teams_service import TeamsService
        svc = TeamsService()
        assert svc is not None
