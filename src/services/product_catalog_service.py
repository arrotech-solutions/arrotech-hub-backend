"""
Structured product catalog — exact identity binding for WhatsApp ordering.

One product row = one record with stable product_id/sku, name, price, image_url.
Used for sheet-direct listing and exact image resolution (no fuzzy cross-binding).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_BROWSE_QUERY_RE = re.compile(
    r"(?:\b(?:catalog|catalogue|all products|show(?: me)?(?: your)? products|"
    r"browse|what do you (?:have|sell)|menu|collection|everything|"
    r"full list|see (?:all|everything))\b)",
    re.IGNORECASE,
)

_IMAGE_COL_ALIASES = {
    "imageurl", "image", "photo", "photourl", "picture", "pictureurl",
    "thumbnail", "thumbnailurl", "img", "imgurl", "productimage",
    "productphoto", "mediaurl", "media", "itemimage", "menuimage",
}

_NAME_ALIASES = {
    "name", "productname", "product", "item", "itemname",
    "title", "menuitem", "dish", "service",
}

_SKU_ALIASES = {"sku", "productsku", "itemsku", "code", "productcode", "itemcode"}

_PRICE_ALIASES = {"price", "cost", "bei", "amount", "unitprice"}


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


def normalize_product_name(value: str) -> str:
    """Lowercase, strip emojis, collapse whitespace."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(
        r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0000FE00-\U0000FE0F"
        r"\U0000200D\U0001F1E0-\U0001F1FF]+",
        "",
        text,
    )
    return re.sub(r"\s+", " ", text.strip().lower())


class ProductCatalogService:
    """Exact-match product catalog operations."""

    @classmethod
    def is_browse_query(cls, query: str) -> bool:
        return bool(_BROWSE_QUERY_RE.search(query or ""))

    @classmethod
    def parse_sheet_rows(
        cls,
        rows: List[List[Any]],
        source_id: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Parse spreadsheet rows into structured product records.
        Skips rows without a valid HTTP image URL (prevents half-broken vectors).
        """
        records: List[Dict[str, Any]] = []
        if not rows or len(rows) < 2:
            return records

        header = [str(h).strip() for h in rows[0]]
        norm_header = [_norm_header(h) for h in header]

        name_idx = next((i for i, h in enumerate(norm_header) if h in _NAME_ALIASES), None)
        sku_idx = next((i for i, h in enumerate(norm_header) if h in _SKU_ALIASES), None)
        price_idx = next((i for i, h in enumerate(norm_header) if h in _PRICE_ALIASES), None)
        image_indices = {i for i, nh in enumerate(norm_header) if nh in _IMAGE_COL_ALIASES}

        for row_num, row in enumerate(rows[1:], start=2):
            if not any(str(c).strip() for c in row):
                continue

            product_name = ""
            if name_idx is not None and name_idx < len(row):
                product_name = str(row[name_idx]).strip()
            if not product_name:
                logger.warning("Catalog row %s skipped: missing product name", row_num)
                continue

            sku = ""
            if sku_idx is not None and sku_idx < len(row):
                sku = str(row[sku_idx]).strip()

            price = 0.0
            if price_idx is not None and price_idx < len(row):
                val = str(row[price_idx]).strip()
                num_m = re.search(r"[\d,]+\.?\d*", val.replace(",", ""))
                if num_m:
                    try:
                        price = float(num_m.group())
                    except ValueError:
                        pass

            image_url = ""
            for i in image_indices:
                if i < len(row):
                    val = str(row[i]).strip()
                    if val.startswith("http://") or val.startswith("https://"):
                        image_url = val
                        break

            if not image_url:
                logger.warning(
                    "Catalog row %s skipped: no image_url for '%s'",
                    row_num,
                    product_name,
                )
                continue

            product_id = sku or f"{source_id}_row_{row_num}".strip("_")

            lines = [product_name]
            desc_parts: List[str] = []
            for i, cell in enumerate(row):
                val = str(cell).strip()
                if not val or i == name_idx or i in image_indices:
                    continue
                if i == sku_idx or i == price_idx:
                    continue
                label = header[i] if i < len(header) and header[i] else f"Column {i + 1}"
                desc_parts.append(f"{label}: {val}")

            if price_idx is not None and price_idx < len(row) and str(row[price_idx]).strip():
                lines.append(f"Price: {str(row[price_idx]).strip()}")
            for part in desc_parts:
                lines.append(part)
            lines.append(f"SKU: {sku}" if sku else f"Product ID: {product_id}")
            lines.append(f"![{product_name}]({image_url})")

            records.append({
                "text": "\n".join(lines),
                "product_name": product_name,
                "sku": sku,
                "product_id": product_id,
                "row_index": row_num,
                "image_url": image_url,
                "price": price,
                "description": " | ".join(desc_parts[:3]),
            })

        return records

    @classmethod
    def _extract_spreadsheet_id(cls, config: Dict[str, Any]) -> str:
        if not config:
            return ""
        if config.get("spreadsheet_id"):
            return str(config["spreadsheet_id"]).strip()
        for key in ("file_id", "url"):
            val = str(config.get(key) or "").strip()
            if not val:
                continue
            m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", val)
            if m:
                return m.group(1)
            if key == "file_id" and val:
                return val
        return ""

    @classmethod
    async def list_from_kb(
        cls,
        kb_id: str,
        user: Any,
        db: Any,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Read catalog products directly from the KB's Google Sheet data source.
        Bypasses vector search for browse/catalog queries.
        """
        import uuid
        from sqlalchemy import select
        from ..models import DataSource

        kb_uuid = uuid.UUID(str(kb_id))
        result = await db.execute(
            select(DataSource).filter(
                DataSource.kb_id == kb_uuid,
                DataSource.status == "active",
            )
        )
        sources = result.scalars().all()
        sheet_types = {"google_sheets", "google_workspace_sheets", "google_drive"}
        sheet_sources = [s for s in sources if s.source_type in sheet_types]

        from .tool_executor import ToolExecutor
        executor = ToolExecutor()

        all_records: List[Dict[str, Any]] = []
        for source in sheet_sources:
            config = source.config or {}
            spreadsheet_id = cls._extract_spreadsheet_id(config)
            if not spreadsheet_id:
                continue
            res = await executor.execute_tool(
                "google_workspace_sheets",
                {
                    "operation": "read_range",
                    "spreadsheet_id": spreadsheet_id,
                    "range_name": "A:Z",
                },
                user,
                db,
            )
            if not res.get("success"):
                continue
            rows = res.get("values")
            if rows is None and isinstance(res.get("data"), dict):
                rows = res["data"].get("values")
            records = cls.parse_sheet_rows(rows or [], source_id=str(source.id))
            all_records.extend(records)
            if len(all_records) >= limit:
                break

        return all_records[:limit]

    @classmethod
    def records_to_display_products(cls, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert structured records to display_product_cards format."""
        products: List[Dict[str, Any]] = []
        for rec in records:
            pid = rec.get("product_id") or rec.get("sku") or ""
            products.append({
                "id": pid,
                "name": rec.get("product_name", ""),
                "price": rec.get("price", 0),
                "description": rec.get("description", ""),
                "image_url": rec.get("image_url", ""),
                "sku": rec.get("sku", ""),
                "product_id": pid,
            })
        return products

    @classmethod
    def build_index_from_search_results(
        cls, results: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Build lookup index keyed by normalized product_name and sku."""
        index: Dict[str, Dict[str, Any]] = {}
        for item in results:
            if not isinstance(item, dict):
                continue
            meta_name = normalize_product_name(item.get("product_name") or "")
            image_url = (item.get("image_url") or "").strip()
            sku = (item.get("sku") or "").strip().lower()
            product_id = (item.get("product_id") or "").strip()
            chunk_text = item.get("text") or ""

            if not image_url:
                urls = item.get("image_urls") or []
                if isinstance(urls, list) and urls:
                    image_url = urls[0]

            if cls._is_multi_product_chunk(chunk_text):
                continue

            if not meta_name or not image_url:
                continue

            record = {
                "name": item.get("product_name") or meta_name,
                "image_url": image_url,
                "sku": item.get("sku") or "",
                "product_id": product_id,
                "vector_id": item.get("vector_id") or "",
                "price": item.get("price", 0),
            }
            index[meta_name] = record
            if sku:
                index[f"sku:{sku}"] = record
            if product_id:
                index[f"id:{product_id.lower()}"] = record

        return index

    @classmethod
    def _is_multi_product_chunk(cls, chunk_text: str) -> bool:
        """Detect summary chunks listing multiple products."""
        if not chunk_text:
            return False
        md_images = re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", chunk_text)
        if len(md_images) > 1:
            alts = {normalize_product_name(a) for a, _ in md_images if a.strip()}
            if len(alts) > 1:
                return True
        price_lines = len(re.findall(r"^\s*Price\s*:", chunk_text, re.MULTILINE | re.IGNORECASE))
        return price_lines > 1

    @classmethod
    def resolve_from_index(
        cls,
        name: str,
        sku: str,
        index: Dict[str, Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Exact lookup only — no fuzzy substring matching."""
        if sku:
            hit = index.get(f"sku:{sku.strip().lower()}")
            if hit:
                return hit
        norm = normalize_product_name(name)
        if norm:
            return index.get(norm)
        return None

    @classmethod
    def enrich_products(
        cls,
        products: List[Dict[str, Any]],
        search_results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Bind each product's image_url from exact catalog index match.
        Clears image if no exact match.
        """
        index = cls.build_index_from_search_results(search_results)
        enriched: List[Dict[str, Any]] = []

        for product in products:
            p = dict(product)
            name = p.get("name", "")
            sku = p.get("sku", "")
            resolved = cls.resolve_from_index(name, sku, index)

            if resolved:
                p["image_url"] = resolved["image_url"]
                p["sku"] = resolved.get("sku") or p.get("sku", "")
                p["product_id"] = resolved.get("product_id") or p.get("product_id", "")
                if not p.get("id") or str(p.get("id", "")).startswith("prod_"):
                    p["id"] = resolved.get("product_id") or p.get("id", "")
                logger.info(
                    "[CATALOG] Bound '%s' → image via exact match (product_id=%s)",
                    name,
                    p.get("product_id"),
                )
            else:
                meta_name = normalize_product_name(name)
                chunk_match = None
                for item in search_results:
                    if not isinstance(item, dict):
                        continue
                    if normalize_product_name(item.get("product_name", "")) == meta_name:
                        if not cls._is_multi_product_chunk(item.get("text", "")):
                            chunk_match = item
                            break
                if chunk_match and chunk_match.get("image_url"):
                    p["image_url"] = chunk_match["image_url"]
                    p["product_id"] = chunk_match.get("product_id") or p.get("product_id", "")
                    p["sku"] = chunk_match.get("sku") or p.get("sku", "")
                    if not p.get("id") or str(p.get("id", "")).startswith("prod_"):
                        p["id"] = p.get("product_id") or p.get("id", "")
                    logger.info("[CATALOG] Bound '%s' → image via chunk metadata", name)
                else:
                    p["image_url"] = ""
                    logger.warning(
                        "[CATALOG] Cleared unverified image for '%s' (no exact match)",
                        name,
                    )

            enriched.append(p)

        return enriched

    @classmethod
    def validate_records(cls, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Audit catalog records for inconsistencies."""
        issues: List[Dict[str, Any]] = []
        names_seen: Dict[str, int] = {}

        for rec in records:
            name = rec.get("product_name", "")
            norm = normalize_product_name(name)
            if norm in names_seen:
                issues.append({
                    "type": "duplicate_name",
                    "product_name": name,
                    "row_index": rec.get("row_index"),
                })
            names_seen[norm] = rec.get("row_index", 0)

            if not rec.get("image_url"):
                issues.append({
                    "type": "missing_image",
                    "product_name": name,
                    "row_index": rec.get("row_index"),
                })

            if name and rec.get("text") and rec.get("image_url"):
                alt_in_text = re.search(
                    rf"!\[{re.escape(name)}\]\(([^)]+)\)",
                    rec.get("text", ""),
                )
                if alt_in_text and alt_in_text.group(1).strip() != rec["image_url"].strip():
                    issues.append({
                        "type": "alt_text_mismatch",
                        "product_name": name,
                        "row_index": rec.get("row_index"),
                    })

        return {
            "total_products": len(records),
            "issue_count": len(issues),
            "issues": issues,
            "healthy": len(issues) == 0,
        }

    @classmethod
    async def validate_kb_catalog(
        cls,
        kb_id: str,
        user: Any,
        db: Any,
    ) -> Dict[str, Any]:
        """Validate all catalog rows from KB sheet sources."""
        records = await cls.list_from_kb(kb_id=kb_id, user=user, db=db, limit=500)
        report = cls.validate_records(records)
        report["kb_id"] = kb_id
        report["source"] = "google_sheet"
        return report


product_catalog_service = ProductCatalogService()
