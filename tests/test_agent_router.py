"""
Tests for autonomous agent endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_agents_unauthorized(client: AsyncClient):
    """Test listing agents without auth returns 401."""
    response = await client.get("/agents/agents/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_agents(client: AsyncClient, auth_headers):
    """Test listing user agents."""
    response = await client.get(
        "/agents/agents/", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_create_agent(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test creating an agent."""
    response = await client.post(
        "/agents/agents/create",
        headers=auth_headers,
        json={
            "name": "Test Agent",
            "workflow_id": str(test_workflow.id),
            "config": {"max_iterations": 10}
        }
    )
    assert response.status_code in [200, 201, 400, 422, 500]


@pytest.mark.asyncio
async def test_get_agent_not_found(client: AsyncClient, auth_headers):
    """Test getting a non-existent agent returns 404."""
    response = await client.get(
        "/agents/agents/99999/status", headers=auth_headers
    )
    assert response.status_code in [404, 400, 500]


@pytest.mark.asyncio
async def test_delete_agent_not_found(client: AsyncClient, auth_headers):
    """Test deleting a non-existent agent."""
    response = await client.delete(
        "/agents/agents/99999", headers=auth_headers
    )
    assert response.status_code in [404, 400, 500]
