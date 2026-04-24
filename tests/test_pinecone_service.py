"""Tests for src/services/pinecone_service.py"""
import pytest

class TestPineconeService:
    def test_import(self):
        from src.services.pinecone_service import PineconeService
        assert PineconeService is not None
