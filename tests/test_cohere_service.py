"""Tests for src/services/cohere_service.py"""
import pytest

class TestCohereService:
    def test_import(self):
        from src.services.cohere_service import CohereService
        assert CohereService is not None
