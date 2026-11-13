"""Catalog HTTP API and Catalog Builder DB export."""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from src.models import Connection, ConnectionStatus


def _product_payload(**overrides):
    data = {
        "name": "Simba Chips",
        "price": "120",
        "category": "Snacks",
        "sku": "SIMBA-50",
        "brand": "Simba",
        "description": "Crispy maize snacks",
        "availability": "in_stock",
    }
    data.update(overrides)
    return data


def _listed_products(body: dict):
    data = body.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("products") or data.get("items") or []
    return []


@pytest.mark.asyncio
async def test_create_and_list_products(client: AsyncClient, auth_headers, test_user):
    """POST /api/catalog/products persists a row; GET lists it for the caller.

    Fails if the catalog router is missing, create drops Price/Category, or
    list does not return the product just created.
    """
    created = await client.post(
        "/api/catalog/products",
        headers=auth_headers,
        json=_product_payload(),
    )
    assert created.status_code in (200, 201), created.text
    body = created.json()
    assert body.get("success") is True
    product = body.get("data") or {}
    assert product.get("name") == "Simba Chips"
    assert "120" in str(product.get("price"))
    assert product.get("category") == "Snacks"
    assert product.get("sku") == "SIMBA-50"
    assert product.get("id")

    listed = await client.get("/api/catalog/products", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    list_body = listed.json()
    assert list_body.get("success") is True
    names = [item.get("name") for item in _listed_products(list_body)]
    assert "Simba Chips" in names

    snacks = await client.get(
        "/api/catalog/products",
        headers=auth_headers,
        params={"q": "snacks"},
    )
    assert snacks.status_code == 200
    snack_names = [item.get("name") for item in _listed_products(snacks.json())]
    assert snack_names == ["Simba Chips"]


@pytest.mark.asyncio
async def test_export_arrotech_db_without_google_connection(
    client: AsyncClient, auth_headers, test_user, db_session
):
    """POST /api/catalog-builder/export destination=arrotech_db saves without Google.

    Fails if export still requires a Google Workspace connection or does not
    write products into the Arrotech catalog.
    """
    result = await db_session.execute(
        select(Connection).where(
            Connection.user_id == test_user.id,
            Connection.platform == "google_workspace",
            Connection.status == ConnectionStatus.ACTIVE,
        )
    )
    assert result.scalar_one_or_none() is None

    response = await client.post(
        "/api/catalog-builder/export",
        headers=auth_headers,
        data={
            "products": json.dumps(
                [
                    {
                        "name": "Coca-Cola 500ml",
                        "price": "80",
                        "category": "Drinks",
                        "sku": "COKE-500",
                        "brand": "Coca-Cola",
                        "availability": "in_stock",
                    }
                ]
            ),
            "destination": "arrotech_db",
            "mode": "new",
        },
        files={"files": ("empty.jpg", b"", "image/jpeg")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("success") is True
    data = body.get("data") or {}
    assert data.get("destination") == "arrotech_db"
    written = data.get("created", 0) + data.get("updated", 0)
    assert (data.get("rows_written") or written) >= 1
    detail = str(body.get("detail") or body.get("message") or "").lower()
    assert "google" not in detail

    listed = await client.get("/api/catalog/products", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    names = [item.get("name") for item in _listed_products(listed.json())]
    assert "Coca-Cola 500ml" in names
    coke = next(
        item
        for item in _listed_products(listed.json())
        if item.get("name") == "Coca-Cola 500ml"
    )
    assert "80" in str(coke.get("price"))
    assert coke.get("sku") == "COKE-500"
