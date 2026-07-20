"""Tests for src/services/unstructured_service.py"""
import pytest

class TestUnstructuredService:
    def test_import(self):
        from src.services.unstructured_service import UnstructuredService
        assert UnstructuredService is not None
