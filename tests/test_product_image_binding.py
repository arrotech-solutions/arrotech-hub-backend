"""Tests for product catalog exact image binding."""

import pytest

from src.services.product_catalog_service import ProductCatalogService
from src.services.conversational_agent_service import ConversationalAgentService


SOFA_IMAGE = "https://example.com/sofa.jpg"
CHAIR_IMAGE = "https://example.com/chair.jpg"


def _sample_sheet_rows():
    return [
        ["Name", "Price", "Image URL", "SKU"],
        ["Luxury Sofa", "45000", SOFA_IMAGE, "SOFA-001"],
        ["Office Chair", "12000", CHAIR_IMAGE, "CHAIR-001"],
    ]


class TestProductCatalogService:
    def test_parse_sheet_rows_one_record_per_product(self):
        records = ProductCatalogService.parse_sheet_rows(_sample_sheet_rows(), source_id="sheet1")
        assert len(records) == 2
        assert records[0]["product_name"] == "Luxury Sofa"
        assert records[0]["image_url"] == SOFA_IMAGE
        assert records[0]["sku"] == "SOFA-001"
        assert records[1]["product_name"] == "Office Chair"
        assert records[1]["image_url"] == CHAIR_IMAGE

    def test_parse_sheet_rows_skips_missing_image(self):
        rows = [
            ["Name", "Price", "Image URL"],
            ["No Image Product", "1000", ""],
            ["Has Image", "2000", CHAIR_IMAGE],
        ]
        records = ProductCatalogService.parse_sheet_rows(rows)
        assert len(records) == 1
        assert records[0]["product_name"] == "Has Image"

    def test_multi_product_chunk_detection(self):
        chunk = (
            "Luxury Sofa\nPrice: 45000\n![Luxury Sofa](https://a.com/sofa.jpg)\n"
            "Office Chair\nPrice: 12000\n![Office Chair](https://a.com/chair.jpg)"
        )
        assert ProductCatalogService._is_multi_product_chunk(chunk) is True

    def test_single_product_chunk_not_multi(self):
        chunk = f"Luxury Sofa\nPrice: 45000\n![Luxury Sofa]({SOFA_IMAGE})"
        assert ProductCatalogService._is_multi_product_chunk(chunk) is False

    def test_enrich_products_exact_match_only(self):
        products = [
            {"id": "prod_0", "name": "Luxury Sofa", "price": 45000, "image_url": CHAIR_IMAGE},
            {"id": "prod_1", "name": "Office Chair", "price": 12000, "image_url": SOFA_IMAGE},
        ]
        search_results = [
            {
                "product_name": "Luxury Sofa",
                "image_url": SOFA_IMAGE,
                "product_id": "SOFA-001",
                "sku": "SOFA-001",
                "text": f"Luxury Sofa\n![Luxury Sofa]({SOFA_IMAGE})",
            },
            {
                "product_name": "Office Chair",
                "image_url": CHAIR_IMAGE,
                "product_id": "CHAIR-001",
                "sku": "CHAIR-001",
                "text": f"Office Chair\n![Office Chair]({CHAIR_IMAGE})",
            },
        ]
        enriched = ProductCatalogService.enrich_products(products, search_results)
        assert enriched[0]["image_url"] == SOFA_IMAGE
        assert enriched[0]["id"] == "SOFA-001"
        assert enriched[1]["image_url"] == CHAIR_IMAGE
        assert enriched[1]["id"] == "CHAIR-001"

    def test_enrich_products_clears_unverified_image(self):
        products = [{"id": "prod_0", "name": "Unknown Item", "image_url": CHAIR_IMAGE}]
        search_results = [
            {
                "product_name": "Luxury Sofa",
                "image_url": SOFA_IMAGE,
                "text": f"Luxury Sofa\n![Luxury Sofa]({SOFA_IMAGE})",
            },
        ]
        enriched = ProductCatalogService.enrich_products(products, search_results)
        assert enriched[0]["image_url"] == ""

    def test_enrich_products_skips_multi_product_chunk(self):
        products = [{"id": "prod_0", "name": "Luxury Sofa", "image_url": CHAIR_IMAGE}]
        multi_chunk = {
            "product_name": "Luxury Sofa",
            "image_url": SOFA_IMAGE,
            "text": (
                f"Luxury Sofa\n![Luxury Sofa]({SOFA_IMAGE})\n"
                f"Office Chair\n![Office Chair]({CHAIR_IMAGE})"
            ),
        }
        enriched = ProductCatalogService.enrich_products(products, [multi_chunk])
        assert enriched[0]["image_url"] == ""

    def test_validate_records_flags_duplicates(self):
        records = ProductCatalogService.parse_sheet_rows(
            [
                ["Name", "Image URL"],
                ["Same Name", SOFA_IMAGE],
                ["Same Name", CHAIR_IMAGE],
            ]
        )
        report = ProductCatalogService.validate_records(records)
        assert report["healthy"] is False
        assert any(i["type"] == "duplicate_name" for i in report["issues"])


class TestConversationalAgentBinding:
    def test_bind_images_no_fuzzy_substring(self):
        products = [{"name": "Luxury Sofa Set", "image_url": ""}]
        chunks = [
            {
                "chunk_text": f"Office Chair\n![Office Chair]({CHAIR_IMAGE})",
                "product_name": "Office Chair",
                "image_url": CHAIR_IMAGE,
                "image_urls": [CHAIR_IMAGE],
                "image_alt_map": {"Office Chair": CHAIR_IMAGE},
            },
        ]
        bound = ConversationalAgentService._bind_images_to_products(products, chunks)
        assert "luxury sofa set" not in bound
        assert bound.get("luxury sofa set") is None

    def test_bind_images_exact_metadata_match(self):
        products = [{"name": "Luxury Sofa", "image_url": ""}]
        chunks = [
            {
                "chunk_text": f"Luxury Sofa\n![Luxury Sofa]({SOFA_IMAGE})",
                "product_name": "Luxury Sofa",
                "image_url": SOFA_IMAGE,
                "image_urls": [SOFA_IMAGE],
                "image_alt_map": {"Luxury Sofa": SOFA_IMAGE},
            },
        ]
        bound = ConversationalAgentService._bind_images_to_products(products, chunks)
        assert bound.get("luxury sofa") == SOFA_IMAGE

    def test_parse_products_skips_multi_product_chunks(self):
        search_data = {
            "results": [
                {
                    "text": (
                        f"Luxury Sofa\nPrice: 45000\n![Luxury Sofa]({SOFA_IMAGE})\n"
                        f"Office Chair\nPrice: 12000\n![Office Chair]({CHAIR_IMAGE})"
                    ),
                    "image_url": SOFA_IMAGE,
                    "product_name": "Luxury Sofa",
                },
                {
                    "text": f"Office Chair\nPrice: 12000\n![Office Chair]({CHAIR_IMAGE})",
                    "image_url": CHAIR_IMAGE,
                    "product_name": "Office Chair",
                    "product_id": "CHAIR-001",
                    "sku": "CHAIR-001",
                    "price": 12000,
                },
            ]
        }
        parsed = ConversationalAgentService._parse_products_from_search_results(search_data)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "Office Chair"
        assert parsed[0]["image_url"] == CHAIR_IMAGE
        assert parsed[0]["id"] == "CHAIR-001"

    def test_is_browse_query(self):
        assert ProductCatalogService.is_browse_query("show me your catalog") is True
        assert ProductCatalogService.is_browse_query("luxury sofa") is False


class TestCatalogProductOverride:
    SHEET_IMAGE = "https://images.pexels.com/photos/1866149/pexels-photo-1866149.jpeg"
    LLM_IMAGE = "https://images.pexels.com/photos/6996085/pexels-photo-6996085.jpeg"

    def test_override_blocks_llm_image_swap(self):
        cached = [{
            "id": "FURN-001",
            "name": "3-seater fabric sofa",
            "price": 499.99,
            "description": "From sheet",
            "image_url": self.SHEET_IMAGE,
            "sku": "FURN-001",
            "product_id": "FURN-001",
        }]
        incoming = [{
            "id": "prod_0_0",
            "name": "3-seater fabric sofa",
            "price": 499.99,
            "description": "LLM description",
            "image_url": self.LLM_IMAGE,
        }]
        result = ConversationalAgentService._apply_catalog_product_override(
            incoming, cached
        )
        assert len(result) == 1
        assert result[0]["image_url"] == self.SHEET_IMAGE
        assert result[0]["id"] == "FURN-001"

    def test_override_uses_full_cache_when_llm_fabricates(self):
        cached = [{
            "id": "FURN-001",
            "name": "3-seater fabric sofa",
            "price": 499.99,
            "image_url": self.SHEET_IMAGE,
        }]
        incoming = [{
            "id": "prod_0_0",
            "name": "sofa",
            "price": 499.99,
            "image_url": self.LLM_IMAGE,
        }]
        result = ConversationalAgentService._apply_catalog_product_override(
            incoming, cached
        )
        assert result[0]["image_url"] == self.SHEET_IMAGE
