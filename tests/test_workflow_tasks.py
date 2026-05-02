import pytest
from unittest.mock import patch

@pytest.fixture(autouse=True)
def mock_run_async():
    """Mock the _run_async utility for all workflow tasks."""
    with patch('src.tasks.workflow_tasks._run_async') as mock:
        yield mock

class TestWorkflowTasks:
    def test_execute_scheduled_workflow_task(self, mock_run_async):
        from src.tasks.workflow_tasks import execute_scheduled_workflow_task
        mock_run_async.return_value = {"status": "completed", "workflow_id": "workflow_123"}
        
        result = execute_scheduled_workflow_task("workflow_123", "user_123")
        assert result == {"status": "completed", "workflow_id": "workflow_123"}
        mock_run_async.assert_called_once()

    def test_sync_workflows_task(self, mock_run_async):
        from src.tasks.workflow_tasks import sync_workflows_task
        mock_run_async.return_value = {"status": "synced"}
        
        result = sync_workflows_task()
        assert result == {"status": "synced"}
        mock_run_async.assert_called_once()
