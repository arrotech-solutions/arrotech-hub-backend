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
    few_shot_examples: Optional[List[Dict[str, str]]] = None


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
        self._initialize_kenyan_platforms()
    
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
        

        
        # Slack Platform
        slack_capabilities = [
            PlatformCapability(
                name="Team Communication",
                description="Send messages, reports, and notifications to Slack channels. USE THIS FOR: sending messages to channels (e.g., 'Send hello to #general'), posting reports, sending alerts. REQUIRED: action (send_message/send_report/send_alert), channel, message",
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
                operations=["send_message", "send_report", "send_alert", "schedule_message"],
                few_shot_examples=[
                    {
                        "user": "Send a message to #general saying 'Hello team'",
                        "tool_call": 'slack_team_communication(action="send_message", channel="#general", message="Hello team")',
                        "response": "✅ Message sent to #general: 'Hello team'"
                    },
                    {
                        "user": "Send an alert to #devops that the server is down",
                        "tool_call": 'slack_team_communication(action="send_alert", channel="#devops", message="Server is down")',
                        "response": "🚨 Alert sent to #devops: 'Server is down'"
                    }
                ]
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
        
        # ClickUp Platform
        clickup_capabilities = [
            PlatformCapability(
                name="Task Management",
                description="Manage ClickUp tasks, lists, and folders",
                tool_name="clickup_task_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create_task", "get_tasks", "get_team_tasks", "update_task", "delete_task", "get_teams"]},
                        "list_id": {"type": "string"},
                        "team_id": {"type": "string"},
                        "assignee_id": {"type": "string"},
                        "task_id": {"type": "string"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "assignees": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["operation"]
                },
                operations=["create_task", "get_tasks", "get_team_tasks", "update_task", "delete_task"]
            ),
            PlatformCapability(
                name="Resource Management",
                description="Navigate ClickUp hierarchy (Spaces, Folders, Lists)",
                tool_name="clickup_resource_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["get_spaces", "get_folders", "get_lists", "get_folderless_lists"]},
                        "team_id": {"type": "string"},
                        "space_id": {"type": "string"},
                        "folder_id": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["get_spaces", "get_folders", "get_lists", "get_folderless_lists"]
            )
        ]

        self.platforms["clickup"] = Platform(
            id="clickup",
            name="ClickUp",
            description="Project management and productivity platform",
            icon="clickup",
            features=[
                "Task creation",
                "List management",
                "Team collaboration",
                "Workflow automation"
            ],
            capabilities=clickup_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "client_id": {"type": "string", "description": "ClickUp Client ID"},
                    "client_secret": {"type": "string", "description": "ClickUp Client Secret"}
                },
                "required": ["client_id", "client_secret"]
            },
            test_function="test_clickup_connection"
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
        
        # Microsoft Teams Platform
        teams_capabilities = [
            PlatformCapability(
                name="Team Communication",
                description="Send messages, notifications, and adaptive cards to Teams channels",
                tool_name="teams_team_communication",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["send_message", "send_adaptive_card", "send_alert", "send_meeting_notification"]},
                        "channel": {"type": "string"},
                        "message": {"type": "string"},
                        "message_type": {"type": "string", "default": "text"},
                        "card_content": {"type": "object"},
                        "alert_type": {"type": "string"},
                        "severity": {"type": "string", "enum": ["info", "warning", "error", "success"]},
                        "meeting_title": {"type": "string"},
                        "meeting_time": {"type": "string"},
                        "meeting_link": {"type": "string"},
                        "attendees": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["action", "channel"]
                },
                operations=["send_message", "send_adaptive_card", "send_alert", "send_meeting_notification"]
            ),
            PlatformCapability(
                name="Channel Management",
                description="Manage Teams channels, members, and team information",
                tool_name="teams_channel_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["list_channels", "get_channel_members", "create_channel", "get_team_info"]},
                        "team_id": {"type": "string"},
                        "channel_name": {"type": "string"},
                        "description": {"type": "string"},
                        "channel_id": {"type": "string"}
                    },
                    "required": ["action"]
                },
                operations=["list_channels", "get_channel_members", "create_channel", "get_team_info"]
            ),
            PlatformCapability(
                name="Message Search",
                description="Search for messages and content in Teams channels",
                tool_name="teams_message_search",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "channel_id": {"type": "string"},
                        "limit": {"type": "integer", "default": 20}
                    },
                    "required": ["query"]
                },
                operations=["search_messages"]
            )
        ]
        
        self.platforms["teams"] = Platform(
            id="teams",
            name="Microsoft Teams",
            description="Microsoft Teams integration for team communication and collaboration",
            icon="teams",
            features=[
                "Team messaging",
                "Adaptive cards",
                "Channel management",
                "Meeting notifications",
                "Message search"
            ],
            capabilities=teams_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "webhook_url": {"type": "string", "description": "Teams Webhook URL (for webhook method)"},
                    "access_token": {"type": "string", "description": "Microsoft Graph API Access Token (for Graph API method)"},
                    "tenant_id": {"type": "string", "description": "Microsoft Tenant ID (for Graph API method)"},
                    "client_id": {"type": "string", "description": "Microsoft Client ID (for Graph API method)"},
                    "client_secret": {"type": "string", "description": "Microsoft Client Secret (for Graph API method)"}
                },
                "anyOf": [
                    {"required": ["webhook_url"]},
                    {"required": ["access_token", "tenant_id", "client_id", "client_secret"]}
                ]
            },
            test_function="test_teams_connection"
        )

        # Zoom
        zoom_capabilities = [
            PlatformCapability(
                name="Meeting Management",
                description="Create, update, delete, and manage Zoom meetings",
                tool_name="zoom_meeting_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["create", "get", "update", "delete", "list"]},
                        "topic": {"type": "string"},
                        "start_time": {"type": "string"},
                        "duration": {"type": "integer", "default": 60},
                        "password": {"type": "string"},
                        "meeting_id": {"type": "string"},
                        "settings": {"type": "object"}
                    },
                    "required": ["action"]
                },
                operations=["create", "get", "update", "delete", "list"]
            ),
            PlatformCapability(
                name="Meeting Operations",
                description="Manage meeting participants, registrants, and operations",
                tool_name="zoom_meeting_operations",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_participants", "get_registrants", "get_invitation", "update_status"]},
                        "meeting_id": {"type": "string"},
                        "page_size": {"type": "integer", "default": 30},
                        "page_number": {"type": "integer", "default": 1}
                    },
                    "required": ["action", "meeting_id"]
                },
                operations=["get_participants", "get_registrants", "get_invitation", "update_status"]
            ),
            PlatformCapability(
                name="Recording Management",
                description="Manage meeting recordings and recordings analytics",
                tool_name="zoom_recording_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_recordings", "delete_recording"]},
                        "meeting_id": {"type": "string"},
                        "recording_id": {"type": "string"},
                        "page_size": {"type": "integer", "default": 30},
                        "page_number": {"type": "integer", "default": 1}
                    },
                    "required": ["action", "meeting_id"]
                },
                operations=["get_recordings", "delete_recording"]
            ),
            PlatformCapability(
                name="User Management",
                description="Manage Zoom users and account information",
                tool_name="zoom_user_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_user", "list_users"]},
                        "user_id": {"type": "string", "default": "me"},
                        "status": {"type": "string", "default": "active"},
                        "page_size": {"type": "integer", "default": 30},
                        "page_number": {"type": "integer", "default": 1}
                    },
                    "required": ["action"]
                },
                operations=["get_user", "list_users"]
            ),
            PlatformCapability(
                name="Webinar Management",
                description="Create and manage Zoom webinars",
                tool_name="zoom_webinar_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["create", "get", "list"]},
                        "topic": {"type": "string"},
                        "start_time": {"type": "string"},
                        "duration": {"type": "integer", "default": 60},
                        "password": {"type": "string"},
                        "webinar_id": {"type": "string"},
                        "settings": {"type": "object"}
                    },
                    "required": ["action"]
                },
                operations=["create", "get", "list"]
            ),
            PlatformCapability(
                name="Analytics and Reports",
                description="Get meeting reports, analytics, and performance data",
                tool_name="zoom_analytics",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_meeting_reports", "get_daily_reports"]},
                        "user_id": {"type": "string", "default": "me"},
                        "from_date": {"type": "string"},
                        "to_date": {"type": "string"},
                        "year": {"type": "integer"},
                        "month": {"type": "integer"},
                        "page_size": {"type": "integer", "default": 30},
                        "page_number": {"type": "integer", "default": 1}
                    },
                    "required": ["action"]
                },
                operations=["get_meeting_reports", "get_daily_reports"]
            )
        ]

        self.platforms["zoom"] = Platform(
            id="zoom",
            name="Zoom",
            description="Zoom integration for meeting management, recordings, and analytics",
            icon="zoom",
            features=[
                "Meeting management",
                "Recording management", 
                "User management",
                "Webinar management",
                "Analytics and reports"
            ],
            capabilities=zoom_capabilities,
                    config_schema={
            "type": "object",
            "properties": {
                "client_id": {"type": "string", "description": "Zoom OAuth client ID"},
                "client_secret": {"type": "string", "description": "Zoom OAuth client secret"},
                "account_id": {"type": "string", "description": "Zoom account ID"}
            },
            "required": ["client_id", "client_secret"]
        },
            test_function="test_zoom_connection"
        )

        # Asana Platform
        asana_capabilities = [
            PlatformCapability(
                name="Project Management",
                description="Create, update, and manage Asana projects",
                tool_name="asana_project_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create", "read", "update", "delete", "list"]},
                        "project_data": {"type": "object"},
                        "workspace_id": {"type": "string"},
                        "team_id": {"type": "string"},
                        "project_id": {"type": "string"},
                        "limit": {"type": "integer", "default": 50}
                    },
                    "required": ["operation"]
                },
                operations=["create", "read", "update", "delete", "list"]
            ),
            PlatformCapability(
                name="Task Management",
                description="Create, update, and manage Asana tasks and subtasks",
                tool_name="asana_task_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create", "read", "update", "delete", "list", "create_subtask"]},
                        "task_data": {"type": "object"},
                        "workspace_id": {"type": "string"},
                        "project_id": {"type": "string"},
                        "assignee": {"type": "string"},
                        "parent_task_id": {"type": "string"},
                        "limit": {"type": "integer", "default": 50}
                    },
                    "required": ["operation"]
                },
                operations=["create", "read", "update", "delete", "list", "create_subtask"]
            ),
            PlatformCapability(
                name="Team Collaboration",
                description="Manage teams, users, and collaboration features",
                tool_name="asana_team_collaboration",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["get_teams", "get_users", "get_team_members", "add_comment"]},
                        "workspace_id": {"type": "string"},
                        "team_id": {"type": "string"},
                        "task_id": {"type": "string"},
                        "comment_text": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["get_teams", "get_users", "get_team_members", "add_comment"]
            ),
            PlatformCapability(
                name="Portfolio Management",
                description="Create and manage portfolios for project organization",
                tool_name="asana_portfolio_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create_portfolio", "get_portfolios", "add_project_to_portfolio"]},
                        "portfolio_data": {"type": "object"},
                        "workspace_id": {"type": "string"},
                        "portfolio_id": {"type": "string"},
                        "project_id": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["create_portfolio", "get_portfolios", "add_project_to_portfolio"]
            )
        ]

        self.platforms["asana"] = Platform(
            id="asana",
            name="Asana",
            description="Project management and team collaboration platform",
            icon="asana",
            features=[
                "Project management",
                "Task management",
                "Team collaboration",
                "Portfolio management",
                "Section management",
                "Tag management"
            ],
            capabilities=asana_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "description": "Asana access token"},
                    "workspace_id": {"type": "string", "description": "Asana workspace ID"}
                },
                "required": ["access_token"]
            },
            test_function="test_asana_connection"
        )

        # Power BI Platform
        powerbi_capabilities = [
            PlatformCapability(
                name="Workspace Management",
                description="Manage Power BI workspaces - create, delete, and get workspace information",
                tool_name="powerbi_workspace_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["list", "create", "delete", "get_info"]},
                        "workspace_name": {"type": "string"},
                        "workspace_description": {"type": "string"},
                        "workspace_id": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["list", "create", "delete", "get_info"]
            ),
            PlatformCapability(
                name="Dataset Operations",
                description="Manage Power BI datasets - get datasets, schema, refresh, and execute DAX queries",
                tool_name="powerbi_dataset_operations",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["list", "get_schema", "refresh", "execute_query", "get_refresh_history"]},
                        "workspace_id": {"type": "string"},
                        "dataset_id": {"type": "string"},
                        "dax_query": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["list", "get_schema", "refresh", "execute_query", "get_refresh_history"]
            ),
            PlatformCapability(
                name="Report Management",
                description="Manage Power BI reports - list reports, get embed tokens, and report analytics",
                tool_name="powerbi_report_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["list", "get_embed_token", "get_analytics"]},
                        "workspace_id": {"type": "string"},
                        "report_id": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["list", "get_embed_token", "get_analytics"]
            ),
            PlatformCapability(
                name="Dashboard Operations",
                description="Manage Power BI dashboards - list dashboards and get dashboard information",
                tool_name="powerbi_dashboard_operations",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["list", "get_info"]},
                        "workspace_id": {"type": "string"},
                        "dashboard_id": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["list", "get_info"]
            ),
            PlatformCapability(
                name="Analytics Summary",
                description="Get comprehensive Power BI analytics summary including workspaces, datasets, reports, and activity logs",
                tool_name="powerbi_analytics_summary",
                input_schema={
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string"},
                        "include_activity_logs": {"type": "boolean", "default": True},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"}
                    }
                },
                operations=["get_analytics_summary"]
            ),
            PlatformCapability(
                name="User Management",
                description="Manage Power BI workspace users and permissions",
                tool_name="powerbi_user_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["list_users", "get_user_info"]},
                        "workspace_id": {"type": "string"},
                        "user_id": {"type": "string"}
                    },
                    "required": ["operation", "workspace_id"]
                },
                operations=["list_users", "get_user_info"]
            )
        ]

        self.platforms["powerbi"] = Platform(
            id="powerbi",
            name="Power BI",
            description="Microsoft Power BI for business intelligence and data analytics",
            icon="powerbi",
            features=[
                "Workspace management",
                "Dataset operations",
                "Report management",
                "Dashboard operations",
                "Analytics summary",
                "User management"
            ],
            capabilities=powerbi_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "client_id": {"type": "string", "description": "Power BI Client ID"},
                    "client_secret": {"type": "string", "description": "Power BI Client Secret"},
                    "tenant_id": {"type": "string", "description": "Power BI Tenant ID"}
                },
                "required": ["client_id", "client_secret", "tenant_id"]
            },
            test_function="test_powerbi_connection"
        )

        # WhatsApp Platform
        whatsapp_capabilities = [
            PlatformCapability(
                name="Messaging",
                description="Send text and media messages to customers via WhatsApp",
                tool_name="whatsapp_messaging",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["send_message", "send_media", "send_location"]},
                        "to_number": {"type": "string"},
                        "message": {"type": "string"},
                        "media_url": {"type": "string"},
                        "media_type": {"type": "string", "enum": ["image", "video", "document", "audio"]},
                        "caption": {"type": "string"},
                        "latitude": {"type": "string"},
                        "longitude": {"type": "string"},
                        "location_name": {"type": "string"},
                        "location_address": {"type": "string"}
                    },
                    "required": ["operation", "to_number"]
                },
                operations=["send_message", "send_media", "send_location"]
            ),
            PlatformCapability(
                name="Template Management",
                description="Manage and send WhatsApp Message Templates",
                tool_name="whatsapp_templates",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["send_template", "list_templates", "create_template"]},
                        "to_number": {"type": "string"},
                        "template_name": {"type": "string"},
                        "language_code": {"type": "string", "default": "en_US"},
                        "components": {"type": "array", "items": {"type": "object"}},
                        "category": {"type": "string", "enum": ["MARKETING", "UTILITY", "AUTHENTICATION"]}
                    },
                    "required": ["operation"]
                },
                operations=["send_template", "list_templates", "create_template"]
            ),
            PlatformCapability(
                name="Account Info",
                description="Get WhatsApp Business Account information",
                tool_name="whatsapp_account_info",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["get_phone_info", "check_connection"]}
                    },
                    "required": ["operation"]
                },
                operations=["get_phone_info", "check_connection"]
            )
        ]

        self.platforms["whatsapp"] = Platform(
            id="whatsapp",
            name="WhatsApp Business",
            description="Send messages and manage interactions on WhatsApp",
            icon="whatsapp",
            features=[
                "Messaging",
                "Template management",
                "Media support",
                "Location sharing",
                "Business profile"
            ],
            capabilities=whatsapp_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "description": "WhatsApp Business API Access Token"},
                    "phone_number_id": {"type": "string", "description": "WhatsApp Phone Number ID"},
                    "business_account_id": {"type": "string", "description": "WhatsApp Business Account ID"},
                    "auth_type": {"type": "string", "enum": ["oauth", "manual"], "default": "manual"}
                },
                "required": ["access_token", "phone_number_id"]
            },
            test_function="test_whatsapp_connection"
        )
        
        # Outlook Platform
        outlook_capabilities = [
            PlatformCapability(
                name="Email Management",
                description="Read, search, and send emails using Microsoft Outlook",
                tool_name="outlook_email_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["read_emails", "search_emails", "send_email"]},
                        "query": {"type": "string", "description": "Query for search"},
                        "limit": {"type": "integer", "default": 10},
                        "to_email": {"type": "string"},
                        "subject": {"type": "string"},
                        "content": {"type": "string"},
                        "content_type": {"type": "string", "enum": ["text", "html"], "default": "text"}
                    },
                    "required": ["action"]
                },
                operations=["read_emails", "search_emails", "send_email"]
            )
        ]

        self.platforms["outlook"] = Platform(
            id="outlook",
            name="Microsoft Outlook",
            description="Manage emails, calendar, and contacts",
            icon="microsoft_outlook",
            features=[
                "Email management",
                "Calendar integration",
                "Contact management"
            ],
            capabilities=outlook_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "description": "Microsoft Graph Access Token"},
                    "refresh_token": {"type": "string", "description": "Refresh Token"}
                },
                "required": ["access_token"]
            },
            test_function="test_outlook_connection"
        )

        # Notion Platform
        notion_capabilities = [
            PlatformCapability(
                name="Workspace Management",
                description="Search and manage pages in Notion workspace",
                tool_name="notion_workspace_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["search_pages", "create_page"]},
                        "query": {"type": "string", "description": "Query for search"},
                        "limit": {"type": "integer", "default": 10},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "parent_id": {"type": "string"}
                    },
                    "required": ["action"]
                },
                operations=["search_pages", "create_page"]
            )
        ]

        self.platforms["notion"] = Platform(
            id="notion",
            name="Notion",
            description="All-in-one workspace for notes, projects, and docs",
            icon="notion",
            features=[
                "Page management",
                "Database integration",
                "Content creation"
            ],
            capabilities=notion_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "description": "Notion Integration Token"},
                    "workspace_name": {"type": "string"}
                },
                "required": ["access_token"]
            },
            test_function="test_notion_connection"
        )

        # Trello Platform
        trello_capabilities = [
            PlatformCapability(
                name="Project Management",
                description="Manage boards, lists and cards in Trello",
                tool_name="trello_project_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_boards", "search_cards", "create_card"]},
                        "query": {"type": "string", "description": "Query for search"},
                        "limit": {"type": "integer", "default": 10},
                        "list_id": {"type": "string"},
                        "name": {"type": "string", "description": "Card name"},
                        "desc": {"type": "string", "description": "Card description"},
                        "due": {"type": "string", "description": "Due date (ISO)"}
                    },
                    "required": ["action"]
                },
                operations=["get_boards", "search_cards", "create_card"]
            )
        ]

        self.platforms["trello"] = Platform(
            id="trello",
            name="Trello",
            description="Manage projects and tasks with boards",
            icon="trello",
            features=[
                "Board management",
                "List tracking",
                "Card creation"
            ],
            capabilities=trello_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "access_token": {"type": "string"},
                    "refresh_token": {"type": "string"}
                },
                "required": ["access_token"]
            },
            test_function="test_trello_connection"
        )
        
        # Jira Platform
        jira_capabilities = [
            PlatformCapability(
                name="Issue Tracking",
                description="Manage issues and projects in Jira",
                tool_name="jira_issue_tracking",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_projects", "search_issues", "create_issue"]},
                        "jql": {"type": "string", "description": "JQL query for search_issues"},
                        "limit": {"type": "integer", "default": 10},
                        "project_key": {"type": "string"},
                        "summary": {"type": "string", "description": "Issue summary"},
                        "description": {"type": "string", "description": "Issue description"},
                        "issuetype": {"type": "string", "default": "Task"}
                    },
                    "required": ["action"]
                },
                operations=["get_projects", "search_issues", "create_issue"]
            )
        ]

        self.platforms["jira"] = Platform(
            id="jira",
            name="Jira",
            description="Issue and project tracking software",
            icon="jira",
            features=[
                "Issue tracking",
                "Project management",
                "Agile boards"
            ],
            capabilities=jira_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "access_token": {"type": "string"},
                    "cloud_id": {"type": "string"}
                },
                "required": ["access_token", "cloud_id"]
            },
            test_function="test_jira_connection"
        )


        # Facebook Platform
        facebook_capabilities = [
            PlatformCapability(
                name="Posting",
                description="Create and manage posts on Facebook Pages",
                tool_name="facebook_posting",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create_post", "get_posts"]},
                        "page_id": {"type": "string"},
                        "message": {"type": "string"},
                        "link": {"type": "string"},
                        "media_url": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["create_post", "get_posts"]
            ),
            PlatformCapability(
                name="Insights",
                description="Get insights and engagement metrics for Facebook Pages",
                tool_name="facebook_insights",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["get_page_insights", "get_post_insights"]},
                        "page_id": {"type": "string"},
                        "metric": {"type": "string"},
                        "period": {"type": "string"}
                    },
                    "required": ["operation", "page_id"]
                },
                operations=["get_page_insights", "get_post_insights"]
            )
        ]

        self.platforms["facebook"] = Platform(
            id="facebook",
            name="Facebook Pages",
            description="Manage posts and insights for Facebook Pages",
            icon="facebook",
            features=[
                "Post Management",
                "Page Insights",
                "Community Engagement"
            ],
            capabilities=facebook_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "description": "Facebook User Access Token"},
                    "auth_type": {"type": "string", "enum": ["oauth"], "default": "oauth"}
                },
                "required": ["access_token"]
            },
            test_function="test_facebook_connection"
        )


        # Instagram Platform
        instagram_capabilities = [
            PlatformCapability(
                name="Media Publishing",
                description="Publish photos and videos to Instagram Business accounts",
                tool_name="instagram_publishing",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["publish_media", "get_media"]},
                        "image_url": {"type": "string"},
                        "caption": {"type": "string"},
                        "media_type": {"type": "string", "enum": ["IMAGE", "VIDEO", "CAROUSEL"]}
                    },
                    "required": ["operation"]
                },
                operations=["publish_media", "get_media"]
            ),
            PlatformCapability(
                name="Comment Management",
                description="Reply to and manage comments on Instagram posts",
                tool_name="instagram_comments",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["reply_comment", "delete_comment", "get_comments"]},
                        "media_id": {"type": "string"},
                        "comment_id": {"type": "string"},
                        "message": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["reply_comment", "delete_comment", "get_comments"]
            )
        ]

        self.platforms["instagram"] = Platform(
            id="instagram",
            name="Instagram Business",
            description="Publish content and manage interactions on Instagram",
            icon="instagram",
            features=[
                "Media Publishing",
                "Comment Management",
                "Business Insights"
            ],
            capabilities=instagram_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "description": "Instagram User Access Token"},
                    "auth_type": {"type": "string", "enum": ["oauth"], "default": "oauth"}
                },
                "required": ["access_token"]
            },
            test_function="test_instagram_connection"
        )



        # Twitter (X) Platform
        twitter_capabilities = [
            PlatformCapability(
                name="Tweet Publishing",
                description="Post tweets and threads to X (Twitter)",
                tool_name="twitter_publishing",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["post_tweet"]},
                        "text": {"type": "string"},
                        "media_ids": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["operation", "text"]
                },
                operations=["post_tweet"]
            ),
            PlatformCapability(
                name="User Profile",
                description="Read user profile information",
                tool_name="twitter_profile",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["get_me"]}
                    },
                    "required": ["operation"]
                },
                operations=["get_me"]
            )
        ]

        self.platforms["twitter"] = Platform(
            id="twitter",
            name="Twitter (X)",
            description="Manage tweets and interact with the X platform",
            icon="twitter",
            features=[
                "Tweet Publishing",
                "Community Engagement"
            ],
            capabilities=twitter_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "access_token": {"type": "string", "description": "Twitter Access Token"},
                    "refresh_token": {"type": "string", "description": "Twitter Refresh Token"},
                    "auth_type": {"type": "string", "enum": ["oauth_pkce"], "default": "oauth_pkce"}
                },
                "required": ["access_token"]
            },
            test_function="test_twitter_connection"
        )

        # M-Pesa Platform
        mpesa_capabilities = [
            PlatformCapability(
                name="Payment Reconciliation",
                description="M-Pesa payment management and reconciliation. USE THIS FOR: viewing today's payments, getting payment summaries, finding unmatched payments, reconciling invoices. EXAMPLES: 'Show today's M-Pesa payments' → operation=search_payments, date_range=today. REQUIRED: operation",
                tool_name="mpesa_payment_reconciliation",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["get_summary", "search_payments", "get_unmatched", "match_to_invoice"]},
                        "date_range": {"type": "string", "enum": ["today", "yesterday", "week", "month", "all"], "default": "today"},
                        "query": {"type": "string"},
                        "payment_id": {"type": "string"},
                        "invoice_id": {"type": "string"},
                        "limit": {"type": "integer", "default": 20}
                    },
                    "required": ["operation"]
                },
                operations=["get_summary", "search_payments", "get_unmatched", "match_to_invoice"]
            ),
            PlatformCapability(
                name="Account Management",
                description="Get M-Pesa account balance and connection status",
                tool_name="mpesa_account_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["get_balance", "get_status"]}
                    },
                    "required": ["operation"]
                },
                operations=["get_balance", "get_status"]
            ),
            PlatformCapability(
                name="Alert Configuration",
                description="Manage real-time M-Pesa payment alerts and notifications",
                tool_name="mpesa_alert_config",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["get_config", "update_config"]},
                        "alert_enabled": {"type": "boolean"},
                        "channel_id": {"type": "string"},
                        "auto_match_enabled": {"type": "boolean"}
                    },
                    "required": ["operation"]
                },
                operations=["get_config", "update_config"]
            )
        ]

        self.platforms["mpesa"] = Platform(
            id="mpesa",
            name="M-Pesa Business",
            description="Mobile money integration for regional businesses with real-time alerts and reconciliation",
            icon="mpesa",
            features=[
                "Real-time payment alerts",
                "Automated reconciliation",
                "Payment matching",
                "Financial summaries",
                "Swahili support"
            ],
            capabilities=mpesa_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "short_code": {"type": "string", "description": "Paybill or Buy Goods Till Number"},
                    "consumer_key": {"type": "string", "description": "Daraja API Consumer Key"},
                    "consumer_secret": {"type": "string", "description": "Daraja API Consumer Secret"},
                    "pass_key": {"type": "string", "description": "Daraja API Pass Key"}
                },
                "required": ["short_code", "consumer_key", "consumer_secret"]
            },
            test_function="test_mpesa_connection"
        )

        # HR Platform
        hr_capabilities = [
            PlatformCapability(
                name="Leave Management",
                description="Manage employee leave requests, balances, and approvals",
                tool_name="hr_leave_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["get_balance", "apply_leave", "get_requests", "approve_rejection"]},
                        "employee_id": {"type": "string"},
                        "leave_type": {"type": "string", "enum": ["annual", "sick", "maternity", "paternity", "compassionate", "unpaid"]},
                        "days": {"type": "integer"},
                        "start_date": {"type": "string"},
                        "reason": {"type": "string"},
                        "request_id": {"type": "string"},
                        "status": {"type": "string", "enum": ["approved", "rejected"]}
                    },
                    "required": ["operation"]
                },
                operations=["get_balance", "apply_leave", "get_requests", "approve_rejection"]
            ),
            PlatformCapability(
                name="Policy Q&A",
                description="Search and query company policies and HR documents (Bilingual)",
                tool_name="hr_policy_lookup",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "language": {"type": "string", "enum": ["english", "swahili"], "default": "english"}
                    },
                    "required": ["query"]
                },
                operations=["search_policies"]
            )
        ]

        self.platforms["hr_hub"] = Platform(
            id="hr_hub",
            name="HR Hub",
            description="HR management tailored for regional business policies and labor laws",
            icon="users",
            features=[
                "Leave tracking",
                "Policy search",
                "Bilingual support",
                "Manager approvals",
                "Law compliance"
            ],
            capabilities=hr_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "company_id": {"type": "string", "description": "Internal Company ID"},
                    "manager_channel": {"type": "string", "description": "Slack channel for leave approvals"}
                },
                "required": ["company_id"]
            },
            test_function="test_hr_hub_connection"
        )

        # Lead Intelligence Platform
        lead_capabilities = [
            PlatformCapability(
                name="Lead Qualification",
                description="Automatically qualify and score leads based on contact data and interactions",
                tool_name="lead_intelligence_qualification",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["score_lead", "summarize_lead", "extract_info"]},
                        "lead_data": {"type": "object"},
                        "interaction_history": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["operation", "lead_data"]
                },
                operations=["score_lead", "summarize_lead", "extract_info"]
            ),
            PlatformCapability(
                name="Follow-up Orchestration",
                description="Draft and schedule personalized follow-up messages for qualified leads",
                tool_name="lead_intelligence_followup",
                input_schema={
                    "type": "object",
                    "properties": {
                        "lead_id": {"type": "string"},
                        "tone": {"type": "string", "enum": ["professional", "casual", "urgent"], "default": "professional"},
                        "channel": {"type": "string", "enum": ["email", "slack", "whatsapp"], "default": "slack"}
                    },
                    "required": ["lead_id"]
                },
                operations=["draft_followup"]
            )
        ]

        self.platforms["lead_intelligence"] = Platform(
            id="lead_intelligence",
            name="Lead Intelligence",
            description="AI-powered lead qualification and sales follow-up automation",
            icon="zap",
            features=[
                "Lead scoring",
                "Automated qualification",
                "Personalized follow-ups",
                "CRM sync",
                "Bilingual extraction"
            ],
            capabilities=lead_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "qualification_threshold": {"type": "integer", "default": 70},
                    "followup_reminder_channel": {"type": "string"}
                },
                "required": []
            },
            test_function="test_lead_intelligence_connection"
        )

        # Logistics Platform
        logistics_capabilities = [
            PlatformCapability(
                name="Delivery Tracking",
                description="Track shipments across various regional logistics providers",
                tool_name="logistics_tracking",
                input_schema={
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string", "enum": ["sendy", "g4s", "wells_fargo", "automatic"], "default": "automatic"},
                        "tracking_number": {"type": "string"},
                        "order_id": {"type": "string"}
                    },
                    "required": ["tracking_number"]
                },
                operations=["get_status", "get_estimated_delivery"]
            ),
            PlatformCapability(
                name="Delivery Creation",
                description="Create new delivery requests with local logistics partners",
                tool_name="logistics_delivery",
                input_schema={
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string", "enum": ["sendy", "g4s"]},
                        "pickup_location": {"type": "string"},
                        "delivery_location": {"type": "string"},
                        "recipient_phone": {"type": "string"},
                        "package_description": {"type": "string"}
                    },
                    "required": ["pickup_location", "delivery_location", "recipient_phone"]
                },
                operations=["create_delivery", "cancel_delivery"]
            )
        ]

        self.platforms["logistics_hub"] = Platform(
            id="logistics_hub",
            name="Logistics Hub",
            description="Integration with regional providers for real-time delivery tracking",
            icon="truck",
            features=[
                "Multi-provider tracking",
                "Delivery alerts",
                "Automated booking",
                "Local context awareness"
            ],
            capabilities=logistics_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "sendy_api_key": {"type": "string"},
                    "g4s_client_id": {"type": "string"},
                    "wells_fargo_api_key": {"type": "string"}
                },
                "required": []
            },
            test_function="test_logistics_hub_connection"
        )

        # Context & Bilingual Platform
        context_capabilities = [
            PlatformCapability(
                name="Bilingual Translation",
                description="Translate business communications between English and regional languages",
                tool_name="context_translation",
                input_schema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "target_lang": {"type": "string", "enum": ["english", "swahili"]}
                    },
                    "required": ["text", "target_lang"]
                },
                operations=["translate"]
            ),
            PlatformCapability(
                name="Business Verification",
                description="Verify tax IDs and check compliance status for regional businesses",
                tool_name="context_verification",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["verify_pin", "check_compliance"]},
                        "pin": {"type": "string"}
                    },
                    "required": ["operation", "pin"]
                },
                operations=["verify_pin", "check_compliance"]
            ),
            PlatformCapability(
                name="Sentiment Analysis",
                description="Analyze sentiment of messages in English or local languages",
                tool_name="context_sentiment",
                input_schema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"}
                    },
                    "required": ["text"]
                },
                operations=["analyze_sentiment"]
            )
        ]

        self.platforms["context_intelligence"] = Platform(
            id="context_intelligence",
            name="Business Intelligence",
            description="Linguistic and regulatory intelligence for regional markets",
            icon="shield",
            features=[
                "Bilingual NLP",
                "Tax ID verification",
                "Compliance checks",
                "Local sentiment analysis"
            ],
            capabilities=context_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "openai_api_key": {"type": "string"}
                },
                "required": []
            },
            test_function="test_context_intelligence_connection"
        )
        
        # Google Workspace Platform
        google_workspace_capabilities = [
            # Gmail Capabilities
            PlatformCapability(
                name="Gmail Operations",
                description="Send, read, search, and manage emails with full Gmail integration",
                tool_name="google_workspace_gmail",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["send_email", "read_emails", "search_emails", "create_label", "apply_label", "create_draft", "delete_email", "get_email_details"]},
                        "to": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                        "cc": {"type": "string"},
                        "bcc": {"type": "string"},
                        "html": {"type": "boolean"},
                        "max_results": {"type": "integer", "default": 10},
                        "label_ids": {"type": "array", "items": {"type": "string"}},
                        "query": {"type": "string"},
                        "message_id": {"type": "string"},
                        "label_name": {"type": "string"},
                        "message_ids": {"type": "array", "items": {"type": "string"}},
                        "permanent": {"type": "boolean"}
                    },
                    "required": ["operation"]
                },
                operations=["send_email", "read_emails", "search_emails", "create_label", "apply_label", "create_draft", "delete_email", "get_email_details"]
            ),
            # Calendar Capabilities
            PlatformCapability(
                name="Calendar Operations",
                description="Manage calendar events, meetings, and scheduling with Google Calendar",
                tool_name="google_workspace_calendar",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create_event", "list_events", "update_event", "delete_event", "check_availability", "create_meeting"]},
                        "summary": {"type": "string"},
                        "start_time": {"type": "string"},
                        "end_time": {"type": "string"},
                        "description": {"type": "string"},
                        "location": {"type": "string"},
                        "attendees": {"type": "array", "items": {"type": "string"}},
                        "timezone": {"type": "string", "default": "Africa/Nairobi"},
                        "calendar_id": {"type": "string", "default": "primary"},
                        "event_id": {"type": "string"},
                        "time_min": {"type": "string"},
                        "time_max": {"type": "string"},
                        "max_results": {"type": "integer", "default": 10}
                    },
                    "required": ["operation"]
                },
                operations=["create_event", "list_events", "update_event", "delete_event", "check_availability", "create_meeting"]
            ),
            # Drive Capabilities
            PlatformCapability(
                name="Drive Operations",
                description="Upload, download, share, and manage files in Google Drive",
                tool_name="google_workspace_drive",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["upload_file", "download_file", "list_files", "create_folder", "delete_file", "share_file", "search_files", "get_metadata", "move_file"]},
                        "filename": {"type": "string"},
                        "content": {"type": "string"},
                        "mime_type": {"type": "string"},
                        "folder_id": {"type": "string"},
                        "file_id": {"type": "string"},
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "default": 100},
                        "order_by": {"type": "string", "default": "modifiedTime desc"},
                        "email": {"type": "string"},
                        "role": {"type": "string", "enum": ["reader", "writer", "commenter", "owner"]}
                    },
                    "required": ["operation"]
                },
                operations=["upload_file", "download_file", "list_files", "create_folder", "delete_file", "share_file", "search_files", "get_metadata", "move_file"]
            ),
            # Sheets Capabilities
            PlatformCapability(
                name="Sheets Operations",
                description="Create, read, write, and manage Google Sheets spreadsheets",
                tool_name="google_workspace_sheets",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create_spreadsheet", "read_range", "write_range", "append_rows", "clear_range", "batch_update", "format_cells", "create_chart", "get_info"]},
                        "spreadsheet_id": {"type": "string"},
                        "title": {"type": "string"},
                        "sheets": {"type": "array", "items": {"type": "string"}},
                        "range_name": {"type": "string"},
                        "values": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                        "value_input_option": {"type": "string", "enum": ["RAW", "USER_ENTERED"], "default": "USER_ENTERED"},
                        "requests": {"type": "array", "items": {"type": "object"}},
                        "format_options": {"type": "object"},
                        "chart_type": {"type": "string"},
                        "sheet_id": {"type": "integer"}
                    },
                    "required": ["operation"]
                },
                operations=[
                    "create_spreadsheet", 
                    "read_range", 
                    "write_range", 
                    "append_rows", 
                    "clear_range", 
                    "batch_update", 
                    "format_cells", 
                    "create_chart", 
                    "get_info"
                ]
            ),
            # Docs Capabilities
            PlatformCapability(
                name="Docs Operations",
                description="Create, edit, format, and manage Google Docs documents",
                tool_name="google_workspace_docs",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create_document", "read_document", "insert_text", "append_text", "replace_text", "format_text", "insert_table", "batch_update", "export_pdf"]},
                        "document_id": {"type": "string"},
                        "title": {"type": "string"},
                        "text": {"type": "string"},
                        "index": {"type": "integer"},
                        "find_text": {"type": "string"},
                        "replace_text": {"type": "string"},
                        "match_case": {"type": "boolean"},
                        "start_index": {"type": "integer"},
                        "end_index": {"type": "integer"},
                        "bold": {"type": "boolean"},
                        "italic": {"type": "boolean"},
                        "font_size": {"type": "integer"},
                        "foreground_color": {"type": "object"},
                        "rows": {"type": "integer"},
                        "columns": {"type": "integer"},
                        "requests": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["operation"]
                },
                operations=[
                    "create_document", 
                    "read_document", 
                    "insert_text", 
                    "append_text", 
                    "replace_text", 
                    "format_text", 
                    "insert_table", 
                    "batch_update", 
                    "export_pdf"
                ]
            ),
            # Analytics Capabilities
            PlatformCapability(
                name="Analytics Operations",
                description="Get comprehensive Google Analytics data including traffic, conversions, and user behavior",
                tool_name="google_workspace_analytics",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["get_traffic", "get_conversions", "get_user_behavior", "get_custom_report", "get_ecommerce_data"]},
                        "property_id": {"type": "string"},
                        "hours": {"type": "integer", "default": 24},
                        "metrics": {"type": "array", "items": {"type": "string"}},
                        "dimensions": {"type": "array", "items": {"type": "string"}},
                        "filters": {"type": "object"}
                    },
                    "required": ["operation"]
                },
                operations=["get_traffic", "get_conversions", "get_user_behavior", "get_custom_report", "get_ecommerce_data"]
            )
        ]
        
        self.platforms["google_workspace"] = Platform(
            id="google_workspace",
            name="Google Workspace",
            description="Complete Google Workspace integration - Gmail, Calendar, Drive, Sheets, and Docs",
            icon="google",
            features=[
                "Email management",
                "Calendar scheduling",
                "File storage and sharing",
                "Spreadsheet operations",
                "Document editing",
                "Analytics"
            ],
            capabilities=google_workspace_capabilities,
            config_schema={
                "type": "object",
                "properties": {
                    "client_id": {"type": "string", "description": "Google OAuth Client ID"},
                    "client_secret": {"type": "string", "description": "Google OAuth Client Secret"},
                    "refresh_token": {"type": "string", "description": "OAuth Refresh Token"},
                    "default_property_id": {"type": "string", "description": "Default Google Analytics Property ID"}
                },
                "required": ["client_id", "client_secret", "refresh_token"]
            },
            test_function="test_google_workspace_connection"
        )

        # System Platform (Workflow Management)
        system_capabilities = [
            PlatformCapability(
                name="Workflow Management",
                description="Manage automation workflows - create, draft, and list workflows",
                tool_name="workflow_management",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create_draft", "list_workflows", "get_workflow"]},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "steps": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["operation"]
                },
                operations=["create_draft", "list_workflows", "get_workflow"]
            )
        ]
        
        self.platforms["system"] = Platform(
            id="system",
            name="System",
            description="Core system capabilities including workflow management",
            icon="settings",
            features=["Workflow automation", "System settings"],
            capabilities=system_capabilities,
            config_schema={"type": "object", "properties": {}, "required": []},
            test_function="test_system_status"
        )


    def _initialize_kenyan_platforms(self):
        """Initialize the 50 new Kenyan business tools."""
        
        # Helper to create platforms in batch
        def register_domain_tools(domain_id_list, domain_name_map, caps_template, icon, config_schema, features):
            for pid in domain_id_list:
                name = domain_name_map.get(pid, pid.replace("_", " ").title())
                
                # Customize capabilities for this specific platform
                platform_caps = []
                for cap in caps_template:
                    platform_caps.append(PlatformCapability(
                        name=cap.name,
                        description=f"{name} {cap.description}",
                        tool_name=f"{pid}_{cap.tool_name.split('_', 1)[1]}",
                        input_schema=cap.input_schema,
                        operations=cap.operations
                    ))
                
                self.platforms[pid] = Platform(
                    id=pid,
                    name=name,
                    description=f"Kenyan {name} integration for business operations",
                    icon=icon,
                    features=features,
                    capabilities=platform_caps,
                    config_schema=config_schema,
                    test_function=f"test_{pid}_connection"
                )

        # 1. Fintech Tools
        fintech_tools = ["airtel_money", "t_kash", "equity_jenga", "flutterwave", "paystack", "kopo_kopo", "cellulant", "pesapal", "ipay", "little_pay"]
        fintech_names = {"airtel_money": "Airtel Money", "t_kash": "T-Kash", "equity_jenga": "Equity Jenga"}
        fintech_caps = [
            PlatformCapability(
                name="Payment Operations",
                description="operations including payment initiation and status queries",
                tool_name="placeholder_payment_ops",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["initiate_payment", "query_status", "fetch_payouts", "verify_transaction"]},
                        "amount": {"type": "number"},
                        "phone_number": {"type": "string"},
                        "transaction_id": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["initiate_payment", "query_status", "fetch_payouts", "verify_transaction"]
            )
        ]
        register_domain_tools(fintech_tools, fintech_names, fintech_caps, "credit-card", 
                             {"type": "object", "properties": {"api_key": {"type": "string"}}, "required": ["api_key"]},
                             ["Real-time payments", "Transaction status", "Payout management"])

        # 2. Ecommerce Tools
        ecommerce_tools = ["jumia", "kilimall", "jiji", "masoko", "copia", "twiga_foods", "wasoko", "sky_garden"]
        ecommerce_names = {"twiga_foods": "Twiga Foods", "sky_garden": "Sky Garden"}
        ecommerce_caps = [
            PlatformCapability(
                name="Store Management",
                description="operations for orders and inventory sync",
                tool_name="placeholder_ecommerce_ops",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["fetch_orders", "sync_inventory", "update_order_status"]},
                        "order_id": {"type": "string"},
                        "product_data": {"type": "object"}
                    },
                    "required": ["operation"]
                },
                operations=["fetch_orders", "sync_inventory", "update_order_status"]
            )
        ]
        register_domain_tools(ecommerce_tools, ecommerce_names, ecommerce_caps, "shopping-cart",
                             {"type": "object", "properties": {"seller_id": {"type": "string"}, "api_token": {"type": "string"}}, "required": ["seller_id", "api_token"]},
                             ["Order tracking", "Inventory sync", "Seller analytics"])

        # 3. Accounting & Tax
        accounting_tools = ["kra_itax", "quickbooks", "xero", "zoho_books", "lipabiz", "sasapay", "vyapar"]
        accounting_names = {"kra_itax": "KRA iTax", "zoho_books": "Zoho Books"}
        accounting_caps = [
            PlatformCapability(
                name="Financial Controls",
                description="operations for tax compliance and invoicing",
                tool_name="placeholder_accounting_ops",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["validate_pin", "check_compliance", "sync_invoices"]},
                        "pin": {"type": "string"},
                        "invoice_data": {"type": "object"}
                    },
                    "required": ["operation"]
                },
                operations=["validate_pin", "check_compliance", "sync_invoices"]
            )
        ]
        register_domain_tools(accounting_tools, accounting_names, accounting_caps, "file-text",
                             {"type": "object", "properties": {"client_id": {"type": "string"}, "client_secret": {"type": "string"}}, "required": ["client_id"]},
                             ["Tax compliance", "Invoice automation", "Financial reporting"])

        # 4. Logistics
        logistics_tools = ["amitruck", "lori_systems", "sendy", "busybee", "fargo_courier", "g4s"]
        logistics_names = {"lori_systems": "Lori Systems", "fargo_courier": "Fargo Courier"}
        logistics_caps = [
            PlatformCapability(
                name="Logistics Operations",
                description="operations for tracking and booking deliveries",
                tool_name="placeholder_logistics_ops",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["get_status", "book_truck", "calculate_fare"]},
                        "tracking_id": {"type": "string"},
                        "pickup": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["get_status", "book_truck", "calculate_fare"]
            )
        ]
        register_domain_tools(logistics_tools, logistics_names, logistics_caps, "truck",
                             {"type": "object", "properties": {"api_key": {"type": "string"}}, "required": ["api_key"]},
                             ["Live tracking", "Fleet management", "Route optimization"])

        # 5. HR & Payroll
        hr_tools = ["workpay", "seamlesshr", "bitrix24", "bamboohr", "rescue"]
        hr_names = {"workpay": "WorkPay", "seamlesshr": "SeamlessHR", "bamboohr": "BambooHR"}
        hr_caps = [
            PlatformCapability(
                name="Workforce Management",
                description="operations for payroll and employee management",
                tool_name="placeholder_hr_ops",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["process_payroll", "approve_leave", "onboard_employee"]},
                        "employee_id": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["process_payroll", "approve_leave", "onboard_employee"]
            )
        ]
        register_domain_tools(hr_tools, hr_names, hr_caps, "users",
                             {"type": "object", "properties": {"subdomain": {"type": "string"}, "api_key": {"type": "string"}}, "required": ["api_key"]},
                             ["Payroll automation", "Leave management", "Employee onboarding"])

        # 6. Agritech
        agri_tools = ["shambasmart", "digifarm", "sunculture", "apollo_agriculture", "iprocure", "m_farm", "farmdrive"]
        agri_names = {"shambasmart": "ShambaSmart", "digifarm": "DigiFarm", "apollo_agriculture": "Apollo Agriculture"}
        agri_caps = [
            PlatformCapability(
                name="Agritech Services",
                description="operations for market data and farm inputs",
                tool_name="placeholder_agri_ops",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["get_market_prices", "order_inputs", "request_credit"]},
                        "crop": {"type": "string"},
                        "location": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["get_market_prices", "order_inputs", "request_credit"]
            )
        ]
        register_domain_tools(agri_tools, agri_names, agri_caps, "leaf",
                             {"type": "object", "properties": {"account_id": {"type": "string"}}, "required": ["account_id"]},
                             ["Market pricing", "Input ordering", "Yield monitoring"])

        # 7. Healthtech
        health_tools = ["mydawa", "penda_health", "ilara_health"]
        health_names = {"mydawa": "MyDawa", "penda_health": "Penda Health", "ilara_health": "Ilara Health"}
        health_caps = [
            PlatformCapability(
                name="Health Management",
                description="operations for medical records and appointments",
                tool_name="placeholder_health_ops",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["book_appointment", "order_medicine", "view_records"]},
                        "patient_id": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                operations=["book_appointment", "order_medicine", "view_records"]
            )
        ]
        register_domain_tools(health_tools, health_names, health_caps, "activity",
                             {"type": "object", "properties": {"patient_token": {"type": "string"}}, "required": ["patient_token"]},
                             ["Telemedicine", "Prescription sync", "Appointment booking"])

        # 8. Utilities
        utility_tools = ["kenya_power", "nairobi_water", "safaricom_biz", "zuku"]
        utility_names = {"kenya_power": "Kenya Power", "nairobi_water": "Nairobi Water", "safaricom_biz": "Safaricom Biz"}
        utility_caps = [
            PlatformCapability(
                name="Utility Management",
                description="operations for bill payments and usage tracking",
                tool_name="placeholder_utility_ops",
                input_schema={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["buy_tokens", "pay_bill", "check_usage"]},
                        "account_number": {"type": "string"},
                        "amount": {"type": "number"}
                    },
                    "required": ["operation"]
                },
                operations=["buy_tokens", "pay_bill", "check_usage"]
            )
        ]
        register_domain_tools(utility_tools, utility_names, utility_caps, "zap",
                             {"type": "object", "properties": {"account_no": {"type": "string"}}, "required": ["account_no"]},
                             ["Bill automation", "Usage tracking", "Outage reports"])

    
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