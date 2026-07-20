"""Tests for src/services/jira_service.py"""
import pytest

class TestJiraService:
    def test_import(self):
        from src.services.jira_service import JiraService
        svc = JiraService()
        assert svc is not None
