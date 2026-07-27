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
    assert needs_confirmation("whatsapp_inbox", {"operation": "list_conversations"}) is False
    assert needs_confirmation("whatsapp_account_info", {}) is False
    assert needs_confirmation("whatsapp_agent_control", {"operation": "handoff_status", "phone_number": "2547"}) is False


def test_format_and_synthesize_gmail_and_calendar():
    from src.services.tool_result_grounding import (
        format_tool_result_for_llm,
        looks_ungrounded,
        looks_like_tool_deferral,
        synthesize_answer_from_tools,
        normalize_drive_search_query,
    )

    gmail = {
        "success": True,
        "emails": [
            {"from": "a@b.com", "subject": "Invoice #12", "date": "Mon", "snippet": "Please pay"},
        ],
        "total": 1,
    }
    formatted = format_tool_result_for_llm("google_workspace_gmail", gmail)
    assert "Invoice #12" in formatted
    assert "TOOL SUCCEEDED" in formatted

    tools = [{"name": "google_workspace_gmail", "result": gmail}]
    bad = "It seems there was an issue retrieving your latest Gmail messages."
    assert looks_ungrounded(bad, tools) is True
    good = synthesize_answer_from_tools("Show my latest 10 Gmail messages", tools)
    assert good and "Invoice #12" in good

    assert looks_like_tool_deferral("Let me check your calendar. One moment please.", []) is True
    assert looks_like_tool_deferral("You are free tomorrow.", []) is False
    assert looks_like_tool_deferral(
        "I'll first gather the unread WhatsApp conversations summary and then send it. "
        "Let's start by retrieving the unread WhatsApp messages.",
        [],
    ) is True
    assert looks_like_tool_deferral(
        "Let's check your Google Calendar for events scheduled tomorrow between 10:00 and 12:00. "
        "I'll retrieve that information now.",
        [],
    ) is True
    assert looks_like_tool_deferral("I'll retrieve that information now.", []) is True
    assert looks_like_tool_deferral(
        "I'll email that summary now.",
        [{"name": "whatsapp_inbox", "result": {"success": True}}],
    ) is True
    assert looks_like_tool_deferral(
        "You're free tomorrow between 10 and 12. I'll send an invite if you want.",
        [{"name": "google_workspace_calendar", "result": {"success": True}}],
    ) is False

    assert "name contains" in normalize_drive_search_query("Hub")
    assert "trashed" in normalize_drive_search_query("Hub")


def test_format_and_synthesize_unread_inbox():
    from src.services.tool_result_grounding import (
        format_tool_result_for_llm,
        looks_ungrounded,
        synthesize_answer_from_tools,
    )

    result = {
        "success": True,
        "result": "8 unread message(s) across 2 chat(s).",
        "data": {
            "total_unread": 8,
            "conversations": [
                {"name": "peter", "phone_number": "254720930988", "unread_count": 7, "inbox_url": "/inbox?contact=1"},
                {"name": "ATC Arrotech", "phone_number": "254711371265", "unread_count": 1, "inbox_url": "/inbox?contact=2"},
            ],
            "widget": "whatsapp_inbox",
        },
    }
    formatted = format_tool_result_for_llm("whatsapp_inbox", result)
    assert "TOOL SUCCEEDED" in formatted
    assert "peter" in formatted
    assert "254720930988" in formatted

    tools_called = [{"name": "whatsapp_inbox", "result": result}]
    bad = "⚠️ I currently can't access your WhatsApp conversations directly."
    assert looks_ungrounded(bad, tools_called) is True
    good = synthesize_answer_from_tools("Show my unread WhatsApp conversations.", tools_called)
    assert good is not None
    assert "peter" in good
    assert "7" in good


def test_ensure_operator_tools_prefers_inbox_for_unread():
    from src.services.tool_selector import PrecisionToolRouter

    router = PrecisionToolRouter.__new__(PrecisionToolRouter)
    tools = [
        {"name": "whatsapp_send_message"},
        {"name": "whatsapp_inbox"},
        {"name": "whatsapp_account_info"},
        {"name": "google_workspace_gmail"},
        {"name": "google_workspace_calendar"},
    ]
    selected = router._ensure_operator_tools(
        "Show my unread WhatsApp conversations",
        tools,
        [],
    )
    names = [t["name"] for t in selected]
    assert "whatsapp_inbox" in names


def test_ensure_operator_tools_email_plus_whatsapp():
    from src.services.tool_selector import PrecisionToolRouter

    router = PrecisionToolRouter.__new__(PrecisionToolRouter)
    tools = [
        {"name": "whatsapp_inbox"},
        {"name": "google_workspace_gmail"},
        {"name": "whatsapp_send_message"},
    ]
    selected = router._ensure_operator_tools(
        "Email arrotechdesign@gmail.com the unread whatsapp conversations summary",
        tools,
        [],
    )
    names = [t["name"] for t in selected]
    assert "whatsapp_inbox" in names
    assert "google_workspace_gmail" in names


def test_ensure_operator_tools_am_i_free():
    from src.services.tool_selector import PrecisionToolRouter

    router = PrecisionToolRouter.__new__(PrecisionToolRouter)
    tools = [
        {"name": "google_workspace_calendar"},
        {"name": "google_workspace_gmail"},
    ]
    selected = router._ensure_operator_tools(
        "Am I free tomorrow between 10:00 and 12:00 Africa/Nairobi?",
        tools,
        [],
    )
    names = [t["name"] for t in selected]
    assert "google_workspace_calendar" in names


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
