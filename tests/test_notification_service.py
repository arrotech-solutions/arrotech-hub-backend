"""
Unit tests for notification preference resolution, quiet hours, and event registry.
"""
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.services.notification_events import (
    DEFAULT_CATEGORY_RULES,
    category_for_event,
    merge_rules,
    severity_for_event,
)
from src.services.notification_service import (
    _in_quiet_hours,
    resolve_channels,
)


def test_merge_rules_defaults():
    rules = merge_rules(None)
    assert set(rules.keys()) == set(DEFAULT_CATEGORY_RULES.keys())
    assert rules["billing"]["in_app"] is True
    assert rules["messaging"]["email"] is False


def test_merge_rules_partial_override():
    rules = merge_rules({"billing": {"email": False, "slack": True}})
    assert rules["billing"]["email"] is False
    assert rules["billing"]["slack"] is True
    assert rules["billing"]["in_app"] is True  # default preserved
    assert rules["security"]["email"] is True


def test_event_category_and_severity():
    assert category_for_event("payment_failed") == "billing"
    assert severity_for_event("payment_failed") == "critical"
    assert category_for_event("new_follower") == "marketplace"
    assert severity_for_event("unknown_event") == "info"


def test_critical_always_in_app_even_if_rules_off():
    settings = SimpleNamespace(
        email_notifications=False,
        slack_notifications=False,
        webhook_notifications=False,
        notification_webhook_url=None,
        notification_rules={"billing": {"in_app": False, "email": False, "slack": False, "webhook": False}},
        quiet_hours=None,
        digest_email_daily=False,
    )
    channels = resolve_channels(settings, "payment_failed")
    assert channels["in_app"] is True
    assert channels["email"] is False


def test_channel_masters_gate_delivery():
    settings = SimpleNamespace(
        email_notifications=False,
        slack_notifications=True,
        webhook_notifications=True,
        notification_webhook_url="https://example.com/hook",
        notification_rules={"commerce": {"in_app": True, "email": True, "slack": True, "webhook": True}},
        quiet_hours=None,
        digest_email_daily=False,
    )
    channels = resolve_channels(settings, "order_received")
    assert channels["email"] is False
    assert channels["slack"] is True
    assert channels["webhook"] is True


def test_quiet_hours_overnight():
    quiet = {"start": "22:00", "end": "07:00", "timezone": "UTC"}
    night = datetime(2026, 7, 26, 23, 0, tzinfo=ZoneInfo("UTC"))
    morning = datetime(2026, 7, 26, 8, 0, tzinfo=ZoneInfo("UTC"))
    assert _in_quiet_hours(quiet, night) is True
    assert _in_quiet_hours(quiet, morning) is False


def test_quiet_hours_suppress_non_critical():
    settings = SimpleNamespace(
        email_notifications=True,
        slack_notifications=True,
        webhook_notifications=False,
        notification_webhook_url=None,
        notification_rules=DEFAULT_CATEGORY_RULES,
        quiet_hours={"start": "00:00", "end": "23:59", "timezone": "UTC"},
        digest_email_daily=False,
    )
    channels = resolve_channels(settings, "new_follower")
    assert channels["in_app"] is True
    assert channels["email"] is False
    assert channels["slack"] is False


@pytest.mark.asyncio
async def test_notification_settings_roundtrip(client, auth_headers):
    """GET/PUT /settings/notifications includes rules matrix."""
    get_resp = await client.get("/settings/notifications", headers=auth_headers)
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body.get("success") is True
    data = body.get("data") or {}
    assert "email_notifications" in data
    assert "notification_rules" in data
    assert "billing" in (data.get("notification_rules") or {})

    rules = dict(data["notification_rules"])
    rules["marketplace"] = {**rules.get("marketplace", {}), "email": False, "in_app": True}
    put_resp = await client.put(
        "/settings/notifications",
        headers=auth_headers,
        json={
            "email_notifications": True,
            "slack_notifications": False,
            "webhook_notifications": False,
            "notification_webhook_url": None,
            "notification_rules": rules,
            "quiet_hours": {"start": "22:00", "end": "07:00", "timezone": "UTC"},
            "digest_email_daily": True,
        },
    )
    assert put_resp.status_code == 200
    put_body = put_resp.json()
    assert put_body.get("success") is True
    put_data = put_body.get("data") or {}
    assert put_data.get("digest_email_daily") is True
    assert put_data.get("notification_rules", {}).get("marketplace", {}).get("email") is False
