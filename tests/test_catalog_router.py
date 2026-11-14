"""Catalog HTTP API and Catalog Builder DB export."""

import base64
import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Connection, ConnectionStatus, User


PUBLIC_CATALOG_IMAGE_PATH = "/api/public/catalog-images"


async def _assert_no_google(db_session: AsyncSession, test_user: User) -> None:
    result = await db_session.execute(
        select(Connection).where(
            Connection.user_id == test_user.id,
            Connection.platform == "google_workspace",
            Connection.status == ConnectionStatus.ACTIVE,
        )
    )
    assert result.scalar_one_or_none() is None


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
    await _assert_no_google(db_session, test_user)

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


@pytest.mark.asyncio
async def test_patch_then_get_product(client: AsyncClient, auth_headers, test_user):
    """PATCH /api/catalog/products/{id} updates fields visible on GET list."""
    created = await client.post(
        "/api/catalog/products",
        headers=auth_headers,
        json=_product_payload(sku="SIMBA-PATCH"),
    )
    assert created.status_code in (200, 201), created.text
    product_id = created.json()["data"]["id"]

    patched = await client.patch(
        f"/api/catalog/products/{product_id}",
        headers=auth_headers,
        json={"price": "150", "name": "Simba Chips Family"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json().get("success") is True
    assert patched.json()["data"]["name"] == "Simba Chips Family"
    assert "150" in str(patched.json()["data"].get("price"))

    listed = await client.get("/api/catalog/products", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    item = next(
        p for p in _listed_products(listed.json()) if p.get("id") == product_id
    )
    assert item.get("name") == "Simba Chips Family"
    assert "150" in str(item.get("price"))
    assert item.get("sku") == "SIMBA-PATCH"


@pytest.mark.asyncio
async def test_delete_then_list_omits_product(client: AsyncClient, auth_headers, test_user):
    """DELETE /api/catalog/products/{id} removes the row from GET list."""
    created = await client.post(
        "/api/catalog/products",
        headers=auth_headers,
        json=_product_payload(sku="SIMBA-DEL", name="Delete Me"),
    )
    assert created.status_code in (200, 201), created.text
    product_id = created.json()["data"]["id"]

    deleted = await client.delete(
        f"/api/catalog/products/{product_id}",
        headers=auth_headers,
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json().get("success") is True

    listed = await client.get("/api/catalog/products", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    ids = [item.get("id") for item in _listed_products(listed.json())]
    names = [item.get("name") for item in _listed_products(listed.json())]
    assert product_id not in ids
    assert "Delete Me" not in names


@pytest.mark.asyncio
async def test_import_csv_multipart_creates_product(
    client: AsyncClient, auth_headers, test_user
):
    """POST /api/catalog/products/import upserts from a CSV with a header row."""
    csv_body = (
        "name,Price,Category,SKU,Brand,Availability\n"
        "Maize Meal,250,Staples,UNGA-2,Pembe,in_stock\n"
    )
    response = await client.post(
        "/api/catalog/products/import",
        headers=auth_headers,
        files={"file": ("catalog.csv", csv_body.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("success") is True
    data = body.get("data") or {}
    assert (data.get("created") or 0) + (data.get("updated") or 0) >= 1

    listed = await client.get("/api/catalog/products", headers=auth_headers)
    item = next(
        p for p in _listed_products(listed.json()) if p.get("name") == "Maize Meal"
    )
    assert "250" in str(item.get("price"))
    assert item.get("sku") == "UNGA-2"
    assert item.get("category") == "Staples"


@pytest.mark.asyncio
async def test_from_builder_stores_image_base64_as_public_url(
    client: AsyncClient, auth_headers, test_user
):
    """POST /api/catalog/products/from-builder stores image_base64 as a catalog URL."""
    image_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")
    response = await client.post(
        "/api/catalog/products/from-builder",
        headers=auth_headers,
        json={
            "products": [
                {
                    "name": "Builder Chips",
                    "price": "99",
                    "category": "Snacks",
                    "sku": "BUILD-99",
                    "brand": "Simba",
                    "availability": "in_stock",
                    "image_base64": image_b64,
                    "image_filename": "builder-chips.png",
                    "image_content_type": "image/png",
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    assert response.json().get("success") is True

    listed = await client.get("/api/catalog/products", headers=auth_headers)
    item = next(
        p for p in _listed_products(listed.json()) if p.get("name") == "Builder Chips"
    )
    image_url = str(item.get("image_url") or "")
    assert PUBLIC_CATALOG_IMAGE_PATH in image_url
    assert "drive.google" not in image_url.lower()
    assert "99" in str(item.get("price"))


@pytest.mark.asyncio
async def test_export_one_byte_jpeg_uses_catalog_public_url_not_drive(
    client: AsyncClient, auth_headers, test_user, db_session
):
    """Export with a one-byte JPEG stores a catalog public URL, without Google."""
    await _assert_no_google(db_session, test_user)

    response = await client.post(
        "/api/catalog-builder/export",
        headers=auth_headers,
        data={
            "products": json.dumps(
                [
                    {
                        "name": "Photo Chips",
                        "price": "110",
                        "category": "Snacks",
                        "sku": "PHOTO-1",
                        "brand": "Simba",
                        "availability": "in_stock",
                        "image_index": 0,
                    }
                ]
            ),
            "destination": "arrotech_db",
            "mode": "new",
        },
        files={"files": ("product.jpg", b"\xff", "image/jpeg")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("success") is True
    detail = str(body.get("detail") or body.get("message") or "").lower()
    assert "google" not in detail

    listed = await client.get("/api/catalog/products", headers=auth_headers)
    item = next(
        p for p in _listed_products(listed.json()) if p.get("name") == "Photo Chips"
    )
    image_url = str(item.get("image_url") or "")
    assert PUBLIC_CATALOG_IMAGE_PATH in image_url
    assert "drive.google" not in image_url.lower()
    assert "docs.google" not in image_url.lower()


@pytest.mark.asyncio
async def test_export_maps_available_display_label_to_in_stock(
    client: AsyncClient, auth_headers, test_user, db_session
):
    """Builder 'Available' is stored as in_stock on the Arrotech catalog row."""
    await _assert_no_google(db_session, test_user)

    response = await client.post(
        "/api/catalog-builder/export",
        headers=auth_headers,
        data={
            "products": json.dumps(
                [
                    {
                        "name": "Fresh Milk",
                        "price": "70",
                        "category": "Dairy",
                        "sku": "MILK-1",
                        "availability": "Available",
                    }
                ]
            ),
            "destination": "arrotech_db",
            "mode": "new",
        },
        files={"files": ("empty.jpg", b"", "image/jpeg")},
    )
    assert response.status_code == 200, response.text
    assert response.json().get("success") is True

    listed = await client.get("/api/catalog/products", headers=auth_headers)
    item = next(
        p for p in _listed_products(listed.json()) if p.get("name") == "Fresh Milk"
    )
    assert item.get("availability") == "in_stock"


@pytest.mark.asyncio
async def test_export_zero_writes_is_not_success(
    client: AsyncClient, auth_headers, test_user, db_session
):
    """Export that writes no rows must not look like success (400 / success false)."""
    await _assert_no_google(db_session, test_user)

    response = await client.post(
        "/api/catalog-builder/export",
        headers=auth_headers,
        data={
            "products": json.dumps(
                [
                    {
                        "name": "Broken Row",
                        "price": "not a price",
                        "category": "Snacks",
                        "sku": "BAD-1",
                    }
                ]
            ),
            "destination": "arrotech_db",
            "mode": "new",
        },
        files={"files": ("empty.jpg", b"", "image/jpeg")},
    )
    assert response.status_code == 400, response.text
    body = response.json()
    payload = body.get("detail") if isinstance(body.get("detail"), dict) else body
    if not isinstance(payload, dict):
        payload = body
    assert payload.get("success") is not True
    listed = await client.get("/api/catalog/products", headers=auth_headers)
    names = [item.get("name") for item in _listed_products(listed.json())]
    assert "Broken Row" not in names
