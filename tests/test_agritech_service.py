"""Tests for src/services/agritech_service.py"""
import pytest


class TestAgritechService:
    def test_import(self):
        from src.services.agritech_service import AgritechService
        svc = AgritechService()
        assert svc is not None

    @pytest.mark.asyncio
    async def test_get_market_prices(self):
        from src.services.agritech_service import AgritechService
        svc = AgritechService()
        result = await svc.handle_operation("shambasmart", "get_market_prices")
        assert result["success"] is True
        assert len(result["prices"]) == 3

    @pytest.mark.asyncio
    async def test_order_inputs(self):
        from src.services.agritech_service import AgritechService
        svc = AgritechService()
        result = await svc.handle_operation("digifarm", "order_inputs")
        assert result["success"] is True
        assert result["status"] == "Confirmed"

    @pytest.mark.asyncio
    async def test_request_credit(self):
        from src.services.agritech_service import AgritechService
        svc = AgritechService()
        result = await svc.handle_operation("digifarm", "request_credit")
        assert result["success"] is True
        assert result["limit_assessed"] == 50000

    @pytest.mark.asyncio
    async def test_get_weather_forecast(self):
        from src.services.agritech_service import AgritechService
        svc = AgritechService()
        result = await svc.handle_operation("shambasmart", "get_weather_forecast", location="Nakuru")
        assert result["success"] is True
        assert result["location"] == "Nakuru"

    @pytest.mark.asyncio
    async def test_weather_default_location(self):
        from src.services.agritech_service import AgritechService
        svc = AgritechService()
        result = await svc.handle_operation("shambasmart", "get_weather_forecast")
        assert result["location"] == "Current Farm Region"

    @pytest.mark.asyncio
    async def test_unsupported_op(self):
        from src.services.agritech_service import AgritechService
        svc = AgritechService()
        result = await svc.handle_operation("shambasmart", "unknown")
        assert result["success"] is False

    def test_global_instance(self):
        from src.services.agritech_service import agri_service
        assert agri_service is not None
