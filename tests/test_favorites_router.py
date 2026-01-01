"""
Tests for favorites endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_favorites_unauthorized(client: AsyncClient):
    """Test getting favorites without auth returns 401."""
    response = await client.get("/favorites/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_favorites(client: AsyncClient, auth_headers):
    """Test getting user favorites."""
    response = await client.get("/favorites/", headers=auth_headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_add_favorite(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test adding a workflow to favorites."""
    response = await client.post(
        f"/favorites/{test_workflow.id}",
        headers=auth_headers
    )
    assert response.status_code in [200, 201]


@pytest.mark.asyncio
async def test_check_favorite(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test checking if workflow is favorited."""
    response = await client.get(
        f"/favorites/{test_workflow.id}/check",
        headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_remove_favorite(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test removing a workflow from favorites."""
    # First add to favorites
    await client.post(
        f"/favorites/{test_workflow.id}", headers=auth_headers
    )

    # Then remove
    response = await client.delete(
        f"/favorites/{test_workflow.id}",
        headers=auth_headers
    )
    assert response.status_code in [200, 204, 404]
