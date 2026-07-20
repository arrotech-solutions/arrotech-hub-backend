"""Tests for src/services/weaviate_service.py"""
import pytest

class TestWeaviateService:
    def test_import(self):
        from src.services.weaviate_service import WeaviateService
        assert WeaviateService is not None
