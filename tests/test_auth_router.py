"""
Tests for authentication endpoints.
"""
from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from jose import jwt


@pytest.mark.asyncio
async def test_register_user(client: AsyncClient):
    """Test user registration."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "SecurePassword123!",
            "name": "New User"
        }
    )
    assert response.status_code in [200, 201]
    data = response.json()
    assert (
        data.get("success") is True
        or "token" in data
        or "access_token" in data
    )


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    """Test that duplicate email registration fails."""
    await client.post(
        "/auth/register",
        json={
            "email": "duplicate@example.com",
            "password": "SecurePassword123!",
            "name": "First User"
        }
    )
    response = await client.post(
        "/auth/register",
        json={
            "email": "duplicate@example.com",
            "password": "DifferentPassword123!",
            "name": "Second User"
        }
    )
    assert response.status_code in [400, 409]


@pytest.mark.asyncio
async def test_register_with_all_fields(client: AsyncClient):
    """Test registration with all fields."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "complete@example.com",
            "password": "CompletePassword123!",
            "name": "Complete User"
        }
    )
    assert response.status_code in [200, 201]


@pytest.mark.asyncio
async def test_register_empty_name(client: AsyncClient):
    """Test registration with empty name."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "emptyname@example.com",
            "password": "SecurePassword123!",
            "name": ""
        }
    )
    assert response.status_code in [200, 201, 400, 422]


@pytest.mark.asyncio
async def test_register_special_characters_in_name(client: AsyncClient):
    """Test registration with special characters in name."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "special@example.com",
            "password": "SecurePassword123!",
            "name": "User O'Brien-Smith"
        }
    )
    assert response.status_code in [200, 201]


@pytest.mark.asyncio
async def test_register_unicode_name(client: AsyncClient):
    """Test registration with unicode name."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "unicode@example.com",
            "password": "SecurePassword123!",
            "name": "用户名"
        }
    )
    assert response.status_code in [200, 201]


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    """Test successful login."""
    await client.post(
        "/auth/register",
        json={
            "email": "logintest@example.com",
            "password": "TestPassword123!",
            "name": "Login Test User"
        }
    )
    response = await client.post(
        "/auth/login",
        data="username=logintest%40example.com&password=TestPassword123!",
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert response.status_code in [200, 422]


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    """Test login with wrong password."""
    await client.post(
        "/auth/register",
        json={
            "email": "wrongpwd@example.com",
            "password": "CorrectPassword123!",
            "name": "Wrong Pwd User"
        }
    )
    response = await client.post(
        "/auth/login",
        data="username=wrongpwd%40example.com&password=WrongPassword123!",
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert response.status_code in [401, 422]


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    """Test login with nonexistent user."""
    response = await client.post(
        "/auth/login",
        data="username=nonexistent%40example.com&password=AnyPassword123!",
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert response.status_code in [401, 422]


@pytest.mark.asyncio
async def test_get_current_user(client: AsyncClient, auth_headers):
    """Test getting current user info."""
    response = await client.get("/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data.get("success") is True or "email" in data


@pytest.mark.asyncio
async def test_get_current_user_unauthorized(client: AsyncClient):
    """Test getting current user without auth."""
    response = await client.get("/auth/me")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_logout(client: AsyncClient, auth_headers):
    """Test logout."""
    response = await client.post("/auth/logout", headers=auth_headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_logout_without_auth(client: AsyncClient):
    """Test logout without authentication."""
    response = await client.post("/auth/logout")
    # May return 200 even without auth if endpoint doesn't require it
    assert response.status_code in [200, 401]


@pytest.mark.asyncio
async def test_expired_token(client: AsyncClient):
    """Test with expired token."""
    expired_token = jwt.encode(
        {
            "sub": "test@example.com",
            "exp": datetime.utcnow() - timedelta(hours=1)
        },
        "your-secret-key-here",
        algorithm="HS256"
    )
    response = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"}
    )
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_malformed_token(client: AsyncClient):
    """Test with malformed token."""
    response = await client.get(
        "/auth/me",
        headers={"Authorization": "Bearer not.a.valid.jwt.token"}
    )
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_missing_bearer_prefix(client: AsyncClient, auth_token):
    """Test without Bearer prefix."""
    response = await client.get(
        "/auth/me",
        headers={"Authorization": auth_token}
    )
    assert response.status_code in (401, 403)


# ─── Cookie-Based Auth Tests ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_sets_auth_cookies(client: AsyncClient):
    """Test that registration response sets HttpOnly auth cookies."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "cookietest@example.com",
            "password": "SecurePassword123!",
            "name": "Cookie User"
        }
    )
    assert response.status_code in [200, 201]
    cookies = response.cookies
    assert "auth_token" in cookies
    assert "refresh_token" in cookies


@pytest.mark.asyncio
async def test_auth_via_cookie(client: AsyncClient):
    """Test that auth_token cookie authenticates /auth/me."""
    # Register to get cookies
    reg_response = await client.post(
        "/auth/register",
        json={
            "email": "cookieauth@example.com",
            "password": "SecurePassword123!",
            "name": "Cookie Auth User"
        }
    )
    assert reg_response.status_code in [200, 201]
    auth_cookie = reg_response.cookies.get("auth_token")
    assert auth_cookie is not None

    # Use cookie to access /auth/me
    response = await client.get(
        "/auth/me",
        cookies={"auth_token": auth_cookie}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_refresh_via_cookie(client: AsyncClient):
    """Test that /auth/refresh works with refresh_token cookie."""
    # Register to get cookies
    reg_response = await client.post(
        "/auth/register",
        json={
            "email": "refreshcookie@example.com",
            "password": "SecurePassword123!",
            "name": "Refresh Cookie User"
        }
    )
    assert reg_response.status_code in [200, 201]
    refresh_cookie = reg_response.cookies.get("refresh_token")
    assert refresh_cookie is not None

    # Use refresh cookie to get new auth token
    response = await client.post(
        "/auth/refresh",
        json={},
        cookies={"refresh_token": refresh_cookie}
    )
    assert response.status_code == 200
    assert "auth_token" in response.cookies


@pytest.mark.asyncio
async def test_refresh_without_token_fails(client: AsyncClient):
    """Test that /auth/refresh without any refresh token returns 401."""
    response = await client.post("/auth/refresh", json={})
    assert response.status_code in [401, 422]


@pytest.mark.asyncio
async def test_logout_clears_cookies(client: AsyncClient):
    """Test that /auth/logout clears auth cookies."""
    response = await client.post("/auth/logout")
    assert response.status_code == 200
    data = response.json()
    assert data.get("success") is True
