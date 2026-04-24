"""Tests for src/services/fraud_detection_service.py"""
import pytest

class TestFraudDetectionService:
    def test_import(self):
        from src.services.fraud_detection_service import FraudDetectionService
        svc = FraudDetectionService()
        assert svc is not None
