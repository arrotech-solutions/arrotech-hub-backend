"""
Tool Registry Service for managing MCP tools and converting them to LLM function format.
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry for MCP tools that can be called by LLMs."""
    
    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}
        self._initialize_tools()
        self._initialize_kenyan_tools()
    
    def _initialize_tools(self):
        """Initialize available MCP tools."""
        self.tools = {
            # HubSpot Contact Management - Enhanced
            "hubspot_contact_operations": {
                "name": "hubspot_contact_operations",
                "description": "Comprehensive HubSpot contact management - read, create, update, search, and segment contacts",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["read", "create", "update", "search", "segment"]},
                        "contact_data": {"type": "object"},
                        "filters": {"type": "object"},
                        "limit": {"type": "integer", "default": 50},
                        "properties": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["operation"]
                }
            },
            "hubspot_deal_management": {
                "name": "hubspot_deal_management",
                "description": "Manage HubSpot deals - create, update, track, and analyze deal pipeline",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["read", "create", "update", "analyze"]},
                        "deal_data": {"type": "object"},
                        "filters": {"type": "object"},
                        "limit": {"type": "integer", "default": 20}
                    },
                    "required": ["operation"]
                }
            },
            "hubspot_analytics": {
                "name": "hubspot_analytics",
                "description": "Get HubSpot analytics and performance metrics",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"},
                        "metrics": {"type": "array", "items": {"type": "string"}}
                    }
                }
            },
            # GA4 Analytics & Reporting - Enhanced
            "ga4_analytics_dashboard": {
                "name": "ga4_analytics_dashboard",
                "description": "Get comprehensive GA4 analytics including traffic, conversions, user behavior, and custom reports",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "report_type": {"type": "string", "enum": ["traffic", "conversions", "user_behavior", "custom", "ecommerce"]},
                        "date_range": {"type": "string", "default": "last_30_days"},
                        "metrics": {"type": "array", "items": {"type": "string"}},
                        "dimensions": {"type": "array", "items": {"type": "string"}},
                        "filters": {"type": "object"}
                    },
                    "required": ["report_type"]
                }
            },
            "ga4_user_behavior": {
                "name": "ga4_user_behavior",
                "description": "Analyze user behavior patterns and engagement metrics",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "hours": {"type": "integer", "default": 24},
                        "user_segments": {"type": "array", "items": {"type": "string"}},
                        "engagement_metrics": {"type": "array", "items": {"type": "string"}}
                    }
                }
            },
            # Slack Team Communication - Enhanced
            "slack_team_communication": {
                "name": "slack_team_communication",
                "description": "Send messages, reports, alerts, and schedule messages to Slack channels with rich formatting",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["send_message", "send_report", "send_alert", "schedule_message", "join_channel"]},
                        "channel": {"type": "string"},
                        "message": {"type": "string"},
                        "report_type": {"type": "string"},
                        "blocks": {"type": "array"},
                        "schedule_time": {"type": "string"}
                    },
                    "required": ["action", "channel"]
                }
            },
            "slack_team_management": {
                "name": "slack_team_management",
                "description": "Manage Slack team channels, members, and workspace settings",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["list_channels", "get_members", "list_members", "list_channel_members", "create_channel", "invite_users", "archive_channel", "set_topic", "set_purpose", "list_users"]},
                        "channel_name": {"type": "string"},
                        "user_ids": {"type": "array", "items": {"type": "string"}},
                        "topic": {"type": "string"},
                        "purpose": {"type": "string"},
                        "include_bots": {"type": "boolean", "default": False}
                    },
                    "required": ["operation"]
                }
            },
            "slack_file_management": {
                "name": "slack_file_management",
                "description": "Upload files and manage file operations in Slack channels",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["upload_file"]},
                        "channel": {"type": "string"},
                        "file_path": {"type": "string"},
                        "title": {"type": "string"},
                        "comment": {"type": "string"}
                    },
                    "required": ["action", "channel", "file_path"]
                }
            },
            "slack_reactions": {
                "name": "slack_reactions",
                "description": "Add reactions to Slack messages",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["add_reaction"]},
                        "channel": {"type": "string"},
                        "timestamp": {"type": "string"},
                        "emoji": {"type": "string"}
                    },
                    "required": ["action", "channel", "timestamp", "emoji"]
                }
            },
            "slack_search": {
                "name": "slack_search",
                "description": "Search for messages and content in Slack",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["search_messages"]},
                        "query": {"type": "string"},
                        "channel": {"type": "string"},
                        "limit": {"type": "integer", "default": 20}
                    },
                    "required": ["action", "query"]
                }
            },
            "slack_user_management": {
                "name": "slack_user_management",
                "description": "Get user information and list workspace users",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_user_info", "list_users"]},
                        "user_id": {"type": "string"},
                        "user_name": {"type": "string"},
                        "include_bots": {"type": "boolean", "default": False}
                    },
                    "required": ["action"]
                }
            },
            "slack_pins": {
                "name": "slack_pins",
                "description": "Pin messages and get pinned content from Slack channels",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["pin_message", "get_pinned_messages"]},
                        "channel": {"type": "string"},
                        "timestamp": {"type": "string"}
                    },
                    "required": ["action", "channel"]
                }
            },
            # AI Agents and Commands
            "slack_ai_agents": {
                "name": "slack_ai_agents",
                "description": "Execute Slack commands and manage AI agent interactions",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["execute_command", "list_commands", "get_command_info"]},
                        "command": {"type": "string"},
                        "channel": {"type": "string"},
                        "user_id": {"type": "string"},
                        "args": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["action"]
                }
            },
            # File Management (Enhanced)
            "slack_file_operations": {
                "name": "slack_file_operations",
                "description": "Read, write, and manage files in Slack with advanced operations",
                "inputSchema": {
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
                }
            },
            # Link Management
            "slack_link_management": {
                "name": "slack_link_management",
                "description": "Manage and track links shared in Slack channels",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_shared_links", "track_link", "get_link_analytics"]},
                        "channel": {"type": "string"},
                        "url": {"type": "string"},
                        "date_range": {"type": "string"}
                    },
                    "required": ["action"]
                }
            },
            # Workflow Management
            "slack_workflows": {
                "name": "slack_workflows",
                "description": "Execute and manage Slack workflows and automation",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["execute_workflow", "list_workflows", "get_workflow_info", "create_workflow"]},
                        "workflow_id": {"type": "string"},
                        "workflow_name": {"type": "string"},
                        "channel": {"type": "string"},
                        "inputs": {"type": "object"}
                    },
                    "required": ["action"]
                }
            },
            # Incoming Webhooks
            "slack_webhooks": {
                "name": "slack_webhooks",
                "description": "Send messages via Slack incoming webhooks",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["send_webhook", "create_webhook", "list_webhooks"]},
                        "webhook_url": {"type": "string"},
                        "channel": {"type": "string"},
                        "message": {"type": "string"},
                        "blocks": {"type": "array"}
                    },
                    "required": ["action"]
                }
            },
            # User Context and Profile Management
            "slack_user_context": {
                "name": "slack_user_context",
                "description": "Read user profiles, team information, and manage user context",
                "inputSchema": {
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
                }
            },
            # Advanced Features
            "slack_advanced_features": {
                "name": "slack_advanced_features",
                "description": "Advanced Slack features including custom message formatting and reminders",
                "inputSchema": {
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
                }
            },
            # Admin and Department Management
            "slack_admin_tools": {
                "name": "slack_admin_tools",
                "description": "Admin tools for managing user groups, channels, and workspace settings",
                "inputSchema": {
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
                }
            },
            # Channel History and Analytics
            "slack_channel_analytics": {
                "name": "slack_channel_analytics",
                "description": "Read channel history and get analytics data",
                "inputSchema": {
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
                }
            },
            # Search and Discovery
            "slack_search_discovery": {
                "name": "slack_search_discovery",
                "description": "Advanced search capabilities for messages, files, and content",
                "inputSchema": {
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
                }
            },
            # Team and Workspace Management
            "slack_workspace_management": {
                "name": "slack_workspace_management",
                "description": "Manage workspace settings, team information, and workspace-wide operations",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_workspace_info", "get_team_stats", "list_workspace_channels", "get_workspace_settings", "get_workspace_analytics"]},
                        "workspace_id": {"type": "string"},
                        "include_private": {"type": "boolean", "default": False},
                        "include_archived": {"type": "boolean", "default": False}
                    },
                    "required": ["action"]
                }
            },
            # Microsoft Teams Integration
            "teams_team_communication": {
                "name": "teams_team_communication",
                "description": "Send messages, adaptive cards, alerts, and meeting notifications to Microsoft Teams channels",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["send_message", "send_adaptive_card", "send_alert", "send_meeting_notification"]},
                        "channel": {"type": "string"},
                        "message": {"type": "string"},
                        "message_type": {"type": "string", "enum": ["text", "html"], "default": "text"},
                        "card_content": {"type": "object"},
                        "alert_type": {"type": "string", "enum": ["info", "warning", "error", "success"]},
                        "severity": {"type": "string", "enum": ["low", "medium", "high"], "default": "medium"},
                        "meeting_title": {"type": "string"},
                        "meeting_time": {"type": "string"},
                        "meeting_link": {"type": "string"},
                        "attendees": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["action"]
                }
            },
            "teams_channel_management": {
                "name": "teams_channel_management",
                "description": "Manage Microsoft Teams channels - list channels, get members, create channels, and get team information",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["list_channels", "get_channel_members", "create_channel", "get_team_info"]},
                        "team_id": {"type": "string"},
                        "channel_name": {"type": "string"},
                        "description": {"type": "string"},
                        "channel_id": {"type": "string"}
                    },
                    "required": ["action"]
                }
            },
            "teams_message_search": {
                "name": "teams_message_search",
                "description": "Search for messages or get recent chats from Microsoft Teams",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["search_messages", "get_recent_chats"], "default": "search_messages"},
                        "query": {"type": "string", "description": "Required for search_messages"},
                        "channel_id": {"type": "string"},
                        "limit": {"type": "integer", "default": 20}
                    },
                    "required": ["action"]
                }
            },
            # Outlook Integration
            "outlook_email_management": {
                "name": "outlook_email_management",
                "description": "Read, search, and send emails using Microsoft Outlook",
                "inputSchema": {
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
                }
            },
            # Notion Integration
            "notion_workspace_management": {
                "name": "notion_workspace_management",
                "description": "Search and manage pages in Notion workspace",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["search_pages", "create_page"]},
                        "query": {"type": "string", "description": "Query for search"},
                        "limit": {"type": "integer", "default": 10},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "parent_id": {"type": "string", "description": "Page or Database ID parent"}
                    },
                    "required": ["action"]
                }
            },
            # Trello Integration
            "trello_project_management": {
                "name": "trello_project_management",
                "description": "Manage boards, lists and cards in Trello",
                "inputSchema": {
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
                }
            },
            # Jira Integration
            "jira_issue_tracking": {
                "name": "jira_issue_tracking",
                "description": "Manage issues and projects in Jira",
                "inputSchema": {
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
                }
            },
            # Zoom Integration
            "zoom_meeting_management": {
                "name": "zoom_meeting_management",
                "description": "Create, update, delete, and manage Zoom meetings",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["create", "get", "update", "delete", "list"]},
                        "topic": {"type": "string"},
                        "start_time": {"type": "string"},
                        "duration": {"type": "integer", "default": 60},
                        "password": {"type": "string"},
                        "meeting_id": {"type": "string"},
                        "settings": {"type": "object"},
                        "user_id": {"type": "string", "default": "me"},
                        "type": {"type": "string", "default": "scheduled"},
                        "page_size": {"type": "integer", "default": 30},
                        "page_number": {"type": "integer", "default": 1}
                    },
                    "required": ["action"]
                }
            },
            "zoom_meeting_operations": {
                "name": "zoom_meeting_operations",
                "description": "Manage meeting participants, registrants, and operations",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_participants", "get_registrants", "get_invitation", "update_status"]},
                        "meeting_id": {"type": "string"},
                        "page_size": {"type": "integer", "default": 30},
                        "page_number": {"type": "integer", "default": 1},
                        "status_action": {"type": "string"}
                    },
                    "required": ["action", "meeting_id"]
                }
            },
            "zoom_recording_management": {
                "name": "zoom_recording_management",
                "description": "Manage meeting recordings and recordings analytics",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_recordings", "delete_recording"]},
                        "meeting_id": {"type": "string"},
                        "recording_id": {"type": "string"},
                        "page_size": {"type": "integer", "default": 30},
                        "page_number": {"type": "integer", "default": 1}
                    },
                    "required": ["action", "meeting_id"]
                }
            },
            "zoom_user_management": {
                "name": "zoom_user_management",
                "description": "Manage Zoom users and account information",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get_user", "list_users"]},
                        "user_id": {"type": "string", "default": "me"},
                        "status": {"type": "string", "default": "active"},
                        "page_size": {"type": "integer", "default": 30},
                        "page_number": {"type": "integer", "default": 1}
                    },
                    "required": ["action"]
                }
            },
            "zoom_webinar_management": {
                "name": "zoom_webinar_management",
                "description": "Create and manage Zoom webinars",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["create", "get", "list"]},
                        "topic": {"type": "string"},
                        "start_time": {"type": "string"},
                        "duration": {"type": "integer", "default": 60},
                        "password": {"type": "string"},
                        "webinar_id": {"type": "string"},
                        "settings": {"type": "object"},
                        "user_id": {"type": "string", "default": "me"},
                        "page_size": {"type": "integer", "default": 30},
                        "page_number": {"type": "integer", "default": 1}
                    },
                    "required": ["action"]
                }
            },
            "zoom_analytics": {
                "name": "zoom_analytics",
                "description": "Get meeting reports, analytics, and performance data",
                "inputSchema": {
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
                }
            },
            # WhatsApp Business API Integration
            "whatsapp_messaging": {
                "name": "whatsapp_messaging",
                "description": "Send WhatsApp messages to phone numbers with rich media support",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["send_message", "send_media", "send_location"]},
                        "to_number": {"type": "string"},
                        "message": {"type": "string"},
                        "media_url": {"type": "string"},
                        "media_type": {"type": "string", "enum": ["image", "video", "audio", "document"]}
                    },
                    "required": ["action", "to_number"]
                }
            },
            "whatsapp_templates": {
                "name": "whatsapp_templates",
                "description": "Send WhatsApp template messages for business communications",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["send_template", "list_templates", "create_template"]},
                        "to_number": {"type": "string"},
                        "template_name": {"type": "string"},
                        "language_code": {"type": "string", "default": "en_US"},
                        "components": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["action"]
                }
            },
            # Marketing Campaign Automation
            "marketing_campaign_automation": {
                "name": "marketing_campaign_automation",
                "description": "Automate marketing campaigns across multiple platforms with AI-driven optimization",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "campaign_type": {"type": "string", "enum": ["email", "social", "ads", "multi_channel"]},
                        "target_audience": {"type": "object"},
                        "content": {"type": "object"},
                        "schedule": {"type": "object"},
                        "optimization_rules": {"type": "object"},
                        "platforms": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["campaign_type", "target_audience"]
                }
            },
            "campaign_performance_tracking": {
                "name": "campaign_performance_tracking",
                "description": "Track and analyze campaign performance across all channels",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "campaign_id": {"type": "string"},
                        "metrics": {"type": "array", "items": {"type": "string"}},
                        "date_range": {"type": "string"},
                        "channels": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["campaign_id"]
                }
            },
            # Phase 2: Advanced Features
            "lead_scoring_engine": {
                "name": "lead_scoring_engine",
                "description": "Score and qualify leads using AI-driven algorithms and behavioral analysis",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["score_lead", "create_rule", "get_analytics", "update_criteria"]},
                        "lead_data": {"type": "object"},
                        "rule_config": {"type": "object"},
                        "date_range": {"type": "string"}
                    },
                    "required": ["operation"]
                }
            },
            "customer_journey_mapping": {
                "name": "customer_journey_mapping",
                "description": "Map and analyze customer journeys across all touchpoints and channels",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create_map", "track_touchpoint", "get_journey", "analyze_trends", "optimize"]},
                        "journey_data": {"type": "object"},
                        "touchpoint_data": {"type": "object"},
                        "optimization_goals": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["operation"]
                }
            },
            "predictive_analytics_engine": {
                "name": "predictive_analytics_engine",
                "description": "Predict customer behavior, churn risk, and business outcomes using AI",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["generate_forecast", "analyze_trends", "predict_behavior", "get_analytics"]},
                        "metric": {"type": "string"},
                        "historical_data": {"type": "object"},
                        "forecast_periods": {"type": "integer"},
                        "confidence_level": {"type": "number"},
                        "customer_data": {"type": "object"},
                        "prediction_type": {"type": "string"},
                        "data_source": {"type": "string"},
                        "date_range": {"type": "string"}
                    },
                    "required": ["operation"]
                }
            },
            "ab_testing_platform": {
                "name": "ab_testing_platform",
                "description": "Create, run, and analyze A/B tests for campaigns and user experiences",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create_test", "run_test", "get_results", "analyze_performance"]},
                        "test_config": {"type": "object"},
                        "test_id": {"type": "string"},
                        "variants": {"type": "array", "items": {"type": "object"}},
                        "traffic_split": {"type": "object"},
                        "success_metrics": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["operation"]
                }
            },
            "social_media_management": {
                "name": "social_media_management",
                "description": "Manage social media campaigns, content scheduling, and engagement tracking",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["schedule_post", "analyze_performance", "engage_audience", "create_campaign"]},
                        "platform": {"type": "string", "enum": ["facebook", "twitter", "linkedin", "instagram"]},
                        "content": {"type": "object"},
                        "schedule": {"type": "object"},
                        "campaign_data": {"type": "object"},
                        "engagement_metrics": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["operation"]
                }
            },
            "social_media_connect_account": {
                "name": "social_media_connect_account",
                "description": "Connect a social media account to the platform",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "platform": {"type": "string", "enum": ["facebook", "twitter", "linkedin", "instagram"], "description": "Social media platform"},
                        "account_name": {"type": "string", "description": "Account name or handle"},
                        "credentials": {"type": "object", "description": "Account credentials"}
                    },
                    "required": ["platform", "account_name", "credentials"]
                }
            },
            "social_media_analytics": {
                "name": "social_media_analytics",
                "description": "Get comprehensive social media analytics and performance metrics",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "date_range": {"type": "string", "description": "Date range for analytics (e.g., '7d', '30d')", "default": "7d"},
                        "platform": {"type": "string", "enum": ["facebook", "twitter", "linkedin", "instagram", "all"], "description": "Specific platform or all platforms", "default": "all"}
                    }
                }
            },
            # Phase 3: Enterprise Features
            "white_label_management": {
                "name": "white_label_management",
                "description": "Create and manage white-label solutions with custom branding and domains",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create_brand", "update_brand", "create_deployment", "get_assets", "get_status"]},
                        "brand_config": {"type": "object"},
                        "domain_config": {"type": "object"},
                        "deployment_config": {"type": "object"},
                        "brand_id": {"type": "string"},
                        "deployment_id": {"type": "string"}
                    },
                    "required": ["operation"]
                }
            },
            "workflow_builder": {
                "name": "workflow_builder",
                "description": "Build custom automation workflows with drag-and-drop interface and conditional logic",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create_workflow", "update_workflow", "execute_workflow", "get_analytics"]},
                        "workflow_config": {"type": "object"},
                        "triggers": {"type": "array", "items": {"type": "object"}},
                        "steps": {"type": "array", "items": {"type": "object"}},
                        "conditions": {"type": "array", "items": {"type": "object"}},
                        "trigger_data": {"type": "object"},
                        "workflow_id": {"type": "string"}
                    },
                    "required": ["operation"]
                }
            },
            "api_management": {
                "name": "api_management",
                "description": "Manage API keys, rate limits, monitoring, and developer portal features",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create_api_key", "validate_key", "set_rate_limit", "get_analytics", "create_portal"]},
                        "user_id": {"type": "string"},
                        "api_key": {"type": "string"},
                        "permissions": {"type": "array", "items": {"type": "string"}},
                        "rate_limit_config": {"type": "object"},
                        "portal_config": {"type": "object"}
                    },
                    "required": ["operation"]
                }
            },
            "enterprise_security": {
                "name": "enterprise_security",
                "description": "Advanced security features, compliance monitoring, and audit logging",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create_policy", "enforce_policy", "encrypt_data", "decrypt_data", "run_compliance_check"]},
                        "policy_config": {"type": "object"},
                        "user_id": {"type": "string"},
                        "action": {"type": "string"},
                        "resource": {"type": "string"},
                        "context": {"type": "object"},
                        "data": {"type": "string"},
                        "key_id": {"type": "string"},
                        "check_type": {"type": "string"},
                        "parameters": {"type": "object"}
                    },
                    "required": ["operation"]
                }
            },
            "multi_tenant_management": {
                "name": "multi_tenant_management",
                "description": "Manage multi-tenant architecture with tenant isolation and resource management",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create_tenant", "update_plan", "check_quota", "get_analytics", "create_integration"]},
                        "tenant_config": {"type": "object"},
                        "tenant_id": {"type": "string"},
                        "new_plan": {"type": "string"},
                        "resource_type": {"type": "string"},
                        "amount": {"type": "integer"},
                        "integration_config": {"type": "object"}
                    },
                    "required": ["operation"]
                }
            },
            # Legacy tools for backward compatibility
            "hubspot_read_contacts": {
                "name": "hubspot_read_contacts",
                "description": "Get contacts from HubSpot CRM",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Number of contacts to retrieve",
                            "default": 10
                        },
                        "properties": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Contact properties to retrieve"
                        }
                    }
                }
            },
            "hubspot_write_contact": {
                "name": "hubspot_write_contact",
                "description": "Create or update a contact in HubSpot CRM",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "Contact email address"
                        },
                        "first_name": {
                            "type": "string",
                            "description": "Contact first name"
                        },
                        "last_name": {
                            "type": "string",
                            "description": "Contact last name"
                        },
                        "company": {
                            "type": "string",
                            "description": "Contact company"
                        },
                        "phone": {
                            "type": "string",
                            "description": "Contact phone number"
                        }
                    },
                    "required": ["email"]
                }
            },
            "hubspot_add_deal_note": {
                "name": "hubspot_add_deal_note",
                "description": "Add a note to a HubSpot deal",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "deal_id": {
                            "type": "string",
                            "description": "HubSpot deal ID"
                        },
                        "note": {
                            "type": "string",
                            "description": "Note content to add"
                        }
                    },
                    "required": ["deal_id", "note"]
                }
            },
            "ga4_get_traffic": {
                "name": "ga4_get_traffic",
                "description": "Get website traffic data from Google Analytics 4",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "hours": {
                            "type": "integer",
                            "description": "Number of hours to look back",
                            "default": 24
                        }
                    }
                }
            },
            "ga4_get_conversions": {
                "name": "ga4_get_conversions",
                "description": "Get conversion data from Google Analytics 4",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "hours": {
                            "type": "integer",
                            "description": "Number of hours to look back",
                            "default": 24
                        },
                        "conversion_events": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific conversion events to track"
                        }
                    }
                }
            },
            "slack_send_message": {
                "name": "slack_send_message",
                "description": "Send a message to a Slack channel",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel": {
                            "type": "string",
                            "description": "Slack channel name or ID"
                        },
                        "message": {
                            "type": "string",
                            "description": "Message content to send"
                        },
                        "blocks": {
                            "type": "array",
                            "description": "Slack blocks for rich formatting"
                        }
                    },
                    "required": ["channel", "message"]
                }
            },
            "slack_send_report": {
                "name": "slack_send_report",
                "description": "Send a formatted report to Slack",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel": {
                            "type": "string",
                            "description": "Slack channel name or ID"
                        },
                        "report_type": {
                            "type": "string",
                            "enum": ["campaign_summary", "traffic_report", "conversion_report"],
                            "description": "Type of report to generate"
                        },
                        "date_range": {
                            "type": "string",
                            "description": "Date range for the report"
                        }
                    },
                    "required": ["channel", "report_type"]
                }
            },
            "social_media_management": {
                "name": "social_media_management",
                "description": "Manage social media campaigns, content scheduling, and engagement tracking",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["schedule_post", "analyze_performance", "engage_audience", "create_campaign"],
                            "description": "Social media operation to perform"
                        },
                        "platform": {
                            "type": "string",
                            "enum": ["facebook", "twitter", "linkedin", "instagram"],
                            "description": "Social media platform"
                        },
                        "content": {
                            "type": "object",
                            "description": "Content data for posts"
                        },
                        "schedule": {
                            "type": "object",
                            "description": "Scheduling configuration"
                        },
                        "campaign_data": {
                            "type": "object",
                            "description": "Campaign configuration data"
                        },
                        "date_range": {
                            "type": "string",
                            "description": "Date range for analytics"
                        }
                    },
                    "required": ["operation"]
                }
            },
            "social_media_connect_account": {
                "name": "social_media_connect_account",
                "description": "Connect a social media account to the platform",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "platform": {
                            "type": "string",
                            "enum": ["facebook", "twitter", "linkedin", "instagram"],
                            "description": "Social media platform"
                        },
                        "account_name": {
                            "type": "string",
                            "description": "Account name or handle"
                        },
                        "credentials": {
                            "type": "object",
                            "description": "Account credentials"
                        }
                    },
                    "required": ["platform", "account_name", "credentials"]
                }
            },
            "social_media_analytics": {
                "name": "social_media_analytics",
                "description": "Get comprehensive social media analytics and performance metrics",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "date_range": {
                            "type": "string",
                            "description": "Date range for analytics (e.g., '7d', '30d')",
                            "default": "7d"
                        },
                        "platform": {
                            "type": "string",
                            "enum": ["facebook", "twitter", "linkedin", "instagram", "all"],
                            "description": "Specific platform or all platforms",
                            "default": "all"
                        }
                    }
                }
            },
            "content_creation": {
                "name": "content_creation",
                "description": "Generate images, create content from templates, and optimize for SEO",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string", 
                            "enum": ["generate_image", "create_from_template", "generate_bulk_content", "optimize_seo", "generate_calendar"],
                            "description": "The type of content creation operation to perform"
                        },
                        "text": {
                            "type": "string",
                            "description": "Text content for image generation or content creation"
                        },
                        "style": {
                            "type": "string",
                            "description": "Style for image generation (modern, minimal, vintage)",
                            "default": "modern"
                        },
                        "size": {
                            "type": "object",
                            "description": "Size dimensions for image generation",
                            "default": [800, 600]
                        },
                        "template_name": {
                            "type": "string",
                            "description": "Template name for content creation"
                        },
                        "variables": {
                            "type": "object",
                            "description": "Variables to fill in template"
                        },
                        "base_content": {
                            "type": "string",
                            "description": "Base content for bulk generation"
                        },
                        "variations": {
                            "type": "integer",
                            "description": "Number of variations to generate",
                            "default": 5
                        },
                        "content_type": {
                            "type": "string",
                            "description": "Type of content for bulk generation"
                        },
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Keywords for SEO optimization"
                        },
                        "start_date": {
                            "type": "string",
                            "description": "Start date for content calendar"
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date for content calendar"
                        }
                    },
                    "required": ["operation"]
                }
            },
            "file_management": {
                "name": "file_management",
                "description": "Upload, download, and manage files with PDF generation and document conversion",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string", 
                            "enum": ["upload", "download", "list", "delete", "generate_pdf", "convert_document", "generate_qr"],
                            "description": "The type of file management operation to perform"
                        },
                        "filename": {
                            "type": "string",
                            "description": "Name of the file to work with"
                        },
                        "content": {
                            "type": "string",
                            "description": "Content to write to file"
                        },
                        "from_format": {
                            "type": "string",
                            "description": "Source format for document conversion"
                        },
                        "to_format": {
                            "type": "string",
                            "description": "Target format for document conversion"
                        },
                        "template": {
                            "type": "string",
                            "description": "Template for PDF generation"
                        },
                        "qr_data": {
                            "type": "string",
                            "description": "Data to encode in QR code"
                        },
                        "qr_size": {
                            "type": "integer",
                            "description": "Size of QR code",
                            "default": 10
                        }
                    },
                    "required": ["operation"]
                }
            },
            # Power BI Analytics & Reporting
            "powerbi_workspace_management": {
                "name": "powerbi_workspace_management",
                "description": "Manage Power BI workspaces - create, delete, and get workspace information",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["list", "create", "delete", "get_info"]},
                        "workspace_name": {"type": "string"},
                        "workspace_description": {"type": "string"},
                        "workspace_id": {"type": "string"}
                    },
                    "required": ["operation"]
                }
            },
            "powerbi_dataset_operations": {
                "name": "powerbi_dataset_operations",
                "description": "Manage Power BI datasets - get datasets, schema, refresh, and execute DAX queries",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["list", "get_schema", "refresh", "execute_query", "get_refresh_history"]},
                        "workspace_id": {"type": "string"},
                        "dataset_id": {"type": "string"},
                        "dax_query": {"type": "string"}
                    },
                    "required": ["operation"]
                }
            },
            "powerbi_report_management": {
                "name": "powerbi_report_management",
                "description": "Manage Power BI reports - list reports, get embed tokens, and report analytics",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["list", "get_embed_token", "get_analytics"]},
                        "workspace_id": {"type": "string"},
                        "report_id": {"type": "string"}
                    },
                    "required": ["operation"]
                }
            },
            "powerbi_dashboard_operations": {
                "name": "powerbi_dashboard_operations",
                "description": "Manage Power BI dashboards - list dashboards and get dashboard information",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["list", "get_info"]},
                        "workspace_id": {"type": "string"},
                        "dashboard_id": {"type": "string"}
                    },
                    "required": ["operation"]
                }
            },
            "powerbi_analytics_summary": {
                "name": "powerbi_analytics_summary",
                "description": "Get comprehensive Power BI analytics summary including workspaces, datasets, reports, and activity logs",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string"},
                        "include_activity_logs": {"type": "boolean", "default": True},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"}
                    }
                }
            },
            "powerbi_user_management": {
                "name": "powerbi_user_management",
                "description": "Manage Power BI workspace users and permissions",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["list_users", "get_user_info"]},
                        "workspace_id": {"type": "string"},
                        "user_id": {"type": "string"}
                    },
                    "required": ["operation", "workspace_id"]
                }
            }
        }

    def _initialize_kenyan_tools(self):
        """Initialize tools for the 50 new Kenyan business platforms."""
        
        # Helper to batch register tools
        def register_domain_tools(tool_ids, domain_desc, input_schema):
            for tid in tool_ids:
                # Use the pattern {id}_{domain_suffix} to match platform_registry
                if "payment" in domain_desc.lower():
                    tool_name = f"{tid}_payment_ops"
                elif "ecommerce" in domain_desc.lower() or "store" in domain_desc.lower():
                    tool_name = f"{tid}_ecommerce_ops"
                elif "accounting" in domain_desc.lower() or "financial" in domain_desc.lower():
                    tool_name = f"{tid}_accounting_ops"
                elif "logistics" in domain_desc.lower():
                    tool_name = f"{tid}_logistics_ops"
                elif "hr" in domain_desc.lower() or "workforce" in domain_desc.lower():
                    tool_name = f"{tid}_hr_ops"
                elif "agritech" in domain_desc.lower() or "agri" in domain_desc.lower():
                    tool_name = f"{tid}_agri_ops"
                elif "health" in domain_desc.lower():
                    tool_name = f"{tid}_health_ops"
                elif "utility" in domain_desc.lower():
                    tool_name = f"{tid}_utility_ops"
                else:
                    continue
                
                name_pretty = tid.replace("_", " ").title()
                self.tools[tool_name] = {
                    "name": tool_name,
                    "description": f"{name_pretty} {domain_desc}",
                    "inputSchema": input_schema
                }

        # fintech
        fintech_tools = ["airtel_money", "t_kash", "equity_jenga", "flutterwave", "paystack", "kopo_kopo", "cellulant", "pesapal", "ipay", "little_pay"]
        register_domain_tools(fintech_tools, "Payment operations including initiation, status queries, and payouts", {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["initiate_payment", "query_status", "fetch_payouts", "verify_transaction"]},
                "amount": {"type": "number"},
                "phone_number": {"type": "string"},
                "transaction_id": {"type": "string"}
            },
            "required": ["operation"]
        })

        # ecommerce
        ecommerce_tools = ["jumia", "kilimall", "jiji", "masoko", "copia", "twiga_foods", "wasoko", "sky_garden"]
        register_domain_tools(ecommerce_tools, "Store management operations for orders, inventory sync, and status updates", {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["fetch_orders", "sync_inventory", "update_order_status"]},
                "order_id": {"type": "string"},
                "product_data": {"type": "object"}
            },
            "required": ["operation"]
        })

        # accounting
        accounting_tools = ["kra_itax", "quickbooks", "xero", "zoho_books", "lipabiz", "sasapay", "vyapar"]
        register_domain_tools(accounting_tools, "Financial and accounting operations for tax compliance and invoicing", {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["validate_pin", "check_compliance", "sync_invoices"]},
                "pin": {"type": "string"},
                "invoice_data": {"type": "object"}
            },
            "required": ["operation"]
        })

        # KRA GavaConnect
        kra_tools = ["kra_pin_checker", "kra_id_checker", "kra_nil_return"]
        register_domain_tools(kra_tools, "KRA Tax operations for PIN verification and NIL return filing", {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["check_pin", "check_id", "file_nil_return"]},
                "pin": {"type": "string"},
                "id_number": {"type": "string"},
                "tax_obligation": {"type": "string"},
                "period_from": {"type": "string"},
                "period_to": {"type": "string"}
            },
            "required": ["operation"]
        })
        
        # logistics
        logistics_tools = ["lori_systems", "sendy", "amitruck", "sokowatch"]
        register_domain_tools(logistics_tools, "Logistics operations for tracking, booking, and fare calculation", {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["get_status", "book_truck", "calculate_fare"]},
                "tracking_id": {"type": "string"},
                "pickup": {"type": "string"}
            },
            "required": ["operation"]
        })

        # hr
        hr_tools = ["workpay", "seamlesshr", "bitrix24", "bamboohr", "rescue"]
        register_domain_tools(hr_tools, "HR and workforce management operations for payroll, leave, and onboarding", {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["process_payroll", "approve_leave", "onboard_employee"]},
                "employee_id": {"type": "string"}
            },
            "required": ["operation"]
        })

        # agritech
        agri_tools = ["shambasmart", "digifarm", "sunculture", "apollo_agriculture", "iprocure", "m_farm", "farmdrive"]
        register_domain_tools(agri_tools, "Agritech operations for market prices, input ordering, and credit requests", {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["get_market_prices", "order_inputs", "request_credit"]},
                "crop": {"type": "string"}
            },
            "required": ["operation"]
        })

        # health
        health_tools = ["mydawa", "penda_health", "ilara_health"]
        register_domain_tools(health_tools, "Health management operations for records, appointments, and medicine orders", {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["book_appointment", "order_medicine", "view_records"]},
                "patient_id": {"type": "string"}
            },
            "required": ["operation"]
        })

        # utility
        utility_tools = ["kenya_power", "nairobi_water", "safaricom_biz", "zuku"]
        register_domain_tools(utility_tools, "Utility management operations for tokens, bill payments, and usage tracking", {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["buy_tokens", "pay_bill", "check_usage"]},
                "account_no": {"type": "string"},
                "amount": {"type": "number"}
            },
            "required": ["operation"]
        })
    
    def get_tools_for_llm(self) -> List[Dict[str, Any]]:
        """Get tools in format suitable for LLM function calling."""
        return list(self.tools.values())
    
    def get_tool(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific tool by name."""
        return self.tools.get(tool_name)
    
    def list_tools(self) -> List[str]:
        """Get list of available tool names."""
        return list(self.tools.keys())
    
    def add_tool(self, tool_name: str, tool_config: Dict[str, Any]):
        """Add a new tool to the registry."""
        self.tools[tool_name] = tool_config
        logger.info(f"Added tool: {tool_name}")
    
    def remove_tool(self, tool_name: str):
        """Remove a tool from the registry."""
        if tool_name in self.tools:
            del self.tools[tool_name]
            logger.info(f"Removed tool: {tool_name}")
    
    def get_tool_descriptions(self) -> str:
        """Get a human-readable description of all available tools."""
        descriptions = []
        for tool_name, tool_config in self.tools.items():
            desc = f"- {tool_name}: {tool_config['description']}"
            descriptions.append(desc)
        return "\n".join(descriptions)


# Global tool registry instance
tool_registry = ToolRegistry() 