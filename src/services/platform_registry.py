"""
Platform Registry Service for managing dynamic platforms and their capabilities.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PlatformCapability:
    """Represents a capability of a platform."""
    name: str
    description: str
    tool_name: str
    input_schema: Dict[str, Any]
    operations: List[str]


@dataclass
class Platform:
    """Represents a platform with its capabilities."""
    id: str
    name: str
    description: str
    icon: str
    features: List[str]
    capabilities: List[PlatformCapability]
    config_schema: Dict[str, Any]
    test_function: str  # Name of the test function in the service


class PlatformRegistry:
    """Registry for managing dynamic platforms and their capabilities."""
    
    def __init__(self):
        self.platforms: Dict[str, Platform] = {}
        self._initialize_default_platforms()
    
    def _initialize_default_platforms(self):
        """Initialize default platforms with their capabilities."""
        
        # HubSpot Platform
        hubspot_capabilities = [
            PlatformCapability(
                name="Contact Management",
                description="Manage HubSpot contacts with full CRUD operations",
                tool_name="hubspot_contact_operations",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["read", "create", "update", "search", "segment"]},
                        "contact_data": {"type": "object"},
                        "filters": {"type": "object"},
                        "limit": {"type": "integer", "default": 50},
                        "properties": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["operation"]
                },
                operations=["read", "create", "update", "search", "segment"]
            ),
            PlatformCapability(
                name="Deal Management",
                description="Manage HubSpot deals - create, update, track, and analyze deal pipeline",
                tool_name="hubspot_deal_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["read", "create", "update", "analyze"]},
                        "deal_data": {"type": "object"},
                        "filters": {"type": "object"},
                        "limit": {"type": "integer", "default": 20}
                    },
                    "required": ["operation"]
                },
                operations=["read", "create", "update", "analyze"]
            ),
            PlatformCapability(
                name="Analytics",
                description="Get HubSpot analytics and performance metrics",
                tool_name="hubspot_analytics",
                input_schema={
                    "type": "object",
                    "properties": {
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                        "metrics": {"type": "array", "items": {"type": "string"}}
                    }
                },
                operations=["get_analytics"]
            )
        ]
        
        self.platforms["hubspot"] = Platform(
            id="hubspot",
            name="HubSpot",
            description="CRM and marketing automation platform",
            icon="hubspot",
            features=[
                "Contact management",
                "Deal tracking",
                "Email marketing",
                "Analytics"
            ],
            capabilities=hubspot_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "api_key": {"type": "string", "description": "HubSpot API Key"}
                },
                "required": ["api_key"]
            },
            test_function="test_hubspot_connection"
        )
        
        # GA4 Platform
        ga4_capabilities = [
            PlatformCapability(
                name="Analytics Dashboard",
                description="Get comprehensive GA4 analytics including traffic, conversions, user behavior, and custom reports",
                tool_name="ga4_analytics_dashboard",
                input_schema={
                    "type": "object",
                    "properties": {
                        "report_type": {"type": "string", "enum": ["traffic", "conversions", "user_behavior", "custom", "ecommerce"]},
                        "date_range": {"type": "string", "default": "last_30_days"},
                        "metrics": {"type": "array", "items": {"type": "string"}},
                        "dimensions": {"type": "array", "items": {"type": "string"}},
                        "filters": {"type": "object"}
                    },
                    "required": ["report_type"]
                },
                operations=["get_traffic", "get_conversions", "get_user_behavior", "get_custom_reports", "get_ecommerce"]
            ),
            PlatformCapability(
                name="User Behavior",
                description="Analyze user behavior patterns and engagement metrics",
                tool_name="ga4_user_behavior",
                input_schema={
                    "type": "object",
                    "properties": {
                        "hours": {"type": "integer", "default": 24},
                        "user_segments": {"type": "array", "items": {"type": "string"}},
                        "engagement_metrics": {"type": "array", "items": {"type": "string"}}
                    }
                },
                operations=["analyze_behavior", "get_segments", "get_engagement"]
            )
        ]
        
        self.platforms["ga4"] = Platform(
            id="ga4",
            name="Google Analytics 4",
            description="Web analytics and reporting",
            icon="analytics",
            features=[
                "Traffic analysis",
                "Conversion tracking",
                "User behavior",
                "Custom reports"
            ],
            capabilities=ga4_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "property_id": {"type": "string", "description": "GA4 Property ID"},
                    "credentials_file": {"type": "string", "description": "Service Account JSON file path"}
                },
                "required": ["property_id", "credentials_file"]
            },
            test_function="test_ga4_connection"
        )
        
        # Slack Platform
        slack_capabilities = [
            PlatformCapability(
                name="Team Communication",
                description="Send messages, reports, and notifications to Slack channels with rich formatting",
                tool_name="slack_team_communication",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["send_message", "send_report", "send_alert", "schedule_message"]},
                        "channel": {"type": "string"},
                        "message": {"type": "string"},
                        "report_type": {"type": "string"},
                        "blocks": {"type": "array"},
                        "schedule_time": {"type": "string"}
                    },
                    "required": ["action", "channel"]
                },
                operations=["send_message", "send_report", "send_alert", "schedule_message"]
            ),
            PlatformCapability(
                name="Team Management",
                description="Manage Slack team channels, members, and workspace settings",
                tool_name="slack_team_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["list_channels", "get_members", "create_channel", "invite_users", "archive_channel", "set_topic", "set_purpose"]},
                        "channel_name": {"type": "string"},
                        "user_ids": {"type": "array", "items": {"type": "string"}},
                        "topic": {"type": "string"},
                        "purpose": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["list_channels", "get_members", "create_channel", "invite_users", "archive_channel", "set_topic", "set_purpose"]
            ),
            PlatformCapability(
                name="File Management",
                description="Upload and manage files in Slack channels",
                tool_name="slack_file_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["upload_file"]},
                        "channel": {"type": "string"},
                        "file_path": {"type": "string"},
                        "title": {"type": "string"},
                        "comment": {"type": "string"}
                    },
                    "required": ["action", "channel", "file_path"]
                },
                operations=["upload_file"]
            ),
            PlatformCapability(
                name="Reactions",
                description="Add reactions to Slack messages",
                tool_name="slack_reactions",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["add_reaction"]},
                        "channel": {"type": "string"},
                        "timestamp": {"type": "string"},
                        "emoji": {"type": "string"}
                    },
                    "required": ["action", "channel", "timestamp", "emoji"]
                },
                operations=["add_reaction"]
            ),
            PlatformCapability(
                name="Search",
                description="Search for messages and content in Slack",
                tool_name="slack_search",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["search_messages"]},
                        "query": {"type": "string"},
                        "channel": {"type": "string"},
                        "limit": {"type": "integer", "default": 20}
                    },
                    "required": ["action", "query"]
                },
                operations=["search_messages"]
            ),
            PlatformCapability(
                name="User Management",
                description="Get user information and list workspace users",
                tool_name="slack_user_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_user_info", "list_users"]},
                        "user_id": {"type": "string"},
                        "user_name": {"type": "string"},
                        "include_bots": {"type": "boolean", "default": False}
                    },
                    "required": ["action"]
                },
                operations=["get_user_info", "list_users"]
            ),
            PlatformCapability(
                name="Pins",
                description="Pin messages and get pinned content from Slack channels",
                tool_name="slack_pins",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["pin_message", "get_pinned_messages"]},
                        "channel": {"type": "string"},
                        "timestamp": {"type": "string"}
                    },
                    "required": ["action", "channel"]
                },
                operations=["pin_message", "get_pinned_messages"]
            ),
            # New Slack Capabilities
            PlatformCapability(
                name="AI Agents",
                description="Execute Slack commands and manage AI agent interactions",
                tool_name="slack_ai_agents",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["execute_command", "list_commands", "get_command_info"]},
                        "command": {"type": "string"},
                        "channel": {"type": "string"},
                        "user_id": {"type": "string"},
                        "args": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["action"]
                },
                operations=["execute_command", "list_commands", "get_command_info"]
            ),
            PlatformCapability(
                name="File Operations",
                description="Read, write, and manage files in Slack with advanced operations",
                tool_name="slack_file_operations",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["upload_file", "download_file", "list_files", "delete_file", "get_file_info"]},
                        "channel": {"type": "string"},
                        "file_path": {"type": "string"},
                        "file_id": {"type": "string"},
                        "title": {"type": "string"},
                        "comment": {"type": "string"},
                        "file_type": {"type": "string"}
                    },
                    "required": ["action"]
                },
                operations=["upload_file", "download_file", "list_files", "delete_file", "get_file_info"]
            ),
            PlatformCapability(
                name="Link Management",
                description="Manage and track links shared in Slack channels",
                tool_name="slack_link_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_shared_links", "track_link", "get_link_analytics"]},
                        "channel": {"type": "string"},
                        "url": {"type": "string"},
                        "date_range": {"type": "string"}
                    },
                    "required": ["action"]
                },
                operations=["get_shared_links", "track_link", "get_link_analytics"]
            ),
            PlatformCapability(
                name="Workflows",
                description="Execute and manage Slack workflows and automation",
                tool_name="slack_workflows",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["execute_workflow", "list_workflows", "get_workflow_info", "create_workflow"]},
                        "workflow_id": {"type": "string"},
                        "workflow_name": {"type": "string"},
                        "channel": {"type": "string"},
                        "inputs": {"type": "object"}
                    },
                    "required": ["action"]
                },
                operations=["execute_workflow", "list_workflows", "get_workflow_info", "create_workflow"]
            ),
            PlatformCapability(
                name="Webhooks",
                description="Send messages via Slack incoming webhooks",
                tool_name="slack_webhooks",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["send_webhook", "create_webhook", "list_webhooks"]},
                        "webhook_url": {"type": "string"},
                        "channel": {"type": "string"},
                        "message": {"type": "string"},
                        "blocks": {"type": "array"}
                    },
                    "required": ["action"]
                },
                operations=["send_webhook", "create_webhook", "list_webhooks"]
            ),
            PlatformCapability(
                name="User Context",
                description="Read user profiles, team information, and manage user context",
                tool_name="slack_user_context",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_user_profile", "update_user_profile", "get_team_info", "get_user_by_email", "get_user_status"]},
                        "user_id": {"type": "string"},
                        "user_email": {"type": "string"},
                        "profile_data": {"type": "object"},
                        "status_text": {"type": "string"},
                        "status_emoji": {"type": "string"}
                    },
                    "required": ["action"]
                },
                operations=["get_user_profile", "update_user_profile", "get_team_info", "get_user_by_email", "get_user_status"]
            ),
            PlatformCapability(
                name="Advanced Features",
                description="Advanced Slack features including custom message formatting and reminders",
                tool_name="slack_advanced_features",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["add_reaction", "remove_reaction", "set_reminder", "list_reminders", "customize_message"]},
                        "channel": {"type": "string"},
                        "timestamp": {"type": "string"},
                        "emoji": {"type": "string"},
                        "reminder_text": {"type": "string"},
                        "reminder_time": {"type": "string"},
                        "message_blocks": {"type": "array"}
                    },
                    "required": ["action"]
                },
                operations=["add_reaction", "remove_reaction", "set_reminder", "list_reminders", "customize_message"]
            ),
            PlatformCapability(
                name="Admin Tools",
                description="Admin tools for managing user groups, channels, and workspace settings",
                tool_name="slack_admin_tools",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["list_user_groups", "create_user_group", "update_user_group", "delete_user_group", "manage_conversations", "get_workspace_stats"]},
                        "group_name": {"type": "string"},
                        "group_handle": {"type": "string"},
                        "user_ids": {"type": "array", "items": {"type": "string"}},
                        "description": {"type": "string"},
                        "channel_id": {"type": "string"}
                    },
                    "required": ["action"]
                },
                operations=["list_user_groups", "create_user_group", "update_user_group", "delete_user_group", "manage_conversations", "get_workspace_stats"]
            ),
            PlatformCapability(
                name="Channel Analytics",
                description="Read channel history and get analytics data",
                tool_name="slack_channel_analytics",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_channel_history", "get_group_history", "get_dm_history", "get_channel_stats", "get_message_analytics"]},
                        "channel": {"type": "string"},
                        "limit": {"type": "integer", "default": 100},
                        "oldest": {"type": "string"},
                        "latest": {"type": "string"},
                        "inclusive": {"type": "boolean", "default": False}
                    },
                    "required": ["action", "channel"]
                },
                operations=["get_channel_history", "get_group_history", "get_dm_history", "get_channel_stats", "get_message_analytics"]
            ),
            PlatformCapability(
                name="Search Discovery",
                description="Advanced search capabilities for messages, files, and content",
                tool_name="slack_search_discovery",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["search_messages", "search_files", "search_all", "get_search_suggestions"]},
                        "query": {"type": "string"},
                        "channel": {"type": "string"},
                        "user": {"type": "string"},
                        "date_from": {"type": "string"},
                        "date_to": {"type": "string"},
                        "count": {"type": "integer", "default": 20},
                        "sort": {"type": "string", "enum": ["score", "timestamp"]}
                    },
                    "required": ["action", "query"]
                },
                operations=["search_messages", "search_files", "search_all", "get_search_suggestions"]
            ),
            PlatformCapability(
                name="Workspace Management",
                description="Manage workspace settings, team information, and workspace-wide operations",
                tool_name="slack_workspace_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_workspace_info", "get_team_stats", "list_workspace_channels", "get_workspace_settings", "get_workspace_analytics"]},
                        "workspace_id": {"type": "string"},
                        "include_private": {"type": "boolean", "default": False},
                        "include_archived": {"type": "boolean", "default": False}
                    },
                    "required": ["action"]
                },
                operations=["get_workspace_info", "get_team_stats", "list_workspace_channels", "get_workspace_settings", "get_workspace_analytics"]
            )
        ]
        
        self.platforms["slack"] = Platform(
            id="slack",
            name="Slack",
            description="Team communication platform",
            icon="slack",
            features=[
                "Message sending",
                "Channel management",
                "Automated notifications",
                "Team collaboration"
            ],
            capabilities=slack_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "bot_token": {"type": "string", "description": "Slack Bot Token"}
                },
                "required": ["bot_token"]
            },
            test_function="test_slack_connection"
        )
        
        # WhatsApp Platform
        whatsapp_capabilities = [
            PlatformCapability(
                name="Messaging",
                description="Send WhatsApp messages to phone numbers with rich media support",
                tool_name="whatsapp_messaging",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["send_message", "send_media", "send_location"]},
                        "to_number": {"type": "string"},
                        "message": {"type": "string"},
                        "media_url": {"type": "string"},
                        "media_type": {"type": "string", "enum": ["image", "video", "audio", "document"]}
                    },
                    "required": ["action", "to_number"]
                },
                operations=["send_message", "send_media", "send_location"]
            ),
            PlatformCapability(
                name="Templates",
                description="Send WhatsApp template messages for business communications",
                tool_name="whatsapp_templates",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["send_template", "list_templates", "create_template"]},
                        "to_number": {"type": "string"},
                        "template_name": {"type": "string"},
                        "language_code": {"type": "string", "default": "en_US"},
                        "components": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["action"]
                },
                operations=["send_template", "list_templates", "create_template"]
            )
        ]
        
        self.platforms["whatsapp"] = Platform(
            id="whatsapp",
            name="WhatsApp Business",
            description="WhatsApp Business API for messaging and templates",
            icon="whatsapp",
            features=[
                "Direct messaging",
                "Template messages",
                "Media sharing",
                "Business API"
            ],
            capabilities=whatsapp_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "phone_number_id": {"type": "string", "description": "WhatsApp Phone Number ID"},
                    "access_token": {"type": "string", "description": "WhatsApp Access Token"}
                },
                "required": ["phone_number_id", "access_token"]
            },
            test_function="test_whatsapp_connection"
        )

        # Facebook Platform
        facebook_capabilities = [
            PlatformCapability(
                name="Content Management",
                description="Create, schedule, and manage Facebook posts and content",
                tool_name="social_media_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["schedule_post", "analyze_performance", "engage_audience", "create_campaign"]},
                        "content": {"type": "object"},
                        "schedule": {"type": "object"},
                        "campaign_data": {"type": "object"},
                        "date_range": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["schedule_post", "analyze_performance", "engage_audience", "create_campaign"]
            ),
            PlatformCapability(
                name="Analytics",
                description="Get Facebook page analytics and performance metrics",
                tool_name="social_media_analytics",
                input_schema={
                    "type": "object",
                    "properties": {
                        "date_range": {"type": "string", "default": "7d"},
                        "platform": {"type": "string", "default": "facebook"}
                    }
                },
                operations=["get_analytics"]
            )
        ]

        self.platforms["facebook"] = Platform(
            id="facebook",
            name="Facebook",
            description="Facebook Pages API for content management and analytics",
            icon="facebook",
            features=[
                "Post scheduling",
                "Content management",
                "Page analytics",
                "Campaign creation"
            ],
            capabilities=facebook_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "description": "Facebook Access Token"},
                    "page_id": {"type": "string", "description": "Facebook Page ID"},
                    "app_id": {"type": "string", "description": "Facebook App ID"},
                    "app_secret": {"type": "string", "description": "Facebook App Secret"}
                },
                "required": ["access_token", "page_id"]
            },
            test_function="test_facebook_connection"
        )

        # Twitter Platform
        twitter_capabilities = [
            PlatformCapability(
                name="Content Management",
                description="Create, schedule, and manage Twitter tweets and content",
                tool_name="social_media_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["schedule_post", "analyze_performance", "engage_audience", "create_campaign"]},
                        "content": {"type": "object"},
                        "schedule": {"type": "object"},
                        "campaign_data": {"type": "object"},
                        "date_range": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["schedule_post", "analyze_performance", "engage_audience", "create_campaign"]
            ),
            PlatformCapability(
                name="Analytics",
                description="Get Twitter analytics and engagement metrics",
                tool_name="social_media_analytics",
                input_schema={
                    "type": "object",
                    "properties": {
                        "date_range": {"type": "string", "default": "7d"},
                        "platform": {"type": "string", "default": "twitter"}
                    }
                },
                operations=["get_analytics"]
            )
        ]

        self.platforms["twitter"] = Platform(
            id="twitter",
            name="Twitter",
            description="Twitter API for tweet management and analytics",
            icon="twitter",
            features=[
                "Tweet scheduling",
                "Content management",
                "Analytics",
                "Campaign creation"
            ],
            capabilities=twitter_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "bearer_token": {"type": "string", "description": "Twitter Bearer Token"},
                    "api_key": {"type": "string", "description": "Twitter API Key"},
                    "api_secret": {"type": "string", "description": "Twitter API Secret"},
                    "access_token": {"type": "string", "description": "Twitter Access Token"},
                    "access_token_secret": {"type": "string", "description": "Twitter Access Token Secret"}
                },
                "required": ["bearer_token", "api_key", "api_secret"]
            },
            test_function="test_twitter_connection"
        )

        # LinkedIn Platform
        linkedin_capabilities = [
            PlatformCapability(
                name="Content Management",
                description="Create, schedule, and manage LinkedIn posts and content",
                tool_name="social_media_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["schedule_post", "analyze_performance", "engage_audience", "create_campaign"]},
                        "content": {"type": "object"},
                        "schedule": {"type": "object"},
                        "campaign_data": {"type": "object"},
                        "date_range": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["schedule_post", "analyze_performance", "engage_audience", "create_campaign"]
            ),
            PlatformCapability(
                name="Analytics",
                description="Get LinkedIn analytics and professional metrics",
                tool_name="social_media_analytics",
                input_schema={
                    "type": "object",
                    "properties": {
                        "date_range": {"type": "string", "default": "7d"},
                        "platform": {"type": "string", "default": "linkedin"}
                    }
                },
                operations=["get_analytics"]
            )
        ]

        self.platforms["linkedin"] = Platform(
            id="linkedin",
            name="LinkedIn",
            description="LinkedIn API for professional content and networking",
            icon="linkedin",
            features=[
                "Post scheduling",
                "Professional content",
                "Analytics",
                "Networking"
            ],
            capabilities=linkedin_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "description": "LinkedIn Access Token"},
                    "client_id": {"type": "string", "description": "LinkedIn Client ID"},
                    "client_secret": {"type": "string", "description": "LinkedIn Client Secret"},
                    "organization_id": {"type": "string", "description": "LinkedIn Organization ID"}
                },
                "required": ["access_token", "client_id", "client_secret"]
            },
            test_function="test_linkedin_connection"
        )

        # Instagram Platform
        instagram_capabilities = [
            PlatformCapability(
                name="Content Management",
                description="Create, schedule, and manage Instagram posts and stories",
                tool_name="social_media_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["schedule_post", "analyze_performance", "engage_audience", "create_campaign"]},
                        "content": {"type": "object"},
                        "schedule": {"type": "object"},
                        "campaign_data": {"type": "object"},
                        "date_range": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["schedule_post", "analyze_performance", "engage_audience", "create_campaign"]
            ),
            PlatformCapability(
                name="Analytics",
                description="Get Instagram analytics and engagement metrics",
                tool_name="social_media_analytics",
                input_schema={
                    "type": "object",
                    "properties": {
                        "date_range": {"type": "string", "default": "7d"},
                        "platform": {"type": "string", "default": "instagram"}
                    }
                },
                operations=["get_analytics"]
            )
        ]

        self.platforms["instagram"] = Platform(
            id="instagram",
            name="Instagram",
            description="Instagram API for visual content and stories",
            icon="instagram",
            features=[
                "Post scheduling",
                "Story creation",
                "Visual content",
                "Analytics"
            ],
            capabilities=instagram_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "description": "Instagram Access Token"},
                    "instagram_business_account_id": {"type": "string", "description": "Instagram Business Account ID"},
                    "app_id": {"type": "string", "description": "Facebook App ID (for Instagram)"},
                    "app_secret": {"type": "string", "description": "Facebook App Secret (for Instagram)"}
                },
                "required": ["access_token", "instagram_business_account_id"]
            },
            test_function="test_instagram_connection"
        )

        # Salesforce Platform
        salesforce_capabilities = [
            PlatformCapability(
                name="Contact Management",
                description="Create, update, and manage Salesforce contacts with full CRUD operations",
                tool_name="salesforce_contact_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create", "update", "search", "get"]},
                        "contact_data": {"type": "object"},
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 50}
                    },
                    "required": ["operation"]
                },
                operations=["create", "update", "search", "get"]
            ),
            PlatformCapability(
                name="Lead Management",
                description="Manage Salesforce leads - create, convert, and track lead pipeline",
                tool_name="salesforce_lead_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create", "update", "convert", "get"]},
                        "lead_data": {"type": "object"},
                        "status": {"type": "string"},
                        "limit": {"type": "integer", "default": 50}
                    },
                    "required": ["operation"]
                },
                operations=["create", "update", "convert", "get"]
            ),
            PlatformCapability(
                name="Opportunity Management",
                description="Manage Salesforce opportunities and sales pipeline",
                tool_name="salesforce_opportunity_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create", "update", "get", "pipeline_report"]},
                        "opportunity_data": {"type": "object"},
                        "stage": {"type": "string"},
                        "limit": {"type": "integer", "default": 50}
                    },
                    "required": ["operation"]
                },
                operations=["create", "update", "get", "pipeline_report"]
            ),
            PlatformCapability(
                name="Account Management",
                description="Manage Salesforce accounts and company information",
                tool_name="salesforce_account_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create", "update", "get"]},
                        "account_data": {"type": "object"},
                        "limit": {"type": "integer", "default": 50}
                    },
                    "required": ["operation"]
                },
                operations=["create", "update", "get"]
            ),
            PlatformCapability(
                name="Data Sync",
                description="Sync data between Salesforce and other platforms like HubSpot",
                tool_name="salesforce_data_sync",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["sync_from_hubspot", "sync_contacts", "sync_leads"]},
                        "source_data": {"type": "array", "items": {"type": "object"}},
                        "mapping": {"type": "object"}
                    },
                    "required": ["operation"]
                },
                operations=["sync_from_hubspot", "sync_contacts", "sync_leads"]
            )
        ]

        self.platforms["salesforce"] = Platform(
            id="salesforce",
            name="Salesforce",
            description="CRM platform for contact, lead, and opportunity management",
            icon="salesforce",
            features=[
                "Contact management",
                "Lead tracking",
                "Opportunity management",
                "Sales pipeline",
                "Data synchronization"
            ],
            capabilities=salesforce_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "client_id": {"type": "string", "description": "Salesforce Connected App Client ID"},
                    "client_secret": {"type": "string", "description": "Salesforce Connected App Client Secret"},
                    "username": {"type": "string", "description": "Salesforce Username"},
                    "password": {"type": "string", "description": "Salesforce Password"},
                    "security_token": {"type": "string", "description": "Salesforce Security Token"}
                },
                "required": ["client_id", "client_secret", "username", "password", "security_token"]
            },
            test_function="test_salesforce_connection"
        )
    
    def get_platform(self, platform_id: str) -> Optional[Platform]:
        """Get a platform by ID."""
        return self.platforms.get(platform_id)
    
    def list_platforms(self) -> List[Platform]:
        """Get all available platforms."""
        return list(self.platforms.values())
    
    def get_platform_capabilities(self, platform_id: str) -> List[PlatformCapability]:
        """Get capabilities for a specific platform."""
        platform = self.get_platform(platform_id)
        return platform.capabilities if platform else []
    
    def add_platform(self, platform: Platform):
        """Add a new platform to the registry."""
        self.platforms[platform.id] = platform
        logger.info(f"Added platform: {platform.name}")
    
    def add_platform_dynamically(self, platform_id: str, platform_name: str, description: str, capabilities: List[Dict[str, Any]], config_schema: Dict[str, Any]):
        """Add a new platform dynamically with capabilities."""
        platform_capabilities = []
        
        for cap in capabilities:
            platform_capabilities.append(PlatformCapability(
                name=cap["name"],
                description=cap["description"],
                tool_name=cap["tool_name"],
                input_schema=cap["input_schema"],
                operations=cap.get("operations", [])
            ))
        
        new_platform = Platform(
            id=platform_id,
            name=platform_name,
            description=description,
            icon=platform_id,
            features=[cap["name"] for cap in capabilities],
            capabilities=platform_capabilities,
            config_schema=config_schema,
            test_function=f"test_{platform_id}_connection"
        )
        
        self.add_platform(new_platform)
        return new_platform
    
    def remove_platform(self, platform_id: str):
        """Remove a platform from the registry."""
        if platform_id in self.platforms:
            del self.platforms[platform_id]
            logger.info(f"Removed platform: {platform_id}")
    
    def get_platform_tools(self, platform_id: str) -> List[Dict[str, Any]]:
        """Get tools for a specific platform."""
        platform = self.get_platform(platform_id)
        if not platform:
            return []
        
        tools = []
        for capability in platform.capabilities:
            tools.append({
                "name": capability.tool_name,
                "description": capability.description,
                "inputSchema": capability.input_schema,
                "platform": platform_id,
                "capability": capability.name
            })
        
        return tools
    
    def get_all_tools(self) -> List[Dict[str, Any]]:
        """Get all tools from all platforms."""
        all_tools = []
        for platform_id in self.platforms:
            tools = self.get_platform_tools(platform_id)
            all_tools.extend(tools)
        return all_tools
    
    def get_platform_config_schema(self, platform_id: str) -> Optional[Dict[str, Any]]:
        """Get configuration schema for a platform."""
        platform = self.get_platform(platform_id)
        return platform.config_schema if platform else None
    
    def validate_platform_config(self, platform_id: str, config: Dict[str, Any]) -> bool:
        """Validate platform configuration."""
        schema = self.get_platform_config_schema(platform_id)
        if not schema:
            return False
        
        # Simple validation - in production, use a proper JSON schema validator
        required_fields = schema.get("required", [])
        for field in required_fields:
            if field not in config:
                return False
        
        return True


# Global platform registry instance
platform_registry = PlatformRegistry() 