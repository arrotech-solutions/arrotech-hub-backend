"""Tests for src/services/bilingual_service.py"""
import pytest


class TestBilingualService:
    def test_import(self):
        from src.services.bilingual_service import BilingualService
        svc = BilingualService()
        assert svc is not None

    def test_cache_key_generation(self):
        from src.services.bilingual_service import BilingualService
        svc = BilingualService()
        key = svc._get_cache_key("Hello world", "sw")
        assert key == "sw:Hello world"

    def test_cache_key_truncation(self):
        from src.services.bilingual_service import BilingualService
        svc = BilingualService()
        long_text = "x" * 500
        key = svc._get_cache_key(long_text, "en")
        assert key.startswith("en:")
        assert len(key) <= 204

    @pytest.mark.asyncio
    async def test_sentiment_positive(self):
        from src.services.bilingual_service import BilingualService
        svc = BilingualService()
        result = await svc.analyze_sentiment_bilingual("Great product, I love it")
        assert result["sentiment"] == "positive"
        assert result["score"] == 0.8

    @pytest.mark.asyncio
    async def test_sentiment_negative_english(self):
        from src.services.bilingual_service import BilingualService
        svc = BilingualService()
        result = await svc.analyze_sentiment_bilingual("This is bad and has an error")
        assert result["sentiment"] == "negative"
        assert result["score"] == 0.2

    @pytest.mark.asyncio
    async def test_sentiment_negative_swahili(self):
        from src.services.bilingual_service import BilingualService
        svc = BilingualService()
        result = await svc.analyze_sentiment_bilingual("Hii ni mbaya sana")
        assert result["sentiment"] == "negative"

    @pytest.mark.asyncio
    async def test_language_detection_swahili(self):
        from src.services.bilingual_service import BilingualService
        svc = BilingualService()
        result = await svc.analyze_sentiment_bilingual("Habari, nimefika leo")
        assert result["detected_language"] == "swahili"

    @pytest.mark.asyncio
    async def test_language_detection_english(self):
        from src.services.bilingual_service import BilingualService
        svc = BilingualService()
        result = await svc.analyze_sentiment_bilingual("Hello, good morning")
        assert result["detected_language"] == "english"

    @pytest.mark.asyncio
    async def test_verify_kra_pin_valid(self):
        from src.services.bilingual_service import BilingualService
        svc = BilingualService()
        result = await svc.verify_kra_pin("A123456789Z")
        assert result["valid"] is True
        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_verify_kra_pin_invalid(self):
        from src.services.bilingual_service import BilingualService
        svc = BilingualService()
        result = await svc.verify_kra_pin("12345")
        assert result["valid"] is False

    @pytest.mark.asyncio
    async def test_check_itax_compliance(self):
        from src.services.bilingual_service import BilingualService
        svc = BilingualService()
        result = await svc.check_itax_compliance("A123456789Z")
        assert result["compliant"] is True
        assert "VAT" in result["certificates"]

    @pytest.mark.asyncio
    async def test_test_connection(self):
        from src.services.bilingual_service import BilingualService
        svc = BilingualService()
        result = await svc.test_connection({})
        assert result["success"] is True
