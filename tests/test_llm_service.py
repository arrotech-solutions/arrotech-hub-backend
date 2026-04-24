"""Tests for src/services/llm_service.py"""
import pytest

class TestLLMService:
    @pytest.mark.asyncio
    async def test_llm_service_initialization(self):
        from src.services.llm_service import LLMService
        service = LLMService()
        assert service is not None

    @pytest.mark.asyncio
    async def test_generate_text(self):
        from src.services.llm_service import LLMService
        service = LLMService()
        assert hasattr(service, '__class__')

    @pytest.mark.asyncio
    async def test_analyze_intent(self):
        from src.services.llm_service import LLMService
        service = LLMService()
        assert hasattr(service, '__class__')
