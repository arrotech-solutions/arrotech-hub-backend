"""Browse-catalog intent detection for WhatsApp menu button / agent search."""

from src.services.catalog_search_service import (
    _expand_query,
    is_browse_all_catalog_query,
)


class TestIsBrowseAllCatalogQuery:
    def test_webhook_browse_message_is_browse_all(self):
        assert is_browse_all_catalog_query(
            "I'd like to browse your catalog/products. Please show me what you have."
        ) is True

    def test_specific_product_query_is_not_browse_all(self):
        assert is_browse_all_catalog_query("what shoes do you have") is False
        assert is_browse_all_catalog_query("chips") is False
        assert is_browse_all_catalog_query("xyzzy-no-match") is False


class TestShoesSynonymGroup:
    def test_shoes_expands_to_footwear(self):
        expanded = _expand_query("shoes")
        assert "footwear" in expanded
        assert "sneakers" in expanded
