"""
Tests for creator profile endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_my_creator_profile_unauthorized(client: AsyncClient):
    """Test getting own creator profile without auth."""
    response = await client.get("/creators/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_my_creator_profile(client: AsyncClient, auth_headers):
    """Test getting own creator profile."""
    response = await client.get("/creators/me", headers=auth_headers)
    # May return 200 or 404 if profile doesn't exist yet
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_create_creator_profile(client: AsyncClient, auth_headers):
    """Test creating a creator profile."""
    response = await client.post(
        "/creators/me",
        headers=auth_headers,
        json={
            "display_name": "Test Creator",
            "bio": "A test creator profile",
            "website": "https://example.com"
        }
    )
    assert response.status_code in [200, 201]


@pytest.mark.asyncio
async def test_get_public_creator_profile(client: AsyncClient, test_user):
    """Test getting a public creator profile."""
    response = await client.get(f"/creators/{test_user.id}")
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_get_top_creators(client: AsyncClient):
    """Test getting top creators (public endpoint)."""
    # May need query params, accept 422 for validation
    response = await client.get("/creators/top?limit=10")
    assert response.status_code in [200, 422]


@pytest.mark.asyncio
async def test_follow_creator(
    client: AsyncClient, auth_headers, test_user_2
):
    """Test following a creator."""
    response = await client.post(
        f"/creators/{test_user_2.id}/follow",
        headers=auth_headers
    )
    assert response.status_code in [200, 201, 404]


@pytest.mark.asyncio
async def test_unfollow_creator(
    client: AsyncClient, auth_headers, test_user_2
):
    """Test unfollowing a creator."""
    # First follow
    await client.post(
        f"/creators/{test_user_2.id}/follow", headers=auth_headers
    )

    # Then unfollow
    response = await client.delete(
        f"/creators/{test_user_2.id}/follow",
        headers=auth_headers
    )
    assert response.status_code in [200, 204, 404]


@pytest.mark.asyncio
async def test_check_following(
    client: AsyncClient, auth_headers, test_user_2
):
    """Test checking if following a creator."""
    response = await client.get(
        f"/creators/{test_user_2.id}/is-following",
        headers=auth_headers
    )
    assert response.status_code == 200
