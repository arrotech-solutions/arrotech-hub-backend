"""
Feature flags and plan-based limits for Arrotech Hub.
Based on the Master Implementation Prompt - Kenya-first pricing.

PLAN HIERARCHY:
- FREE (KES 0): Unified Visibility - Read-only access
- STARTER (KES 1,500): Unified Action - Solo productivity
- BUSINESS (KES 5,000): Unified Operations - SME operations
- PRO (KES 10,000): Unified Command Center - Agencies & scale
- ENTERPRISE (Custom): Everything unlocked + dedicated support
"""

from typing import Dict, Any, List, Set
from ..models import SubscriptionTier, User


# ============================================================================
# PLAN LIMITS CONFIGURATION (Authoritative - from Master Implementation Prompt)
# ============================================================================

PLAN_LIMITS: Dict[str, Dict[str, Any]] = {
    # -------------------------------------------------------------------------
    # FREE TIER - "Unified Visibility" - KES 0
    # Purpose: Discovery & visibility. Read-only access.
    # -------------------------------------------------------------------------
    SubscriptionTier.FREE: {
        # Usage Limits
        "ai_actions_monthly": 100,
        "automation_runs_monthly": 500,
        "max_active_workflows": 3,  # Templates only
        "team_members": 1,
        
        # Provider Limits (per category)
        "email_providers": 1,       # 1 email provider (Gmail or Outlook)
        "messaging_providers": 1,   # 1 messaging (Slack, Teams, or WhatsApp)
        "calendar_providers": 1,    # 1 calendar provider
        "task_providers": 1,        # 1 task tool (Jira, Trello, Asana, ClickUp)
        
        # Feature Flags
        "inbox_read": True,
        "inbox_send": False,
        "inbox_ai_reply": False,
        "inbox_multi_client": False,
        "inbox_message_triggers": False,
        
        "calendar_view": True,
        "calendar_create_edit": False,
        "calendar_smart_scheduler": False,
        "calendar_auto_followups": False,
        "calendar_advanced_rules": False,
        
        "tasks_view": True,
        "tasks_create_update": False,
        "tasks_multiple_tools": False,
        "tasks_analytics": False,
        "tasks_client_separation": False,
        
        "ai_context": "read_only",  # read_only, workspace, full_business, multi_client
        "ai_briefing": "weekly_fixed",  # weekly_fixed, daily_weekly, custom_role_based, multi_client_realtime
        "smart_scheduler": False,
        
        "api_access": False,
        "white_label": False,
        "sso": False,
        
        # Support
        "support_level": "community",
        
        # Allowed connections (all platforms available for read)
        "allowed_connections": [
            "gmail", "outlook", "microsoft_outlook",
            "slack", "microsoft_teams", "teams", "whatsapp", "whatsapp_business",
            "google_calendar", "google_workspace",  # Google Workspace for Gmail + Calendar
            "jira", "trello", "asana", "clickup",
            "mpesa", "context_tools"
        ],
    },
    
    # -------------------------------------------------------------------------
    # STARTER TIER - "Unified Action" - KES 1,500/month
    # Purpose: Solo productivity. Send, reply, create tasks.
    # -------------------------------------------------------------------------
    SubscriptionTier.STARTER: {
        # Usage Limits
        "ai_actions_monthly": 500,
        "automation_runs_monthly": 2000,
        "max_active_workflows": 5,
        "team_members": 1,
        
        # Provider Limits
        "email_providers": 2,
        "messaging_providers": 2,
        "calendar_providers": 2,
        "task_providers": 1,  # 1 task tool synced
        
        # Feature Flags
        "inbox_read": True,
        "inbox_send": True,
        "inbox_create_task_from_message": True,
        "inbox_ai_reply": False,
        "inbox_multi_client": False,
        "inbox_message_triggers": False,
        
        "calendar_view": True,
        "calendar_create_edit": True,
        "calendar_manual_scheduling": True,
        "calendar_smart_scheduler": False,
        "calendar_auto_followups": False,
        "calendar_advanced_rules": False,
        
        "tasks_view": True,
        "tasks_create_update": True,
        "tasks_multiple_tools": False,
        "tasks_analytics": False,
        "tasks_client_separation": False,
        
        "ai_context": "workspace",
        "ai_briefing": "daily_weekly",
        "smart_scheduler": False,
        
        "api_access": False,
        "white_label": False,
        "sso": False,
        
        # Support
        "support_level": "email",
        
        # Allowed connections
        "allowed_connections": [
            "gmail", "outlook", "microsoft_outlook",
            "slack", "microsoft_teams", "teams", "whatsapp", "whatsapp_business",
            "google_calendar", "outlook_calendar",
            "jira", "trello", "asana", "clickup",
            "mpesa", "context_tools",
            "google_workspace", "zoho_crm", "kra_portal"
        ],
    },
    
    # -------------------------------------------------------------------------
    # BUSINESS TIER - "Unified Operations" - KES 5,000/month
    # Purpose: SME operations. AI-assisted, Smart Scheduler.
    # -------------------------------------------------------------------------
    SubscriptionTier.BUSINESS: {
        # Usage Limits
        "ai_actions_monthly": 2000,
        "automation_runs_monthly": 15000,
        "max_active_workflows": 30,
        "team_members": 3,
        
        # Provider Limits
        "email_providers": 5,
        "messaging_providers": 5,
        "calendar_providers": 5,
        "task_providers": 5,  # Multiple task tools
        
        # Feature Flags
        "inbox_read": True,
        "inbox_send": True,
        "inbox_create_task_from_message": True,
        "inbox_ai_reply": True,
        "inbox_message_triggers": True,
        "inbox_multi_client": False,
        
        "calendar_view": True,
        "calendar_create_edit": True,
        "calendar_manual_scheduling": True,
        "calendar_smart_scheduler": True,
        "calendar_conflict_detection": True,
        "calendar_auto_followups": True,
        "calendar_advanced_rules": False,
        
        "tasks_view": True,
        "tasks_create_update": True,
        "tasks_multiple_tools": True,
        "tasks_analytics": True,
        "tasks_progress_tracking": True,
        "tasks_client_separation": False,
        
        "ai_context": "full_business",
        "ai_briefing": "custom_role_based",
        "smart_scheduler": True,
        
        "api_access": True,
        "api_requests_daily": 5000,
        "white_label": False,
        "sso": False,
        
        # Support
        "support_level": "priority",
        
        # Allowed connections - all major integrations
        "allowed_connections": [
            # Email & Messaging
            "gmail", "outlook", "microsoft_outlook",
            "slack", "microsoft_teams", "teams", "whatsapp", "whatsapp_business",
            # Calendar
            "google_calendar", "outlook_calendar",
            # Tasks
            "jira", "trello", "asana", "clickup", "notion",
            # CRM & Marketing
            "hubspot", "salesforce", "zoho_crm",
            "ga4", "google_analytics",
            "facebook", "facebook_marketing",
            "instagram", "instagram_graph",
            "linkedin", "linkedin_ads",
            "twitter", "twitter_ads",
            "tiktok",
            # E-commerce
            "shopify", "jumia", "kilimall",
            # Payments
            "mpesa", "stripe", "airtel", "airtel_money", "pesapal",
            "equity", "equity_bank",
            # Productivity
            "google_workspace", "zoom",
            # Analytics & Accounting
            "powerbi", "power_bi",
            "quickbooks", "quick_books", "zoho_books",
            "kra_portal",
            # Other
            "context_tools"
        ],
    },
    
    # -------------------------------------------------------------------------
    # PRO TIER - "Unified Command Center" - KES 10,000/month
    # Purpose: Agencies & scale. Multi-client, advanced features.
    # -------------------------------------------------------------------------
    SubscriptionTier.PRO: {
        # Usage Limits
        "ai_actions_monthly": 5000,
        "automation_runs_monthly": 50000,
        "max_active_workflows": 999999,  # Unlimited
        "team_members": 10,
        
        # Provider Limits - Unlimited
        "email_providers": 999999,
        "messaging_providers": 999999,
        "calendar_providers": 999999,
        "task_providers": 999999,
        
        # Feature Flags - All enabled
        "inbox_read": True,
        "inbox_send": True,
        "inbox_create_task_from_message": True,
        "inbox_ai_reply": True,
        "inbox_message_triggers": True,
        "inbox_multi_client": True,
        "inbox_sla_tracking": True,
        
        "calendar_view": True,
        "calendar_create_edit": True,
        "calendar_manual_scheduling": True,
        "calendar_smart_scheduler": True,
        "calendar_conflict_detection": True,
        "calendar_auto_followups": True,
        "calendar_advanced_rules": True,
        "calendar_cross_client": True,
        
        "tasks_view": True,
        "tasks_create_update": True,
        "tasks_multiple_tools": True,
        "tasks_analytics": True,
        "tasks_progress_tracking": True,
        "tasks_client_separation": True,
        "tasks_advanced_reports": True,
        
        "ai_context": "multi_client",
        "ai_chat_mode": "power",  # reasoning, debugging
        "ai_briefing": "multi_client_realtime",
        "smart_scheduler": True,
        "smart_scheduler_advanced": True,
        
        "api_access": True,
        "api_requests_daily": 50000,
        "white_label": False,
        "sso": False,
        
        # Support
        "support_level": "dedicated",
        
        # Allowed connections - ALL
        "allowed_connections": ["*"],
    },
    
    # -------------------------------------------------------------------------
    # ENTERPRISE TIER - Custom Pricing
    # Purpose: Large organizations. Everything + custom features.
    # -------------------------------------------------------------------------
    SubscriptionTier.ENTERPRISE: {
        # Usage Limits - Unlimited
        "ai_actions_monthly": 999999,
        "automation_runs_monthly": 999999,
        "max_active_workflows": 999999,
        "team_members": 999999,
        
        # Provider Limits - Unlimited
        "email_providers": 999999,
        "messaging_providers": 999999,
        "calendar_providers": 999999,
        "task_providers": 999999,
        
        # All features enabled
        "inbox_read": True,
        "inbox_send": True,
        "inbox_create_task_from_message": True,
        "inbox_ai_reply": True,
        "inbox_message_triggers": True,
        "inbox_multi_client": True,
        "inbox_sla_tracking": True,
        
        "calendar_view": True,
        "calendar_create_edit": True,
        "calendar_manual_scheduling": True,
        "calendar_smart_scheduler": True,
        "calendar_conflict_detection": True,
        "calendar_auto_followups": True,
        "calendar_advanced_rules": True,
        "calendar_cross_client": True,
        
        "tasks_view": True,
        "tasks_create_update": True,
        "tasks_multiple_tools": True,
        "tasks_analytics": True,
        "tasks_progress_tracking": True,
        "tasks_client_separation": True,
        "tasks_advanced_reports": True,
        
        "ai_context": "multi_client",
        "ai_chat_mode": "power",
        "ai_briefing": "multi_client_realtime",
        "ai_dedicated_models": True,
        "smart_scheduler": True,
        "smart_scheduler_advanced": True,
        
        "api_access": True,
        "api_requests_daily": 999999,
        "white_label": True,
        "sso": True,
        "compliance_audit_logs": True,
        "private_deployment": True,
        "custom_integrations": 2,  # Per year
        
        # Support
        "support_level": "dedicated_account_manager",
        
        # Allowed connections - ALL
        "allowed_connections": ["*"],
    },
}


# ============================================================================
# PRICING CONFIGURATION (KES)
# ============================================================================

PLAN_PRICING: Dict[str, Dict[str, Any]] = {
    SubscriptionTier.FREE: {
        "price_monthly": 0,
        "currency": "KES",
        "name": "Free",
        "tagline": "Unified Visibility",
        "description": "Perfect for discovery. See all your work in one place."
    },
    SubscriptionTier.STARTER: {
        "price_monthly": 1500,
        "currency": "KES",
        "name": "Starter",
        "tagline": "Unified Action",
        "description": "Essential tools for solo productivity."
    },
    SubscriptionTier.BUSINESS: {
        "price_monthly": 5000,
        "currency": "KES",
        "name": "Business",
        "tagline": "Unified Operations",
        "description": "Full power for growing businesses."
    },
    SubscriptionTier.PRO: {
        "price_monthly": 10000,
        "currency": "KES",
        "name": "Pro / Agency",
        "tagline": "Unified Command Center",
        "description": "Ultimate solution for agencies and scale."
    },
    SubscriptionTier.ENTERPRISE: {
        "price_monthly": None,  # Custom
        "currency": "KES",
        "name": "Enterprise",
        "tagline": "Custom Solution",
        "description": "Everything unlocked plus dedicated support."
    },
}


# ============================================================================
# ADD-ONS PRICING
# ============================================================================

ADDON_PRICING: Dict[str, Dict[str, Any]] = {
    "automation_runs_1000": {
        "price": 500,
        "currency": "KES",
        "runs": 1000,
        "description": "+1,000 automation runs"
    },
    "automation_runs_5000": {
        "price": 2000,
        "currency": "KES",
        "runs": 5000,
        "description": "+5,000 automation runs"
    },
}


# ============================================================================
# FEATURE GATE CLASS
# ============================================================================

class FeatureGate:
    """Service to check user permissions based on their subscription tier."""
    
    @staticmethod
    def get_limits(tier: str) -> Dict[str, Any]:
        """Get the limits for a specific tier."""
        # Convert string tier to enum if needed
        if isinstance(tier, str) and not isinstance(tier, SubscriptionTier):
            try:
                tier_enum = SubscriptionTier(tier.lower())
            except ValueError:
                tier_enum = SubscriptionTier.FREE
        else:
            tier_enum = tier
        return PLAN_LIMITS.get(tier_enum, PLAN_LIMITS[SubscriptionTier.FREE])
    
    @staticmethod
    def get_pricing(tier: str) -> Dict[str, Any]:
        """Get pricing info for a specific tier."""
        # Convert string tier to enum if needed
        if isinstance(tier, str) and not isinstance(tier, SubscriptionTier):
            try:
                tier_enum = SubscriptionTier(tier.lower())
            except ValueError:
                tier_enum = SubscriptionTier.FREE
        else:
            tier_enum = tier
        return PLAN_PRICING.get(tier_enum, PLAN_PRICING[SubscriptionTier.FREE])
    
    @staticmethod
    def can_activate_workflow(user: User, active_workflow_count: int) -> bool:
        """Check if user can activate another workflow."""
        limits = FeatureGate.get_limits(user.subscription_tier)
        return active_workflow_count < limits["max_active_workflows"]

    @staticmethod
    def can_use_ai_action(user: User, monthly_action_count: int) -> bool:
        """Check if user is within their monthly AI action limit."""
        limits = FeatureGate.get_limits(user.subscription_tier)
        return monthly_action_count < limits["ai_actions_monthly"]
    
    @staticmethod
    def can_use_automation_run(user: User, monthly_run_count: int) -> bool:
        """Check if user is within their monthly automation run limit."""
        limits = FeatureGate.get_limits(user.subscription_tier)
        return monthly_run_count < limits["automation_runs_monthly"]
    
    @staticmethod
    def can_use_ai_message(user: User, daily_message_count: int) -> bool:
        """
        Legacy compatibility - maps to AI actions.
        Kept for backward compatibility with existing code.
        """
        # check against monthly limit directly to avoid artificial daily caps
        limits = FeatureGate.get_limits(user.subscription_tier)
        monthly_limit = limits["ai_actions_monthly"]
        return daily_message_count < monthly_limit

    @staticmethod
    def has_connection_access(user: User, platform: str) -> bool:
        """Check if user has access to a specific integration platform."""
        limits = FeatureGate.get_limits(user.subscription_tier)
        allowed = limits["allowed_connections"]
        return "*" in allowed or platform.lower() in [p.lower() for p in allowed]
    
    @staticmethod
    def has_feature(user: User, feature_name: str) -> bool:
        """Check if user has access to a specific feature."""
        limits = FeatureGate.get_limits(user.subscription_tier)
        return limits.get(feature_name, False)
    
    @staticmethod
    def get_provider_limit(user: User, provider_type: str) -> int:
        """Get the limit for a specific provider type (email, messaging, calendar, task)."""
        limits = FeatureGate.get_limits(user.subscription_tier)
        key = f"{provider_type}_providers"
        return limits.get(key, 1)
    
    @staticmethod
    def get_usage_percentage(used: int, limit: int) -> float:
        """Calculate usage percentage."""
        if limit == 0 or limit >= 999999:
            return 0.0
        return (used / limit) * 100
    
    @staticmethod
    def should_show_warning(used: int, limit: int) -> bool:
        """Check if usage is at 80% threshold for soft warning."""
        if limit >= 999999:
            return False
        return FeatureGate.get_usage_percentage(used, limit) >= 80
    
    @staticmethod
    def is_at_limit(used: int, limit: int) -> bool:
        """Check if usage has reached 100% for hard enforcement."""
        if limit >= 999999:
            return False
        return used >= limit
    
    @staticmethod
    def get_upgrade_message(current_tier: str, feature: str) -> str:
        """Get contextual upgrade message for a gated feature."""
        messages = {
            "inbox_send": "Upgrade to Starter to send and reply to messages",
            "inbox_ai_reply": "Upgrade to Business for AI-assisted replies",
            "inbox_multi_client": "Upgrade to Pro for multi-client inbox management",
            "calendar_create_edit": "Upgrade to Starter to create and edit events",
            "calendar_smart_scheduler": "Upgrade to Business to unlock Smart Scheduling",
            "tasks_create_update": "Upgrade to Starter to create and update tasks",
            "tasks_analytics": "Upgrade to Business for task analytics",
            "tasks_client_separation": "Upgrade to Pro for client-level task separation",
            "ai_actions": "You're close to your AI action limit. Upgrade for more.",
            "automation_runs": "You're running low on automation runs this month.",
        }
        return messages.get(feature, f"Upgrade to unlock {feature}")
