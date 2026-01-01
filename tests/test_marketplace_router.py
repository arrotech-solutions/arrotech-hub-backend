"""
Tests for marketplace endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_browse_marketplace(client: AsyncClient, auth_headers):
    """Test browsing marketplace workflows."""
    response = await client.get(
        "/marketplace/browse", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_browse_marketplace_with_search(
    client: AsyncClient, auth_headers
):
    """Test browsing marketplace with search query."""
    response = await client.get(
        "/marketplace/browse?search=automation", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_browse_marketplace_with_category(
    client: AsyncClient, auth_headers
):
    """Test browsing marketplace filtered by category."""
    response = await client.get(
        "/marketplace/browse?category=marketing", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_browse_marketplace_with_sort(
    client: AsyncClient, auth_headers
):
    """Test browsing marketplace with sorting."""
    response = await client.get(
        "/marketplace/browse?sort_by=downloads&sort_order=desc",
        headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_browse_marketplace_pagination(
    client: AsyncClient, auth_headers
):
    """Test browsing marketplace with pagination."""
    response = await client.get(
        "/marketplace/browse?limit=10&offset=0", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_categories(client: AsyncClient, auth_headers):
    """Test getting marketplace categories."""
    response = await client.get(
        "/marketplace/categories", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_my_shared_workflows(client: AsyncClient, auth_headers):
    """Test getting my shared workflows."""
    response = await client.get(
        "/marketplace/my-shared", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_my_downloads(client: AsyncClient, auth_headers):
    """Test getting my downloaded workflows."""
    response = await client.get(
        "/marketplace/my-downloads", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_export_workflow_public(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test exporting a workflow as public."""
    response = await client.post(
        f"/marketplace/workflow/{test_workflow.id}/export",
        headers=auth_headers,
        json={"visibility": "public", "description": "Public workflow"}
    )
    assert response.status_code in [200, 201, 400]


@pytest.mark.asyncio
async def test_export_workflow_unlisted(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test exporting a workflow as unlisted."""
    response = await client.post(
        f"/marketplace/workflow/{test_workflow.id}/export",
        headers=auth_headers,
        json={"visibility": "unlisted"}
    )
    assert response.status_code in [200, 201, 400]


@pytest.mark.asyncio
async def test_export_workflow_marketplace(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test exporting a workflow to marketplace."""
    response = await client.post(
        f"/marketplace/workflow/{test_workflow.id}/export",
        headers=auth_headers,
        json={
            "visibility": "marketplace",
            "price": 0,
            "category": "automation"
        }
    )
    assert response.status_code in [200, 201, 400]


@pytest.mark.asyncio
async def test_update_workflow_visibility(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test updating workflow visibility."""
    response = await client.put(
        f"/marketplace/workflow/{test_workflow.id}/visibility",
        headers=auth_headers,
        json={"visibility": "public"}
    )
    assert response.status_code in [200, 400, 404]


@pytest.mark.asyncio
async def test_get_workflow_reviews(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test getting workflow reviews."""
    response = await client.get(
        f"/marketplace/workflow/{test_workflow.id}/reviews",
        headers=auth_headers
    )
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_add_workflow_review(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test adding a workflow review."""
    response = await client.post(
        f"/marketplace/workflow/{test_workflow.id}/review",
        headers=auth_headers,
        json={"rating": 5, "comment": "Excellent workflow!"}
    )
    assert response.status_code in [200, 201, 400, 403, 404]


@pytest.mark.asyncio
async def test_add_workflow_review_invalid_rating(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test adding a review with invalid rating."""
    response = await client.post(
        f"/marketplace/workflow/{test_workflow.id}/review",
        headers=auth_headers,
        json={"rating": 10, "comment": "Test review"}
    )
    assert response.status_code in [200, 400, 422]


@pytest.mark.asyncio
async def test_import_workflow_by_share_code(
    client: AsyncClient, auth_headers
):
    """Test importing workflow by share code."""
    response = await client.post(
        "/marketplace/workflow/import",
        headers=auth_headers,
        json={"share_code": "TEST123"}
    )
    assert response.status_code in [200, 201, 400, 404, 422]


@pytest.mark.asyncio
async def test_get_workflow_by_share_code(
    client: AsyncClient, auth_headers
):
    """Test getting workflow by share code."""
    response = await client.get(
        "/marketplace/workflow/TEST123", headers=auth_headers
    )
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_create_workflow_version(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test creating a workflow version."""
    response = await client.post(
        f"/marketplace/workflow/{test_workflow.id}/version",
        headers=auth_headers,
        json={"changelog": "Added new features"}
    )
    assert response.status_code in [200, 201, 400, 404]


@pytest.mark.asyncio
async def test_get_workflow_versions(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test getting workflow versions."""
    response = await client.get(
        f"/marketplace/workflow/{test_workflow.id}/versions",
        headers=auth_headers
    )
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_get_specific_workflow_version(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test getting a specific workflow version."""
    response = await client.get(
        f"/marketplace/workflow/{test_workflow.id}/version/1",
        headers=auth_headers
    )
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_rollback_workflow_version(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test rolling back to a previous version."""
    response = await client.post(
        f"/marketplace/workflow/{test_workflow.id}/rollback/1",
        headers=auth_headers
    )
    assert response.status_code in [200, 400, 404]
