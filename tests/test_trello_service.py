"""Tests for src/services/trello_service.py"""
import pytest

class TestTrelloService:
    def test_import(self):
        from src.services.trello_service import TrelloService
        svc = TrelloService()
        assert svc is not None
