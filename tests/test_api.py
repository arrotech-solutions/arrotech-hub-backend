"""
Basic API endpoint tests.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    """Test health check endpoint."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient):
    """Test root endpoint."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data or "status" in data


@pytest.mark.asyncio
async def test_docs_available(client: AsyncClient):
    """Test that API docs are available."""
    response = await client.get("/docs")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_openapi_schema(client: AsyncClient):
    """Test that OpenAPI schema is available."""
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "openapi" in data
    assert "paths" in data


@pytest.mark.asyncio
async def test_unauthorized_access(client: AsyncClient):
    """Test that protected endpoints return 401 without auth."""
    # Test a protected endpoint without authentication
    response = await client.get("/settings/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token(client: AsyncClient):
    """Test that invalid token returns 401."""
    headers = {"Authorization": "Bearer invalid_token"}
    response = await client.get("/settings/", headers=headers)
    assert response.status_code == 401
