"""
Catalog Builder router.

Endpoints powering the Product Catalog Builder wizard:
  - GET  /api/catalog-builder/status   -> Google Workspace connection state
  - GET  /api/catalog-builder/sheets   -> existing spreadsheets (append targets)
  - POST /api/catalog-builder/extract  -> photos -> AI-extracted product draft
  - POST /api/catalog-builder/export   -> photos + edited rows -> Google Sheet

This feature stops at sheet generation; RAG ingestion is a separate workflow.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User
from .auth_router import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/catalog-builder", tags=["catalog-builder"])

# Guardrails to keep vision cost predictable.
MAX_IMAGES_PER_EXTRACT = 6
MAX_PRODUCTS_PER_EXPORT = 200
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB per image


async def _google_workspace_connected(user_id: Any, db: AsyncSession) -> bool:
    from ..models import Connection, ConnectionStatus

    result = await db.execute(
        select(Connection).where(
            Connection.user_id == user_id,
            Connection.platform == "google_workspace",
            Connection.status == ConnectionStatus.ACTIVE,
        )
    )
    return result.scalar_one_or_none() is not None


@router.get("/status")
async def get_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Report prerequisite connection state for the wizard gate."""
    from ..config import settings

    connected = await _google_workspace_connected(user.id, db)
    vision_ready = bool(getattr(settings, "OPENAI_API_KEY", ""))
    if not vision_ready:
        # BYOK key would also satisfy this; check user settings.
        try:
            from ..models import UserSettings

            res = await db.execute(
                select(UserSettings).where(UserSettings.user_id == user.id)
            )
            us = res.scalar_one_or_none()
            vision_ready = bool(us and us.openai_api_key)
        except Exception:
            pass

    return {
        "success": True,
        "data": {
            "google_workspace_connected": connected,
            "vision_ready": vision_ready,
            "required_connections": ["google_workspace"],
        },
    }


@router.get("/sheets")
async def list_sheets(
    folder_id: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List existing spreadsheets the user can append to."""
    from ..services.catalog_builder_service import (
        CatalogBuilderError,
        catalog_builder_service,
    )

    try:
        sheets = await catalog_builder_service.list_spreadsheets(user.id, db, folder_id=folder_id)
        return {"success": True, "data": sheets}
    except CatalogBuilderError as e:
        return {"success": False, "message": str(e), "data": []}
    except Exception as e:
        logger.error(f"[CATALOG] list_sheets failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list spreadsheets",
        )


@router.post("/extract")
async def extract_product(
    files: List[UploadFile] = File(...),
    currency: str = Form("KES"),
    hint: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Extract structured product details from one product's photo(s)."""
    from ..services.product_vision_service import product_vision_service

    if not files:
        raise HTTPException(status_code=400, detail="No images uploaded")
    if len(files) > MAX_IMAGES_PER_EXTRACT:
        raise HTTPException(
            status_code=400,
            detail=f"Up to {MAX_IMAGES_PER_EXTRACT} images per product",
        )

    images: List[bytes] = []
    mime_types: List[str] = []
    for f in files:
        content = await f.read()
        if not content:
            continue
        if len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Image '{f.filename}' exceeds the 8 MB limit",
            )
        images.append(content)
        mime_types.append(f.content_type or "image/jpeg")

    if not images:
        raise HTTPException(status_code=400, detail="No valid images uploaded")

    result = await product_vision_service.extract_product(
        images=images,
        mime_types=mime_types,
        currency=currency or "KES",
        hint=hint,
        user_id=user.id,
        db=db,
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=502,
            detail=result.get("error", "Vision extraction failed"),
        )
    return {"success": True, "data": result.get("product", {})}


@router.post("/export")
async def export_catalog(
    products: str = Form(...),
    mode: str = Form("new"),
    title: Optional[str] = Form(None),
    spreadsheet_id: Optional[str] = Form(None),
    folder_id: Optional[str] = Form(None),
    want_csv: bool = Form(False),
    files: List[UploadFile] = File(default=[]),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Export edited product rows to a Google Sheet, hosting photos on Drive.

    `products` is a JSON array. Each product may reference an uploaded image by
    index via an `image_index` field that maps into the `files` list.
    """
    from ..services.catalog_builder_service import (
        CatalogBuilderError,
        catalog_builder_service,
    )

    try:
        parsed_products: List[Dict[str, Any]] = json.loads(products)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid products payload")

    if not isinstance(parsed_products, list) or not parsed_products:
        raise HTTPException(status_code=400, detail="No products to export")
    if len(parsed_products) > MAX_PRODUCTS_PER_EXPORT:
        raise HTTPException(
            status_code=400,
            detail=f"Up to {MAX_PRODUCTS_PER_EXPORT} products per export",
        )
    if mode == "append" and not spreadsheet_id:
        raise HTTPException(
            status_code=400, detail="Select a spreadsheet to append to"
        )

    # Read uploaded image files into an index-addressable list.
    image_blobs: List[Optional[Dict[str, Any]]] = []
    for f in files or []:
        content = await f.read()
        if content and len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Image '{f.filename}' exceeds the 8 MB limit",
            )
        image_blobs.append(
            {
                "content": content,
                "mime_type": f.content_type or "image/jpeg",
                "filename": f.filename or "product.jpg",
            }
            if content
            else None
        )

    # Attach images to their product by image_index.
    normalized: List[Dict[str, Any]] = []
    for product in parsed_products:
        if not isinstance(product, dict):
            continue
        entry = {
            "name": str(product.get("name", "")).strip(),
            "price": product.get("price", ""),
            "description": str(product.get("description", "")).strip(),
            "category": str(product.get("category", "")).strip(),
            "sku": str(product.get("sku", "")).strip(),
            "brand": str(product.get("brand", "")).strip(),
            "image_url": str(product.get("image_url", "")).strip(),
            "availability": str(product.get("availability", "")).strip(),
        }
        if not entry["name"]:
            # Skip nameless rows — name is the only hard requirement.
            continue
        idx = product.get("image_index")
        if isinstance(idx, int) and 0 <= idx < len(image_blobs) and image_blobs[idx]:
            entry["_image"] = image_blobs[idx]
        normalized.append(entry)

    if not normalized:
        raise HTTPException(
            status_code=400, detail="No valid products (each needs a name)"
        )

    try:
        result = await catalog_builder_service.export_catalog(
            user_id=user.id,
            db=db,
            products=normalized,
            target={
                "mode": mode,
                "title": title,
                "spreadsheet_id": spreadsheet_id,
                "folder_id": folder_id,
            },
            want_csv=bool(want_csv),
        )
        return {"success": True, "data": result}
    except CatalogBuilderError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[CATALOG] export failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to export catalog"
        )
