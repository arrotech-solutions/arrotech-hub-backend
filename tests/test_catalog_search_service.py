"""CatalogSearchService slang and lexical product match."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from src.models import User


_RESULT_KEYS = {
    "name",
    "price",
    "description",
    "category",
    "image_url",
    "availability",
    "sku",
    "score",
}


@pytest.fixture(autouse=True)
def avoid_external_embeddings(monkeypatch):
    from src.services import catalog_service

    monkeypatch.setattr(
        catalog_service, "embed_catalog_text", AsyncMock(return_value=None)
    )


def _user(email: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        name="Merchant",
        password_hash="hash",
    )


async def _seed_catalog(db_session, email: str, rows: list[dict]):
    from src.services.catalog_service import CatalogService

    user = _user(email)
    db_session.add(user)
    await db_session.commit()
    svc = CatalogService()
    for row in rows:
        await svc.create_product(db_session, user.id, row)
    return user


@pytest.mark.asyncio
async def test_search_chips_returns_simba_chips(db_session):
    """Query chips returns Simba Chips from search_text.

    Fails if lexical ranking misses a name substring.
    """
    from src.services.catalog_search_service import CatalogSearchService

    user = await _seed_catalog(
        db_session,
        "search-chips@test.com",
        [
            {
                "name": "Simba Chips",
                "Price": "120",
                "Description": "Crispy maize snacks",
                "Category": "Snacks",
                "SKU": "SIMBA-50",
                "Brand": "Simba",
                "image_url": "https://cdn.example/simba.jpg",
                "Availability": "in_stock",
            }
        ],
    )

    results = await CatalogSearchService().search_products(
        db_session, user.id, "chips"
    )

    assert [r["name"] for r in results] == ["Simba Chips"]
    assert set(results[0]) == _RESULT_KEYS
    assert Decimal(results[0]["price"]) == Decimal("120.00")
    assert results[0]["sku"] == "SIMBA-50"
    assert results[0]["availability"] == "in_stock"
    assert results[0]["score"] > 0


@pytest.mark.asyncio
async def test_search_soda_or_coke_returns_coca_cola(db_session):
    """Query soda or coke returns Coca-Cola 500ml via Kenyan drink slang.

    Fails if soda/coke is not expanded onto a cola product whose search_text
    has no soda or coke tokens (name+brand only).
    """
    from src.services.catalog_search_service import CatalogSearchService

    user = await _seed_catalog(
        db_session,
        "search-soda@test.com",
        [
            {
                "name": "Coca-Cola 500ml",
                "Price": "80",
                "Category": "Drinks",
                "SKU": "COKE-500",
                "Brand": "Coca-Cola",
            }
        ],
    )
    svc = CatalogSearchService()

    soda = await svc.search_products(db_session, user.id, "soda")
    coke = await svc.search_products(db_session, user.id, "coke")

    assert [r["name"] for r in soda] == ["Coca-Cola 500ml"]
    assert [r["name"] for r in coke] == ["Coca-Cola 500ml"]
    assert set(soda[0]) == _RESULT_KEYS
    assert Decimal(soda[0]["price"]) == Decimal("80.00")
    assert soda[0]["sku"] == "COKE-500"
    assert soda[0]["score"] > 0
    assert coke[0]["score"] > 0


@pytest.mark.asyncio
async def test_search_unknown_query_returns_empty(db_session):
    """Query xyzzy-no-match returns [] even when the catalog has products.

    Fails if an unmatched query still returns a hit or throws.
    """
    from src.services.catalog_search_service import CatalogSearchService

    user = await _seed_catalog(
        db_session,
        "search-nomatch@test.com",
        [
            {
                "name": "Simba Chips",
                "Price": "120",
                "Category": "Snacks",
                "SKU": "SIMBA-50",
            },
            {
                "name": "Coca-Cola 500ml",
                "Price": "80",
                "Category": "Drinks",
                "SKU": "COKE-500",
                "Brand": "Coca-Cola",
            },
        ],
    )

    results = await CatalogSearchService().search_products(
        db_session, user.id, "xyzzy-no-match"
    )

    assert results == []


@pytest.mark.asyncio
async def test_search_cola_does_not_match_chocolate(db_session):
    """Query cola returns Coca-Cola and does not substring-hit Chocolate.

    Fails if 'cola' is treated as a character substring of 'chocolate'.
    """
    from src.services.catalog_search_service import CatalogSearchService

    user = await _seed_catalog(
        db_session,
        "search-cola-chocolate@test.com",
        [
            {
                "name": "Coca-Cola 500ml",
                "Price": "80",
                "Category": "Drinks",
                "SKU": "COLA-500",
                "Brand": "Coca-Cola",
            },
            {
                "name": "Hot Chocolate",
                "Price": "150",
                "Category": "Drinks",
                "SKU": "CHOC-1",
            },
        ],
    )

    results = await CatalogSearchService().search_products(
        db_session, user.id, "cola"
    )

    assert [r["name"] for r in results] == ["Coca-Cola 500ml"]


@pytest.mark.asyncio
async def test_search_products_is_scoped_to_user(db_session):
    """search_products returns only the calling merchant's Simba Chips.

    Fails if user B's row is mixed into A's chips hits, or if A's catalog
    leaks into B's unmatched xyzzy-no-match query.
    """
    from src.services.catalog_search_service import CatalogSearchService

    owner_a = await _seed_catalog(
        db_session,
        "search-tenant-a@test.com",
        [
            {
                "name": "Simba Chips",
                "Price": "120",
                "Category": "Snacks",
                "SKU": "A-CHIPS",
            }
        ],
    )
    owner_b = await _seed_catalog(
        db_session,
        "search-tenant-b@test.com",
        [
            {
                "name": "Simba Chips",
                "Price": "99",
                "Category": "Snacks",
                "SKU": "B-CHIPS",
            }
        ],
    )
    svc = CatalogSearchService()

    a_hits = await svc.search_products(db_session, owner_a.id, "chips")
    assert [r["sku"] for r in a_hits] == ["A-CHIPS"]
    assert Decimal(a_hits[0]["price"]) == Decimal("120.00")

    b_miss = await svc.search_products(db_session, owner_b.id, "xyzzy-no-match")
    assert b_miss == []


@pytest.mark.asyncio
async def test_hybrid_rank_does_not_demote_lexical_hits(db_session, monkeypatch):
    """Closer embedding ranks first; equal-name lexical-only is not sorted below.

    Fails if 0.65*lex+0.35*cos pulls an embedded lexical hit under its
    lexical-only twin, or if a farther vector outranks a closer one.
    """
    from sqlalchemy import select

    from src.models import CatalogProduct
    from src.services import catalog_search_service
    from src.services.catalog_search_service import CatalogSearchService

    async def fake_embed(query: str):
        return [1.0, 0.0]

    monkeypatch.setattr(catalog_search_service, "_query_embedding", fake_embed)

    user = await _seed_catalog(
        db_session,
        "search-hybrid@test.com",
        [
            {"name": "Near Chips", "Price": "10", "Category": "Snacks", "SKU": "NEAR-1"},
            {"name": "Far Chips", "Price": "20", "Category": "Snacks", "SKU": "FAR-EMB"},
            {"name": "Far Chips", "Price": "30", "Category": "Snacks", "SKU": "FAR-LEX"},
        ],
    )
    loaded = await db_session.execute(
        select(CatalogProduct).where(CatalogProduct.user_id == user.id)
    )
    by_sku = {p.sku: p for p in loaded.scalars().all()}
    by_sku["NEAR-1"].embedding = [1.0, 0.0]
    by_sku["FAR-EMB"].embedding = [0.0, 1.0]
    by_sku["FAR-LEX"].embedding = None
    await db_session.commit()

    results = await CatalogSearchService().search_products(
        db_session, user.id, "chips"
    )
    assert results[0]["sku"] == "NEAR-1"
    far = {r["sku"]: r for r in results if r["name"] == "Far Chips"}
    assert set(far) == {"FAR-EMB", "FAR-LEX"}
    assert far["FAR-LEX"]["score"] >= far["FAR-EMB"]["score"]


@pytest.mark.asyncio
async def test_search_empty_catalog_returns_empty(db_session):
    """Empty catalog search returns [] and does not throw.

    Fails if a merchant with no products raises instead of an empty list.
    """
    from src.services.catalog_search_service import CatalogSearchService

    user = _user("search-empty@test.com")
    db_session.add(user)
    await db_session.commit()

    results = await CatalogSearchService().search_products(
        db_session, user.id, "chips"
    )

    assert results == []


@pytest.mark.asyncio
async def test_browse_catalog_query_lists_products_without_name_match(db_session):
    """WhatsApp Browse Catalog button phrasing must list products.

    The webhook sends a sentence like 'browse your catalog/products' which
    does not match product names. That used to return [] and the agent then
    fell through to the human-handoff placeholder.
    """
    from src.services.catalog_search_service import CatalogSearchService

    user = await _seed_catalog(
        db_session,
        "search-browse@test.com",
        [
            {
                "name": "Nike Air Max",
                "Price": "8500",
                "Category": "Footwear",
                "SKU": "NIKE-1",
            },
            {
                "name": "Adidas Samba",
                "Price": "7200",
                "Category": "Footwear",
                "SKU": "ADI-1",
            },
        ],
    )

    results = await CatalogSearchService().search_products(
        db_session,
        user.id,
        "I'd like to browse your catalog/products. Please show me what you have.",
    )

    assert {r["sku"] for r in results} == {"NIKE-1", "ADI-1"}
    assert all(r["score"] > 0 for r in results)


@pytest.mark.asyncio
async def test_search_shoes_matches_footwear_category(db_session):
    """Query shoes returns Footwear-category products via slang expansion."""
    from src.services.catalog_search_service import CatalogSearchService

    user = await _seed_catalog(
        db_session,
        "search-shoes@test.com",
        [
            {
                "name": "Nike Air Max",
                "Price": "8500",
                "Category": "Footwear",
                "SKU": "NIKE-SHOE",
            },
            {
                "name": "Coca-Cola 500ml",
                "Price": "80",
                "Category": "Drinks",
                "SKU": "COKE-500",
                "Brand": "Coca-Cola",
            },
        ],
    )

    results = await CatalogSearchService().search_products(
        db_session, user.id, "what shoes do you have"
    )

    assert [r["sku"] for r in results] == ["NIKE-SHOE"]


@pytest.mark.asyncio
async def test_search_shoes_matches_jordan_sneakers_by_name(db_session):
    """Query shoes matches a product named Jordan sneakers via the footwear group.

    Category is Street so the hit cannot come from a Footwear category token.
    """
    from src.services.catalog_search_service import CatalogSearchService

    user = await _seed_catalog(
        db_session,
        "search-jordan@test.com",
        [
            {
                "name": "Jordan sneakers",
                "Price": "9000",
                "Category": "Street",
                "SKU": "JORDAN-1",
            },
            {
                "name": "Coca-Cola 500ml",
                "Price": "80",
                "Category": "Drinks",
                "SKU": "COKE-500",
            },
        ],
    )

    results = await CatalogSearchService().search_products(
        db_session, user.id, "shoes"
    )

    assert [r["sku"] for r in results] == ["JORDAN-1"]


@pytest.mark.asyncio
async def test_browse_catalog_lists_only_sellable_products(db_session):
    """Browse-all omits out-of-stock rows and rows with quantity 0.

    Quantity None stays listed. Availability "available" counts as in stock.
    Fails if unsellable SKUs are returned with the sellable ones.
    """
    from src.services.catalog_search_service import CatalogSearchService

    user = await _seed_catalog(
        db_session,
        "search-sellable@test.com",
        [
            {
                "name": "Nike Air Max",
                "Price": "8500",
                "Category": "Footwear",
                "SKU": "SELL-1",
                "Availability": "in_stock",
                "quantity": "2",
            },
            {
                "name": "Open Run",
                "Price": "4000",
                "Category": "Footwear",
                "SKU": "OPEN-1",
                "Availability": "available",
            },
            {
                "name": "Zero Stock Samba",
                "Price": "7200",
                "Category": "Footwear",
                "SKU": "ZERO-1",
                "Availability": "in_stock",
                "quantity": "0",
            },
            {
                "name": "Sold Out Puma",
                "Price": "6000",
                "Category": "Footwear",
                "SKU": "OOS-1",
                "Availability": "out_of_stock",
                "quantity": "4",
            },
        ],
    )

    results = await CatalogSearchService().search_products(
        db_session,
        user.id,
        "I'd like to browse your catalog/products. Please show me what you have.",
    )

    assert {r["sku"] for r in results} == {"SELL-1", "OPEN-1"}
