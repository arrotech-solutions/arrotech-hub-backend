"""Merchant catalog CRUD and Catalog Builder CSV upsert."""

from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CatalogProduct

_KEY_MAP = {
    "name": "name",
    "price": "price",
    "costprice": "cost_price",
    "description": "description",
    "category": "category",
    "sku": "sku",
    "brand": "brand",
    "quantity": "quantity",
    "unit": "unit",
    "condition": "condition",
    "imageurl": "image_url",
    "availability": "availability",
}

_STRING_DEFAULTS = {
    "description": "",
    "category": "",
    "sku": "",
    "brand": "",
    "unit": "",
    "condition": "",
    "image_url": "",
}

_SEARCH_FIELDS = ("name", "description", "category", "brand")


class CatalogNotFound(LookupError):
    """Raised when a product id is missing for the calling user."""

    def __init__(self, product_id: uuid.UUID):
        self.product_id = product_id
        super().__init__(f"Product {product_id} not found")


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (key or "").lower())


def _as_uuid(value) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def normalize_product_fields(data: dict | None) -> dict:
    """Map Catalog Builder headers and snake_case keys onto model fields."""
    normalized: dict = {}
    for key, value in (data or {}).items():
        field = _KEY_MAP.get(_norm_key(str(key)))
        if field:
            normalized[field] = value
    return normalized


def _text(fields: dict, key: str, default: str = "") -> str:
    if key not in fields or fields[key] is None:
        return default
    return str(fields[key]).strip()


def _money(value, *, required: bool) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError("price is required")
        return None
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    cleaned = re.sub(r"[^0-9.\-]", "", str(value).replace(",", ""))
    if cleaned in {"", ".", "-", "-."}:
        if required:
            raise ValueError("price is required")
        if value is not None and str(value).strip():
            raise ValueError("invalid number")
        return None
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        if required:
            raise ValueError("price is invalid")
        raise ValueError("invalid number")


def build_search_text(product_fields: dict) -> str:
    """Lexical blob of name, description, category, and brand."""
    fields = normalize_product_fields(product_fields)
    parts: list[str] = []
    for key in _SEARCH_FIELDS:
        text = _text(fields, key)
        if text:
            parts.append(text)
    return " ".join(parts).lower()


def _like_pattern(query: str) -> str:
    escaped = (
        query.strip()
        .lower()
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


class CatalogService:
    """Per-user catalog products stored on CatalogProduct."""

    def _assign(self, product: CatalogProduct, fields: dict, *, creating: bool) -> None:
        """Parse every provided field before mutating so a bad value leaves the row unchanged."""
        values: dict = {}
        if creating or "name" in fields:
            name = _text(fields, "name")
            if not name:
                raise ValueError("name is required")
            values["name"] = name

        if creating or "price" in fields:
            values["price"] = _money(fields.get("price"), required=True)

        for key, default in _STRING_DEFAULTS.items():
            if creating or key in fields:
                values[key] = _text(fields, key, default)

        if creating or "availability" in fields:
            values["availability"] = _text(fields, "availability", "in_stock") or "in_stock"

        if creating or "cost_price" in fields:
            values["cost_price"] = _money(fields.get("cost_price"), required=False)
        if creating or "quantity" in fields:
            values["quantity"] = _money(fields.get("quantity"), required=False)

        for key, value in values.items():
            setattr(product, key, value)

        product.search_text = build_search_text(
            {
                "name": product.name,
                "description": product.description,
                "category": product.category,
                "brand": product.brand,
            }
        )

    async def _find_for_upsert(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        fields: dict,
    ) -> CatalogProduct | None:
        sku = _text(fields, "sku") if "sku" in fields else ""
        if sku:
            result = await db.execute(
                select(CatalogProduct).where(
                    CatalogProduct.user_id == user_id,
                    func.lower(CatalogProduct.sku) == sku.lower(),
                )
            )
            return result.scalars().first()

        name = _text(fields, "name")
        if not name:
            return None
        result = await db.execute(
            select(CatalogProduct).where(
                CatalogProduct.user_id == user_id,
                func.lower(CatalogProduct.name) == name.lower(),
            )
        )
        return result.scalars().first()

    async def _get_owned(
        self,
        db: AsyncSession,
        user_id,
        product_id,
    ) -> CatalogProduct:
        pid = _as_uuid(product_id)
        result = await db.execute(
            select(CatalogProduct).where(
                CatalogProduct.id == pid,
                CatalogProduct.user_id == _as_uuid(user_id),
            )
        )
        product = result.scalar_one_or_none()
        if product is None:
            raise CatalogNotFound(pid)
        return product

    async def create_product(self, db, user_id, data: dict) -> CatalogProduct:
        product = CatalogProduct(user_id=_as_uuid(user_id))
        self._assign(product, normalize_product_fields(data), creating=True)
        db.add(product)
        await db.commit()
        await db.refresh(product)
        return product

    async def update_product(self, db, user_id, product_id, data: dict) -> CatalogProduct:
        product = await self._get_owned(db, user_id, product_id)
        self._assign(product, normalize_product_fields(data), creating=False)
        await db.commit()
        await db.refresh(product)
        return product

    async def delete_product(self, db, user_id, product_id) -> None:
        product = await self._get_owned(db, user_id, product_id)
        await db.delete(product)
        await db.commit()

    async def list_products(
        self,
        db,
        user_id,
        *,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CatalogProduct]:
        stmt = select(CatalogProduct).where(CatalogProduct.user_id == _as_uuid(user_id))
        if q and q.strip():
            stmt = stmt.where(
                func.lower(CatalogProduct.search_text).like(_like_pattern(q), escape="\\")
            )
        stmt = (
            stmt.order_by(CatalogProduct.name.asc(), CatalogProduct.id.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def bulk_upsert_from_rows(self, db, user_id, rows: list[dict]) -> dict:
        created = 0
        updated = 0
        errors: list[dict] = []
        uid = _as_uuid(user_id)

        for index, row in enumerate(rows or []):
            try:
                fields = normalize_product_fields(row)
                if "name" in fields and not _text(fields, "name"):
                    raise ValueError("name is required")
                if "price" in fields:
                    _money(fields.get("price"), required=True)
                existing = await self._find_for_upsert(db, uid, fields)
                if existing is None and not _text(fields, "name"):
                    raise ValueError("name is required")
                if existing is None and "price" not in fields:
                    raise ValueError("price is required")
                if existing is None:
                    product = CatalogProduct(user_id=uid)
                    self._assign(product, fields, creating=True)
                    db.add(product)
                    await db.flush()
                    created += 1
                else:
                    self._assign(existing, fields, creating=False)
                    await db.flush()
                    updated += 1
            except ValueError as exc:
                errors.append({"row": index, "error": str(exc)})

        await db.commit()
        return {"created": created, "updated": updated, "errors": errors}


async def create_product(db, user_id, data: dict) -> CatalogProduct:
    return await CatalogService().create_product(db, user_id, data)


async def update_product(db, user_id, product_id, data: dict) -> CatalogProduct:
    return await CatalogService().update_product(db, user_id, product_id, data)


async def delete_product(db, user_id, product_id) -> None:
    return await CatalogService().delete_product(db, user_id, product_id)


async def list_products(
    db,
    user_id,
    *,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[CatalogProduct]:
    return await CatalogService().list_products(
        db, user_id, q=q, limit=limit, offset=offset
    )


async def bulk_upsert_from_rows(db, user_id, rows: list[dict]) -> dict:
    return await CatalogService().bulk_upsert_from_rows(db, user_id, rows)
