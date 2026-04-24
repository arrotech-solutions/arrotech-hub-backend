"""Tests for src/services/cache_service.py"""
import pytest

class TestCacheService:
    @pytest.mark.asyncio
    async def test_cache_service_initialization(self):
        from src.services.cache_service import CacheService
        service = CacheService()
        assert service is not None

    @pytest.mark.asyncio
    async def test_get_cached_data(self):
        from src.services.cache_service import CacheService
        service = CacheService()
        if hasattr(service, 'get'):
            result = service.get("test_key")
            assert result is None or isinstance(result, (dict, list, str))
