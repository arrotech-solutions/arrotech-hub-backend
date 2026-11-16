"""Merchant catalog CRUD and Catalog Builder CSV upsert."""

from __future__ import annotations

import logging
import re
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CatalogProduct

logger = logging.getLogger(__name__)

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
_LEADING_CURRENCY = re.compile(r"^(?:kes|kshs|ksh|usd|\$)\s*", re.IGNORECASE)
_PLAIN_DECIMAL = re.compile(r"^\d+(\.\d+)?$")


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


def _money_error(required: bool) -> ValueError:
    return ValueError("price is invalid" if required else "invalid number")


def _money(value, *, required: bool) -> Decimal | None:
    """Parse a non-negative decimal. Currency tokens and thousands separators are allowed."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError("price is required")
        return None
    if isinstance(value, Decimal):
        if not value.is_finite() or value < 0:
            raise _money_error(required)
        return value.quantize(Decimal("0.01"))
    text = _LEADING_CURRENCY.sub("", str(value).strip(), count=1)
    text = text.replace(",", "").replace(" ", "")
    if not _PLAIN_DECIMAL.fullmatch(text):
        raise _money_error(required)
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        raise _money_error(required) from None
    if parsed < 0:
        raise _money_error(required)
    return parsed.quantize(Decimal("0.01"))


def build_search_text(product_fields: dict) -> str:
    """Lexical blob of name, description, category, and brand."""
    fields = normalize_product_fields(product_fields)
    parts: list[str] = []
    for key in _SEARCH_FIELDS:
        text = _text(fields, key)
        if text:
            parts.append(text)
    return " ".join(parts).lower()


async def embed_catalog_text(text: str) -> list[float] | None:
    """Create an embedding for catalog search. Fail open to None."""
    blob = (text or "").strip()
    if not blob:
        return None
    try:
        from .openai_service import OpenAIEmbeddingService

        result = await OpenAIEmbeddingService().openai_create_embedding(blob)
        embedding = result.get("embedding") if result.get("success") else None
        if isinstance(embedding, list) and embedding and all(
            isinstance(x, (int, float)) for x in embedding
        ):
            return [float(x) for x in embedding]
    except Exception as exc:
        logger.warning("Catalog embedding failed (continuing without vector): %s", exc)
    return None


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
                select(CatalogProduct)
                .where(
                    CatalogProduct.user_id == user_id,
                    func.lower(CatalogProduct.sku) == sku.lower(),
                )
                .limit(2)
            )
            matches = result.scalars().all()
            if len(matches) > 1:
                raise ValueError("ambiguous sku")
            return matches[0] if matches else None

        name = _text(fields, "name")
        if not name:
            return None
        result = await db.execute(
            select(CatalogProduct)
            .where(
                CatalogProduct.user_id == user_id,
                func.lower(CatalogProduct.name) == name.lower(),
            )
            .limit(2)
        )
        matches = result.scalars().all()
        if len(matches) > 1:
            raise ValueError("ambiguous name")
        return matches[0] if matches else None

    async def _ensure_unique_sku(self, db, user_id, sku: str, *, exclude_id=None) -> None:
        if not (sku or "").strip():
            return
        stmt = select(CatalogProduct.id).where(
            CatalogProduct.user_id == _as_uuid(user_id),
            func.lower(CatalogProduct.sku) == sku.strip().lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(CatalogProduct.id != exclude_id)
        result = await db.execute(stmt.limit(1))
        if result.first() is not None:
            raise ValueError("sku already exists")

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

    async def _refresh_embedding(self, product: CatalogProduct) -> None:
        """Attach a vector for hybrid search; never block CRUD on embed failure."""
        try:
            product.embedding = await embed_catalog_text(product.search_text or product.name or "")
        except Exception as exc:
            logger.warning("Catalog embedding assign failed for %s: %s", product.id, exc)

    async def create_product(self, db, user_id, data: dict) -> CatalogProduct:
        fields = normalize_product_fields(data)
        await self._ensure_unique_sku(
            db, user_id, _text(fields, "sku") if "sku" in fields else ""
        )
        product = CatalogProduct(user_id=_as_uuid(user_id))
        self._assign(product, fields, creating=True)
        await self._refresh_embedding(product)
        db.add(product)
        await db.commit()
        await db.refresh(product)
        return product

    async def update_product(self, db, user_id, product_id, data: dict) -> CatalogProduct:
        product = await self._get_owned(db, user_id, product_id)
        fields = normalize_product_fields(data)
        sku = _text(fields, "sku") if "sku" in fields else (product.sku or "")
        await self._ensure_unique_sku(db, user_id, sku, exclude_id=product.id)
        self._assign(product, fields, creating=False)
        await self._refresh_embedding(product)
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
                    await self._refresh_embedding(product)
                    db.add(product)
                    await db.flush()
                    created += 1
                else:
                    self._assign(existing, fields, creating=False)
                    await self._refresh_embedding(existing)
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
