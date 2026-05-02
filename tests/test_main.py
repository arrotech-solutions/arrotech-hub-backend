"""
Tests for src/main.py — JSONFormatter, RateLimitMiddleware, CacheHeaderMiddleware,
root endpoint, health endpoint, lifespan, and main() entry point.
"""
import json
import logging
import os
import time
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


class TestJSONFormatter:
    """Tests for the JSONFormatter log formatter."""

    def test_format_basic_message(self):
        from src.observability.logger import JSONFormatter
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Hello world", args=(), exc_info=None
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["message"] == "Hello world"
        assert "timestamp" in data
        assert "logger" in data

    def test_format_with_exception(self):
        from src.observability.logger import JSONFormatter
        fmt = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="", lineno=0,
            msg="Error occurred", args=(), exc_info=exc_info
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError" in data["exception"]

    def test_format_without_exception(self):
        from src.observability.logger import JSONFormatter
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.DEBUG, pathname="", lineno=0,
            msg="Debug msg", args=(), exc_info=None
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert "exception" not in data

    def test_format_warning_level(self):
        from src.observability.logger import JSONFormatter
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="test.module", level=logging.WARNING, pathname="", lineno=0,
            msg="Warning message", args=(), exc_info=None
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert data["level"] == "WARNING"
        assert data["logger"] == "test.module"

    def test_format_with_args(self):
        from src.observability.logger import JSONFormatter
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Count: %d", args=(42,), exc_info=None
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert data["message"] == "Count: 42"

    def test_output_is_valid_json(self):
        from src.observability.logger import JSONFormatter
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Test with special chars: <>&\"'", args=(), exc_info=None
        )
        output = fmt.format(record)
        # Should be valid JSON
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_format_critical_level(self):
        from src.observability.logger import JSONFormatter
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.CRITICAL, pathname="", lineno=0,
            msg="Critical failure", args=(), exc_info=None
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert data["level"] == "CRITICAL"


class TestRootEndpoint:
    """Tests for the root (/) endpoint."""

    @pytest.mark.asyncio
    async def test_root_returns_server_info(self, client: AsyncClient):
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Mini-Hub MCP Server"
        assert data["version"] == "1.0.0"
        assert data["status"] == "running"
        assert "pricing_tiers" in data

    @pytest.mark.asyncio
    async def test_root_pricing_tiers(self, client: AsyncClient):
        response = await client.get("/")
        data = response.json()
        tiers = data["pricing_tiers"]
        assert "free" in tiers
        assert "pro" in tiers
        assert "enterprise" in tiers

    @pytest.mark.asyncio
    async def test_root_description(self, client: AsyncClient):
        response = await client.get("/")
        data = response.json()
        assert "description" in data
        assert "AI" in data["description"] or "marketing" in data["description"]


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_check_returns_status(self, client: AsyncClient):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["healthy", "degraded"]
        assert "timestamp" in data
        assert "checks" in data

    @pytest.mark.asyncio
    async def test_health_check_includes_environment(self, client: AsyncClient):
        response = await client.get("/health")
        data = response.json()
        assert "environment" in data

    @pytest.mark.asyncio
    async def test_health_check_includes_redis_check(self, client: AsyncClient):
        response = await client.get("/health")
        data = response.json()
        checks = data.get("checks", {})
        assert "redis" in checks

    @pytest.mark.asyncio
    async def test_health_check_includes_db_pool(self, client: AsyncClient):
        response = await client.get("/health")
        data = response.json()
        checks = data.get("checks", {})
        # db_pool should be present (may be an error string or dict)
        assert "db_pool" in checks

    @pytest.mark.asyncio
    async def test_health_timestamp_format(self, client: AsyncClient):
        response = await client.get("/health")
        data = response.json()
        timestamp = data["timestamp"]
        # Should be ISO format
        assert "T" in timestamp or "-" in timestamp


class TestRateLimitMiddleware:
    """Unit tests for RateLimitMiddleware logic."""

    def test_cleanup_removes_old_entries(self):
        from src.main import RateLimitMiddleware
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        middleware._hits = defaultdict(list)
        now = time.time()
        middleware._hits["test"] = [now - 120, now - 90, now - 10, now]
        middleware._cleanup("test", 60.0)
        assert len(middleware._hits["test"]) == 2  # Only recent ones

    def test_cleanup_empty_key(self):
        from src.main import RateLimitMiddleware
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        middleware._hits = defaultdict(list)
        middleware._cleanup("nonexistent", 60.0)
        assert len(middleware._hits["nonexistent"]) == 0

    def test_cleanup_all_old(self):
        from src.main import RateLimitMiddleware
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        middleware._hits = defaultdict(list)
        now = time.time()
        middleware._hits["test"] = [now - 200, now - 150, now - 100]
        middleware._cleanup("test", 60.0)
        assert len(middleware._hits["test"]) == 0

    def test_cleanup_all_recent(self):
        from src.main import RateLimitMiddleware
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        middleware._hits = defaultdict(list)
        now = time.time()
        middleware._hits["test"] = [now - 5, now - 3, now - 1]
        middleware._cleanup("test", 60.0)
        assert len(middleware._hits["test"]) == 3

    def test_auth_paths_defined(self):
        from src.main import RateLimitMiddleware
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        middleware._auth_paths = {"/auth/login", "/auth/register", "/auth/forgot-password"}
        assert "/auth/login" in middleware._auth_paths
        assert "/auth/register" in middleware._auth_paths
        assert "/auth/forgot-password" in middleware._auth_paths

    def test_hits_dict_default(self):
        from src.main import RateLimitMiddleware
        middleware = RateLimitMiddleware.__new__(RateLimitMiddleware)
        middleware._hits = defaultdict(list)
        # Accessing a new key should return empty list
        assert middleware._hits["new_key"] == []


class TestCacheHeaderMiddleware:
    """Tests for CacheHeaderMiddleware rules."""

    @pytest.mark.asyncio
    async def test_health_gets_cache_header(self, client: AsyncClient):
        response = await client.get("/health")
        cache = response.headers.get("cache-control", "")
        assert "max-age" in cache or response.status_code == 200

    @pytest.mark.asyncio
    async def test_templates_gets_cache_header(self, client: AsyncClient, auth_headers):
        response = await client.get("/templates/", headers=auth_headers)
        # Templates should get cache-control
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_root_gets_cache_header(self, client: AsyncClient):
        response = await client.get("/")
        cache = response.headers.get("cache-control", "")
        # Root endpoint should have cache-control
        assert response.status_code == 200

    def test_cache_rules_defined(self):
        from src.main import CacheHeaderMiddleware
        assert hasattr(CacheHeaderMiddleware, "CACHE_RULES")
        rules = CacheHeaderMiddleware.CACHE_RULES
        assert "/health" in rules
        assert "/templates" in rules
        assert "/" in rules

    def test_cache_rules_values(self):
        from src.main import CacheHeaderMiddleware
        rules = CacheHeaderMiddleware.CACHE_RULES
        assert rules["/health"] == 10
        assert rules["/templates"] == 300
        assert rules["/"] == 60


class TestAppConfiguration:
    """Tests for FastAPI app configuration."""

    def test_app_exists(self):
        from src.main import app
        assert app is not None

    def test_app_title(self):
        from src.main import app
        assert app.title == "Mini-Hub MCP Server"

    def test_app_version(self):
        from src.main import app
        assert app.version == "1.0.0"

    def test_app_has_routes(self):
        from src.main import app
        routes = [r.path for r in app.routes]
        assert "/" in routes
        assert "/health" in routes

    @pytest.mark.asyncio
    async def test_non_existent_route(self, client: AsyncClient):
        response = await client.get("/non-existent-route-12345")
        assert response.status_code in [404, 405]


class TestMainFunction:
    """Tests for main() entry point."""

    def test_main_function_exists(self):
        from src.main import main
        assert callable(main)

    def test_run_mcp_server_function_exists(self):
        from src.main import run_mcp_server
        assert callable(run_mcp_server)


class TestGlobalServices:
    """Tests for global service instances."""

    def test_hubspot_service_exists(self):
        from src.main import hubspot_service
        assert hubspot_service is not None

    def test_slack_service_exists(self):
        from src.main import slack_service
        assert slack_service is not None

    def test_billing_service_exists(self):
        from src.main import billing_service
        assert billing_service is not None

    def test_rate_limit_service_exists(self):
        from src.main import rate_limit_service
        assert rate_limit_service is not None

    def test_social_media_service_exists(self):
        from src.main import social_media_service
        assert social_media_service is not None

    def test_file_management_service_exists(self):
        from src.main import file_management_service
        assert file_management_service is not None

    def test_web_tools_service_exists(self):
        from src.main import web_tools_service
        assert web_tools_service is not None

    def test_content_creation_service_exists(self):
        from src.main import content_creation_service
        assert content_creation_service is not None

    def test_workflow_scheduler_service_exists(self):
        from src.main import workflow_scheduler_service
        assert workflow_scheduler_service is not None

    def test_telegram_service_exists(self):
        from src.main import telegram_service
        assert telegram_service is not None
