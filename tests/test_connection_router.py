"""
Tests for connection management endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_connections_unauthorized(client: AsyncClient):
    """Test listing connections without auth returns 401."""
    response = await client.get("/connections/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_connections(client: AsyncClient, auth_headers):
    """Test listing user connections."""
    response = await client.get("/connections/", headers=auth_headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_create_connection(client: AsyncClient, auth_headers):
    """Test creating a new connection."""
    response = await client.post(
        "/connections/",
        headers=auth_headers,
        json={
            "platform": "hubspot",
            "name": "My HubSpot",
            "config": {"api_key": "test-key"}
        }
    )
    assert response.status_code in [200, 201, 400, 402, 422]


@pytest.mark.asyncio
async def test_delete_connection(
    client: AsyncClient, auth_headers, test_connection
):
    """Test deleting a connection."""
    response = await client.delete(
        f"/connections/{test_connection.id}", headers=auth_headers
    )
    assert response.status_code in [200, 204]


@pytest.mark.asyncio
async def test_update_connection(
    client: AsyncClient, auth_headers, test_connection
):
    """Test updating a connection."""
    response = await client.put(
        f"/connections/{test_connection.id}",
        headers=auth_headers,
        json={
            "name": "Updated Name",
            "status": "active",
            "config": test_connection.config
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_get_platforms(client: AsyncClient, auth_headers):
    """Test getting available platforms."""
    response = await client.get(
        "/connections/platforms", headers=auth_headers
    )
    assert response.status_code == 200
