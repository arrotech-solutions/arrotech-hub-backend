"""
Parse catalog products from RAG chunks and resolve card payloads against KB data.

Images must never come from LLM guesses — only from the same KB chunk/block as the product.
"""

from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MARKDOWN_IMAGE_PATTERN = re.compile(
    r"!\[([^\]]*)\]\((https?://[^\s\)]+)\)", re.IGNORECASE
)
_IMAGE_EXT_PATTERN = re.compile(
    r"https?://[^\s<>\"']+\.(?:jpg|jpeg|png|webp|gif)(?:\?[^\s<>\"']*)?",
    re.IGNORECASE,
)


def _extract_image_urls(text: str) -> List[str]:
    if not text:
        return []
    seen: set = set()
    urls: List[str] = []

    def _add(url: str) -> None:
        url = url.rstrip(".,;:!?)\"']")
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    for match in _MARKDOWN_IMAGE_PATTERN.finditer(text):
        _add(match.group(2))
    for match in _IMAGE_EXT_PATTERN.finditer(text):
        _add(match.group(0))
    return urls

_PRICE_RE = re.compile(
    r"(?:price|cost|kes|ksh)[:\s]*(?:KES|KSH|USD|\$)?\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_PRICE_INLINE_RE = re.compile(
    r"(?:KES|KSH)\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_ID_RE = re.compile(
    r"(?:product[_\s]?id|item[_\s]?id|sku|code)[:\s#]*([A-Za-z0-9][\w\-]*)",
    re.IGNORECASE,
)
_NUMBERED_LINE_RE = re.compile(r"^\s*\d+[\.\)]\s+(.+)$", re.MULTILINE)
_SKIP_NAME_PREFIXES = (
    "price",
    "description",
    "image",
    "photo",
    "sku",
    "product id",
    "item id",
    "http",
    "www.",
    "source:",
    "file:",
)


def _parse_price(text: str) -> float:
    match = _PRICE_RE.search(text)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            pass
    match = _PRICE_INLINE_RE.search(text)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            pass
    return 0.0


def _slug_id(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", (name or "item").lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug[:80] or "item"


def _normalize_product(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = (
        raw.get("name")
        or raw.get("product_name")
        or raw.get("title")
        or ""
    )
    if isinstance(name, str):
        name = name.strip()
    if not name:
        return None

    price = raw.get("price", raw.get("unit_price", 0))
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = _parse_price(str(raw.get("description", "")))

    image = (
        raw.get("image_url")
        or raw.get("image")
        or raw.get("photo_url")
        or raw.get("thumbnail")
        or raw.get("media_url")
        or ""
    )
    if isinstance(image, list):
        image = image[0] if image else ""
    image = str(image or "").strip()
    if image and not image.startswith("http"):
        image = ""

    product_id = str(
        raw.get("id")
        or raw.get("product_id")
        or raw.get("sku")
        or _slug_id(name)
    ).strip()

    description = str(raw.get("description", "") or "").strip()[:500]

    return {
        "id": product_id,
        "name": name[:200],
        "price": round(price, 2) if price else 0.0,
        "description": description,
        "image_url": image,
    }


def _try_json_products(text: str) -> List[Dict[str, Any]]:
    products: List[Dict[str, Any]] = []
    text = text.strip()
    if not text:
        return products

    candidates = [text]
    # Extract embedded JSON objects/arrays
    for match in re.finditer(r"(\{[^{}]*\}|\[[^\[\]]*\])", text, re.DOTALL):
        candidates.append(match.group(1))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            if any(k in parsed for k in ("name", "product_name", "title", "price")):
                norm = _normalize_product(parsed)
                if norm:
                    products.append(norm)
        elif isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    norm = _normalize_product(item)
                    if norm:
                        products.append(norm)
    return products


def _parse_line_product(line: str) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line or len(line) < 2:
        return None

    urls = _extract_image_urls(line)
    image_url = urls[0] if len(urls) == 1 else ""
    line_no_url = line
    for url in urls:
        line_no_url = line_no_url.replace(url, " ").strip()

    price = _parse_price(line_no_url)
    id_match = _ID_RE.search(line_no_url)
    product_id = id_match.group(1) if id_match else ""

    name_part = line_no_url
    for prefix in ("price:", "cost:", "description:"):
        idx = name_part.lower().find(prefix)
        if idx > 0:
            name_part = name_part[:idx].strip()

    name_part = re.sub(
        r"\s*[-–—]\s*(?:KES|KSH|USD)?\s*[\d,]+(?:\.\d+)?\s*$",
        "",
        name_part,
        flags=re.IGNORECASE,
    ).strip(" -*•")

    if not name_part:
        return None
    lower = name_part.lower()
    if any(lower.startswith(p) for p in _SKIP_NAME_PREFIXES):
        return None

    if price <= 0 and not product_id:
        return None

    return _normalize_product(
        {
            "id": product_id or _slug_id(name_part),
            "name": name_part,
            "price": price,
            "description": "",
            "image_url": image_url,
        }
    )


def _parse_product_block(block: str) -> List[Dict[str, Any]]:
    block = block.strip()
    if not block or block == "NO_CONTENT_HERE":
        return []

    json_products = _try_json_products(block)
    if json_products:
        return json_products

    # Numbered list: one product per line
    numbered = _NUMBERED_LINE_RE.findall(block)
    if numbered and len(numbered) >= 2:
        line_products = []
        for line in numbered:
            parsed = _parse_line_product(line)
            if parsed:
                line_products.append(parsed)
        if line_products:
            return line_products

    # Single product block — bind at most one image from this block
    block_urls = _extract_image_urls(block)
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]

    name = ""
    description_lines: List[str] = []
    for line in lines:
        lower = line.lower()
        if _extract_image_urls(line):
            continue
        if lower.startswith(_SKIP_NAME_PREFIXES) or lower.startswith("price:"):
            continue
        if not name and not lower.startswith(("source", "file", "---")):
            name = line.strip("*# ")
            continue
        if name:
            description_lines.append(line)

    if not name:
        return []

    price = _parse_price(block)
    id_match = _ID_RE.search(block)
    product_id = id_match.group(1) if id_match else _slug_id(name)
    image_url = block_urls[0] if len(block_urls) == 1 else ""

    if len(block_urls) > 1:
        # Multiple images in one block — only attach if a URL is on the same line as the name
        for line in lines:
            if name.lower() in line.lower():
                line_urls = _extract_image_urls(line)
                if len(line_urls) == 1:
                    image_url = line_urls[0]
                    break
        else:
            image_url = ""

    product = _normalize_product(
        {
            "id": product_id,
            "name": name,
            "price": price,
            "description": " ".join(description_lines)[:500],
            "image_url": image_url,
        }
    )
    return [product] if product else []


def parse_products_from_rag_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract products from raw RAG chunks; each image stays with its chunk/block."""
    if not results:
        return []

    all_products: List[Dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "") or "")
        chunk_products = _parse_product_block(text)
        if not chunk_products:
            # Try line-by-line for dense menus
            for line in text.splitlines():
                parsed = _parse_line_product(line)
                if parsed:
                    chunk_products.append(parsed)

        # Chunk-level metadata from ingestion (if present)
        meta_image = (
            item.get("image_url")
            or item.get("image")
            or item.get("thumbnail")
            or ""
        )
        if isinstance(meta_image, str) and meta_image.startswith("http"):
            if len(chunk_products) == 1 and not chunk_products[0].get("image_url"):
                chunk_products[0]["image_url"] = meta_image

        all_products.extend(chunk_products)

    return dedupe_catalog_products(all_products)


def dedupe_catalog_products(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge duplicates by id or normalized name; prefer entry with image."""
    by_key: Dict[str, Dict[str, Any]] = {}
    for product in products:
        if not product or not product.get("name"):
            continue
        key = str(product.get("id") or _slug_id(product["name"])).lower()
        name_key = product["name"].strip().lower()
        existing = by_key.get(key) or by_key.get(name_key)
        if not existing:
            by_key[key] = product
            continue
        if not existing.get("image_url") and product.get("image_url"):
            by_key[key] = product
        elif product.get("price") and not existing.get("price"):
            existing["price"] = product["price"]
    return list(by_key.values())


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def find_catalog_match(
    product: Dict[str, Any],
    catalog: List[Dict[str, Any]],
    min_similarity: float = 0.82,
) -> Optional[Dict[str, Any]]:
    if not catalog:
        return None

    pid = str(product.get("id") or "").strip().lower()
    name = str(product.get("name") or "").strip()
    name_lower = name.lower()

    for entry in catalog:
        entry_id = str(entry.get("id") or "").strip().lower()
        if pid and entry_id and pid == entry_id:
            return entry
        if name_lower and entry.get("name", "").strip().lower() == name_lower:
            return entry

    best: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for entry in catalog:
        score = _name_similarity(name, entry.get("name", ""))
        if score > best_score:
            best_score = score
            best = entry
    if best_score >= min_similarity:
        return best
    return None


def resolve_products_for_cards(
    llm_products: List[Dict[str, Any]],
    catalog: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Build card payloads from catalog truth. LLM image_url is never trusted.
  """
    if not llm_products:
        return []

    resolved: List[Dict[str, Any]] = []
    for raw in llm_products:
        if not isinstance(raw, dict):
            continue
        match = find_catalog_match(raw, catalog)
        if match:
            resolved.append(
                {
                    "id": match.get("id") or raw.get("id", ""),
                    "name": match.get("name") or raw.get("name", "Product"),
                    "price": float(match.get("price") or raw.get("price") or 0),
                    "description": (
                        match.get("description")
                        or raw.get("description", "")
                    )[:500],
                    "image_url": match.get("image_url", "") or "",
                }
            )
            continue

        # No catalog match — text-only card (no hallucinated image)
        llm_image = str(raw.get("image_url", "") or "").strip()
        if llm_image:
            logger.warning(
                "[CATALOG] Dropping unverified image for unknown product: %s",
                raw.get("name"),
            )
        resolved.append(
            {
                "id": str(raw.get("id") or _slug_id(str(raw.get("name", "item")))),
                "name": str(raw.get("name", "Product")),
                "price": float(raw.get("price", 0) or 0),
                "description": str(raw.get("description", ""))[:500],
                "image_url": "",
            }
        )
    return resolved


def format_catalog_for_agent(products: List[Dict[str, Any]], currency: str = "KES") -> str:
    if not products:
        return "No structured products were found in the knowledge base for this search."

    lines = [
        f"Catalog matches ({len(products)}). Use these exact ids and names in display_product_cards.",
        "Leave image_url as empty string — the system attaches verified images automatically.",
        "",
    ]
    for i, p in enumerate(products[:10], 1):
        price = p.get("price", 0)
        price_str = f"{currency} {price:,.0f}" if price else "price on request"
        has_img = "yes" if p.get("image_url") else "no"
        lines.append(
            f"{i}. id={p.get('id')} | name={p.get('name')} | price={price_str} "
            f"| image_in_catalog={has_img}"
        )
        if p.get("description"):
            lines.append(f"   description: {p['description'][:120]}")
    return "\n".join(lines)
