"""Merchant catalog HTTP API."""

from __future__ import annotations

import base64
import csv
import io
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User
from .auth_router import get_current_user
from ..services.catalog_image_service import store_catalog_image
from ..services.catalog_service import (
    CatalogNotFound,
    bulk_upsert_from_rows,
    create_product,
    delete_product,
    list_products,
    update_product,
)

router = APIRouter(prefix="/api/catalog", tags=["catalog"])

_BUILDER_AVAILABILITY = {
    "available": "in_stock",
    "in stock": "in_stock",
    "out of stock": "out_of_stock",
    "outofstock": "out_of_stock",
}


def normalize_builder_availability(value: Any) -> str:
    """Map Catalog Builder display labels onto catalog availability tokens."""
    text = "" if value is None else str(value).strip()
    if not text:
        return text
    spaced = " ".join(text.lower().split())
    compact = spaced.replace(" ", "")
    return (
        _BUILDER_AVAILABILITY.get(spaced)
        or _BUILDER_AVAILABILITY.get(compact)
        or text
    )


class FromBuilderBody(BaseModel):
    products: List[Dict[str, Any]] = Field(default_factory=list)


def serialize_product(product) -> Dict[str, Any]:
    """JSON-safe catalog product."""
    def money(value):
        if value is None:
            return None
        if isinstance(value, Decimal):
            return format(value, "f")
        return str(value)

    return {
        "id": str(product.id),
        "user_id": str(product.user_id),
        "name": product.name,
        "price": money(product.price),
        "cost_price": money(product.cost_price),
        "description": product.description,
        "category": product.category,
        "sku": product.sku,
        "brand": product.brand,
        "quantity": money(product.quantity),
        "unit": product.unit,
        "condition": product.condition,
        "image_url": product.image_url,
        "availability": product.availability,
        "search_text": product.search_text,
        "created_at": product.created_at.isoformat() if product.created_at else None,
        "updated_at": product.updated_at.isoformat() if product.updated_at else None,
    }


def safe_image_filename(original: Optional[str]) -> str:
    """UUID-based filename that store_catalog_image will accept."""
    name = (original or "product.jpg").replace("\\", "/").rsplit("/", 1)[-1]
    if "." in name:
        ext = name.rsplit(".", 1)[-1]
        ext = "".join(ch for ch in ext if ch.isalnum())[:8] or "jpg"
    else:
        ext = "jpg"
    return f"{uuid.uuid4().hex}.{ext}"


async def persist_product_image(
    user_id,
    content: bytes,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
) -> str:
    """Store bytes and return a public catalog image URL."""
    return await store_catalog_image(
        user_id,
        safe_image_filename(filename),
        content,
        content_type or "image/jpeg",
    )


def _decode_image_payload(value: Any) -> Optional[bytes]:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return raw or None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.lower().startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    try:
        decoded = base64.b64decode(text, validate=False)
    except Exception:
        return None
    return decoded or None


async def attach_stored_image(user_id, product: Dict[str, Any]) -> Dict[str, Any]:
    """Copy product fields and persist image bytes/urls via catalog image storage."""
    fields = dict(product or {})
    filename = fields.pop("image_filename", None) or fields.pop("filename", None)
    content_type = (
        fields.pop("image_content_type", None)
        or fields.pop("content_type", None)
        or fields.pop("mime_type", None)
    )
    blob = fields.pop("_image", None)
    if isinstance(blob, dict) and blob.get("content"):
        content = blob.get("content")
        if isinstance(content, str):
            content = _decode_image_payload(content)
        if content:
            fields["image_url"] = await persist_product_image(
                user_id,
                content if isinstance(content, bytes) else bytes(content),
                blob.get("filename") or filename,
                blob.get("mime_type") or content_type,
            )
            if "availability" in fields:
                fields["availability"] = normalize_builder_availability(
                    fields.get("availability")
                )
            return fields

    raw = (
        fields.pop("image_bytes", None)
        or fields.pop("image_base64", None)
        or fields.pop("image_data", None)
    )
    content = _decode_image_payload(raw)
    if content:
        fields["image_url"] = await persist_product_image(
            user_id, content, filename, content_type
        )
    if "availability" in fields:
        fields["availability"] = normalize_builder_availability(fields.get("availability"))
    return fields


def _http_for_catalog(exc: Exception) -> HTTPException:
    if isinstance(exc, CatalogNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc


@router.post("/products", status_code=status.HTTP_201_CREATED)
async def create_catalog_product(
    payload: Dict[str, Any] = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a catalog product for the caller."""
    try:
        product = await create_product(db, user.id, payload)
    except (CatalogNotFound, ValueError) as exc:
        raise _http_for_catalog(exc) from exc
    return {"success": True, "data": serialize_product(product)}


@router.get("/products")
async def list_catalog_products(
    q: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the caller's catalog products, optionally filtered by q."""
    products = await list_products(db, user.id, q=q, limit=limit, offset=offset)
    return {
        "success": True,
        "data": {"products": [serialize_product(item) for item in products]},
    }


@router.post("/products/import")
async def import_catalog_products(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upsert products from a CSV multipart upload."""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig", errors="replace")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSV encoding"
        ) from exc
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(row) for row in reader]
    result = await bulk_upsert_from_rows(db, user.id, rows)
    return {"success": True, "data": result}


@router.post("/products/from-builder")
async def import_from_builder(
    body: FromBuilderBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upsert edited Catalog Builder products, storing images when bytes/urls are given."""
    if not body.products:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No products to import"
        )
    rows: List[Dict[str, Any]] = []
    for product in body.products:
        if not isinstance(product, dict):
            continue
        rows.append(await attach_stored_image(user.id, product))
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No products to import"
        )
    result = await bulk_upsert_from_rows(db, user.id, rows)
    return {"success": True, "data": result}


@router.patch("/products/{product_id}")
async def patch_catalog_product(
    product_id: uuid.UUID,
    payload: Dict[str, Any] = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Partial-update a product owned by the caller."""
    try:
        product = await update_product(db, user.id, product_id, payload)
    except (CatalogNotFound, ValueError) as exc:
        raise _http_for_catalog(exc) from exc
    return {"success": True, "data": serialize_product(product)}


@router.delete("/products/{product_id}")
async def delete_catalog_product(
    product_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a product owned by the caller."""
    try:
        await delete_product(db, user.id, product_id)
    except (CatalogNotFound, ValueError) as exc:
        raise _http_for_catalog(exc) from exc
    return {"success": True, "data": {"id": str(product_id)}}
