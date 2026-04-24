"""Tests for src/services/huggingface_service.py"""
import pytest

class TestHuggingFaceService:
    def test_import(self):
        from src.services.huggingface_service import HuggingFaceService
        assert HuggingFaceService is not None
