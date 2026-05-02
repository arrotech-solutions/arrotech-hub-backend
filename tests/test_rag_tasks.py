import pytest
from unittest.mock import patch

@pytest.fixture(autouse=True)
def mock_run_async():
    """Mock the _run_async utility for all RAG tasks."""
    with patch('src.tasks.rag_tasks._run_async') as mock:
        yield mock

class TestRagTasks:
    def test_rag_ingest_source_task(self, mock_run_async):
        from src.tasks.rag_tasks import rag_ingest_source_task
        mock_run_async.return_value = {"status": "success", "chunks_processed": 5}
        
        result = rag_ingest_source_task("source_123")
        assert result == {"status": "success", "chunks_processed": 5}
        mock_run_async.assert_called_once()

    def test_rag_ingest_content_task(self, mock_run_async):
        from src.tasks.rag_tasks import rag_ingest_content_task
        mock_run_async.return_value = {"status": "success", "chunks_processed": 10}
        
        result = rag_ingest_content_task("workspace_123", "Some big document content")
        assert result == {"status": "success", "chunks_processed": 10}
        mock_run_async.assert_called_once()
