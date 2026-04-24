"""Tests for src/services/notion_service.py"""
import pytest

class TestNotionService:
    def test_import(self):
        from src.services.notion_service import NotionService
        svc = NotionService()
        assert svc is not None
