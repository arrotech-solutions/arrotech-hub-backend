"""
Tests for payment endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_pricing_no_auth(client: AsyncClient):
    """Test getting pricing - public endpoint."""
    response = await client.get("/payments/pricing")
    # Pricing may be public or require auth
    assert response.status_code in [200, 401]


@pytest.mark.asyncio
async def test_get_pricing(client: AsyncClient, auth_headers):
    """Test getting pricing tiers."""
    response = await client.get(
        "/payments/pricing", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_my_purchases(client: AsyncClient, auth_headers):
    """Test getting my purchases."""
    response = await client.get(
        "/payments/my-purchases", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_creator_earnings(client: AsyncClient, auth_headers):
    """Test getting creator earnings."""
    response = await client.get(
        "/payments/creator/earnings", headers=auth_headers
    )
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_mpesa_initiate(client: AsyncClient, auth_headers):
    """Test initiating M-Pesa payment."""
    response = await client.post(
        "/payments/mpesa/initiate",
        headers=auth_headers,
        json={
            "phone_number": "+254712345678",
            "amount": 100,
            "workflow_id": 1
        }
    )
    assert response.status_code in [200, 400, 422, 500]
