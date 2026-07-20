"""Tests for src/services/real_estate_tools.py"""
import pytest

class TestRealEstateTools:
    def test_import(self):
        from src.services.real_estate_tools import RealEstateTools
        svc = RealEstateTools()
        assert svc is not None

    def test_instantiate(self):
        from src.services.real_estate_tools import RealEstateTools
        svc = RealEstateTools()
        assert hasattr(svc, '__class__')
