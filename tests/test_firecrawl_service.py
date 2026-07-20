"""Tests for src/services/firecrawl_service.py"""
import pytest

class TestFirecrawlService:
    def test_import(self):
        from src.services.firecrawl_service import FirecrawlService
        assert FirecrawlService is not None
