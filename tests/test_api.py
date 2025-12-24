"""
API endpoint tests for Mini-Hub
"""
import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_check(self, client: TestClient):
        """Test health check returns 200."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "healthy"


class TestAuthEndpoints:
    """Tests for authentication endpoints."""

    def test_register_user(self, client: TestClient, test_user_data):
        """Test user registration."""
        response = client.post("/auth/register", json=test_user_data)
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == test_user_data["email"]
        assert "id" in data

    def test_register_duplicate_email(self, client: TestClient, test_user_data):
        """Test registration with duplicate email fails."""
        client.post("/auth/register", json=test_user_data)
        response = client.post("/auth/register", json=test_user_data)
        assert response.status_code == 400

    def test_login_user(self, client: TestClient, test_user_data):
        """Test user login."""
        # Register first
        client.post("/auth/register", json=test_user_data)
        
        # Login
        response = client.post(
            "/auth/login",
            json={
                "email": test_user_data["email"],
                "password": test_user_data["password"]
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "token_type" in data

    def test_login_invalid_credentials(self, client: TestClient):
        """Test login with invalid credentials fails."""
        response = client.post(
            "/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "wrongpassword"
            }
        )
        assert response.status_code == 401

    def test_get_current_user(self, client: TestClient, auth_headers):
        """Test getting current user information."""
        response = client.get("/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "email" in data
        assert "id" in data

    def test_get_current_user_unauthorized(self, client: TestClient):
        """Test getting current user without authentication fails."""
        response = client.get("/auth/me")
        assert response.status_code == 401


class TestPaymentEndpoints:
    """Tests for payment endpoints."""

    def test_get_pricing(self, client: TestClient):
        """Test getting pricing information."""
        response = client.get("/payments/pricing")
        assert response.status_code == 200
        data = response.json()
        assert "tiers" in data
        assert len(data["tiers"]) > 0


class TestConnectionEndpoints:
    """Tests for connection management endpoints."""

    def test_list_platforms(self, client: TestClient):
        """Test listing available platforms."""
        response = client.get("/connections/platforms")
        assert response.status_code == 200
        data = response.json()
        assert "platforms" in data

    def test_create_connection_unauthorized(self, client: TestClient):
        """Test creating connection without authentication fails."""
        response = client.post(
            "/connections/",
            json={
                "platform": "hubspot",
                "credentials": {}
            }
        )
        assert response.status_code == 401


@pytest.mark.asyncio
class TestAsyncEndpoints:
    """Tests for async endpoints."""

    async def test_async_operation(self, client: TestClient):
        """Test async endpoint."""
        # Add async endpoint tests here
        pass


class TestErrorHandling:
    """Tests for error handling."""

    def test_404_not_found(self, client: TestClient):
        """Test 404 error for non-existent endpoint."""
        response = client.get("/nonexistent")
        assert response.status_code == 404

    def test_validation_error(self, client: TestClient):
        """Test validation error handling."""
        response = client.post(
            "/auth/register",
            json={"email": "invalid-email"}
        )
        assert response.status_code == 422

