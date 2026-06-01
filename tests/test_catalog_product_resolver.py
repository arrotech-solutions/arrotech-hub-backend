"""Tests for catalog product parsing and image resolution."""

from src.services.catalog_product_resolver import (
    find_catalog_match,
    parse_products_from_rag_results,
    resolve_products_for_cards,
)


def test_parse_single_product_block_with_image():
    chunk = {
        "text": (
            "Cappuccino Double\n"
            "Price: KES 250\n\n"
            "Fresh cappuccino double.\n"
            "https://cdn.example.com/cappuccino-double.jpg"
        )
    }
    products = parse_products_from_rag_results([chunk])
    assert len(products) == 1
    assert products[0]["name"] == "Cappuccino Double"
    assert products[0]["price"] == 250
    assert "cappuccino-double.jpg" in products[0]["image_url"]


def test_resolve_strips_llm_hallucinated_image():
    catalog = [
        {
            "id": "cap-reg",
            "name": "Cappuccino",
            "price": 150,
            "description": "Regular",
            "image_url": "https://cdn.example.com/cappuccino.jpg",
        }
    ]
    llm_products = [
        {
            "id": "cap-reg",
            "name": "Cappuccino",
            "price": 150,
            "description": "Regular",
            "image_url": "https://wrong.example.com/other.jpg",
        }
    ]
    resolved = resolve_products_for_cards(llm_products, catalog)
    assert resolved[0]["image_url"] == "https://cdn.example.com/cappuccino.jpg"


def test_resolve_unknown_product_has_no_image():
    resolved = resolve_products_for_cards(
        [
            {
                "id": "x",
                "name": "Unknown Item",
                "price": 99,
                "image_url": "https://wrong.example.com/x.jpg",
            }
        ],
        [],
    )
    assert resolved[0]["image_url"] == ""


def test_find_catalog_match_by_name():
    catalog = [{"id": "1", "name": "Cappuccino Double", "price": 250, "image_url": ""}]
    match = find_catalog_match({"name": "cappuccino double"}, catalog)
    assert match is not None
    assert match["name"] == "Cappuccino Double"
