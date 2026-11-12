"""Smart catalog search: lexical/search_text plus Kenyan slang synonyms.

Default path does not call Pinecone. Embeddings, when already stored on a
product, hybrid-rank with OpenAI query vectors and fail open to lexical.
"""

from __future__ import annotations

import math
import re
import uuid

from sqlalchemy import select

from ..models import CatalogProduct

# Bidirectional groups. soda/coke → Coca-Cola because search_text omits SKU
# and does not contain those slang tokens.
_SYNONYM_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"soda", "coke", "cola", "cocacola", "coca"}),
    frozenset({"chips", "crisps"}),
    frozenset({"mandazi", "maandazi", "doughnut", "donut"}),
    frozenset({"chapati", "chapatti", "roti"}),
    frozenset({"ugali", "sima"}),
    frozenset({"samosa", "sambusa"}),
    frozenset({"chai", "tea"}),
    frozenset({"uji", "porridge"}),
    frozenset({"sukuma", "sukumawiki", "kale"}),
    frozenset({"kuku", "chicken"}),
    frozenset({"nyama", "meat", "beef"}),
    frozenset({"bread", "mkate"}),
    frozenset({"milk", "maziwa"}),
    frozenset({"water", "maji"}),
    frozenset({"rice", "wali", "mchele"}),
    frozenset({"beans", "maharagwe"}),
)

_SYNONYM_MAP: dict[str, frozenset[str]] = {}
for _group in _SYNONYM_GROUPS:
    for _token in _group:
        _SYNONYM_MAP[_token] = _group

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_LEXICAL_WEIGHT = 0.65
_EMBED_WEIGHT = 0.35
_EMBED_MIN = 0.35


def _as_uuid(value) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _expand_query(query: str) -> set[str]:
    q = (query or "").strip().lower()
    terms: set[str] = set()
    if q:
        terms.add(q)
        compact = _compact(q)
        if compact:
            terms.add(compact)
    for tok in _tokens(q):
        if len(tok) < 2:
            continue
        terms.add(tok)
        group = _SYNONYM_MAP.get(tok) or _SYNONYM_MAP.get(_compact(tok))
        if group:
            terms.update(group)
    return terms


def _haystack(product: CatalogProduct) -> str:
    return " ".join(
        part
        for part in (
            product.name,
            product.description,
            product.category,
            product.brand,
            product.search_text,
            product.sku,
        )
        if part
    ).lower()


def _product_tokens(product: CatalogProduct) -> set[str]:
    haystack = _haystack(product)
    tokens = set(_tokens(haystack))
    for part in (product.name, product.brand, product.sku, product.search_text):
        if part and ("-" in part or " " in part):
            compact = _compact(part)
            if compact:
                tokens.add(compact)
    return tokens


def _term_matches(term: str, hay_tokens: set[str]) -> bool:
    if not term:
        return False
    compact_term = _compact(term)
    if term in hay_tokens or compact_term in hay_tokens:
        return True
    if len(compact_term) >= 4:
        return any(
            tok.startswith(compact_term)
            or (compact_term.startswith(tok) and len(tok) >= 4)
            for tok in hay_tokens
        )
    return False


def _lexical_score(query: str, product: CatalogProduct) -> float:
    q = (query or "").strip().lower()
    if not q:
        return 0.0
    haystack = _haystack(product)
    hay_tokens = _product_tokens(product)
    original = [tok for tok in _tokens(q) if len(tok) >= 2]
    if (" " in q or "-" in q) and q in haystack:
        return 1.0
    if q in hay_tokens:
        return 1.0

    orig_hits = 0
    for tok in original:
        synonyms = _SYNONYM_MAP.get(tok) or _SYNONYM_MAP.get(_compact(tok)) or (tok,)
        if any(_term_matches(term, hay_tokens) for term in synonyms):
            orig_hits += 1
    if orig_hits:
        return 0.6 + 0.4 * (orig_hits / max(len(original), 1))

    expanded = _expand_query(q)
    if any(_term_matches(term, hay_tokens) for term in expanded):
        return 0.55
    return 0.0


def _is_vector(value) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(x, (int, float)) for x in value
    )


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_l = math.sqrt(sum(a * a for a in left))
    norm_r = math.sqrt(sum(b * b for b in right))
    if norm_l == 0.0 or norm_r == 0.0:
        return 0.0
    return dot / (norm_l * norm_r)


def _result(product: CatalogProduct, score: float) -> dict:
    return {
        "name": product.name,
        "price": product.price,
        "description": product.description,
        "category": product.category,
        "image_url": product.image_url,
        "availability": product.availability,
        "sku": product.sku,
        "score": score,
    }


async def _query_embedding(query: str) -> list[float] | None:
    try:
        from .openai_service import OpenAIEmbeddingService

        result = await OpenAIEmbeddingService().openai_create_embedding(query)
        embedding = result.get("embedding") if result.get("success") else None
        if _is_vector(embedding):
            return embedding
    except Exception:
        return None
    return None


class CatalogSearchService:
    """Per-user product search ranked by search_text, slang, and optional embeddings."""

    async def search_products(
        self,
        db,
        user_id,
        query: str,
        *,
        top_k: int = 10,
    ) -> list[dict]:
        if top_k <= 0 or not (query or "").strip():
            return []

        result = await db.execute(
            select(CatalogProduct).where(CatalogProduct.user_id == _as_uuid(user_id))
        )
        products = list(result.scalars().all())
        if not products:
            return []

        query_vec = None
        if any(_is_vector(p.embedding) for p in products):
            query_vec = await _query_embedding(query.strip())

        scored: list[tuple[float, CatalogProduct]] = []
        for product in products:
            lexical = _lexical_score(query, product)
            if query_vec is not None and _is_vector(product.embedding):
                cosine = max(_cosine(query_vec, product.embedding), 0.0)
                score = _LEXICAL_WEIGHT * lexical + _EMBED_WEIGHT * cosine
                if lexical <= 0.0 and cosine < _EMBED_MIN:
                    score = 0.0
            else:
                score = lexical
            if score > 0.0:
                scored.append((score, product))

        scored.sort(key=lambda item: (-item[0], (item[1].name or "").lower(), str(item[1].id)))
        return [_result(product, score) for score, product in scored[:top_k]]


async def search_products(db, user_id, query: str, *, top_k: int = 10) -> list[dict]:
    return await CatalogSearchService().search_products(
        db, user_id, query, top_k=top_k
    )
