import pytest
from unittest.mock import patch, MagicMock

@pytest.fixture(autouse=True)
def mock_run_async():
    """Mock the _run_async utility for all maintenance tasks."""
    with patch('src.tasks.maintenance_tasks._run_async') as mock:
        yield mock

class TestMaintenanceTasks:
    def test_log_cleanup_task(self, mock_run_async):
        from src.tasks.maintenance_tasks import log_cleanup_task
        mock_run_async.return_value = 15
        
        result = log_cleanup_task(14)
        assert result == {"deleted": 15}
        mock_run_async.assert_called_once()

    def test_refresh_whatsapp_tokens_task(self, mock_run_async):
        from src.tasks.maintenance_tasks import refresh_whatsapp_tokens_task
        mock_run_async.return_value = 2
        
        result = refresh_whatsapp_tokens_task()
        assert result == {"refreshed": 2}
        mock_run_async.assert_called_once()

    def test_check_tiktok_schedules_task(self, mock_run_async):
        from src.tasks.maintenance_tasks import check_tiktok_schedules_task
        mock_run_async.return_value = 1
        
        result = check_tiktok_schedules_task()
        assert result == {"published": 1}
        mock_run_async.assert_called_once()
