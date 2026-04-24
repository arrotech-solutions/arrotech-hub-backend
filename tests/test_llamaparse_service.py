"""Tests for src/services/llamaparse_service.py"""
import pytest

class TestLlamaParseService:
    def test_import(self):
        from src.services.llamaparse_service import LlamaParseService
        assert LlamaParseService is not None
