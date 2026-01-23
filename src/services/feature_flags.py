"""
Feature flags and plan-based limits for Arrotech Hub.
"""

from typing import Dict, Any, Optional
from ..models import SubscriptionTier, User

# Plan Limitations Configuration
PLAN_LIMITS: Dict[str, Dict[str, Any]] = {
    SubscriptionTier.FREE: {
        "max_active_workflows": 3,  # Increased from 1
        "max_ai_messages_daily": 10,  # Increased from 5
        "allowed_connections": ["mpesa", "slack", "context_tools"],
        "support_level": "community",
        "reports": "basic",
        "team_members": 1,
        "api_access": False
    },
    SubscriptionTier.LITE: {  # NEW TIER - Biashara Lite
        "max_active_workflows": 10,
        "max_ai_messages_daily": 50,
        "allowed_connections": [
            "mpesa", "slack", "context_tools",
            "google_workspace", "gmail", "microsoft_outlook", 
            "whatsapp_business", "zoho_crm"
        ],
        "support_level": "email",
        "reports": "weekly",
        "team_members": 1,
        "api_access": False
    },
    SubscriptionTier.PRO: {  # Previously STARTER, upgraded features
        "max_active_workflows": 50,
        "max_ai_messages_daily": 500,
        "allowed_connections": [
            # All LITE connections plus advanced integrations
            "mpesa", "slack", "context_tools", "google_workspace", "gmail",
            "microsoft_outlook", "whatsapp_business", "zoho_crm",
            # Business & Marketing
            "hubspot", "salesforce", "ga4", "google_analytics",
            "facebook_marketing", "facebook", "instagram_graph", "instagram",
            "linkedin_ads", "linkedin", "twitter_ads", "twitter",
            # E-commerce
            "shopify", "jumia", "kilimall",
            # Payments
            "stripe", "airtel_money", "airtel", "pesapal", "equity_bank", "equity",
            # Productivity & Project Management
            "asana", "trello", "clickup", "notion", "jira",
            # Communication & Collaboration
            "zoom", "microsoft_teams", "teams",
            # Analytics & Accounting
            "power_bi", "powerbi", "quickbooks", "quick_books", "zoho_books"
        ],
        "support_level": "priority_chat",
        "reports": "daily_auto",
        "team_members": 5,
        "api_access": True,
        "api_requests_daily": 5000
    },
    SubscriptionTier.ENTERPRISE: {  # NEW TIER
        "max_active_workflows": 9999,  # Unlimited
        "max_ai_messages_daily": 9999,  # Unlimited
        "allowed_connections": ["*"],  # All connections allowed
        "support_level": "dedicated_whatsapp",
        "reports": "real_time_custom",
        "team_members": 9999,  # Unlimited
        "api_access": True,
        "api_requests_daily": 999999,  # Unlimited
        "white_label": True,
        "sso": True,
        "custom_integrations": 2  # Per year
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
