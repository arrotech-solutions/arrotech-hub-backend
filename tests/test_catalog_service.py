"""CatalogService CRUD and CSV row upsert."""

import uuid
from decimal import Decimal

import pytest

from src.models import User


def _user(email: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        name="Merchant",
        password_hash="hash",
    )


@pytest.mark.asyncio
async def test_create_and_list_product(db_session):
    """Create persists catalog-builder headers and list is scoped and searchable.

    Fails if create drops Price/Category, list leaks across users, or q ignores search text.
    """
    from src.services.catalog_service import CatalogService

    user = _user("catalog-create@test.com")
    other = _user("catalog-other@test.com")
    db_session.add_all([user, other])
    await db_session.commit()

    created = await CatalogService().create_product(
        db_session,
        user.id,
        {
            "name": "Simba Chips",
            "Price": "120",
            "Cost Price": "80",
            "Description": "Crispy maize snacks",
            "Category": "Snacks",
            "SKU": "SIMBA-50",
            "Brand": "Simba",
            "Quantity": "24",
            "Unit": "pack",
            "Condition": "new",
            "image_url": "https://cdn.example/simba.jpg",
            "Availability": "in_stock",
        },
    )

    assert created.name == "Simba Chips"
    assert Decimal(created.price) == Decimal("120.00")
    assert Decimal(created.cost_price) == Decimal("80.00")
    assert created.description == "Crispy maize snacks"
    assert created.category == "Snacks"
    assert created.sku == "SIMBA-50"
    assert created.brand == "Simba"
    assert Decimal(created.quantity) == Decimal("24.00")
    assert created.unit == "pack"
    assert created.condition == "new"
    assert created.image_url == "https://cdn.example/simba.jpg"
    assert created.availability == "in_stock"
    assert created.user_id == user.id
    assert "simba chips" in created.search_text.lower()
    assert "snacks" in created.search_text.lower()

    listed = await CatalogService().list_products(db_session, user.id)
    assert [p.id for p in listed] == [created.id]

    assert await CatalogService().list_products(db_session, other.id) == []
    snacks = await CatalogService().list_products(db_session, user.id, q="snacks")
    assert [p.id for p in snacks] == [created.id]
    assert await CatalogService().list_products(db_session, user.id, q="xyzzy-no-match") == []


@pytest.mark.asyncio
async def test_bulk_upsert_from_rows_creates_two(db_session):
    """Two catalog rows insert two products and report created=2.

    Fails if header case is ignored incorrectly or the second row is skipped.
    """
    from src.services.catalog_service import CatalogService

    user = _user("catalog-bulk@test.com")
    db_session.add(user)
    await db_session.commit()

    result = await CatalogService().bulk_upsert_from_rows(
        db_session,
        user.id,
        [
            {
                "name": "Coca-Cola 500ml",
                "Price": "80",
                "Category": "Drinks",
                "SKU": "COKE-500",
                "Brand": "Coca-Cola",
            },
            {
                "NAME": "Bread",
                "price": "60",
                "category": "Bakery",
                "sku": "BREAD-1",
            },
        ],
    )

    assert result["created"] == 2
    assert result["updated"] == 0
    assert result["errors"] == []

    listed = await CatalogService().list_products(db_session, user.id)
    assert {p.name for p in listed} == {"Coca-Cola 500ml", "Bread"}
    coke = next(p for p in listed if p.sku == "COKE-500")
    assert Decimal(coke.price) == Decimal("80.00")
    assert coke.category == "Drinks"


@pytest.mark.asyncio
async def test_bulk_upsert_updates_by_sku_and_reports_errors(db_session):
    """Same SKU updates in place; a row without a name is an error, not a product.

    Fails if re-import duplicates SKUs or a bad row aborts the batch.
    """
    from src.services.catalog_service import CatalogService

    user = _user("catalog-upsert@test.com")
    db_session.add(user)
    await db_session.commit()
    svc = CatalogService()

    first = await svc.bulk_upsert_from_rows(
        db_session,
        user.id,
        [{"name": "Coca-Cola 500ml", "Price": "80", "SKU": "COKE-500"}],
    )
    assert first["created"] == 1

    again = await svc.bulk_upsert_from_rows(
        db_session,
        user.id,
        [
            {"name": "Coca-Cola 500ml", "Price": "90", "SKU": "COKE-500", "Category": "Drinks"},
            {"Description": "missing name and price"},
        ],
    )
    assert again["created"] == 0
    assert again["updated"] == 1
    assert len(again["errors"]) == 1
    assert "name" in again["errors"][0]["error"].lower()

    listed = await svc.list_products(db_session, user.id)
    assert len(listed) == 1
    assert Decimal(listed[0].price) == Decimal("90.00")
    assert listed[0].category == "Drinks"

    by_sku_only = await svc.bulk_upsert_from_rows(
        db_session,
        user.id,
        [{"SKU": "COKE-500", "Price": "95"}],
    )
    assert by_sku_only["created"] == 0
    assert by_sku_only["updated"] == 1
    assert by_sku_only["errors"] == []
    listed = await svc.list_products(db_session, user.id)
    assert listed[0].name == "Coca-Cola 500ml"
    assert Decimal(listed[0].price) == Decimal("95.00")


@pytest.mark.asyncio
async def test_update_and_delete_product(db_session):
    """Update rewrites fields and search text; delete removes only that user's row.

    Fails if update leaves a stale search_text or delete crosses tenants.
    """
    from src.services.catalog_service import CatalogNotFound, CatalogService

    owner = _user("catalog-owner@test.com")
    other = _user("catalog-stranger@test.com")
    db_session.add_all([owner, other])
    await db_session.commit()
    svc = CatalogService()

    created = await svc.create_product(
        db_session,
        owner.id,
        {"name": "Mandazi", "Price": "20", "Category": "Bakery"},
    )
    updated = await svc.update_product(
        db_session,
        owner.id,
        created.id,
        {"Price": "25", "Category": "Snacks"},
    )
    assert Decimal(updated.price) == Decimal("25.00")
    assert updated.category == "Snacks"
    assert updated.name == "Mandazi"
    assert "snacks" in updated.search_text.lower()
    assert "mandazi" in updated.search_text.lower()

    with pytest.raises(CatalogNotFound):
        await svc.update_product(db_session, other.id, created.id, {"Price": "1"})

    with pytest.raises(CatalogNotFound):
        await svc.delete_product(db_session, other.id, created.id)

    still_there = await svc.list_products(db_session, owner.id)
    assert [p.id for p in still_there] == [created.id]

    await svc.delete_product(db_session, owner.id, created.id)
    assert await svc.list_products(db_session, owner.id) == []


def test_build_search_text_includes_name_and_category():
    """Search text contains the product name and category from builder headers.

    Fails if name or category is omitted from the lexical blob.
    """
    from src.services.catalog_service import build_search_text

    text = build_search_text(
        {
            "name": "Simba Chips",
            "Description": "Crispy maize",
            "Category": "Snacks",
            "Brand": "Simba",
        }
    )
    lowered = text.lower()
    assert "simba chips" in lowered
    assert "snacks" in lowered
    assert "crispy maize" in lowered
    assert "simba" in lowered


def _stored_product(user_id, *, name: str, sku: str, price: str) -> "CatalogProduct":
    from src.models import CatalogProduct

    return CatalogProduct(
        user_id=user_id,
        name=name,
        price=Decimal(price),
        description="",
        category="",
        sku=sku,
        brand="",
        unit="",
        condition="",
        image_url="",
        availability="in_stock",
        search_text=name.lower(),
    )


@pytest.mark.asyncio
async def test_bulk_upsert_parses_currency_and_rejects_prose_amounts(db_session):
    """Currency amounts parse; prose amounts are errors and are not stored.

    Fails if digits are concatenated (`2 for 100` → 2100, `120 (was 150)` → 120150).
    """
    from src.services.catalog_service import CatalogService

    user = _user("catalog-money@test.com")
    db_session.add(user)
    await db_session.commit()
    svc = CatalogService()

    result = await svc.bulk_upsert_from_rows(
        db_session,
        user.id,
        [
            {"name": "Rice", "Price": "KES 1,250.50", "SKU": "RICE-1"},
            {"name": "Offer", "Price": "2 for 100", "SKU": "OFFER-1"},
            {"name": "Was", "Price": "120 (was 150)", "SKU": "WAS-1"},
        ],
    )

    assert result["created"] == 1
    assert result["updated"] == 0
    assert result["errors"] == [
        {"row": 1, "error": "price is invalid"},
        {"row": 2, "error": "price is invalid"},
    ]
    listed = await svc.list_products(db_session, user.id)
    assert [p.name for p in listed] == ["Rice"]
    assert Decimal(listed[0].price) == Decimal("1250.50")

    with pytest.raises(ValueError, match="price is invalid"):
        await svc.create_product(
            db_session,
            user.id,
            {"name": "Refund", "Price": Decimal("-1"), "SKU": "NEG-1"},
        )
    listed = await svc.list_products(db_session, user.id)
    assert [p.name for p in listed] == ["Rice"]

    free = await svc.create_product(
        db_session,
        user.id,
        {"name": "Sample", "Price": Decimal("0"), "SKU": "FREE-1"},
    )
    assert Decimal(free.price) == Decimal("0.00")


@pytest.mark.asyncio
async def test_bulk_upsert_rejects_ambiguous_sku_and_name(db_session):
    """More than one SKU or name match is an error and does not change either row.

    Fails if upsert picks an arbitrary duplicate and writes a new price.
    """
    from src.services.catalog_service import CatalogService

    user = _user("catalog-ambiguous@test.com")
    db_session.add(user)
    await db_session.commit()
    db_session.add_all(
        [
            _stored_product(user.id, name="Cola A", sku="DUP-SKU", price="10.00"),
            _stored_product(user.id, name="Cola B", sku="DUP-SKU", price="11.00"),
            _stored_product(user.id, name="Chapati", sku="", price="20.00"),
            _stored_product(user.id, name="Chapati", sku="", price="21.00"),
        ]
    )
    await db_session.commit()
    svc = CatalogService()

    result = await svc.bulk_upsert_from_rows(
        db_session,
        user.id,
        [
            {"name": "Ignored", "Price": "999", "SKU": "DUP-SKU"},
            {"name": "Chapati", "Price": "50"},
        ],
    )

    assert result["created"] == 0
    assert result["updated"] == 0
    assert result["errors"] == [
        {"row": 0, "error": "ambiguous sku"},
        {"row": 1, "error": "ambiguous name"},
    ]
    listed = await svc.list_products(db_session, user.id)
    prices = {p.name: Decimal(p.price) for p in listed}
    assert prices["Cola A"] == Decimal("10.00")
    assert prices["Cola B"] == Decimal("11.00")
    chapati = [Decimal(p.price) for p in listed if p.name == "Chapati"]
    assert sorted(chapati) == [Decimal("20.00"), Decimal("21.00")]


@pytest.mark.asyncio
async def test_create_and_update_reject_duplicate_sku(db_session):
    """A non-empty SKU already used by this user is rejected and not saved.

    Fails if a second product silently takes the same SKU.
    """
    from src.services.catalog_service import CatalogService

    user = _user("catalog-sku@test.com")
    other = _user("catalog-sku-other@test.com")
    db_session.add_all([user, other])
    await db_session.commit()
    svc = CatalogService()

    original = await svc.create_product(
        db_session,
        user.id,
        {"name": "Coca-Cola 500ml", "Price": "80", "SKU": "COKE-500"},
    )
    with pytest.raises(ValueError):
        await svc.create_product(
            db_session,
            user.id,
            {"name": "Coke Copy", "Price": "81", "SKU": "coke-500"},
        )
    listed = await svc.list_products(db_session, user.id)
    assert [p.name for p in listed] == ["Coca-Cola 500ml"]

    other_product = await svc.create_product(
        db_session,
        other.id,
        {"name": "Their Coke", "Price": "70", "SKU": "COKE-500"},
    )
    assert other_product.sku == "COKE-500"

    second = await svc.create_product(
        db_session,
        user.id,
        {"name": "Bread", "Price": "60", "SKU": "BREAD-1"},
    )
    with pytest.raises(ValueError):
        await svc.update_product(
            db_session,
            user.id,
            second.id,
            {"SKU": "COKE-500", "Price": "61"},
        )
    listed = await svc.list_products(db_session, user.id)
    bread = next(p for p in listed if p.id == second.id)
    assert bread.sku == "BREAD-1"
    assert Decimal(bread.price) == Decimal("60.00")

    kept = await svc.update_product(
        db_session,
        user.id,
        original.id,
        {"SKU": "COKE-500", "Price": "85"},
    )
    assert kept.sku == "COKE-500"
    assert Decimal(kept.price) == Decimal("85.00")
