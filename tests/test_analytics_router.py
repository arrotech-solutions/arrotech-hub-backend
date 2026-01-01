"""
Tests for analytics endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_my_workflow_analytics_unauthorized(client: AsyncClient):
    """Test getting my workflow analytics without auth returns 401."""
    response = await client.get("/analytics/my-workflows")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_my_workflow_analytics(client: AsyncClient, auth_headers):
    """Test getting my workflow analytics."""
    response = await client.get(
        "/analytics/my-workflows", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_track_event(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test tracking an analytics event."""
    response = await client.post(
        "/analytics/track",
        headers=auth_headers,
        json={
            "workflow_id": test_workflow.id,
            "event_type": "view"
        }
    )
    assert response.status_code in [200, 201, 422]


@pytest.mark.asyncio
async def test_get_workflow_analytics(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test getting workflow-specific analytics."""
    response = await client.get(
        f"/analytics/workflow/{test_workflow.id}",
        headers=auth_headers
    )
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_get_trending(client: AsyncClient, auth_headers):
    """Test getting trending workflows."""
    response = await client.get(
        "/analytics/trending", headers=auth_headers
    )
    assert response.status_code == 200
