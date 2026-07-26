"""
Unit tests for Ask AI WhatsApp/Google Workspace confirmation + free-tier gates.
"""
from types import SimpleNamespace

from src.services.tool_confirmation import needs_confirmation, summarize_proposal
from src.services.tool_executor import ToolExecutor


def test_needs_confirmation_whatsapp_send():
    assert needs_confirmation("whatsapp_send_message", {"to_number": "2547", "message": "hi"}) is True


def test_needs_confirmation_whatsapp_list_templates():
    assert needs_confirmation("whatsapp_templates", {"operation": "list_templates"}) is False


def test_needs_confirmation_whatsapp_inbox_read():
    assert needs_confirmation("whatsapp_inbox", {"operation": "unread_summary"}) is False


def test_needs_confirmation_gmail_send():
    assert needs_confirmation("google_workspace_gmail", {"operation": "send_email", "to": "a@b.com"}) is True


def test_needs_confirmation_gmail_read():
    assert needs_confirmation("google_workspace_gmail", {"operation": "read_emails"}) is False


def test_summarize_proposal_whatsapp():
    s = summarize_proposal("whatsapp_send_message", {"to_number": "254700", "message": "Hello there"})
    assert "254700" in s
    assert "Hello" in s


def _free_user():
    return SimpleNamespace(
        id="u1",
        subscription_tier="free",
        subscription_end_date=None,
        subscription_status=None,
        trial_ends_at=None,
    )


def test_free_tier_blocks_whatsapp_send():
    executor = ToolExecutor()
    user = _free_user()
    denied = executor._check_write_operation_access(
        "whatsapp_send_message",
        {"to_number": "2547", "message": "hi", "action": "send_message"},
        user,
    )
    assert denied is not None
    assert denied.get("upgrade_required") is True


def test_free_tier_allows_whatsapp_inbox_read():
    executor = ToolExecutor()
    user = _free_user()
    denied = executor._check_write_operation_access(
        "whatsapp_inbox",
        {"operation": "list_conversations"},
        user,
    )
    assert denied is None


def test_free_tier_allows_gmail_read():
    executor = ToolExecutor()
    user = _free_user()
    denied = executor._check_write_operation_access(
        "google_workspace_gmail",
        {"operation": "read_emails"},
        user,
    )
    assert denied is None


def test_free_tier_blocks_sheets_write():
    executor = ToolExecutor()
    user = _free_user()
    denied = executor._check_write_operation_access(
        "google_workspace_sheets",
        {"operation": "append_rows"},
        user,
    )
    assert denied is not None
    assert denied.get("upgrade_required") is True
