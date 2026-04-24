"""Tests for src/services/rag_pipeline_service.py"""
import pytest

class TestRAGPipelineService:
    def test_import(self):
        from src.services.rag_pipeline_service import RAGPipelineService
        svc = RAGPipelineService()
        assert svc is not None

    def test_instantiate(self):
        from src.services.rag_pipeline_service import RAGPipelineService
        svc = RAGPipelineService()
        assert hasattr(svc, '__class__')
