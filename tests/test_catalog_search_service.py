"""CatalogSearchService slang and lexical product match."""

import uuid
from decimal import Decimal

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
