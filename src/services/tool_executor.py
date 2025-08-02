"""
Tool Executor Service for executing MCP tools based on LLM decisions.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from slack_sdk import WebClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from .content_creation_service import ContentCreationService
from .file_management_service import FileManagementService
from .ga4_service import GA4Service
from .hubspot_service import HubSpotService
from .salesforce_service import SalesforceService
from .slack_service import SlackService
from .social_media_service import SocialMediaService
from .web_tools_service import WebToolsService
from .whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Executes MCP tools based on LLM decisions."""

    def __init__(self):
        self.services = {
            "slack": SlackService(),
            "hubspot": HubSpotService(),
            "salesforce": SalesforceService(),
            "ga4": GA4Service(),
            "whatsapp": WhatsAppService(),
            "social_media": SocialMediaService(),
            "file_management": FileManagementService(),
            "web_tools": WebToolsService(),
            "content_creation": ContentCreationService(),
        }
        # Initialize services
        self._initialized = False

    async def _initialize_services(self):
        """Initialize all services that don't require parameters."""
        if not self._initialized:
            for service_name, service in self.services.items():
                if hasattr(service, 'initialize'):
                    # Only initialize services that don't require parameters
                    # Services like Salesforce require a connection parameter and should be initialized per-request
                    if service_name in ["slack", "ga4", "whatsapp", "social_media", "file_management", "web_tools", "content_creation", "rate_limit", "billing"]:
                        await service.initialize()
            self._initialized = True

    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession,
        tools_called: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute a specific tool with given arguments."""
        try:
            logger.info(
                f"Executing tool: {tool_name} with arguments: {arguments}")

            # Initialize services if not already done
            await self._initialize_services()
            
            # Store tools_called for reference resolution
            if tools_called is not None:
                self._tools_called = tools_called

            # Route to appropriate service based on tool name
            if tool_name.startswith("slack_"):
                return await self._execute_slack_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("hubspot_"):
                return await self._execute_hubspot_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("salesforce_"):
                return await self._execute_salesforce_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("ga4_"):
                return await self._execute_ga4_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("marketing_"):
                return await self._execute_marketing_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("whatsapp_"):
                return await self._execute_whatsapp_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("social_media_"):
                return await self._execute_social_media_tool(tool_name, arguments, user, db)
            elif tool_name == "file_management":
                return await self._execute_file_management_tool(arguments, user, db, getattr(self, '_tools_called', []))
            elif tool_name == "web_tools":
                return await self._execute_web_tools_tool(arguments, user, db)
            elif tool_name == "content_creation":
                return await self._execute_content_creation_tool(arguments, user, db)
            else:
                return {
                    "success": False,
                    "error": f"Unknown tool: {tool_name}",
                    "result": None
                }

        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "result": None
            }

    async def _execute_slack_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Slack-related tools."""
        # Get user's Slack connection
        result = await db.execute(
            select(Connection)
            .filter(
                Connection.user_id == user.id,
                Connection.platform == "slack",
                Connection.status == ConnectionStatus.ACTIVE
            )
        )
        connection = result.scalar_one_or_none()

        if not connection:
            return {
                "success": False,
                "error": "No active Slack connection found",
                "result": None
            }

        # Initialize Slack service with user's connection token
        slack_service = SlackService()
        bot_token = connection.config.get("bot_token")
        if not bot_token:
            return {
                "success": False,
                "error": "No bot token found in Slack connection",
                "result": None
            }

        # Initialize the service with the user's token
        slack_service.client = WebClient(token=bot_token)
        print(
            f"🔧 Initialized Slack service with user token for user {user.id}")

        if tool_name == "slack_team_communication":
            action = arguments.get("action", "send_message")
            channel = arguments.get("channel", "")
            message = arguments.get("message", "")
            file_path = arguments.get("file_path") # Get the file_path from arguments

            # Ensure channel has # prefix
            if channel and not channel.startswith("#"):
                channel = f"#{channel}"

            if action == "send_message":
                if file_path:
                    # If file_path is present, use upload_file instead of send_message
                    print(f"📤 Uploading file {file_path} to Slack channel {channel} with message: {message}")
                    result = await slack_service.upload_file(
                        channel=channel,
                        file_path=file_path,
                        comment=message # Use message as initial comment
                    )
                    return {
                        "success": result.get("success", False),
                        "result": f"File uploaded to {channel}: {file_path}",
                        "data": result,
                        "processed_arguments": {
                            "channel": channel,
                            "file_path": file_path,
                            "message": message
                        }
                    }
                else:
                    # Original send_message logic if no file_path
                    print(f"💬 Sending message to Slack channel {channel}: {message}")
                    result = await slack_service.send_message(
                        channel, message
                    )
                    return {
                        "success": True,
                        "result": f"Message sent to {channel}: {message}",
                        "data": result,
                        "processed_arguments": {
                            "channel": channel,  # This will have the # prefix
                            "message": message
                        }
                    }
            elif action == "send_report":
                report_type = arguments.get("report_type", "analytics_report")
                result = await slack_service.send_report(
                    channel=channel,
                    report_type=report_type,
                    date_range=arguments.get("date_range")
                )
                return {
                    "success": True,
                    "result": f"Report sent to {channel}: {report_type}",
                    "data": result,
                    "processed_arguments": {
                        "channel": channel,
                        "report_type": report_type
                    }
                }
            elif action == "join_channel":
                print(f"🔗 Joining Slack channel: {channel}")
                result = await slack_service.join_channel(channel)
                return {
                    "success": result.get("success", False),
                    "result": f"Channel join attempt for {channel}",
                    "data": result,
                    "processed_arguments": {
                        "channel": channel
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Slack action: {action}",
                    "result": None
                }

        elif tool_name == "slack_team_management":
            # Handle both "action" and "operation" parameters
            operation = arguments.get("operation") or arguments.get("action")

            if operation == "list_channels":
                channels = await slack_service.list_channels()
                return {
                    "success": True,
                    "result": f"Found {len(channels)} channels",
                    "data": channels
                }
        
        elif tool_name == "slack_list_channels":
            print(f"📋 Listing Slack channels for user {user.id}")
            result = await slack_service.list_channels()
            return {
                "success": True,
                "result": f"Retrieved {len(result.get('channels', []))} Slack channels",
                "data": result,
                "processed_arguments": {}
            }
        
        elif tool_name == "slack_send_message":
            channel = arguments.get("channel", "")
            message = arguments.get("message", "")
            
            # Ensure channel has # prefix
            if channel and not channel.startswith("#"):
                channel = f"#{channel}"
            
            print(f"💬 Sending message to Slack channel {channel}: {message}")
            result = await slack_service.send_message(channel, message)
            return {
                "success": True,
                "result": f"Message sent to {channel}: {message}",
                "data": result,
                "processed_arguments": {
                    "channel": channel,
                    "message": message
                }
            }
        
        elif tool_name == "slack_get_channel_members":
            channel_name = arguments.get("channel_name", "")
            print(f"👥 Getting members for Slack channel {channel_name}")
            result = await slack_service.get_channel_members(channel_name)
            return {
                "success": True,
                "result": f"Retrieved members for channel {channel_name}",
                "data": result,
                "processed_arguments": {
                    "channel_name": channel_name
                }
            }
        
        elif tool_name == "slack_create_channel":
            channel_name = arguments.get("channel_name", "")
            print(f"➕ Creating new Slack channel {channel_name}")
            result = await slack_service.create_channel(channel_name)
            return {
                "success": True,
                "result": f"Created new Slack channel: {channel_name}",
                "data": result,
                "processed_arguments": {
                    "channel_name": channel_name
                }
            }
        

        elif tool_name == "slack_file_management":
            action = arguments.get("action")

            if action == "upload_file":
                channel = arguments.get("channel")
                file_path = arguments.get("file_path")
                title = arguments.get("title")
                comment = arguments.get("comment")

                if not channel or not file_path:
                    return {
                        "success": False,
                        "error": "Channel and file path are required",
                        "result": None
                    }

                result = await slack_service.upload_file(channel, file_path, title, comment)
                return {
                    "success": True,
                    "result": f"File uploaded to {channel}",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown file management action: {action}",
                    "result": None
                }

        elif tool_name == "slack_reactions":
            action = arguments.get("action")

            if action == "add_reaction":
                channel = arguments.get("channel")
                timestamp = arguments.get("timestamp")
                emoji = arguments.get("emoji")

                if not all([channel, timestamp, emoji]):
                    return {
                        "success": False,
                        "error": "Channel, timestamp, and emoji are required",
                        "result": None
                    }

                result = await slack_service.add_reaction(channel, timestamp, emoji)
                return {
                    "success": True,
                    "result": f"Reaction {emoji} added to message",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown reaction action: {action}",
                    "result": None
                }

        elif tool_name == "slack_search":
            action = arguments.get("action")

            if action == "search_messages":
                query = arguments.get("query")
                channel = arguments.get("channel")
                limit = arguments.get("limit", 20)

                if not query:
                    return {
                        "success": False,
                        "error": "Search query is required",
                        "result": None
                    }

                result = await slack_service.search_messages(query, channel, limit)
                return {
                    "success": True,
                    "result": f"Found {result.get('total_found', 0)} messages",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown search action: {action}",
                    "result": None
                }

        elif tool_name == "slack_user_management":
            action = arguments.get("action")

            if action == "get_user_info":
                user_id = arguments.get("user_id")
                user_name = arguments.get("user_name")

                if not user_id and not user_name:
                    return {
                        "success": False,
                        "error": "Either user_id or user_name is required",
                        "result": None
                    }

                result = await slack_service.get_user_info(user_id, user_name)
                return {
                    "success": True,
                    "result": "User information retrieved",
                    "data": result
                }
            elif action == "list_users":
                include_bots = arguments.get("include_bots", False)

                result = await slack_service.list_users(include_bots)
                return {
                    "success": True,
                    "result": f"Found {result.get('total_users', 0)} users",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown user management action: {action}",
                    "result": None
                }

        elif tool_name == "slack_pins":
            action = arguments.get("action")

            if action == "pin_message":
                channel = arguments.get("channel")
                timestamp = arguments.get("timestamp")

                if not channel or not timestamp:
                    return {
                        "success": False,
                        "error": "Channel and timestamp are required",
                        "result": None
                    }

                result = await slack_service.pin_message(channel, timestamp)
                return {
                    "success": True,
                    "result": "Message pinned successfully",
                    "data": result
                }
            elif action == "get_pinned_messages":
                channel = arguments.get("channel")

                if not channel:
                    return {
                        "success": False,
                        "error": "Channel is required",
                        "result": None
                    }

                result = await slack_service.get_pinned_messages(channel)
                return {
                    "success": True,
                    "result": f"Found {result.get('total_pinned', 0)} pinned items",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown pin action: {action}",
                    "result": None
                }

        # New Slack Tools
        elif tool_name == "slack_ai_agents":
            action = arguments.get("action", "execute_command")
            command = arguments.get("command", "")
            channel = arguments.get("channel", "")
            user_id = arguments.get("user_id", "")
            args = arguments.get("args", [])

            if action == "execute_command":
                if not command:
                    return {
                        "success": False,
                        "error": "Command is required",
                        "result": None
                    }

                result = await slack_service.execute_command(command, channel, user_id, args)
                return {
                    "success": True,
                    "result": f"Command '{command}' executed successfully",
                    "data": result
                }
            elif action == "list_commands":
                result = await slack_service.list_commands()
                return {
                    "success": True,
                    "result": f"Found {result.get('total_commands', 0)} commands",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Slack AI agents action: {action}",
                    "result": None
                }

        elif tool_name == "slack_file_operations":
            action = arguments.get("action", "list_files")
            channel = arguments.get("channel", "")
            file_id = arguments.get("file_id", "")
            file_path = arguments.get("file_path", "")
            title = arguments.get("title", "")
            comment = arguments.get("comment", "")

            if action == "list_files":
                result = await slack_service.list_files(channel)
                return {
                    "success": True,
                    "result": f"Found {result.get('total_files', 0)} files",
                    "data": result
                }
            elif action == "get_file_info":
                if not file_id:
                    return {
                        "success": False,
                        "error": "File ID is required",
                        "result": None
                    }

                result = await slack_service.get_file_info(file_id)
                return {
                    "success": True,
                    "result": f"File information retrieved",
                    "data": result
                }
            elif action == "upload_file":
                if not file_path or not channel:
                    return {
                        "success": False,
                        "error": "File path and channel are required",
                        "result": None
                    }

                result = await slack_service.upload_file(channel, file_path, title, comment)
                return {
                    "success": True,
                    "result": f"File uploaded to {channel}",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Slack file operations action: {action}",
                    "result": None
                }

        elif tool_name == "slack_link_management":
            action = arguments.get("action", "get_shared_links")
            channel = arguments.get("channel", "")
            url = arguments.get("url", "")
            date_range = arguments.get("date_range", "")

            if action == "get_shared_links":
                result = await slack_service.get_shared_links(channel, date_range)
                return {
                    "success": True,
                    "result": f"Found {result.get('total_links', 0)} shared links",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Slack link management action: {action}",
                    "result": None
                }

        elif tool_name == "slack_workflows":
            action = arguments.get("action", "list_workflows")
            workflow_id = arguments.get("workflow_id", "")
            workflow_name = arguments.get("workflow_name", "")
            inputs = arguments.get("inputs", {})

            if action == "list_workflows":
                result = await slack_service.list_workflows()
                return {
                    "success": True,
                    "result": f"Found {result.get('total_workflows', 0)} workflows",
                    "data": result
                }
            elif action == "execute_workflow":
                if not workflow_id:
                    return {
                        "success": False,
                        "error": "Workflow ID is required",
                        "result": None
                    }

                result = await slack_service.execute_workflow(workflow_id, inputs)
                return {
                    "success": True,
                    "result": f"Workflow '{workflow_id}' executed successfully",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Slack workflows action: {action}",
                    "result": None
                }

        elif tool_name == "slack_webhooks":
            action = arguments.get("action", "send_webhook")
            webhook_url = arguments.get("webhook_url", "")
            message = arguments.get("message", "")
            channel = arguments.get("channel", "")
            blocks = arguments.get("blocks", [])

            if action == "send_webhook":
                if not webhook_url or not message:
                    return {
                        "success": False,
                        "error": "Webhook URL and message are required",
                        "result": None
                    }

                result = await slack_service.send_webhook(webhook_url, message, channel, blocks)
                return {
                    "success": True,
                    "result": f"Webhook message sent successfully",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Slack webhooks action: {action}",
                    "result": None
                }

        elif tool_name == "slack_user_context":
            action = arguments.get("action", "get_user_profile")
            user_id = arguments.get("user_id", "")
            user_email = arguments.get("user_email", "")
            profile_data = arguments.get("profile_data", {})

            if action == "get_user_profile":
                if not user_id:
                    return {
                        "success": False,
                        "error": "User ID is required",
                        "result": None
                    }

                result = await slack_service.get_user_info(user_id)
                return {
                    "success": True,
                    "result": f"User profile retrieved",
                    "data": result
                }
            elif action == "update_user_profile":
                if not user_id or not profile_data:
                    return {
                        "success": False,
                        "error": "User ID and profile data are required",
                        "result": None
                    }

                result = await slack_service.update_user_profile(user_id, profile_data)
                return {
                    "success": True,
                    "result": f"User profile updated successfully",
                    "data": result
                }
            elif action == "get_user_by_email":
                if not user_email:
                    return {
                        "success": False,
                        "error": "User email is required",
                        "result": None
                    }

                result = await slack_service.get_user_by_email(user_email)
                return {
                    "success": True,
                    "result": f"User found by email",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Slack user context action: {action}",
                    "result": None
                }

        elif tool_name == "slack_advanced_features":
            action = arguments.get("action", "add_reaction")
            channel = arguments.get("channel", "")
            timestamp = arguments.get("timestamp", "")
            emoji = arguments.get("emoji", "")
            reminder_text = arguments.get("reminder_text", "")
            reminder_time = arguments.get("reminder_time", "")

            if action == "add_reaction":
                if not channel or not timestamp or not emoji:
                    return {
                        "success": False,
                        "error": "Channel, timestamp, and emoji are required",
                        "result": None
                    }

                result = await slack_service.add_reaction(channel, timestamp, emoji)
                return {
                    "success": True,
                    "result": f"Reaction {emoji} added to message",
                    "data": result
                }
            elif action == "remove_reaction":
                if not channel or not timestamp or not emoji:
                    return {
                        "success": False,
                        "error": "Channel, timestamp, and emoji are required",
                        "result": None
                    }

                result = await slack_service.remove_reaction(channel, timestamp, emoji)
                return {
                    "success": True,
                    "result": f"Reaction {emoji} removed from message",
                    "data": result
                }
            elif action == "set_reminder":
                if not user_id or not reminder_text or not reminder_time:
                    return {
                        "success": False,
                        "error": "User ID, reminder text, and reminder time are required",
                        "result": None
                    }

                result = await slack_service.set_reminder(user_id, reminder_text, reminder_time)
                return {
                    "success": True,
                    "result": f"Reminder set successfully",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Slack advanced features action: {action}",
                    "result": None
                }

        elif tool_name == "slack_admin_tools":
            action = arguments.get("action", "list_user_groups")
            group_name = arguments.get("group_name", "")
            group_handle = arguments.get("group_handle", "")
            user_ids = arguments.get("user_ids", [])
            description = arguments.get("description", "")

            if action == "list_user_groups":
                result = await slack_service.list_user_groups()
                return {
                    "success": True,
                    "result": f"Found {result.get('total_groups', 0)} user groups",
                    "data": result
                }
            elif action == "create_user_group":
                if not group_name or not group_handle or not user_ids:
                    return {
                        "success": False,
                        "error": "Group name, handle, and user IDs are required",
                        "result": None
                    }

                result = await slack_service.create_user_group(group_name, group_handle, user_ids, description)
                return {
                    "success": True,
                    "result": f"User group '{group_name}' created successfully",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Slack admin tools action: {action}",
                    "result": None
                }

        elif tool_name == "slack_channel_analytics":
            action = arguments.get("action", "get_channel_history")
            channel = arguments.get("channel", "")
            limit = arguments.get("limit", 100)
            oldest = arguments.get("oldest", "")
            latest = arguments.get("latest", "")

            if action == "get_channel_history":
                if not channel:
                    return {
                        "success": False,
                        "error": "Channel is required",
                        "result": None
                    }

                result = await slack_service.get_channel_history(channel, limit, oldest, latest)
                return {
                    "success": True,
                    "result": f"Retrieved {result.get('total_messages', 0)} messages from channel history",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Slack channel analytics action: {action}",
                    "result": None
                }

        elif tool_name == "slack_search_discovery":
            action = arguments.get("action", "search_messages")
            query = arguments.get("query", "")
            channel = arguments.get("channel", "")
            user = arguments.get("user", "")
            count = arguments.get("count", 20)

            if action == "search_files":
                if not query:
                    return {
                        "success": False,
                        "error": "Search query is required",
                        "result": None
                    }

                result = await slack_service.search_files(query, channel, user, count=count)
                return {
                    "success": True,
                    "result": f"Found {result.get('total_found', 0)} files",
                    "data": result
                }
            elif action == "search_messages":
                if not query:
                    return {
                        "success": False,
                        "error": "Search query is required",
                        "result": None
                    }

                result = await slack_service.search_messages(query, channel, count)
                return {
                    "success": True,
                    "result": f"Found {result.get('total_found', 0)} messages",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Slack search discovery action: {action}",
                    "result": None
                }

        elif tool_name == "slack_workspace_management":
            action = arguments.get("action", "get_workspace_info")
            workspace_id = arguments.get("workspace_id", "")
            include_private = arguments.get("include_private", False)
            include_archived = arguments.get("include_archived", False)

            if action == "get_workspace_info":
                result = await slack_service.get_workspace_info()
                return {
                    "success": True,
                    "result": f"Workspace information retrieved",
                    "data": result
                }
            elif action == "get_workspace_analytics":
                result = await slack_service.get_workspace_analytics()
                return {
                    "success": True,
                    "result": f"Workspace analytics retrieved",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Slack workspace management action: {action}",
                    "result": None
                }

        return {
            "success": False,
            "error": f"Unknown Slack tool: {tool_name}",
            "result": None
        }

    async def _execute_hubspot_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute HubSpot-related tools."""
        # Get user's HubSpot connection
        result = await db.execute(
            select(Connection)
            .filter(
                Connection.user_id == user.id,
                Connection.platform == "hubspot",
                Connection.status == ConnectionStatus.ACTIVE
            )
        )
        connection = result.scalar_one_or_none()

        if not connection:
            return {
                "success": False,
                "error": "No active HubSpot connection found",
                "result": None
            }

        # Initialize HubSpot service with user's connection config
        hubspot_service = HubSpotService()
        print(
            f"🔧 Initialized HubSpot service with user config for user {user.id}")

        if tool_name == "hubspot_contact_operations":
            operation = arguments.get("operation")

            if operation == "create":
                contact_data = arguments.get("contact_data", {})
                result = await hubspot_service.create_contact(connection, contact_data)
                return {
                    "success": True,
                    "result": "Contact created successfully",
                    "data": result
                }
            elif operation == "read":
                contact_id = arguments.get("contact_id")
                result = await hubspot_service.get_contact(connection, contact_id)
                return {
                    "success": True,
                    "result": "Contact retrieved successfully",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown HubSpot operation: {operation}",
                    "result": None
                }

        return {
            "success": False,
            "error": f"Unknown HubSpot tool: {tool_name}",
            "result": None
        }

    async def _execute_salesforce_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Salesforce-related tools."""
        # Get user's Salesforce connection
        result = await db.execute(
            select(Connection)
            .filter(
                Connection.user_id == user.id,
                Connection.platform == "salesforce",
                Connection.status == ConnectionStatus.ACTIVE
            )
        )
        connection = result.scalar_one_or_none()

        if not connection:
            return {
                "success": False,
                "error": "No active Salesforce connection found",
                "result": None
            }

        # Initialize Salesforce service with user's connection config
        salesforce_service = SalesforceService()
        await salesforce_service.initialize(connection)
        print(f"🔧 Initialized Salesforce service with user config for user {user.id}")

        if tool_name == "salesforce_create_contact":
            result = await salesforce_service.create_contact(arguments)
            return {
                "success": result["success"],
                "result": result.get("message", "Contact operation completed"),
                "data": result
            }
        elif tool_name == "salesforce_search_contacts":
            query = arguments.get("query")
            limit = arguments.get("limit", 50)
            result = await salesforce_service.search_contacts(query, limit)
            return {
                "success": result["success"],
                "result": f"Found {result.get('total_size', 0)} contacts",
                "data": result
            }
        elif tool_name == "salesforce_create_lead":
            result = await salesforce_service.create_lead(arguments)
            return {
                "success": result["success"],
                "result": result.get("message", "Lead operation completed"),
                "data": result
            }
        elif tool_name == "salesforce_get_leads":
            status = arguments.get("status")
            limit = arguments.get("limit", 50)
            result = await salesforce_service.get_leads(status, limit)
            return {
                "success": result["success"],
                "result": f"Retrieved {result.get('total_size', 0)} leads",
                "data": result
            }
        elif tool_name == "salesforce_create_opportunity":
            result = await salesforce_service.create_opportunity(arguments)
            return {
                "success": result["success"],
                "result": result.get("message", "Opportunity operation completed"),
                "data": result
            }
        elif tool_name == "salesforce_get_opportunities":
            stage = arguments.get("stage")
            limit = arguments.get("limit", 50)
            result = await salesforce_service.get_opportunities(stage, limit)
            return {
                "success": result["success"],
                "result": f"Retrieved {result.get('total_size', 0)} opportunities",
                "data": result
            }
        elif tool_name == "salesforce_get_pipeline_report":
            date_range = arguments.get("date_range", "30")
            result = await salesforce_service.get_sales_pipeline_report(date_range)
            return {
                "success": result["success"],
                "result": "Pipeline report generated",
                "data": result
            }
        elif tool_name == "salesforce_sync_from_hubspot":
            hubspot_contacts = arguments.get("hubspot_contacts", [])
            result = await salesforce_service.sync_contacts_from_hubspot(hubspot_contacts)
            return {
                "success": result["success"],
                "result": result.get("message", "Sync operation completed"),
                "data": result
            }
        else:
            return {
                "success": False,
                "error": f"Unknown Salesforce tool: {tool_name}",
                "result": None
            }

    async def _execute_ga4_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute GA4-related tools."""
        # Get user's GA4 connection
        result = await db.execute(
            select(Connection)
            .filter(
                Connection.user_id == user.id,
                Connection.platform == "ga4",
                Connection.status == ConnectionStatus.ACTIVE
            )
        )
        connection = result.scalar_one_or_none()

        if not connection:
            return {
                "success": False,
                "error": "No active GA4 connection found",
                "result": None
            }

        # Initialize GA4 service with user's connection config
        ga4_service = GA4Service()
        await ga4_service.initialize()
        print(f"🔧 Initialized GA4 service with user config for user {user.id}")

        if tool_name == "ga4_analytics_dashboard":
            report_type = arguments.get("report_type", "traffic")
            date_range = arguments.get("date_range", "last_30_days")
            hours = 24 if "24" in str(date_range) else 168  # Default to 7 days

            if report_type == "traffic":
                result = await ga4_service.get_traffic(hours=hours)
            elif report_type == "conversions":
                result = await ga4_service.get_conversions(hours=hours)
            elif report_type == "user_behavior":
                result = await ga4_service.get_user_behavior(hours=hours)
            elif report_type == "ecommerce":
                result = await ga4_service.get_ecommerce_data(hours=hours)
            else:
                return {
                    "success": False,
                    "error": f"Unknown report type: {report_type}",
                    "result": None
                }

            return {
                "success": True,
                "result": f"GA4 {report_type} report generated",
                "data": result
            }

        elif tool_name == "ga4_get_traffic":
            hours = arguments.get("hours", 24)
            result = await ga4_service.get_traffic(hours=hours)
            return {
                "success": True,
                "result": f"GA4 traffic data for last {hours} hours",
                "data": result
            }

        elif tool_name == "ga4_get_conversions":
            hours = arguments.get("hours", 24)
            conversion_events = arguments.get("conversion_events")
            result = await ga4_service.get_conversions(hours=hours, conversion_events=conversion_events)
            return {
                "success": True,
                "result": f"GA4 conversion data for last {hours} hours",
                "data": result
            }

        elif tool_name == "ga4_user_behavior":
            hours = arguments.get("hours", 24)
            user_segments = arguments.get("user_segments")
            engagement_metrics = arguments.get("engagement_metrics")
            result = await ga4_service.get_user_behavior(hours=hours, user_segments=user_segments, engagement_metrics=engagement_metrics)
            return {
                "success": True,
                "result": f"GA4 user behavior data for last {hours} hours",
                "data": result
            }

        return {
            "success": False,
            "error": f"Unknown GA4 tool: {tool_name}",
            "result": None
        }

    async def _execute_marketing_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute marketing-related tools."""
        if tool_name == "marketing_campaign_automation":
            campaign_type = arguments.get("campaign_type")
            target_audience = arguments.get("target_audience", {})

            return {
                "success": True,
                "result": f"Marketing campaign '{campaign_type}' created successfully",
                "data": {
                    "campaign_type": campaign_type,
                    "target_audience": target_audience,
                    "status": "scheduled"
                }
            }

        elif tool_name == "campaign_performance_tracking":
            campaign_id = arguments.get("campaign_id")

            return {
                "success": True,
                "result": f"Performance tracking enabled for campaign {campaign_id}",
                "data": {
                    "campaign_id": campaign_id,
                    "metrics": ["opens", "clicks", "conversions"],
                    "status": "active"
                }
            }

        return {
            "success": False,
            "error": f"Unknown marketing tool: {tool_name}",
            "result": None
        }

    async def _execute_whatsapp_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute WhatsApp-related tools."""
        # Get user's WhatsApp connection
        result = await db.execute(
            select(Connection)
            .filter(
                Connection.user_id == user.id,
                Connection.platform == "whatsapp",
                Connection.status == ConnectionStatus.ACTIVE
            )
        )
        connection = result.scalar_one_or_none()

        if not connection:
            return {
                "success": False,
                "error": "No active WhatsApp connection found",
                "result": None
            }

        # Initialize WhatsApp service with user's connection config
        whatsapp_service = WhatsAppService()
        print(
            f"🔧 Initialized WhatsApp service with user config for user {user.id}")

        if tool_name == "whatsapp_messaging":
            action = arguments.get("action", "send_message")
            to_number = arguments.get("to_number", "")

            if action == "send_message":
                message = arguments.get("message", "")
                if not to_number or not message:
                    return {
                        "success": False,
                        "error": "Phone number and message are required",
                        "result": None
                    }

                result = await whatsapp_service.send_message(
                    to_number, message, config=connection.config
                )
                return {
                    "success": True,
                    "result": f"Message sent to {to_number}: {message}",
                    "data": result,
                    "processed_arguments": {
                        "to_number": to_number,
                        "message": message
                    }
                }
            elif action == "send_media":
                media_url = arguments.get("media_url", "")
                media_type = arguments.get("media_type", "image")
                caption = arguments.get("caption", "")

                if not to_number or not media_url:
                    return {
                        "success": False,
                        "error": "Phone number and media URL are required",
                        "result": None
                    }

                result = await whatsapp_service.send_media_message(
                    to_number, media_url, media_type, caption, config=connection.config
                )
                return {
                    "success": True,
                    "result": f"Media message sent to {to_number}",
                    "data": result,
                    "processed_arguments": {
                        "to_number": to_number,
                        "media_url": media_url,
                        "media_type": media_type
                    }
                }
            elif action == "send_location":
                latitude = arguments.get("latitude", "")
                longitude = arguments.get("longitude", "")
                name = arguments.get("name", "")
                address = arguments.get("address", "")

                if not to_number or not latitude or not longitude:
                    return {
                        "success": False,
                        "error": "Phone number, latitude, and longitude are required",
                        "result": None
                    }

                result = await whatsapp_service.send_location_message(
                    to_number, latitude, longitude, name, address, config=connection.config
                )
                return {
                    "success": True,
                    "result": f"Location message sent to {to_number}",
                    "data": result,
                    "processed_arguments": {
                        "to_number": to_number,
                        "latitude": latitude,
                        "longitude": longitude
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown WhatsApp action: {action}",
                    "result": None
                }

        elif tool_name == "whatsapp_templates":
            action = arguments.get("action", "send_template")

            if action == "send_template":
                to_number = arguments.get("to_number", "")
                template_name = arguments.get("template_name", "")
                language_code = arguments.get("language_code", "en_US")

                if not to_number or not template_name:
                    return {
                        "success": False,
                        "error": "Phone number and template name are required",
                        "result": None
                    }

                result = await whatsapp_service.send_template_message(
                    to_number, template_name, language_code, config=connection.config
                )
                return {
                    "success": True,
                    "result": f"Template message sent to {to_number}",
                    "data": result
                }
            elif action == "list_templates":
                result = await whatsapp_service.list_templates(config=connection.config)
                return {
                    "success": True,
                    "result": "Templates retrieved successfully",
                    "data": result
                }
            elif action == "create_template":
                template_name = arguments.get("template_name", "")
                language_code = arguments.get("language_code", "en_US")
                category = arguments.get("category", "MARKETING")
                components = arguments.get("components", [])

                if not template_name:
                    return {
                        "success": False,
                        "error": "Template name is required",
                        "result": None
                    }

                result = await whatsapp_service.create_template(
                    template_name, language_code, category, components, config=connection.config
                )
                return {
                    "success": True,
                    "result": f"Template '{template_name}' created successfully",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown WhatsApp template action: {action}",
                    "result": None
                }

        return {
            "success": False,
            "error": f"Unknown WhatsApp tool: {tool_name}",
            "result": None
        }

    async def _execute_social_media_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute social media tools."""
        try:
            from .social_media_service import social_media_service
            
            operation = arguments.get("operation")
            
            if operation == "connect_account":
                # Check if required parameters are provided
                if "platform" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'platform' parameter for account connection"
                    }
                if "credentials" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'credentials' parameter for account connection"
                    }
                
                return await social_media_service.connect_account(
                    platform=arguments["platform"],
                    credentials=arguments["credentials"],
                    user_id=user.id
                )
            elif operation == "create_post":
                # Check if required parameters are provided
                if "platform" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'platform' parameter for post creation"
                    }
                if "content" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'content' parameter for post creation"
                    }
                
                return await social_media_service.create_post(
                    platform=arguments["platform"],
                    content=arguments["content"],
                    user_id=user.id
                )
            elif operation == "schedule_campaign":
                # Check if required parameters are provided
                if "platform" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'platform' parameter for campaign scheduling"
                    }
                if "campaign_data" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'campaign_data' parameter for campaign scheduling"
                    }
                
                return await social_media_service.schedule_campaign(
                    platform=arguments["platform"],
                    campaign_data=arguments["campaign_data"],
                    user_id=user.id
                )
            elif operation == "get_analytics":
                # Check if required parameters are provided
                if "platform" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'platform' parameter for analytics retrieval"
                    }
                
                return await social_media_service.get_analytics(
                    platform=arguments["platform"],
                    date_range=arguments.get("date_range", "7d"),
                    user_id=user.id
                )
            else:
                return {
                    "success": False,
                    "error": f"Unknown social media operation: {operation}"
                }
        except Exception as e:
            logger.error(f"Error executing social media tool: {e}")
            return {"success": False, "error": str(e)}

    def _resolve_tool_output_references(self, arguments: Dict[str, Any], tools_called: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Resolve tool output references like $(tool_name.output) or $output_of_tool_name in arguments."""
        import re
        
        def replace_reference(match):
            tool_name = match.group(1)
            output_key = match.group(2) if match.group(2) else "result"
            
            # Find the tool call result
            for tool_call in tools_called:
                if tool_call.get("name") == tool_name and tool_call.get("result"):
                    result = tool_call["result"]
                    if output_key == "output" and "data" in result:
                        return str(result["data"])
                    elif output_key in result:
                        return str(result[output_key])
                    elif "result" in result:
                        return str(result["result"])
                    elif "data" in result:
                        return str(result["data"])
            return match.group(0)  # Return original if not found
        
        def replace_output_of_reference(match):
            tool_name = match.group(1)
            
            # Find the tool call result
            for tool_call in tools_called:
                if tool_call.get("name") == tool_name and tool_call.get("result"):
                    result = tool_call["result"]
                    # Try to get the most relevant data
                    if "data" in result:
                        return str(result["data"])
                    elif "result" in result:
                        return str(result["result"])
                    elif "content" in result:
                        return str(result["content"])
            return match.group(0)  # Return original if not found
        
        # Process all string values in arguments
        processed_args = {}
        for key, value in arguments.items():
            if isinstance(value, str):
                # Replace references like $(tool_name.output) or $(tool_name.result)
                processed_value = re.sub(r'\$\(([^\.]+)\.([^\)]+)\)', replace_reference, value)
                processed_value = re.sub(r'\$\(([^\)]+)\)', replace_reference, processed_value)
                # Replace references like $output_of_tool_name
                processed_value = re.sub(r'\$output_of_([a-zA-Z_]+)', replace_output_of_reference, processed_value)
                processed_args[key] = processed_value
            else:
                processed_args[key] = value
        
        return processed_args

    async def _execute_file_management_tool(self, arguments: Dict[str, Any], user: User, db: AsyncSession, tools_called: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute file management tools."""
        try:
            from .file_management_service import file_management_service

            # Resolve tool output references
            if tools_called:
                arguments = self._resolve_tool_output_references(arguments, tools_called)
            
            # Parameter mapping to handle LLM-generated parameter names
            operation = arguments.get("operation") or arguments.get("action")
            
            # Map inputFile and input_file to content if present
            if "inputFile" in arguments and "content" not in arguments:
                arguments["content"] = arguments["inputFile"]
            if "input_file" in arguments and "content" not in arguments:
                arguments["content"] = arguments["input_file"]
            
            if operation == "generate_pdf" or operation == "generate_pdf":
                if "html_content" in arguments:
                    return await file_management_service.generate_pdf_from_html(
                        html_content=arguments["html_content"],
                        filename=arguments.get("filename")
                    )
                elif "markdown_content" in arguments:
                    return await file_management_service.generate_pdf_from_markdown(
                        markdown_content=arguments["markdown_content"],
                        filename=arguments.get("filename")
                    )
                elif "data" in arguments:
                    return await file_management_service.generate_pdf_from_data(
                        data=arguments["data"],
                        template=arguments.get("template", "default")
                    )
                elif "content" in arguments:
                    # Convert plain content to HTML for PDF generation
                    html_content = f"""
                    <html>
                    <head>
                        <style>
                            body {{ font-family: Arial, sans-serif; margin: 40px; }}
                            h1 {{ color: #333; }}
                            .section {{ margin: 20px 0; }}
                            .data {{ background: #f5f5f5; padding: 10px; border-radius: 5px; }}
                        </style>
                    </head>
                    <body>
                        <h1>Analytics Report</h1>
                        <div class="section">
                            <h2>Report Content</h2>
                            <div class="data">
                                {arguments["content"]}
                            </div>
                        </div>
                    </body>
                    </html>
                    """
                    return await file_management_service.generate_pdf_from_html(
                        html_content=html_content,
                        filename=arguments.get("filename")
                    )
                else:
                    return {"success": False, "error": "No content provided for PDF generation. Please provide 'content', 'html_content', 'markdown_content', or 'data' parameter."}
            
            elif operation == "convert_document":
                # Check if required parameters are provided
                if "content" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'content' parameter for document conversion"
                    }
                if "from_format" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'from_format' parameter for document conversion"
                    }
                if "to_format" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'to_format' parameter for document conversion"
                    }
                
                return await file_management_service.convert_document(
                    content=arguments["content"],
                    from_format=arguments["from_format"],
                    to_format=arguments["to_format"]
                )
            
            elif operation == "generate_qr":
                # Check if required parameters are provided
                if "qr_data" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'qr_data' parameter for QR code generation"
                    }
                
                return await file_management_service.generate_qr_code(
                    data=arguments["qr_data"],
                    size=arguments.get("qr_size", 10)
                )
            
            elif operation == "list":
                return await file_management_service.list_user_files(user.id)
            
            elif operation == "download":
                # Check if required parameters are provided
                if "filename" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'filename' parameter for file download"
                    }
                
                return await file_management_service.download_file(
                    filename=arguments["filename"],
                    user_id=user.id
                )
            
            elif operation == "delete":
                # Check if required parameters are provided
                if "filename" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'filename' parameter for file deletion"
                    }
                
                return await file_management_service.delete_file(
                    filename=arguments["filename"],
                    user_id=user.id
                )
            
            elif operation == "upload":
                # Check if required parameters are provided
                if "filename" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'filename' parameter for file upload"
                    }
                if "content" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'content' parameter for file upload"
                    }
                
                return await file_management_service.upload_content(
                    filename=arguments["filename"],
                    content=arguments["content"],
                    user_id=user.id
                )
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown file management operation: {operation}. Available operations: generate_pdf, convert_document, generate_qr, list, download, delete, upload"
                }
        except Exception as e:
            logger.error(f"Error executing file management tool: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_web_tools_tool(self, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute web tools."""
        try:
            from .web_tools_service import web_tools_service
            
            operation = arguments.get("operation")
            
            if operation == "scrape_website":
                # Check if required parameters are provided
                if "url" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'url' parameter for website scraping"
                    }
                
                # Use robust scraping for production-ready results
                return await web_tools_service.scrape_website_robust(
                    url=arguments["url"],
                    use_selenium=arguments.get("use_selenium", True)
                )
            
            elif operation == "extract_data":
                # Check if required parameters are provided
                if "url" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'url' parameter for data extraction"
                    }
                
                return await web_tools_service.extract_structured_data(
                    url=arguments["url"]
                )
            
            elif operation == "generate_short_link":
                # Check if required parameters are provided
                if "original_url" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'original_url' parameter for short link generation"
                    }
                
                return await web_tools_service.generate_short_link(
                    original_url=arguments["original_url"],
                    custom_alias=arguments.get("custom_alias")
                )
            
            elif operation == "generate_tracking_link":
                # Check if required parameters are provided
                if "original_url" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'original_url' parameter for tracking link generation"
                    }
                
                return await web_tools_service.generate_tracking_link(
                    original_url=arguments["original_url"],
                    campaign=arguments.get("campaign"),
                    source=arguments.get("source")
                )
            
            elif operation == "automate_task":
                # Check if required parameters are provided
                if "task_config" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'task_config' parameter for task automation"
                    }
                
                return await web_tools_service.automate_web_task(
                    task_config=arguments["task_config"]
                )
            
            elif operation == "check_status":
                # Check if required parameters are provided
                if "url" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'url' parameter for status check"
                    }
                
                return await web_tools_service.check_website_status(
                    url=arguments["url"]
                )
            
            elif operation == "extract_emails":
                # Check if required parameters are provided
                if "url" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'url' parameter for email extraction"
                    }
                
                return await web_tools_service.extract_emails_from_website(
                    url=arguments["url"]
                )
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown web tools operation: {operation}"
                }
        except Exception as e:
            logger.error(f"Error executing web tools: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_content_creation_tool(self, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute content creation tools."""
        try:
            from .content_creation_service import content_creation_service
            
            operation = arguments.get("operation")
            
            if operation == "generate_image":
                # Check if text parameter is provided
                if "text" not in arguments or not arguments["text"]:
                    return {
                        "success": False,
                        "error": "Missing required 'text' parameter for image generation. Please provide a description of the image you want to generate."
                    }
                
                return await content_creation_service.generate_image_from_text(
                    text=arguments["text"],
                    style=arguments.get("style", "modern"),
                    size=arguments.get("size", (800, 600))
                )
            
            elif operation == "create_from_template":
                # Check if required parameters are provided
                if "template_name" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'template_name' parameter"
                    }
                if "variables" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'variables' parameter"
                    }
                
                return await content_creation_service.create_content_from_template(
                    template_name=arguments["template_name"],
                    variables=arguments["variables"]
                )
            
            elif operation == "generate_bulk_content":
                # Check if required parameters are provided
                if "base_content" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'base_content' parameter"
                    }
                
                return await content_creation_service.generate_bulk_content(
                    base_content=arguments["base_content"],
                    variations=arguments.get("variations", 5),
                    content_type=arguments.get("content_type", "social_post")
                )
            
            elif operation == "optimize_seo":
                # Check if required parameters are provided
                if "content" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'content' parameter"
                    }
                
                return await content_creation_service.optimize_content_for_seo(
                    content=arguments["content"],
                    keywords=arguments.get("keywords")
                )
            
            elif operation == "generate_calendar":
                # Check if required parameters are provided
                if "start_date" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'start_date' parameter"
                    }
                if "end_date" not in arguments:
                    return {
                        "success": False,
                        "error": "Missing required 'end_date' parameter"
                    }
                
                return await content_creation_service.generate_content_calendar(
                    start_date=arguments["start_date"],
                    end_date=arguments["end_date"],
                    content_types=arguments.get("content_types")
                )
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown content creation operation: {operation}"
                }
        except Exception as e:
            logger.error(f"Error executing content creation tool: {e}")
            return {"success": False, "error": str(e)}


# Global tool executor instance
tool_executor = ToolExecutor()
