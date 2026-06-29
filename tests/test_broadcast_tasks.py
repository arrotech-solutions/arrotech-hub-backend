import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def mock_run_async():
    with patch("src.tasks.broadcast_tasks._run_async") as mock:
        yield mock


class TestBroadcastTasks:
    def test_execute_broadcast_campaign_task(self, mock_run_async):
        from src.tasks.broadcast_tasks import execute_broadcast_campaign_task

        mock_run_async.return_value = {"sent": 100, "failed": 0, "total": 100}

        result = execute_broadcast_campaign_task("broadcast-id", "user-id")
        assert result["sent"] == 100
        assert result["failed"] == 0
        mock_run_async.assert_called_once()
