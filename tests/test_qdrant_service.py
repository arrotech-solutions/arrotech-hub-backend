"""Tests for src/services/qdrant_service.py"""
import pytest

class TestQdrantService:
    def test_import(self):
        from src.services.qdrant_service import QdrantService
        assert QdrantService is not None
