"""
Feature flags and plan-based limits for Arrotech Hub.
"""

from typing import Dict, Any, Optional
from ..models import SubscriptionTier, User

# Plan Limitations Configuration
PLAN_LIMITS: Dict[str, Dict[str, Any]] = {
    SubscriptionTier.FREE: {
        "max_active_workflows": 1,
        "max_ai_messages_daily": 5,
        "allowed_connections": ["ga4"],
        "support_level": "community",
        "reports": "standard"
    },
    SubscriptionTier.STARTER: {
        "max_active_workflows": 10,
        "max_ai_messages_daily": 100,
        "allowed_connections": ["ga4", "slack", "hubspot", "mpesa"],
        "support_level": "priority_email",
        "reports": "daily_auto"
    },
    SubscriptionTier.TESTING: {
        "max_active_workflows": 9999,  # Unlimited for testing
        "max_ai_messages_daily": 9999,  # Unlimited for testing
        "allowed_connections": ["*"],  # All allowed for testing
        "support_level": "email",
        "reports": "daily_auto"
    },
    SubscriptionTier.PRO: {
        "max_active_workflows": 9999,  # Unlimited
        "max_ai_messages_daily": 9999,  # Unlimited
        "allowed_connections": ["*"],  # All allowed
        "support_level": "dedicated_whatsapp",
        "reports": "real_time"
    },
    SubscriptionTier.ENTERPRISE: {
        "max_active_workflows": 9999,
        "max_ai_messages_daily": 9999,
        "allowed_connections": ["*"],
        "support_level": "dedicated_manager",
        "reports": "custom"
    },
}

class FeatureGate:
    """Service to check user permissions based on their subscription tier."""
    
    @staticmethod
    def get_limits(tier: str) -> Dict[str, Any]:
        """Get the limits for a specific tier."""
        return PLAN_LIMITS.get(tier, PLAN_LIMITS[SubscriptionTier.FREE])

    @staticmethod
    def can_activate_workflow(user: User, active_workflow_count: int) -> bool:
        """Check if user can activate another workflow."""
        limits = FeatureGate.get_limits(user.subscription_tier)
        return active_workflow_count < limits["max_active_workflows"]

    @staticmethod
    def can_use_ai_message(user: User, daily_message_count: int) -> bool:
        """Check if user is within their daily AI message limit."""
        limits = FeatureGate.get_limits(user.subscription_tier)
        return daily_message_count < limits["max_ai_messages_daily"]

    @staticmethod
    def has_connection_access(user: User, platform: str) -> bool:
        """Check if user has access to a specific integration platform."""
        limits = FeatureGate.get_limits(user.subscription_tier)
        allowed = limits["allowed_connections"]
        return "*" in allowed or platform.lower() in [p.lower() for p in allowed]
