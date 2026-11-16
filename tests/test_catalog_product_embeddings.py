"""Catalog products get embeddings on create/update (fail-open)."""

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
async def test_create_product_stores_embedding(db_session, monkeypatch):
    from src.services import catalog_service
    from src.services.catalog_service import CatalogService

    async def fake_embed(text: str):
        assert "nike" in text.lower()
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(catalog_service, "embed_catalog_text", fake_embed)

    user = _user("embed-create@test.com")
    db_session.add(user)
    await db_session.commit()

    created = await CatalogService().create_product(
        db_session,
        user.id,
        {"name": "Nike Air", "Price": "1000", "Category": "Footwear"},
    )

    assert created.embedding == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_create_product_succeeds_when_embed_fails(db_session, monkeypatch):
    from src.services import catalog_service
    from src.services.catalog_service import CatalogService

    async def boom(text: str):
        raise RuntimeError("openai down")

    monkeypatch.setattr(catalog_service, "embed_catalog_text", boom)

    user = _user("embed-fail@test.com")
    db_session.add(user)
    await db_session.commit()

    created = await CatalogService().create_product(
        db_session,
        user.id,
        {"name": "Simba Chips", "Price": "120", "Category": "Snacks"},
    )

    assert created.name == "Simba Chips"
    assert Decimal(created.price) == Decimal("120.00")
    assert created.embedding is None
