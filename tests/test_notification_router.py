"""
Tests for notification endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_notifications_unauthorized(client: AsyncClient):
    """Test getting notifications without auth returns 401."""
    response = await client.get("/notifications")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_notifications(client: AsyncClient, auth_headers):
    """Test getting user notifications."""
    response = await client.get("/notifications", headers=auth_headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_unread_count(client: AsyncClient, auth_headers):
    """Test getting unread notification count."""
    response = await client.get(
        "/notifications/unread-count", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_mark_all_as_read(client: AsyncClient, auth_headers):
    """Test marking all notifications as read."""
    response = await client.put(
        "/notifications/read-all", headers=auth_headers
    )
    assert response.status_code in [200, 400]
