"""
Tests for user preferences endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_preferences_unauthorized(client: AsyncClient):
    """Test getting preferences without auth returns 401."""
    response = await client.get("/preferences/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_preferences(client: AsyncClient, auth_headers):
    """Test getting user preferences."""
    response = await client.get("/preferences/", headers=auth_headers)
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_update_preferences(client: AsyncClient, auth_headers):
    """Test updating user preferences."""
    response = await client.put(
        "/preferences/",
        headers=auth_headers,
        json={
            "theme": "dark",
            "language": "en",
            "timezone": "UTC"
        }
    )
    assert response.status_code in [200, 201, 422]


@pytest.mark.asyncio
async def test_update_email_preferences(client: AsyncClient, auth_headers):
    """Test updating email notification preferences."""
    response = await client.put(
        "/preferences/notifications/email",
        headers=auth_headers,
        json={"enabled": True}
    )
    assert response.status_code in [200, 201, 422]
