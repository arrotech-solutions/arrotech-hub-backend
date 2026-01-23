"""
Tier-based access control for Arrotech Hub.
Handles checking user permissions and raising appropriate upgrade notifications.
"""

from fastapi import HTTPException, status
from typing import Optional
from ..models import User, SubscriptionTier
from .feature_flags import FeatureGate


class TierGateError(HTTPException):
    """Custom exception for tier-based access restrictions."""
    
    def __init__(
        self, 
        feature: str, 
        required_tier: str,
        current_tier: str,
        upgrade_url: str = "/pricing"
    ):
        detail = {
            "error": "upgrade_required",
            "message": f"This feature requires {required_tier} plan or higher",
            "feature": feature,
            "current_tier": current_tier,
            "required_tier": required_tier,
            "upgrade_url": upgrade_url,
            "status_code": 402  # Payment Required
        }
        super().__init__(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, 
            detail=detail
        )


def check_connection_access(user: User, platform: str) -> None:
    """
    Check if user has access to a connection platform.
    Raises TierGateError if access is denied.
    
    Args:
        user: The current user
        platform: Platform ID (e.g., 'google_workspace', 'hubspot')
        
    Raises:
        TierGateError: If user's tier doesn't have access to the platform
    """
    # Debug logging
    print(f"[TIER CHECK] User: {user.email}, Tier: {user.subscription_tier}, Platform: {platform}")
    
    has_access = FeatureGate.has_connection_access(user, platform)
    print(f"[TIER CHECK] Has access: {has_access}")
    
    if not has_access:
        required_tier = get_tier_for_platform(platform)
        print(f"[TIER CHECK] Access DENIED - Required tier: {required_tier}")
        raise TierGateError(
            feature=f"{format_platform_name(platform)} integration",
            required_tier=required_tier,
            current_tier=format_tier_name(user.subscription_tier)
        )
    
    print(f"[TIER CHECK] Access GRANTED")


def check_workflow_limit(user: User, active_workflow_count: int) -> None:
    """
    Check if user can activate another workflow.
    Raises TierGateError if limit exceeded.
    
    Args:
        user: The current user
        active_workflow_count: Number of currently active workflows
        
    Raises:
        TierGateError: If user has reached their workflow limit
    """
    limits = FeatureGate.get_limits(user.subscription_tier)
    max_workflows = limits["max_active_workflows"]
    
    if active_workflow_count >= max_workflows:
        # Determine next tier with higher limit
        next_tier = get_next_tier(user.subscription_tier)
        raise TierGateError(
            feature=f"More than {max_workflows} active workflows",
            required_tier=format_tier_name(next_tier),
            current_tier=format_tier_name(user.subscription_tier)
        )


def check_ai_message_limit(user: User, daily_message_count: int) -> None:
    """
    Check if user is within their daily AI message limit.
    Raises TierGateError if limit exceeded.
    
    Args:
        user: The current user
        daily_message_count: Number of AI messages used today
        
    Raises:
        TierGateError: If user has exceeded their daily AI message limit
    """
    limits = FeatureGate.get_limits(user.subscription_tier)
    max_messages = limits["max_ai_messages_daily"]
    
    if daily_message_count >= max_messages:
        next_tier = get_next_tier(user.subscription_tier)
        raise TierGateError(
            feature=f"More than {max_messages} AI messages per day",
            required_tier=format_tier_name(next_tier),
            current_tier=format_tier_name(user.subscription_tier)
        )


def get_tier_for_platform(platform: str) -> str:
    """
    Determine the minimum tier required for a platform.
    
    Args:
        platform: Platform ID
        
    Returns:
        Formatted tier name (e.g., "Biashara Lite", "Business Pro")
    """
    platform_lower = platform.lower().replace("_", "").replace("-", "")
    
    # Enterprise-only platforms
    enterprise_platforms = ["sap", "oracle", "customerp"]
    if any(p in platform_lower for p in enterprise_platforms):
        return "Enterprise"
    
    # Business Pro platforms
    pro_platforms = [
        "hubspot", "salesforce", "ga4", "googleanalytics",
        "facebook", "instagram", "linkedin", "twitter",
        "shopify", "jumia", "kilimall", "stripe",
        "airtel", "pesapal", "equity", "asana", "trello",
        "clickup", "notion", "jira", "zoom", "microsoftteams",
        "teams", "powerbi", "quickbooks", "zohobooks"
    ]
    if any(p in platform_lower for p in pro_platforms):
        return "Business Pro"
    
    # Biashara Lite platforms
    lite_platforms = [
        "googleworkspace", "gmail", "microsoftoutlook",
        "outlook", "whatsappbusiness", "whatsapp", "zohocrm"
    ]
    if any(p in platform_lower for p in lite_platforms):
        return "Biashara Lite"
    
    # Free tier default
    return "Free"


def get_next_tier(current_tier: str) -> str:
    """
    Get the next tier above the current one.
    
    Args:
        current_tier: Current subscription tier
        
    Returns:
        Next tier identifier
    """
    tier_hierarchy = [
        SubscriptionTier.FREE,
        SubscriptionTier.LITE,
        SubscriptionTier.PRO,
        SubscriptionTier.ENTERPRISE
    ]
    
    try:
        current_index = tier_hierarchy.index(current_tier)
        if current_index < len(tier_hierarchy) - 1:
            return tier_hierarchy[current_index + 1]
    except ValueError:
        pass
    
    # Default to LITE if current tier not found
    return SubscriptionTier.LITE


def format_tier_name(tier: str) -> str:
    """
    Format tier for user-friendly display.
    
    Args:
        tier: Tier identifier (e.g., 'free', 'lite', 'pro')
        
    Returns:
        Formatted tier name (e.g., 'Free', 'Biashara Lite', 'Business Pro')
    """
    tier_names = {
        SubscriptionTier.FREE: "Free",
        SubscriptionTier.LITE: "Biashara Lite",
        SubscriptionTier.PRO: "Business Pro",
        SubscriptionTier.ENTERPRISE: "Enterprise"
    }
    return tier_names.get(tier, tier.title())


def format_platform_name(platform: str) -> str:
    """
    Format platform name for user-friendly display.
    
    Args:
        platform: Platform ID (e.g., 'google_workspace', 'hubspot')
        
    Returns:
        Formatted platform name (e.g., 'Google Workspace', 'HubSpot')
    """
    # Special cases
    special_names = {
        "google_workspace": "Google Workspace",
        "microsoft_outlook": "Microsoft Outlook",
        "microsoft_teams": "Microsoft Teams",
        "whatsapp_business": "WhatsApp Business",
        "ga4": "Google Analytics 4",
        "google_analytics": "Google Analytics",
        "facebook_marketing": "Facebook Marketing",
        "instagram_graph": "Instagram",
        "linkedin_ads": "LinkedIn Ads",
        "twitter_ads": "Twitter Ads",
        "mpesa": "M-Pesa",
        "airtel_money": "Airtel Money",
        "equity_bank": "Equity Bank",
        "power_bi": "Power BI",
        "quick_books": "QuickBooks",
        "zoho_crm": "Zoho CRM",
        "zoho_books": "Zoho Books"
    }
    
    if platform in special_names:
        return special_names[platform]
    
    # Default: capitalize each word
    return " ".join(word.capitalize() for word in platform.replace("_", " ").split())
