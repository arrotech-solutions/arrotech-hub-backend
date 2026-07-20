"""Tests for src/services/openai_service.py"""
import pytest

class TestOpenAIService:
    def test_import(self):
        from src.services.openai_service import OpenAIEmbeddingService
        assert OpenAIEmbeddingService is not None
