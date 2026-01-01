"""
Tests for workflow templates endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_templates_no_auth(client: AsyncClient):
    """Test getting templates - may be public or require auth."""
    response = await client.get("/templates/")
    # Templates may be public or require auth
    assert response.status_code in [200, 401]


@pytest.mark.asyncio
async def test_get_templates(client: AsyncClient, auth_headers):
    """Test getting workflow templates."""
    response = await client.get("/templates/", headers=auth_headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_template_categories(client: AsyncClient, auth_headers):
    """Test getting template categories."""
    response = await client.get(
        "/templates/categories", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_use_template(client: AsyncClient, auth_headers):
    """Test using a workflow template."""
    response = await client.post(
        "/templates/1/use", headers=auth_headers
    )
    assert response.status_code in [200, 201, 404]


@pytest.mark.asyncio
async def test_get_featured_templates(client: AsyncClient, auth_headers):
    """Test getting featured templates."""
    response = await client.get(
        "/templates/featured/list", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_popular_templates(client: AsyncClient, auth_headers):
    """Test getting popular templates."""
    response = await client.get(
        "/templates/stats/popular", headers=auth_headers
    )
    assert response.status_code == 200
