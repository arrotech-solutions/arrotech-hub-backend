"""Products desk catalog writes persist image bytes as public URLs."""

import base64

import pytest
from httpx import AsyncClient

PUBLIC_CATALOG_IMAGE_PATH = "/api/public/catalog-images"


def _tiny_png_b64() -> str:
    return base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")


def _product_payload(**overrides):
    data = {
        "name": "Desk Chips",
        "price": "120",
        "category": "Snacks",
        "sku": "DESK-50",
        "brand": "Simba",
        "description": "Crispy maize snacks",
        "availability": "in_stock",
    }
    data.update(overrides)
    return data


def _image_url(body: dict) -> str:
    return str((body.get("data") or {}).get("image_url") or "")


@pytest.mark.asyncio
async def test_create_product_stores_image_base64_as_public_url(
    client: AsyncClient, auth_headers, test_user
):
    """POST /api/catalog/products stores image_base64 as a catalog URL on the response.

    Fails if create skips attach_stored_image and leaves image_url empty.
    """
    created = await client.post(
        "/api/catalog/products",
        headers=auth_headers,
        json=_product_payload(
            sku="DESK-CREATE",
            name="Desk Create Chips",
            image_base64=_tiny_png_b64(),
            image_filename="desk-create.png",
            image_content_type="image/png",
        ),
    )
    assert created.status_code in (200, 201), created.text
    body = created.json()
    assert body.get("success") is True
    image_url = _image_url(body)
    assert PUBLIC_CATALOG_IMAGE_PATH in image_url
    assert "drive.google" not in image_url.lower()
    assert "Desk Create Chips" == (body.get("data") or {}).get("name")


@pytest.mark.asyncio
async def test_patch_product_stores_image_base64_as_public_url(
    client: AsyncClient, auth_headers, test_user
):
    """PATCH /api/catalog/products/{id} stores image_base64 as a catalog URL.

    Fails if patch skips attach_stored_image and leaves image_url empty.
    """
    created = await client.post(
        "/api/catalog/products",
        headers=auth_headers,
        json=_product_payload(sku="DESK-PATCH", name="Desk Patch Chips"),
    )
    assert created.status_code in (200, 201), created.text
    product_id = created.json()["data"]["id"]
    assert PUBLIC_CATALOG_IMAGE_PATH not in _image_url(created.json())

    patched = await client.patch(
        f"/api/catalog/products/{product_id}",
        headers=auth_headers,
        json={
            "image_base64": _tiny_png_b64(),
            "image_filename": "desk-patch.png",
            "image_content_type": "image/png",
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json().get("success") is True
    image_url = _image_url(patched.json())
    assert PUBLIC_CATALOG_IMAGE_PATH in image_url
    assert "drive.google" not in image_url.lower()
    assert (patched.json().get("data") or {}).get("name") == "Desk Patch Chips"
