import pytest
from unittest.mock import patch, MagicMock, AsyncMock

@pytest.fixture(autouse=True)
def mock_run_async():
    """Mock the _run_async utility for all email tasks to prevent actual asyncio loops."""
    with patch('src.tasks.email_tasks._run_async') as mock:
        yield mock

class TestEmailTasks:
    def test_send_email_task(self, mock_run_async):
        from src.tasks.email_tasks import send_email_task
        mock_run_async.return_value = True
        
        result = send_email_task("test@test.com", "Subject", "<p>HTML</p>", "TEXT")
        assert result == {"status": "sent", "to": "test@test.com"}
        mock_run_async.assert_called_once()

    def test_send_email_task_failure(self, mock_run_async):
        from src.tasks.email_tasks import send_email_task
        mock_run_async.return_value = False
        
        with pytest.raises(RuntimeError, match="Email send returned False for test@test.com"):
            send_email_task("test@test.com", "Subject", "<p>HTML</p>", "TEXT")

    def test_send_welcome_email_task(self, mock_run_async):
        from src.tasks.email_tasks import send_welcome_email_task
        mock_run_async.return_value = True
        
        result = send_welcome_email_task("test@test.com", "User")
        assert result == {"status": "sent", "to": "test@test.com"}

    def test_send_password_reset_email_task(self, mock_run_async):
        from src.tasks.email_tasks import send_password_reset_email_task
        mock_run_async.return_value = True
        
        result = send_password_reset_email_task("test@test.com", "token123", "http://reset")
        assert result == {"status": "sent", "to": "test@test.com"}

    def test_send_2fa_otp_email_task(self, mock_run_async):
        from src.tasks.email_tasks import send_2fa_otp_email_task
        mock_run_async.return_value = True
        
        result = send_2fa_otp_email_task("test@test.com", "123456")
        assert result == {"status": "sent", "to": "test@test.com"}

    def test_send_email_verification_task(self, mock_run_async):
        from src.tasks.email_tasks import send_email_verification_task
        mock_run_async.return_value = True
        
        result = send_email_verification_task("test@test.com", "User", "123456")
        assert result == {"status": "sent", "to": "test@test.com"}

    def test_send_org_invitation_email_task(self, mock_run_async):
        from src.tasks.email_tasks import send_org_invitation_email_task
        mock_run_async.return_value = True
        
        result = send_org_invitation_email_task("test@test.com", "Org", "Inviter", "Admin", "http://invite")
        assert result == {"status": "sent", "to": "test@test.com"}

    def test_send_payment_notification_task(self, mock_run_async):
        from src.tasks.email_tasks import send_payment_notification_task
        mock_run_async.return_value = True
        
        result = send_payment_notification_task("test@test.com", "User", 100.0, "USD", "Card", "Item")
        assert result == {"status": "sent", "to": "test@test.com"}
