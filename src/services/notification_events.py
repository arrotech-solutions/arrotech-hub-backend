"""
Notification event registry — single source of truth for event keys,
categories, severity, and default channel matrix.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


CATEGORIES = (
    "billing",
    "security",
    "workflows",
    "agents",
    "messaging",
    "commerce",
    "marketplace",
    "system",
)

CHANNELS = ("in_app", "email", "slack", "webhook")


@dataclass(frozen=True)
class NotificationEvent:
    key: str
    category: str
    severity: str  # critical | important | info
    title_template: str = ""
    # Defaults applied when user has no rule override for this category
    default_channels: Dict[str, bool] = field(default_factory=dict)


def _ch(in_app=True, email=False, slack=False, webhook=False) -> Dict[str, bool]:
    return {"in_app": in_app, "email": email, "slack": slack, "webhook": webhook}


# Default category × channel matrix for new users / missing rules
DEFAULT_CATEGORY_RULES: Dict[str, Dict[str, bool]] = {
    "billing": _ch(True, True, False, False),
    "security": _ch(True, True, True, False),
    "workflows": _ch(True, False, True, False),
    "agents": _ch(True, False, False, False),
    "messaging": _ch(True, False, False, False),
    "commerce": _ch(True, True, True, False),
    "marketplace": _ch(True, True, False, False),
    "system": _ch(True, True, False, False),
}


EVENTS: Dict[str, NotificationEvent] = {
    # Billing
    "payment_succeeded": NotificationEvent("payment_succeeded", "billing", "important", default_channels=_ch(True, True)),
    "payment_failed": NotificationEvent("payment_failed", "billing", "critical", default_channels=_ch(True, True, True)),
    "payment_refunded": NotificationEvent("payment_refunded", "billing", "important", default_channels=_ch(True, True)),
    "subscription_renewing": NotificationEvent("subscription_renewing", "billing", "important", default_channels=_ch(True, True)),
    "subscription_renewed": NotificationEvent("subscription_renewed", "billing", "info", default_channels=_ch(True, True)),
    "subscription_cancelled": NotificationEvent("subscription_cancelled", "billing", "important", default_channels=_ch(True, True)),
    "subscription_past_due": NotificationEvent("subscription_past_due", "billing", "critical", default_channels=_ch(True, True, True)),
    "invoice_available": NotificationEvent("invoice_available", "billing", "info", default_channels=_ch(True, True)),
    "withdrawal_completed": NotificationEvent("withdrawal_completed", "billing", "important", default_channels=_ch(True, True)),
    "withdrawal_failed": NotificationEvent("withdrawal_failed", "billing", "critical", default_channels=_ch(True, True)),
    # Security
    "new_login": NotificationEvent("new_login", "security", "important", default_channels=_ch(True, True)),
    "password_changed": NotificationEvent("password_changed", "security", "critical", default_channels=_ch(True, True)),
    "email_changed": NotificationEvent("email_changed", "security", "critical", default_channels=_ch(True, True)),
    "2fa_changed": NotificationEvent("2fa_changed", "security", "important", default_channels=_ch(True, True)),
    "api_key_changed": NotificationEvent("api_key_changed", "security", "important", default_channels=_ch(True, True)),
    "suspicious_activity": NotificationEvent("suspicious_activity", "security", "critical", default_channels=_ch(True, True, True)),
    # Workflows
    "workflow_run_failed": NotificationEvent("workflow_run_failed", "workflows", "critical", default_channels=_ch(True, True, True)),
    "workflow_run_completed": NotificationEvent("workflow_run_completed", "workflows", "info", default_channels=_ch(True, False)),
    "workflow_schedule_disabled": NotificationEvent("workflow_schedule_disabled", "workflows", "important", default_channels=_ch(True, True)),
    "quota_exceeded": NotificationEvent("quota_exceeded", "workflows", "important", default_channels=_ch(True, True)),
    # Agents
    "agent_escalation": NotificationEvent("agent_escalation", "agents", "critical", default_channels=_ch(True, True, True)),
    "agent_error": NotificationEvent("agent_error", "agents", "important", default_channels=_ch(True, False)),
    "agent_action_completed": NotificationEvent("agent_action_completed", "agents", "info", default_channels=_ch(True, False)),
    # Messaging
    "conversation_assigned": NotificationEvent("conversation_assigned", "messaging", "important", default_channels=_ch(True, False)),
    "sla_breach": NotificationEvent("sla_breach", "messaging", "critical", default_channels=_ch(True, True)),
    "connection_disconnected": NotificationEvent("connection_disconnected", "messaging", "critical", default_channels=_ch(True, True, True)),
    "connection_token_expired": NotificationEvent("connection_token_expired", "messaging", "critical", default_channels=_ch(True, True)),
    # Commerce
    "order_received": NotificationEvent("order_received", "commerce", "important", default_channels=_ch(True, True, True)),
    "stk_result": NotificationEvent("stk_result", "commerce", "important", default_channels=_ch(True, True)),
    "order_cancelled": NotificationEvent("order_cancelled", "commerce", "important", default_channels=_ch(True, True)),
    "payment_failure_burst": NotificationEvent("payment_failure_burst", "commerce", "critical", default_channels=_ch(True, True, True)),
    # Marketplace
    "workflow_imported": NotificationEvent("workflow_imported", "marketplace", "info", default_channels=_ch(True, True)),
    "earnings_received": NotificationEvent("earnings_received", "marketplace", "important", default_channels=_ch(True, True)),
    "workflow_reviewed": NotificationEvent("workflow_reviewed", "marketplace", "info", default_channels=_ch(True, True)),
    "workflow_rated": NotificationEvent("workflow_rated", "marketplace", "info", default_channels=_ch(True, False)),
    "new_follower": NotificationEvent("new_follower", "marketplace", "info", default_channels=_ch(True, True)),
    "milestone_reached": NotificationEvent("milestone_reached", "marketplace", "info", default_channels=_ch(True, True)),
    # System
    "system_announcement": NotificationEvent("system_announcement", "system", "important", default_channels=_ch(True, True)),
    "maintenance": NotificationEvent("maintenance", "system", "important", default_channels=_ch(True, True)),
}


def get_event(event_key: str) -> Optional[NotificationEvent]:
    return EVENTS.get(event_key)


def category_for_event(event_key: str) -> str:
    ev = EVENTS.get(event_key)
    return ev.category if ev else "system"


def severity_for_event(event_key: str) -> str:
    ev = EVENTS.get(event_key)
    return ev.severity if ev else "info"


def merge_rules(stored: Optional[Dict]) -> Dict[str, Dict[str, bool]]:
    """Merge user-stored rules with defaults so every category is present."""
    base = {k: dict(v) for k, v in DEFAULT_CATEGORY_RULES.items()}
    if not stored or not isinstance(stored, dict):
        return base
    for cat, channels in stored.items():
        if cat not in base or not isinstance(channels, dict):
            continue
        for ch in CHANNELS:
            if ch in channels and isinstance(channels[ch], bool):
                base[cat][ch] = channels[ch]
    return base


def list_categories_for_ui() -> List[Dict[str, str]]:
    labels = {
        "billing": "Billing & subscriptions",
        "security": "Security & account",
        "workflows": "Workflows & automations",
        "agents": "Agents",
        "messaging": "Messaging & inbox",
        "commerce": "Orders & payments",
        "marketplace": "Marketplace & creator",
        "system": "System",
    }
    return [{"id": c, "label": labels.get(c, c)} for c in CATEGORIES]
