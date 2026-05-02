import pytest
from unittest.mock import patch, MagicMock

@pytest.fixture(autouse=True)
def mock_run_async():
    """Mock the _run_async utility for all webhook tasks to prevent actual asyncio loops."""
    with patch('src.tasks.webhook_tasks._run_async') as mock:
        yield mock

class TestWebhookTasks:
    def test_process_whatsapp_message_task(self, mock_run_async):
        from src.tasks.webhook_tasks import process_whatsapp_message_task
        mock_run_async.return_value = {"status": "processed", "type": "whatsapp"}
        
        result = process_whatsapp_message_task("user_123", {"entry": []})
        assert result == {"status": "processed", "type": "whatsapp"}
        mock_run_async.assert_called_once()

    def test_process_telegram_message_task(self, mock_run_async):
        from src.tasks.webhook_tasks import process_telegram_message_task
        mock_run_async.return_value = {"status": "processed", "type": "telegram"}
        
        result = process_telegram_message_task("user_123", {"update_id": 123})
        assert result == {"status": "processed", "type": "telegram"}
        mock_run_async.assert_called_once()

    def test_process_slack_event_task(self, mock_run_async):
        from src.tasks.webhook_tasks import process_slack_event_task
        mock_run_async.return_value = {"status": "processed", "type": "slack"}
        
        result = process_slack_event_task("user_123", {"event": {}})
        assert result == {"status": "processed", "type": "slack"}
        mock_run_async.assert_called_once()

    def test_process_gmail_notification_task(self, mock_run_async):
        from src.tasks.webhook_tasks import process_gmail_notification_task
        mock_run_async.return_value = {"status": "processed", "type": "gmail"}
        
        result = process_gmail_notification_task("user_123", "user@test.com", 12345)
        assert result == {"status": "processed", "type": "gmail"}
        mock_run_async.assert_called_once()
