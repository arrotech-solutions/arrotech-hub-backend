"""Catalog product photo storage and Meta-fetchable public URLs."""

import uuid
from urllib.parse import urlparse

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_store_catalog_image_returns_url_containing_public_path(tmp_path, monkeypatch):
    """store_catalog_image returns an absolute public catalog-images URL.

    Fails if the URL is relative, omits /api/public/catalog-images/, or ignores PUBLIC_API_BASE_URL.
    """
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "https://cdn.example.com")
    from src.services.file_management_service import file_management_service

    monkeypatch.setattr(file_management_service, "upload_dir", tmp_path)

    from src.services.catalog_image_service import store_catalog_image

    user_id = uuid.uuid4()
    filename = "simba.png"
    content = b"\x89PNG\r\n\x1a\nfake-image"
    url = await store_catalog_image(user_id, filename, content, "image/png")

    public_path = f"/api/public/catalog-images/{user_id}/{filename}"
    assert public_path in url
    assert url == f"https://cdn.example.com{public_path}"
    stored = tmp_path / str(user_id) / "catalog" / filename
    assert stored.read_bytes() == content


@pytest.mark.asyncio
async def test_store_catalog_image_rejects_path_traversal(tmp_path, monkeypatch):
    """store_catalog_image refuses filenames that escape uploads/{user_id}/catalog/.

    Fails if '..' is written outside the catalog directory.
    """
    from src.services.file_management_service import file_management_service

    monkeypatch.setattr(file_management_service, "upload_dir", tmp_path)

    from src.services.catalog_image_service import store_catalog_image

    user_id = uuid.uuid4()
    with pytest.raises(ValueError, match="Invalid catalog image path"):
        await store_catalog_image(user_id, "../secret.png", b"nope", "image/png")
    with pytest.raises(ValueError, match="Invalid catalog image path"):
        await store_catalog_image(user_id, "..", b"nope", "image/png")
    assert not (tmp_path / "secret.png").exists()


@pytest.mark.asyncio
async def test_public_catalog_image_get_requires_no_auth(tmp_path, monkeypatch):
    """GET /api/public/catalog-images/{user_id}/{filename} serves bytes without auth.

    Fails if the route is missing, requires a token, or reads a different disk path.
    """
    from src.main import app
    from src.services.file_management_service import file_management_service

    monkeypatch.setattr(file_management_service, "upload_dir", tmp_path)

    from src.services.catalog_image_service import store_catalog_image

    user_id = uuid.uuid4()
    content = b"\x89PNG\r\n\x1a\nchips"
    await store_catalog_image(user_id, "chips.png", content, "image/png")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/public/catalog-images/{user_id}/chips.png")

    assert response.status_code == 200
    assert response.content == content


@pytest.mark.asyncio
async def test_public_catalog_image_get_rejects_path_traversal(tmp_path, monkeypatch):
    """Public GET returns 400 when filename contains '..'.

    Fails if path hardening is only applied on store, not on fetch.
    """
    from src.main import app
    from src.services.file_management_service import file_management_service

    monkeypatch.setattr(file_management_service, "upload_dir", tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Bare `/../` is collapsed by the HTTP stack; `..png` still matches the route.
        response = await client.get("/api/public/catalog-images/user-1/..png")

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_store_catalog_image_percent_encodes_filename_and_get_roundtrips(
    tmp_path, monkeypatch
):
    """Spaces in filenames become %20 in the public URL; GET of that URL returns the bytes.

    Fails if store interpolates a raw space that Meta cannot fetch.
    """
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "https://cdn.example.com")
    from src.services.file_management_service import file_management_service

    monkeypatch.setattr(file_management_service, "upload_dir", tmp_path)

    from src.services.catalog_image_service import store_catalog_image

    user_id = uuid.uuid4()
    filename = "Simba Chips.png"
    content = b"\x89PNG\r\n\x1a\nsimba-chips"
    url = await store_catalog_image(user_id, filename, content, "image/png")

    assert " " not in urlparse(url).path
    assert "%20" in url
    assert url.endswith("Simba%20Chips.png")

    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(urlparse(url).path)

    assert response.status_code == 200
    assert response.content == content
