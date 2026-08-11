"""Tests for RAG plain-text and zip ingestion helpers."""
from src.services.rag_pipeline_service import (
    _decode_plain_text,
    _is_plain_text_file,
)


class TestPlainTextDetection:
    def test_markdown_is_plain_text(self):
        assert _is_plain_text_file("employee-admin-hr.md", "text/plain")

    def test_zip_is_not_plain_text(self):
        assert not _is_plain_text_file("arrotech-kb.zip", "application/zip")


class TestPlainTextDecode:
    def test_utf8_markdown(self):
        content = b"# Title\n\nHello **world**"
        assert "Hello" in _decode_plain_text(content)
