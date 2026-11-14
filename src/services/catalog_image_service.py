"""Store catalog product photos and build Meta-fetchable public URLs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union
from urllib.parse import quote
from uuid import UUID

import aiofiles

from .file_management_service import file_management_service

PUBLIC_CATALOG_IMAGE_PATH = "/api/public/catalog-images"


def public_api_base_url() -> str:
    """Origin Meta can fetch. PUBLIC_API_BASE_URL wins over API_BASE_URL."""
    from ..config import settings

    return (
        os.getenv("PUBLIC_API_BASE_URL")
        or os.getenv("API_BASE_URL")
        or settings.API_BASE_URL
        or "http://localhost:8000"
    ).rstrip("/")


def catalog_image_dir(user_id: Union[str, UUID]) -> Path:
    """FileManagementService layout: uploads/{user_id}/catalog/."""
    return file_management_service.upload_dir / str(user_id) / "catalog"


def _reject_path_escape(value: str) -> str:
    if not value or value in (".", "..") or ".." in value:
        raise ValueError("Invalid catalog image path")
    if "/" in value or "\\" in value or "\x00" in value:
        raise ValueError("Invalid catalog image path")
    return value


def resolve_catalog_image_path(user_id: Union[str, UUID], filename: str) -> Path:
    """Resolve a catalog image path; raise ValueError if it escapes the catalog dir."""
    safe_user = _reject_path_escape(str(user_id))
    safe_name = _reject_path_escape(filename)
    catalog_root = catalog_image_dir(safe_user).resolve()
    dest = (catalog_root / safe_name).resolve()
    try:
        dest.relative_to(catalog_root)
    except ValueError as exc:
        raise ValueError("Invalid catalog image path") from exc
    return dest


async def store_catalog_image(
    user_id,
    filename: str,
    content: bytes,
    content_type: str,
) -> str:
    """Write bytes under uploads/{user_id}/catalog/ and return an absolute public URL."""
    del content_type  # reserved for serve-time media type; URL is path-based
    dest = resolve_catalog_image_path(user_id, filename)
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(dest, "wb") as handle:
        await handle.write(content)
    return (
        f"{public_api_base_url()}{PUBLIC_CATALOG_IMAGE_PATH}/"
        f"{quote(str(user_id), safe='')}/{quote(filename, safe='.')}"
    )
