"""Tests for commerce catalog, order, and reservation ORM models."""


def test_commerce_model_tablenames():
    from src.models import CatalogProduct, CommerceOrder, CommerceReservation

    assert CatalogProduct.__tablename__ == "catalog_products"
    assert CommerceOrder.__tablename__ == "commerce_orders"
    assert CommerceReservation.__tablename__ == "commerce_reservations"
