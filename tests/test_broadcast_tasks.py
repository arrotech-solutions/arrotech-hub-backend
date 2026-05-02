import pytest
from unittest.mock import patch

@pytest.fixture(autouse=True)
def mock_run_async():
    """Mock the _run_async utility for all broadcast tasks."""
    with patch('src.tasks.broadcast_tasks._run_async') as mock:
        yield mock

class TestBroadcastTasks:
    def test_execute_broadcast_campaign_task(self, mock_run_async):
        from src.tasks.broadcast_tasks import execute_broadcast_campaign_task
        mock_run_async.return_value = {"status": "completed", "messages_sent": 100}
        
        result = execute_broadcast_campaign_task("campaign_123", "user_123", ["contact_1", "contact_2"])
        assert result == {"status": "completed", "messages_sent": 100}
        mock_run_async.assert_called_once()
