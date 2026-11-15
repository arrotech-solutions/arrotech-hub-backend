"""Browse-catalog intent detection for WhatsApp menu button / agent search."""

from src.services.catalog_search_service import _expand_query


def _is_browse_all(query: str) -> bool:
    from src.services.catalog_search_service import is_browse_all_catalog_query

    return is_browse_all_catalog_query(query)


class TestIsBrowseAllCatalogQuery:
    def test_webhook_browse_message_is_browse_all(self):
        assert _is_browse_all(
            "I'd like to browse your catalog/products. Please show me what you have."
        ) is True

    def test_specific_product_query_is_not_browse_all(self):
        assert _is_browse_all("what shoes do you have") is False
        assert _is_browse_all("chips") is False
        assert _is_browse_all("xyzzy-no-match") is False


class TestShoesSynonymGroup:
    def test_shoes_expands_to_footwear(self):
        expanded = _expand_query("shoes")
        assert "footwear" in expanded
        assert "sneakers" in expanded
