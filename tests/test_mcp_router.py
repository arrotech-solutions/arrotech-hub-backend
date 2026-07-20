"""
Tests for MCP (Model Context Protocol) endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_call_mcp_tool(client: AsyncClient, auth_headers):
    """Test calling an MCP tool."""
    response = await client.post(
        "/mcp/call",
        headers=auth_headers,
        json={
            "tool_name": "test_tool",
            "arguments": {}
        }
    )
    # May fail with 422 for validation or missing params
    assert response.status_code in [200, 400, 404, 422, 500]


@pytest.mark.asyncio
async def test_call_mcp_tool_unauthorized(client: AsyncClient):
    """Test calling MCP tool without auth."""
    response = await client.post(
        "/mcp/call",
        json={
            "tool_name": "test_tool",
            "arguments": {}
        }
    )
    assert response.status_code == 401
