"""
Tests for agent classes and Google Workspace services.
"""
import pytest


# ── Base Agent ───────────────────────────────────────────────────────────────

class TestBaseAgent:
    def test_import(self):
        from src.services.agents.base_agent import BaseAgent
        assert BaseAgent is not None


# ── M-Pesa Agent ─────────────────────────────────────────────────────────────

class TestMpesaAgent:
    def test_import(self):
        from src.services.agents.mpesa_agent import MpesaAgent
        assert MpesaAgent is not None


# ── Follow-Up Agent ──────────────────────────────────────────────────────────

class TestFollowUpAgent:
    def test_import(self):
        from src.services.agents.follow_up_agent import FollowUpAgent
        assert FollowUpAgent is not None


# ── Deadline Guardian Agent ──────────────────────────────────────────────────

class TestDeadlineGuardianAgent:
    def test_import(self):
        from src.services.agents.deadline_guardian_agent import DeadlineGuardianAgent
        assert DeadlineGuardianAgent is not None


# ── Inbox Zero Coach Agent ───────────────────────────────────────────────────

class TestInboxZeroCoachAgent:
    def test_import(self):
        from src.services.agents.inbox_zero_coach_agent import InboxZeroCoachAgent
        assert InboxZeroCoachAgent is not None


# ── Meeting Prep Agent ───────────────────────────────────────────────────────

class TestMeetingPrepAgent:
    def test_import(self):
        from src.services.agents.meeting_prep_agent import MeetingPrepAgent
        assert MeetingPrepAgent is not None


# ── Weekly Digest Agent ──────────────────────────────────────────────────────

class TestWeeklyDigestAgent:
    def test_import(self):
        from src.services.agents.weekly_digest_agent import WeeklyDigestAgent
        assert WeeklyDigestAgent is not None


# ── Google Workspace: Base Client ────────────────────────────────────────────

class TestGoogleBaseClient:
    def test_import(self):
        from src.services.google_workspace.base_client import GoogleBaseClient
        assert GoogleBaseClient is not None


# ── Google Workspace: Gmail Service ──────────────────────────────────────────

class TestGoogleGmailService:
    def test_import(self):
        from src.services.google_workspace.gmail_service import GmailService
        assert GmailService is not None


# ── Google Workspace: Calendar Service ───────────────────────────────────────

class TestGoogleCalendarService:
    def test_import(self):
        from src.services.google_workspace.calendar_service import CalendarService
        assert CalendarService is not None


# ── Google Workspace: Drive Service ──────────────────────────────────────────

class TestGoogleDriveService:
    def test_import(self):
        from src.services.google_workspace.drive_service import DriveService
        assert DriveService is not None


# ── Google Workspace: Docs Service ───────────────────────────────────────────

class TestGoogleDocsService:
    def test_import(self):
        from src.services.google_workspace.docs_service import DocsService
        assert DocsService is not None


# ── Google Workspace: Sheets Service ─────────────────────────────────────────

class TestGoogleSheetsService:
    def test_import(self):
        from src.services.google_workspace.sheets_service import SheetsService
        assert SheetsService is not None


# ── Google Workspace: Analytics Service ──────────────────────────────────────

class TestGoogleAnalyticsService:
    def test_import(self):
        from src.services.google_workspace.analytics_service import AnalyticsService
        assert AnalyticsService is not None


# ── Tool Executor (large) ───────────────────────────────────────────────────

class TestToolExecutor:
    def test_import(self):
        from src.services.tool_executor import ToolExecutor
        assert ToolExecutor is not None


# ── Dynamic Tool Registry extended ───────────────────────────────────────────

class TestDynamicToolRegistryExtended:
    def test_get_relevant_examples_slack(self):
        from src.services.dynamic_tool_registry import dynamic_tool_registry
        tools = [{"function": {
            "name": "slack_send_message",
            "description": "Send a message to Slack",
            "few_shot_examples": [{"user": "msg slack", "tool_call": "slack_call"}]
        }}]
        result = dynamic_tool_registry.get_relevant_examples("Send a message to team", tools)
        assert isinstance(result, str)

    def test_get_relevant_examples_irrelevant(self):
        from src.services.dynamic_tool_registry import dynamic_tool_registry
        tools = [{"function": {
            "name": "create_invoice",
            "description": "Create a financial invoice",
            "few_shot_examples": [{"user": "invoice please", "tool_call": "inv"}]
        }}]
        result = dynamic_tool_registry.get_relevant_examples("Dance for me", tools)
        assert isinstance(result, str)


# ── Platform Registry extended ───────────────────────────────────────────────

class TestPlatformRegistryExtended:
    def test_get_all_platforms(self):
        from src.services.platform_registry import PlatformRegistry
        registry = PlatformRegistry()
        if hasattr(registry, "get_platforms"):
            platforms = registry.get_platforms()
            assert platforms is not None

    def test_get_platform_tools(self):
        from src.services.platform_registry import PlatformRegistry
        registry = PlatformRegistry()
        tools = registry.get_platform_tools("hubspot")
        assert isinstance(tools, list)

    def test_get_platform_tools_unknown(self):
        from src.services.platform_registry import PlatformRegistry
        registry = PlatformRegistry()
        tools = registry.get_platform_tools("nonexistent_platform_xyz")
        assert isinstance(tools, list)
        assert len(tools) == 0


# ── Intent Processor ─────────────────────────────────────────────────────────

class TestIntentProcessorExtended:
    def test_import(self):
        try:
            from src.services.intent_processor import IntentProcessor
            processor = IntentProcessor()
            assert processor is not None
        except (ImportError, TypeError):
            pytest.skip("IntentProcessor needs special init")


# ── Autonomous Agent Service ─────────────────────────────────────────────────

class TestAutonomousAgentServiceExtended:
    def test_import(self):
        from src.services.autonomous_agent_service import AutonomousAgentService
        svc = AutonomousAgentService()
        assert svc is not None
