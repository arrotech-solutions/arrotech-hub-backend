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
from .asana_service import AsanaService
from .content_creation_service import ContentCreationService
from .file_management_service import FileManagementService
from .ga4_service import GA4Service
from .hubspot_service import HubSpotService
from .mpesa_reconciliation_service import MpesaReconciliationService
from .powerbi_service import PowerBIService
from .salesforce_service import SalesforceService
from .slack_service import SlackService
from .social_media_service import SocialMediaService
from .teams_service import TeamsService
from .web_tools_service import WebToolsService
from .whatsapp_service import WhatsAppService
from .zoom_service import ZoomService
from .hr_service import HRService
from .lead_intelligence_service import LeadIntelligenceService
from .logistics_service import LogisticsService
from .bilingual_service import BilingualService
from .payment_service import PaymentService
from .ecommerce_service import EcommerceService
from .accounting_service import AccountingService
from .agritech_service import AgritechService
from .health_service import HealthService
from .utilities_service import UtilitiesService
from .feature_flags import FeatureGate

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Executes MCP tools based on LLM decisions."""

    def __init__(self):
        self.services = {
            "slack": SlackService(),
            "hubspot": HubSpotService(),
            "powerbi": PowerBIService(),
            "salesforce": SalesforceService(),
            "teams": TeamsService(),
            "zoom": ZoomService(),
            "ga4": GA4Service(),
            "whatsapp": WhatsAppService(),
            "social_media": SocialMediaService(),
            "file_management": FileManagementService(),
            "web_tools": WebToolsService(),
            "content_creation": ContentCreationService(),
            "asana": AsanaService(),
            "mpesa": MpesaReconciliationService(),
            "hr_hub": HRService(),
            "lead_intelligence": LeadIntelligenceService(),
            "logistics_hub": LogisticsService(),
            "context_intelligence": BilingualService(),
            "fintech": PaymentService(),
            "ecommerce": EcommerceService(),
            "accounting": AccountingService(),
            "agritech": AgritechService(),
            "health": HealthService(),
            "utility": UtilitiesService(),
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
                    if service_name in ["slack", "teams", "zoom", "ga4", "whatsapp", "social_media", "file_management", "web_tools", "content_creation", "rate_limit", "billing"]:
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

            # Check connection access based on plan
            if not await self._check_connection_access(tool_name, user, db):
                return {
                    "success": False,
                    "error": f"Plan restriction: Your {user.subscription_tier} plan does not have access to the '{self._get_platform_from_tool(tool_name)}' integration. Please upgrade.",
                    "result": None
                }

            # Route to appropriate service based on tool name
            if tool_name.startswith("slack_"):
                return await self._execute_slack_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("teams_"):
                return await self._execute_teams_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("zoom_"):
                return await self._execute_zoom_tool(tool_name, arguments, user, db)
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
            elif tool_name.startswith("asana_"):
                return await self._execute_asana_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("powerbi_"):
                return await self._execute_powerbi_tool(tool_name, arguments, user, db)
            elif tool_name == "file_management":
                return await self._execute_file_management_tool(arguments, user, db, getattr(self, '_tools_called', []))
            elif tool_name == "web_tools":
                return await self._execute_web_tools_tool(arguments, user, db)
            elif tool_name == "content_creation":
                return await self._execute_content_creation_tool(arguments, user, db)
            elif tool_name == "mpesa_payment_reconciliation":
                return await self._execute_mpesa_tool(arguments, user, db)
            elif tool_name == "context_intelligence":
                return await self._execute_context_intelligence_tool(arguments, user, db)
            elif tool_name.startswith("hr_"):
                return await self._execute_hr_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("lead_intelligence_"):
                return await self._execute_lead_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("logistics_"):
                return await self._execute_logistics_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("context_"):
                return await self._execute_context_tool(tool_name, arguments, user, db)
            elif tool_name.endswith("_payment_ops"):
                return await self._execute_fintech_tool(tool_name, arguments, user, db)
            elif tool_name.endswith("_ecommerce_ops"):
                return await self._execute_ecommerce_tool(tool_name, arguments, user, db)
            elif tool_name.endswith("_accounting_ops"):
                return await self._execute_accounting_tool(tool_name, arguments, user, db)
            elif tool_name.endswith("_agri_ops"):
                return await self._execute_agri_tool(tool_name, arguments, user, db)
            elif tool_name.endswith("_health_ops"):
                return await self._execute_health_tool(tool_name, arguments, user, db)
            elif tool_name.endswith("_utility_ops"):
                return await self._execute_utility_tool(tool_name, arguments, user, db)
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

    async def _check_connection_access(self, tool_name: str, user: User, db: AsyncSession) -> bool:
        """Check if the user has access to the connection required by the tool."""
        platform = self._get_platform_from_tool(tool_name)
        if not platform:
            return True # If no specific platform, allow it (e.g. content_creation, web_tools)
            
        return FeatureGate.has_connection_access(user, platform)

    def _get_platform_from_tool(self, tool_name: str) -> Optional[str]:
        """Map tool name to platform string."""
        if tool_name.startswith("slack_"): return "slack"
        if tool_name.startswith("teams_"): return "teams"
        if tool_name.startswith("zoom_"): return "zoom"
        if tool_name.startswith("hubspot_"): return "hubspot"
        if tool_name.startswith("salesforce_"): return "salesforce"
        if tool_name.startswith("ga4_"): return "ga4"
        if tool_name.startswith("whatsapp_"): return "whatsapp"
        if tool_name.startswith("social_media_"): return "social_media"
        if tool_name.startswith("asana_"): return "asana"
        if tool_name.startswith("powerbi_"): return "powerbi"
        if tool_name.startswith("mpesa_"): return "mpesa"
        if tool_name.startswith("hr_"): return "hr_hub"
        if tool_name.startswith("lead_intelligence_"): return "lead_intelligence"
        if tool_name.startswith("logistics_"): return "logistics_hub"
        
        # Kenyan Specific Mappings
        if tool_name.endswith("_payment_ops"): return tool_name.replace("_payment_ops", "")
        if tool_name.endswith("_ecommerce_ops"): return tool_name.replace("_ecommerce_ops", "")
        if tool_name.endswith("_accounting_ops"): return tool_name.replace("_accounting_ops", "")
        if tool_name.endswith("_agri_ops"): return tool_name.replace("_agri_ops", "")
        if tool_name.endswith("_health_ops"): return tool_name.replace("_health_ops", "")
        if tool_name.endswith("_utility_ops"): return tool_name.replace("_utility_ops", "")
        
        return None

    async def _execute_slack_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Slack-related tools."""
        # Helper to check if a string looks like a Slack ID
        def is_slack_id(c: str) -> bool:
            return bool(c and len(c) >= 9 and c[0].isupper() and c[0] in "CUDGW")

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

            # Ensure channel has # prefix if it's not already prefixed and doesn't look like a Slack ID
            def is_slack_id(c):
                return bool(c and len(c) >= 9 and c[0].isupper() and c[0] in "CUDGW")

            if channel and not channel.startswith("#") and not is_slack_id(channel):
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
                        "success": result.get("success", False),
                        "result": result.get("message") or result.get("error") or f"Message sent to {channel}",
                        "data": result,
                        "processed_arguments": {
                            "channel": channel,
                            "message": message
                        }
                    }
            elif action == "send_report":
                report_type = arguments.get("report_type", "analytics_report")
                result = await slack_service.send_report(
                    channel=channel,
                    report_type=report_type,
                    date_range=arguments.get("date_range"),
                    message=arguments.get("message")
                )
                return {
                    "success": result.get("success", False),
                    "result": result.get("message") or result.get("error") or f"Report sent to {channel}",
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
            elif action == "send_alert":
                print(f"🚨 Sending alert to Slack channel {channel}: {message}")
                result = await slack_service.send_alert(channel, message)
                return {
                    "success": result.get("success", False),
                    "result": result.get("message") or result.get("error") or f"Alert sent to {channel}",
                    "data": result,
                    "processed_arguments": {
                        "channel": channel,
                        "message": message
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
                    "success": channels.get("success", False),
                    "result": f"Found {len(channels.get('channels', []))} channels",
                    "data": channels
                }
        
        elif tool_name == "slack_list_channels":
            print(f"📋 Listing Slack channels for user {user.id}")
            result = await slack_service.list_channels()
            return {
                "success": result.get("success", False),
                "result": f"Retrieved {len(result.get('channels', []))} Slack channels",
                "data": result,
                "processed_arguments": {}
            }
        
        elif tool_name == "slack_send_message":
            channel = arguments.get("channel", "")
            message = arguments.get("message", "")
            
            # Ensure channel has # prefix if it's not an ID
            if channel and not channel.startswith("#") and not is_slack_id(channel):
                channel = f"#{channel}"
            
            print(f"💬 Sending message to Slack channel {channel}: {message}")
            result = await slack_service.send_message(channel, message)
            return {
                "success": result.get("success", False),
                "result": result.get("message") or f"Message sent to {channel}",
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
                "success": result.get("success", False),
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
                "success": result.get("success", False),
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
                    "success": result.get("success", False),
                    "result": "User information retrieved",
                    "data": result
                }
            elif action == "list_users":
                include_bots = arguments.get("include_bots", False)

                result = await slack_service.list_users(include_bots)
                return {
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
                    "result": f"Command '{command}' executed successfully",
                    "data": result
                }
            elif action == "list_commands":
                result = await slack_service.list_commands()
                return {
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
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
                    "success": result.get("success", False),
                    "result": f"Workspace information retrieved",
                    "data": result
                }
            elif action == "get_workspace_analytics":
                result = await slack_service.get_workspace_analytics()
                return {
                    "success": result.get("success", False),
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

    async def _execute_teams_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Microsoft Teams-related tools."""
        # Get user's Teams connection
        result = await db.execute(
            select(Connection)
            .filter(
                Connection.user_id == user.id,
                Connection.platform == "teams",
                Connection.status == ConnectionStatus.ACTIVE
            )
        )
        connection = result.scalar_one_or_none()

        if not connection:
            return {
                "success": False,
                "error": "No active Teams connection found",
                "result": None
            }

        # Initialize Teams service with user's connection config
        teams_service = TeamsService()
        webhook_url = connection.config.get("webhook_url")
        access_token = connection.config.get("access_token")
        
        if not webhook_url and not access_token:
            return {
                "success": False,
                "error": "No webhook URL or access token found in Teams connection",
                "result": None
            }
        
        # Initialize the service with the user's credentials
        if webhook_url:
            teams_service.webhook_url = webhook_url
        if access_token:
            teams_service.access_token = access_token
        print(f"🔧 Initialized Teams service with user credentials for user {user.id}")

        if tool_name == "teams_team_communication":
            action = arguments.get("action", "send_message")
            channel = arguments.get("channel", "")
            message = arguments.get("message", "")
            message_type = arguments.get("message_type", "text")
            card_content = arguments.get("card_content")
            alert_type = arguments.get("alert_type")
            severity = arguments.get("severity", "info")
            meeting_title = arguments.get("meeting_title")
            meeting_time = arguments.get("meeting_time")
            meeting_link = arguments.get("meeting_link")
            attendees = arguments.get("attendees", [])

            if action == "send_message":
                result = await teams_service.send_message(
                    channel=channel,
                    message=message,
                    message_type=message_type
                )
                return {
                    "success": result.get("success", False),
                    "result": result.get("message", "Message sent"),
                    "data": result
                }
            elif action == "send_adaptive_card":
                if not card_content:
                    return {
                        "success": False,
                        "error": "Card content is required for adaptive card",
                        "result": None
                    }
                result = await teams_service.send_adaptive_card(
                    channel=channel,
                    card_content=card_content
                )
                return {
                    "success": result.get("success", False),
                    "result": result.get("message", "Adaptive card sent"),
                    "data": result
                }
            elif action == "send_alert":
                if not alert_type or not message:
                    return {
                        "success": False,
                        "error": "Alert type and message are required",
                        "result": None
                    }
                result = await teams_service.send_alert(
                    channel=channel,
                    alert_type=alert_type,
                    message=message,
                    severity=severity
                )
                return {
                    "success": result.get("success", False),
                    "result": result.get("message", "Alert sent"),
                    "data": result
                }
            elif action == "send_meeting_notification":
                if not meeting_title or not meeting_time:
                    return {
                        "success": False,
                        "error": "Meeting title and time are required",
                        "result": None
                    }
                result = await teams_service.send_meeting_notification(
                    channel=channel,
                    meeting_title=meeting_title,
                    meeting_time=meeting_time,
                    meeting_link=meeting_link,
                    attendees=attendees
                )
                return {
                    "success": result.get("success", False),
                    "result": result.get("message", "Meeting notification sent"),
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Teams communication action: {action}",
                    "result": None
                }

        elif tool_name == "teams_channel_management":
            action = arguments.get("action")
            team_id = arguments.get("team_id")
            channel_name = arguments.get("channel_name")
            description = arguments.get("description")
            channel_id = arguments.get("channel_id")

            if action == "list_channels":
                result = await teams_service.list_channels()
                return {
                    "success": result.get("success", False),
                    "result": "Channels retrieved",
                    "data": result
                }
            elif action == "get_channel_members":
                if not channel_id:
                    return {
                        "success": False,
                        "error": "Channel ID is required",
                        "result": None
                    }
                result = await teams_service.get_channel_members(channel_id)
                return {
                    "success": result.get("success", False),
                    "result": "Channel members retrieved",
                    "data": result
                }
            elif action == "create_channel":
                if not team_id or not channel_name:
                    return {
                        "success": False,
                        "error": "Team ID and channel name are required",
                        "result": None
                    }
                result = await teams_service.create_channel(
                    team_id=team_id,
                    channel_name=channel_name,
                    description=description
                )
                return {
                    "success": result.get("success", False),
                    "result": result.get("message", "Channel created"),
                    "data": result
                }
            elif action == "get_team_info":
                if not team_id:
                    return {
                        "success": False,
                        "error": "Team ID is required",
                        "result": None
                    }
                result = await teams_service.get_team_info(team_id)
                return {
                    "success": result.get("success", False),
                    "result": "Team info retrieved",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Teams channel management action: {action}",
                    "result": None
                }

        elif tool_name == "teams_message_search":
            query = arguments.get("query")
            channel_id = arguments.get("channel_id")
            limit = arguments.get("limit", 20)

            if not query:
                return {
                    "success": False,
                    "error": "Search query is required",
                    "result": None
                }

            result = await teams_service.search_messages(
                query=query,
                channel_id=channel_id,
                limit=limit
            )
            return {
                "success": result.get("success", False),
                "result": "Messages searched",
                "data": result
            }

        return {
            "success": False,
            "error": f"Unknown Teams tool: {tool_name}",
            "result": None
        }

    async def _execute_zoom_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Zoom-related tools."""
        # Get user's Zoom connection
        result = await db.execute(
            select(Connection)
            .filter(
                Connection.user_id == user.id,
                Connection.platform == "zoom",
                Connection.status == ConnectionStatus.ACTIVE
            )
        )
        connection = result.scalar_one_or_none()

        if not connection:
            return {
                "success": False,
                "error": "No active Zoom connection found",
                "result": None
            }

        # Initialize Zoom service with user's connection config
        zoom_service = ZoomService()
        client_id = connection.config.get("client_id")
        client_secret = connection.config.get("client_secret")
        account_id = connection.config.get("account_id")
        
        if not client_id or not client_secret:
            return {
                "success": False,
                "error": "Missing required Zoom credentials (client_id, client_secret)",
                "result": None
            }
        
        # Initialize the service with the user's credentials
        await zoom_service.initialize(client_id, client_secret, account_id)
        print(f"🔧 Initialized Zoom service with user credentials for user {user.id}")

        if tool_name == "zoom_meeting_management":
            action = arguments.get("action")
            topic = arguments.get("topic")
            start_time = arguments.get("start_time")
            duration = arguments.get("duration", 60)
            password = arguments.get("password")
            meeting_id = arguments.get("meeting_id")
            settings = arguments.get("settings")

            if action == "create":
                if not topic:
                    return {
                        "success": False,
                        "error": "Topic is required for creating a meeting",
                        "result": None
                    }
                result = await zoom_service.create_meeting(
                    topic=topic,
                    start_time=start_time,
                    duration=duration,
                    password=password,
                    settings=settings
                )
                return {
                    "success": result.get("success", False),
                    "result": "Meeting created successfully",
                    "data": result
                }
            elif action == "get":
                if not meeting_id:
                    return {
                        "success": False,
                        "error": "Meeting ID is required",
                        "result": None
                    }
                result = await zoom_service.get_meeting(meeting_id)
                return {
                    "success": result.get("success", False),
                    "result": "Meeting details retrieved",
                    "data": result
                }
            elif action == "update":
                if not meeting_id:
                    return {
                        "success": False,
                        "error": "Meeting ID is required",
                        "result": None
                    }
                result = await zoom_service.update_meeting(
                    meeting_id=meeting_id,
                    topic=topic,
                    start_time=start_time,
                    duration=duration,
                    settings=settings
                )
                return {
                    "success": result.get("success", False),
                    "result": "Meeting updated successfully",
                    "data": result
                }
            elif action == "delete":
                if not meeting_id:
                    return {
                        "success": False,
                        "error": "Meeting ID is required",
                        "result": None
                    }
                result = await zoom_service.delete_meeting(meeting_id)
                return {
                    "success": result.get("success", False),
                    "result": "Meeting deleted successfully",
                    "data": result
                }
            elif action == "list":
                user_id = arguments.get("user_id", "me")
                meeting_type = arguments.get("type", "scheduled")
                page_size = arguments.get("page_size", 30)
                page_number = arguments.get("page_number", 1)
                
                result = await zoom_service.list_meetings(
                    user_id=user_id,
                    type=meeting_type,
                    page_size=page_size,
                    page_number=page_number
                )
                return {
                    "success": result.get("success", False),
                    "result": "Meetings listed successfully",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Zoom meeting management action: {action}",
                    "result": None
                }

        elif tool_name == "zoom_meeting_operations":
            action = arguments.get("action")
            meeting_id = arguments.get("meeting_id")
            page_size = arguments.get("page_size", 30)
            page_number = arguments.get("page_number", 1)

            if not meeting_id:
                return {
                    "success": False,
                    "error": "Meeting ID is required",
                    "result": None
                }

            if action == "get_participants":
                result = await zoom_service.get_meeting_participants(
                    meeting_id=meeting_id,
                    page_size=page_size,
                    page_number=page_number
                )
                return {
                    "success": result.get("success", False),
                    "result": "Meeting participants retrieved",
                    "data": result
                }
            elif action == "get_registrants":
                result = await zoom_service.get_meeting_registrants(
                    meeting_id=meeting_id,
                    page_size=page_size,
                    page_number=page_number
                )
                return {
                    "success": result.get("success", False),
                    "result": "Meeting registrants retrieved",
                    "data": result
                }
            elif action == "get_invitation":
                result = await zoom_service.get_meeting_invitation(meeting_id)
                return {
                    "success": result.get("success", False),
                    "result": "Meeting invitation retrieved",
                    "data": result
                }
            elif action == "update_status":
                status_action = arguments.get("status_action")
                if not status_action:
                    return {
                        "success": False,
                        "error": "Status action is required",
                        "result": None
                    }
                result = await zoom_service.update_meeting_status(meeting_id, status_action)
                return {
                    "success": result.get("success", False),
                    "result": "Meeting status updated",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Zoom meeting operations action: {action}",
                    "result": None
                }

        elif tool_name == "zoom_recording_management":
            action = arguments.get("action")
            meeting_id = arguments.get("meeting_id")
            recording_id = arguments.get("recording_id")
            page_size = arguments.get("page_size", 30)
            page_number = arguments.get("page_number", 1)

            if not meeting_id:
                return {
                    "success": False,
                    "error": "Meeting ID is required",
                    "result": None
                }

            if action == "get_recordings":
                result = await zoom_service.get_meeting_recordings(
                    meeting_id=meeting_id,
                    page_size=page_size,
                    page_number=page_number
                )
                return {
                    "success": result.get("success", False),
                    "result": "Meeting recordings retrieved",
                    "data": result
                }
            elif action == "delete_recording":
                if not recording_id:
                    return {
                        "success": False,
                        "error": "Recording ID is required",
                        "result": None
                    }
                result = await zoom_service.delete_recording(meeting_id, recording_id)
                return {
                    "success": result.get("success", False),
                    "result": "Recording deleted successfully",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Zoom recording management action: {action}",
                    "result": None
                }

        elif tool_name == "zoom_user_management":
            action = arguments.get("action")
            user_id = arguments.get("user_id", "me")
            status = arguments.get("status", "active")
            page_size = arguments.get("page_size", 30)
            page_number = arguments.get("page_number", 1)

            if action == "get_user":
                result = await zoom_service.get_user(user_id)
                return {
                    "success": result.get("success", False),
                    "result": "User information retrieved",
                    "data": result
                }
            elif action == "list_users":
                result = await zoom_service.list_users(
                    status=status,
                    page_size=page_size,
                    page_number=page_number
                )
                return {
                    "success": result.get("success", False),
                    "result": "Users listed successfully",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Zoom user management action: {action}",
                    "result": None
                }

        elif tool_name == "zoom_webinar_management":
            action = arguments.get("action")
            topic = arguments.get("topic")
            start_time = arguments.get("start_time")
            duration = arguments.get("duration", 60)
            password = arguments.get("password")
            webinar_id = arguments.get("webinar_id")
            settings = arguments.get("settings")

            if action == "create":
                if not topic:
                    return {
                        "success": False,
                        "error": "Topic is required for creating a webinar",
                        "result": None
                    }
                result = await zoom_service.create_webinar(
                    topic=topic,
                    start_time=start_time,
                    duration=duration,
                    password=password,
                    settings=settings
                )
                return {
                    "success": result.get("success", False),
                    "result": "Webinar created successfully",
                    "data": result
                }
            elif action == "get":
                if not webinar_id:
                    return {
                        "success": False,
                        "error": "Webinar ID is required",
                        "result": None
                    }
                result = await zoom_service.get_webinar(webinar_id)
                return {
                    "success": result.get("success", False),
                    "result": "Webinar details retrieved",
                    "data": result
                }
            elif action == "list":
                user_id = arguments.get("user_id", "me")
                page_size = arguments.get("page_size", 30)
                page_number = arguments.get("page_number", 1)
                
                result = await zoom_service.list_webinars(
                    user_id=user_id,
                    page_size=page_size,
                    page_number=page_number
                )
                return {
                    "success": result.get("success", False),
                    "result": "Webinars listed successfully",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Zoom webinar management action: {action}",
                    "result": None
                }

        elif tool_name == "zoom_analytics":
            action = arguments.get("action")
            user_id = arguments.get("user_id", "me")
            from_date = arguments.get("from_date")
            to_date = arguments.get("to_date")
            year = arguments.get("year")
            month = arguments.get("month")
            page_size = arguments.get("page_size", 30)
            page_number = arguments.get("page_number", 1)

            if action == "get_meeting_reports":
                result = await zoom_service.get_meeting_reports(
                    user_id=user_id,
                    from_date=from_date,
                    to_date=to_date,
                    page_size=page_size,
                    page_number=page_number
                )
                return {
                    "success": result.get("success", False),
                    "result": "Meeting reports retrieved",
                    "data": result
                }
            elif action == "get_daily_reports":
                if not year or not month:
                    return {
                        "success": False,
                        "error": "Year and month are required for daily reports",
                        "result": None
                    }
                result = await zoom_service.get_daily_reports(
                    year=year,
                    month=month,
                    page_size=page_size,
                    page_number=page_number
                )
                return {
                    "success": result.get("success", False),
                    "result": "Daily reports retrieved",
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown Zoom analytics action: {action}",
                    "result": None
                }

        return {
            "success": False,
            "error": f"Unknown Zoom tool: {tool_name}",
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
        access_token = connection.config.get("api_key")  # Keep same key name for compatibility
        if not access_token:
            return {
                "success": False,
                "error": "No access token found in HubSpot connection",
                "result": None
            }

        # Initialize the service with the user's access token
        hubspot_service.api_key = access_token
        hubspot_service.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        print(f"🔧 Initialized HubSpot service with user access token for user {user.id}")

        if tool_name == "hubspot_contact_operations":
            operation = arguments.get("operation")

            if operation == "create":
                contact_data = arguments.get("contact_data", {})
                result = await hubspot_service.create_contact(contact_data)
                return {
                    "success": result.get("success", False),
                    "result": result.get("message", "Contact created successfully"),
                    "data": result
                }
            elif operation == "read":
                contact_id = arguments.get("contact_id")
                result = await hubspot_service.get_contact(contact_id)
                return {
                    "success": result.get("success", False),
                    "result": result.get("message", "Contact retrieved successfully"),
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
        client_id = connection.config.get("client_id")
        client_secret = connection.config.get("client_secret")
        username = connection.config.get("username")
        password = connection.config.get("password")
        security_token = connection.config.get("security_token")
        instance_url = connection.config.get("instance_url")
        
        if not client_id or not client_secret or not username or not password:
            return {
                "success": False,
                "error": "Missing required Salesforce credentials (client_id, client_secret, username, password)",
                "result": None
            }
        
        # Initialize the service with the user's credentials
        await salesforce_service.initialize(client_id, client_secret, username, password, security_token, instance_url)
        print(f"🔧 Initialized Salesforce service with user credentials for user {user.id}")

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
        
        # Extract configuration from user's connection
        property_id = connection.config.get("property_id")
        credentials_file = connection.config.get("credentials_file")
        
        if not property_id:
            return {
                "success": False,
                "error": "No property ID found in GA4 connection",
                "result": None
            }
        
        if not credentials_file:
            return {
                "success": False,
                "error": "No credentials file found in GA4 connection",
                "result": None
            }
        
        # Initialize the service with the user's configuration
        config = {
            "property_id": property_id,
            "credentials_file": credentials_file
        }
        await ga4_service.initialize(config)
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
        access_token = connection.config.get("access_token")
        phone_number_id = connection.config.get("phone_number_id")
        
        if not access_token or not phone_number_id:
            return {
                "success": False,
                "error": "Missing required WhatsApp credentials (access_token, phone_number_id)",
                "result": None
            }
        
        # Initialize the service with the user's credentials
        whatsapp_service.access_token = access_token
        whatsapp_service.phone_number_id = phone_number_id
        print(f"🔧 Initialized WhatsApp service with user credentials for user {user.id}")

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
                    to_number, message
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
                    to_number, media_url, media_type, caption
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

    async def _execute_asana_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Asana tools."""
        try:
            # Get user's Asana connection
            result = await db.execute(
                select(Connection)
                .filter(
                    Connection.user_id == user.id,
                    Connection.platform == "asana",
                    Connection.status == ConnectionStatus.ACTIVE
                )
            )
            connection = result.scalars().first()
            
            if not connection:
                return {
                    "success": False,
                    "error": "No active Asana connection found. Please create an Asana connection first."
                }

            # Initialize Asana service with user's connection config
            asana_service = AsanaService()
            access_token = connection.config.get("access_token")
            workspace_id = connection.config.get("workspace_id")
            
            if not access_token:
                return {
                    "success": False,
                    "error": "No access token found in Asana connection",
                    "result": None
                }
            
            # Initialize the service with the user's credentials
            config = {"access_token": access_token}
            if workspace_id:
                config["workspace_id"] = workspace_id
            await asana_service.initialize(config)
            print(f"🔧 Initialized Asana service with user access token for user {user.id}")
            
            # Route to specific Asana tool
            if tool_name == "asana_create_project":
                return await self._execute_asana_create_project(arguments, asana_service, connection)
            elif tool_name == "asana_list_projects":
                return await self._execute_asana_list_projects(arguments, asana_service, connection)
            elif tool_name == "asana_create_task":
                return await self._execute_asana_create_task(arguments, asana_service, connection)
            elif tool_name == "asana_list_tasks":
                return await self._execute_asana_list_tasks(arguments, asana_service, connection)
            elif tool_name == "asana_add_comment":
                return await self._execute_asana_add_comment(arguments, asana_service, connection)
            elif tool_name == "asana_get_teams":
                return await self._execute_asana_get_teams(arguments, asana_service, connection)
            elif tool_name == "asana_get_workspaces":
                return await self._execute_asana_get_workspaces(arguments, asana_service, connection)
            else:
                return {
                    "success": False,
                    "error": f"Unknown Asana tool: {tool_name}"
                }
        except Exception as e:
            logger.error(f"Error executing Asana tool {tool_name}: {e}")
            return {
                "success": False,
                "error": f"Asana tool execution failed: {str(e)}"
            }

    async def _execute_asana_create_project(
        self,
        arguments: Dict[str, Any],
        asana_service: AsanaService,
        connection: Connection
    ) -> Dict[str, Any]:
        """Execute Asana create project tool."""
        try:
            name = arguments.get("name")
            if not name:
                return {
                    "success": False,
                    "error": "Project name is required"
                }

            # Use connection config or fallback to environment variables
            config = connection.config
            workspace_id = arguments.get("workspace_id") or config.get("workspace_id")
            team_id = arguments.get("team_id")
            notes = arguments.get("notes", "")
            


            # Ensure we have either workspace_id or team_id for project creation
            if not workspace_id and not team_id:
                # Try to get workspace_id from the service's initialized config
                if asana_service.workspace_id:
                    workspace_id = asana_service.workspace_id
                else:
                    return {
                        "success": False,
                        "error": "Either workspace_id or team_id is required for project creation. Please ensure your Asana connection includes a workspace_id or specify one in the request."
                    }

            result = await asana_service.create_project(
                name=name,
                notes=notes,
                workspace_id=workspace_id,
                team_id=team_id
            )

            if result.get("success"):
                return {
                    "success": True,
                    "result": f"Created Asana project: {name}",
                    "data": result.get("data")
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "Failed to create Asana project")
                }
        except Exception as e:
            logger.error(f"Error creating Asana project: {e}")
            return {
                "success": False,
                "error": f"Failed to create Asana project: {str(e)}"
            }

    async def _execute_asana_list_projects(
        self,
        arguments: Dict[str, Any],
        asana_service: AsanaService,
        connection: Connection
    ) -> Dict[str, Any]:
        """Execute Asana list projects tool."""
        try:
            config = connection.config
            workspace_id = arguments.get("workspace_id") or config.get("workspace_id")
            team_id = arguments.get("team_id")

            # Ensure we have either workspace_id or team_id for listing projects
            if not workspace_id and not team_id:
                # Try to get workspace_id from the service's initialized config
                if asana_service.workspace_id:
                    workspace_id = asana_service.workspace_id
                else:
                    return {
                        "success": False,
                        "error": "Either workspace_id or team_id is required for listing projects. Please ensure your Asana connection includes a workspace_id or specify one in the request."
                    }

            result = await asana_service.list_projects(
                workspace_id=workspace_id,
                team_id=team_id
            )

            if result.get("success"):
                return {
                    "success": True,
                    "result": f"Retrieved {len(result.get('data', []))} Asana projects",
                    "data": result.get("data")
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "Failed to list Asana projects")
                }
        except Exception as e:
            logger.error(f"Error listing Asana projects: {e}")
            return {
                "success": False,
                "error": f"Failed to list Asana projects: {str(e)}"
            }

    async def _execute_asana_create_task(
        self,
        arguments: Dict[str, Any],
        asana_service: AsanaService,
        connection: Connection
    ) -> Dict[str, Any]:
        """Execute Asana create task tool."""
        try:
            name = arguments.get("name")
            if not name:
                return {
                    "success": False,
                    "error": "Task name is required"
                }

            config = connection.config
            workspace_id = config.get("workspace_id")
            project_id = arguments.get("project_id")
            assignee = arguments.get("assignee")
            due_date = arguments.get("due_date")
            notes = arguments.get("notes", "")

            # Ensure we have workspace_id for task creation
            if not workspace_id:
                # Try to get workspace_id from the service's initialized config
                if asana_service.workspace_id:
                    workspace_id = asana_service.workspace_id
                else:
                    return {
                        "success": False,
                        "error": "workspace_id is required for task creation. Please ensure your Asana connection includes a workspace_id."
                    }

            result = await asana_service.create_task(
                name=name,
                notes=notes,
                workspace_id=workspace_id,
                projects=[project_id] if project_id else None,
                assignee=assignee,
                due_date=due_date
            )

            if result.get("success"):
                return {
                    "success": True,
                    "result": f"Created Asana task: {name}",
                    "data": result.get("data")
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "Failed to create Asana task")
                }
        except Exception as e:
            logger.error(f"Error creating Asana task: {e}")
            return {
                "success": False,
                "error": f"Failed to create Asana task: {str(e)}"
            }

    async def _execute_asana_list_tasks(
        self,
        arguments: Dict[str, Any],
        asana_service: AsanaService,
        connection: Connection
    ) -> Dict[str, Any]:
        """Execute Asana list tasks tool."""
        try:
            config = connection.config
            workspace_id = config.get("workspace_id")
            project_id = arguments.get("project_id")
            assignee = arguments.get("assignee")
            limit = arguments.get("limit", 50)

            # Ensure we have workspace_id for task listing
            if not workspace_id:
                # Try to get workspace_id from the service's initialized config
                if asana_service.workspace_id:
                    workspace_id = asana_service.workspace_id
                else:
                    return {
                        "success": False,
                        "error": "workspace_id is required for task listing. Please ensure your Asana connection includes a workspace_id."
                    }

            result = await asana_service.list_tasks(
                workspace_id=workspace_id,
                project_id=project_id,
                assignee=assignee,
                limit=limit
            )

            if result.get("success"):
                return {
                    "success": True,
                    "result": f"Retrieved {len(result.get('data', []))} Asana tasks",
                    "data": result.get("data")
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "Failed to list Asana tasks")
                }
        except Exception as e:
            logger.error(f"Error listing Asana tasks: {e}")
            return {
                "success": False,
                "error": f"Failed to list Asana tasks: {str(e)}"
            }

    async def _execute_asana_add_comment(
        self,
        arguments: Dict[str, Any],
        asana_service: AsanaService,
        connection: Connection
    ) -> Dict[str, Any]:
        """Execute Asana add comment tool."""
        try:
            task_id = arguments.get("task_id")
            comment_text = arguments.get("comment_text")
            
            if not task_id:
                return {
                    "success": False,
                    "error": "Task ID is required"
                }
            if not comment_text:
                return {
                    "success": False,
                    "error": "Comment text is required"
                }

            result = await asana_service.add_comment(
                task_id=task_id,
                text=comment_text
            )

            if result.get("success"):
                return {
                    "success": True,
                    "result": f"Added comment to Asana task {task_id}",
                    "data": result.get("data")
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "Failed to add comment to Asana task")
                }
        except Exception as e:
            logger.error(f"Error adding comment to Asana task: {e}")
            return {
                "success": False,
                "error": f"Failed to add comment to Asana task: {str(e)}"
            }

    async def _execute_asana_get_teams(
        self,
        arguments: Dict[str, Any],
        asana_service: AsanaService,
        connection: Connection
    ) -> Dict[str, Any]:
        """Execute Asana get teams tool."""
        try:
            config = connection.config
            workspace_id = arguments.get("workspace_id") or config.get("workspace_id")

            # Ensure we have workspace_id for getting teams
            if not workspace_id:
                # Try to get workspace_id from the service's initialized config
                if asana_service.workspace_id:
                    workspace_id = asana_service.workspace_id
                else:
                    return {
                        "success": False,
                        "error": "workspace_id is required for getting teams. Please ensure your Asana connection includes a workspace_id."
                    }

            result = await asana_service.get_teams(workspace_id=workspace_id)

            if result.get("success"):
                return {
                    "success": True,
                    "result": f"Retrieved {len(result.get('data', []))} Asana teams",
                    "data": result.get("data")
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "Failed to get Asana teams")
                }
        except Exception as e:
            logger.error(f"Error getting Asana teams: {e}")
            return {
                "success": False,
                "error": f"Failed to get Asana teams: {str(e)}"
            }

    async def _execute_asana_get_workspaces(
        self,
        arguments: Dict[str, Any],
        asana_service: AsanaService,
        connection: Connection
    ) -> Dict[str, Any]:
        """Execute Asana get workspaces tool."""
        try:
            result = await asana_service.get_workspaces()

            if result.get("success"):
                workspaces = result.get("data", [])
                return {
                    "success": True,
                    "result": f"Retrieved {len(workspaces)} Asana workspaces",
                    "data": workspaces
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "Failed to get Asana workspaces")
                }
        except Exception as e:
            logger.error(f"Error getting Asana workspaces: {e}")
            return {
                "success": False,
                "error": f"Failed to get Asana workspaces: {str(e)}"
            }

    async def _execute_powerbi_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Power BI-related tools."""
        try:
            # Get user's Power BI connection
            result = await db.execute(
                select(Connection)
                .filter(
                    Connection.user_id == user.id,
                    Connection.platform == "powerbi",
                    Connection.status == ConnectionStatus.ACTIVE
                )
            )
            connection = result.scalar_one_or_none()

            if not connection:
                return {
                    "success": False,
                    "error": "No active Power BI connection found",
                    "result": None
                }

            # Initialize Power BI service with user's connection config
            powerbi_service = PowerBIService()
            client_id = connection.config.get("client_id")
            client_secret = connection.config.get("client_secret")
            tenant_id = connection.config.get("tenant_id")
            
            if not client_id or not client_secret or not tenant_id:
                return {
                    "success": False,
                    "error": "Missing required Power BI credentials (client_id, client_secret, tenant_id)",
                    "result": None
                }
            
            # Initialize the service with the user's credentials
            await powerbi_service.initialize(client_id, client_secret, tenant_id)
            print(f"🔧 Initialized Power BI service with user credentials for user {user.id}")
            
            # Route to specific Power BI tool
            if tool_name == "powerbi_workspace_management":
                return await self._execute_powerbi_workspace_management(arguments, powerbi_service, connection)
            elif tool_name == "powerbi_dataset_operations":
                return await self._execute_powerbi_dataset_operations(arguments, powerbi_service, connection)
            elif tool_name == "powerbi_report_management":
                return await self._execute_powerbi_report_management(arguments, powerbi_service, connection)
            elif tool_name == "powerbi_dashboard_operations":
                return await self._execute_powerbi_dashboard_operations(arguments, powerbi_service, connection)
            elif tool_name == "powerbi_analytics_summary":
                return await self._execute_powerbi_analytics_summary(arguments, powerbi_service, connection)
            elif tool_name == "powerbi_user_management":
                return await self._execute_powerbi_user_management(arguments, powerbi_service, connection)
            else:
                return {
                    "success": False,
                    "error": f"Unknown Power BI tool: {tool_name}",
                    "result": None
                }

        except Exception as e:
            logger.error(f"Error executing Power BI tool {tool_name}: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to execute Power BI tool: {str(e)}",
                "result": None
            }

    async def _execute_powerbi_workspace_management(
        self,
        arguments: Dict[str, Any],
        powerbi_service: PowerBIService,
        connection: Connection
    ) -> Dict[str, Any]:
        """Execute Power BI workspace management operations."""
        try:
            operation = arguments.get("operation", "list")
            
            if operation == "list":
                result = await powerbi_service.get_workspaces()
            elif operation == "create":
                workspace_name = arguments.get("workspace_name")
                workspace_description = arguments.get("workspace_description")
                result = await powerbi_service.create_workspace(workspace_name, workspace_description)
            elif operation == "delete":
                workspace_id = arguments.get("workspace_id")
                result = await powerbi_service.delete_workspace(workspace_id)
            elif operation == "get_info":
                # For get_info, we'll return the workspaces list
                result = await powerbi_service.get_workspaces()
            else:
                return {
                    "success": False,
                    "error": f"Unknown operation: {operation}",
                    "result": None
                }

            return {
                "success": result.get("success", False),
                "result": result.get("data", result.get("message", "Operation completed")),
                "data": result
            }

        except Exception as e:
            logger.error(f"Error in Power BI workspace management: {e}")
            return {
                "success": False,
                "error": f"Failed to execute Power BI workspace operation: {str(e)}"
            }

    async def _execute_powerbi_dataset_operations(
        self,
        arguments: Dict[str, Any],
        powerbi_service: PowerBIService,
        connection: Connection
    ) -> Dict[str, Any]:
        """Execute Power BI dataset operations."""
        try:
            operation = arguments.get("operation", "list")
            workspace_id = arguments.get("workspace_id")
            
            if operation == "list":
                result = await powerbi_service.get_datasets(workspace_id)
            elif operation == "get_schema":
                dataset_id = arguments.get("dataset_id")
                result = await powerbi_service.get_dataset_schema(dataset_id, workspace_id)
            elif operation == "refresh":
                dataset_id = arguments.get("dataset_id")
                result = await powerbi_service.refresh_dataset(dataset_id, workspace_id)
            elif operation == "execute_query":
                dataset_id = arguments.get("dataset_id")
                dax_query = arguments.get("dax_query")
                result = await powerbi_service.execute_dax_query(dataset_id, dax_query, workspace_id)
            elif operation == "get_refresh_history":
                dataset_id = arguments.get("dataset_id")
                result = await powerbi_service.get_refresh_history(dataset_id, workspace_id)
            else:
                return {
                    "success": False,
                    "error": f"Unknown operation: {operation}",
                    "result": None
                }

            return {
                "success": result.get("success", False),
                "result": result.get("data", result.get("message", "Operation completed")),
                "data": result
            }

        except Exception as e:
            logger.error(f"Error in Power BI dataset operations: {e}")
            return {
                "success": False,
                "error": f"Failed to execute Power BI dataset operation: {str(e)}"
            }

    async def _execute_powerbi_report_management(
        self,
        arguments: Dict[str, Any],
        powerbi_service: PowerBIService,
        connection: Connection
    ) -> Dict[str, Any]:
        """Execute Power BI report management operations."""
        try:
            operation = arguments.get("operation", "list")
            workspace_id = arguments.get("workspace_id")
            
            if operation == "list":
                result = await powerbi_service.get_reports(workspace_id)
            elif operation == "get_embed_token":
                report_id = arguments.get("report_id")
                result = await powerbi_service.get_report_embed_token(report_id, workspace_id)
            elif operation == "get_analytics":
                # For analytics, we'll return the reports list with additional info
                result = await powerbi_service.get_reports(workspace_id)
            else:
                return {
                    "success": False,
                    "error": f"Unknown operation: {operation}",
                    "result": None
                }

            return {
                "success": result.get("success", False),
                "result": result.get("data", result.get("message", "Operation completed")),
                "data": result
            }

        except Exception as e:
            logger.error(f"Error in Power BI report management: {e}")
            return {
                "success": False,
                "error": f"Failed to execute Power BI report operation: {str(e)}"
            }

    async def _execute_powerbi_dashboard_operations(
        self,
        arguments: Dict[str, Any],
        powerbi_service: PowerBIService,
        connection: Connection
    ) -> Dict[str, Any]:
        """Execute Power BI dashboard operations."""
        try:
            operation = arguments.get("operation", "list")
            workspace_id = arguments.get("workspace_id")
            
            if operation == "list":
                result = await powerbi_service.get_dashboards(workspace_id)
            elif operation == "get_info":
                # For get_info, we'll return the dashboards list
                result = await powerbi_service.get_dashboards(workspace_id)
            else:
                return {
                    "success": False,
                    "error": f"Unknown operation: {operation}",
                    "result": None
                }

            return {
                "success": result.get("success", False),
                "result": result.get("data", result.get("message", "Operation completed")),
                "data": result
            }

        except Exception as e:
            logger.error(f"Error in Power BI dashboard operations: {e}")
            return {
                "success": False,
                "error": f"Failed to execute Power BI dashboard operation: {str(e)}"
            }

    async def _execute_powerbi_analytics_summary(
        self,
        arguments: Dict[str, Any],
        powerbi_service: PowerBIService,
        connection: Connection
    ) -> Dict[str, Any]:
        """Execute Power BI analytics summary."""
        try:
            workspace_id = arguments.get("workspace_id")
            result = await powerbi_service.get_analytics_summary(workspace_id)

            return {
                "success": result.get("success", False),
                "result": result.get("data", result.get("message", "Analytics summary generated")),
                "data": result
            }

        except Exception as e:
            logger.error(f"Error in Power BI analytics summary: {e}")
            return {
                "success": False,
                "error": f"Failed to generate Power BI analytics summary: {str(e)}"
            }

    async def _execute_powerbi_user_management(
        self,
        arguments: Dict[str, Any],
        powerbi_service: PowerBIService,
        connection: Connection
    ) -> Dict[str, Any]:
        """Execute Power BI user management operations."""
        try:
            operation = arguments.get("operation", "list_users")
            workspace_id = arguments.get("workspace_id")
            
            if operation == "list_users":
                result = await powerbi_service.get_workspace_users(workspace_id)
            elif operation == "get_user_info":
                # For get_user_info, we'll return the users list
                result = await powerbi_service.get_workspace_users(workspace_id)
            else:
                return {
                    "success": False,
                    "error": f"Unknown operation: {operation}",
                    "result": None
                }

            return {
                "success": result.get("success", False),
                "result": result.get("data", result.get("message", "Operation completed")),
                "data": result
            }

        except Exception as e:
            logger.error(f"Error in Power BI user management: {e}")
            return {
                "success": False,
                "error": f"Failed to execute Power BI user management operation: {str(e)}"
            }

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

    async def _execute_mpesa_tool(
        self,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute M-Pesa payment reconciliation tools."""
        try:
            service = MpesaReconciliationService()
            operation = arguments.get("operation")
            
            # Type casting for potential string placeholders
            def is_placeholder(val):
                return isinstance(val, str) and val.startswith("{{") and val.endswith("}}")

            def safe_int(val, default=0, name="parameter"):
                if val is None: return default
                if isinstance(val, int): return val
                if is_placeholder(val):
                    raise ValueError(f"Variable substitution failed for '{val}'. Step might have failed or variable is undefined.")
                try: return int(str(val))
                except: return default
            
            def safe_float(val, default=0.0, name="parameter"):
                if val is None: return default
                if isinstance(val, (int, float)): return float(val)
                if is_placeholder(val):
                    raise ValueError(f"Variable substitution failed for '{val}'. Step might have failed or variable is undefined.")
                try: return float(str(val))
                except: return default
            
            if operation == "get_summary":
                # Get payment summary for a period
                days = safe_int(arguments.get("days"), 1)
                summary = await service.get_payment_summary(user.id, db, days=days)
                
                # Format the summary for display
                total_amount = float(summary.get("total_amount", 0))
                formatted_summary = f"""📊 M-Pesa Payment Summary (Last {days} day{'s' if days != 1 else ''})

💰 Total Amount: KES {total_amount:,.2f}
📈 Total Payments: {summary.get('total_count', 0)}
✅ Matched: {summary.get('matched_count', 0)}
⚠️ Unmatched: {summary.get('unmatched_count', 0)}
⏳ Pending: {summary.get('pending_count', 0)}"""
                
                return {
                    "success": True,
                    "result": formatted_summary,
                    "data": summary
                }

            elif operation == "search_payments":
                # Alias for get_summary with query/date handling
                from datetime import datetime, timedelta
                
                query = arguments.get("query", "today")
                days = 1 if "today" in query.lower() else 7
                
                # Calculate date range
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days)
                
                summary = await service.get_payment_summary(user.id, start_date, end_date, db)
                
                # Format for display
                total_amount = float(summary.get("total_amount", 0))
                total_count = int(summary.get("total_count", 0))
                
                formatted_summary = f"💰 Daily Summary: KES {total_amount:,.2f} ({total_count} txns)"
                
                # Flatten keys for template access {{step_1.total_amount}}
                response_data = summary.copy()
                response_data["total_amount"] = total_amount
                response_data["transaction_count"] = total_count
                
                return {
                    "success": True,
                    "result": formatted_summary,
                    "data": response_data,
                    "total_amount": total_amount, # Top level access
                    "transaction_count": total_count # Top level access
                }
            
            elif operation == "get_payments":
                # Get list of payments with filters
                status = arguments.get("status", "all")
                limit = safe_int(arguments.get("limit"), 20)
                
                from datetime import datetime, timedelta
                from sqlalchemy import select
                from ..models import MpesaPayment
                
                stmt = select(MpesaPayment).where(
                    MpesaPayment.user_id == user.id
                )
                
                if status != "all":
                    stmt = stmt.where(MpesaPayment.status == status)
                
                stmt = stmt.order_by(MpesaPayment.transaction_time.desc()).limit(limit)
                
                # DEBUG: Log query details
                logger.info(f"🔍 Querying payments for user_id={user.id}, status={status}, limit={limit}")
                
                result = await db.execute(stmt)
                payments = result.scalars().all()
                
                # DEBUG: Log results
                logger.info(f"🔍 Found {len(payments)} payments")
                
                if not payments:
                    return {
                        "success": True,
                        "result": "No payments found matching your criteria.",
                        "data": []
                    }
                
                # Format payments for display
                payment_list = []
                for payment in payments:
                    payment_list.append({
                        "transaction_id": payment.transaction_id,
                        "amount": float(payment.amount),
                        "phone_number": payment.phone_number,
                        "status": payment.status,
                        "transaction_time": payment.transaction_time.isoformat(),
                        "reference": payment.reference
                    })
                
                formatted_result = f"📋 Found {len(payment_list)} payment(s):\n\n"
                for i, p in enumerate(payment_list[:10], 1):  # Show first 10
                    formatted_result += f"{i}. {p['transaction_id']} - KES {p['amount']:,.2f} - {p['status']}\n"
                
                if len(payment_list) > 10:
                    formatted_result += f"...and {len(payment_list) - 10} more."
                
                return {
                    "success": True,
                    "result": formatted_result,
                    "data": payment_list
                }

            elif operation == "match_payment":
                transaction_id = arguments.get("transaction_id")
                if not transaction_id:
                     return {"success": False, "error": "transaction_id required"}
                
                from sqlalchemy import select
                from ..models import MpesaPayment
                stmt = select(MpesaPayment).where(
                    MpesaPayment.transaction_id == transaction_id,
                    MpesaPayment.user_id == user.id
                )
                result = await db.execute(stmt)
                payment = result.scalar_one_or_none()
                
                if not payment:
                    return {"success": False, "error": "Payment not found"}
                
                match_result = await service.attempt_auto_match(payment, db)
                if match_result and match_result["match_type"] != "none":
                     inv = match_result["invoice"]
                     await db.commit()
                     return {
                         "success": True, 
                         "result": f"✅ Matched to Invoice {inv.invoice_number} (Confidence: {match_result['confidence']:.2f})",
                         "data": {"matched": True, "invoice_id": inv.id, "confidence": match_result['confidence']}
                     }
                
                await db.commit()
                return {
                    "success": True, 
                    "result": "❌ No match found",
                    "data": {"matched": False}
                }

            elif operation == "match_payments":
                # Batch match all pending payments
                match_results = await service.match_all_pending_payments(user.id, db)
                
                summary = f"🔄 Batch Matching Results:\n"
                summary += f"- Total Processed: {match_results['total_processed']}\n"
                summary += f"- Matched: {match_results['matched_count']}\n"
                summary += f"- Unmatched: {match_results['unmatched_count']}\n"
                
                return {
                    "success": True,
                    "result": summary,
                    "data": match_results
                }

            elif operation == "create_invoice":
                 invoice_data = arguments.get("invoice_data", {})
                 if not invoice_data:
                      # try flattened params
                      invoice_data = {
                          "invoice_number": arguments.get("invoice_number"),
                           "amount": safe_float(arguments.get("amount"), 0.0),
                          "customer_name": arguments.get("customer_name"),
                          "reference": arguments.get("reference"),
                          "due_date": arguments.get("due_date")
                      }
                 
                 if not invoice_data.get("invoice_number") or not invoice_data.get("amount"):
                      return {"success": False, "error": "invoice_number and amount required"}
                 
                 try:
                     inv = await service.invoice_service.create_invoice(user.id, invoice_data, db)
                     return {
                         "success": True,
                         "result": f"✅ Invoice {inv.invoice_number} created.",
                         "data": {"id": inv.id, "invoice_number": inv.invoice_number}
                     }
                 except Exception as e:
                     return {"success": False, "error": str(e)}

            elif operation == "list_invoices":
                status = arguments.get("status")
                limit = safe_int(arguments.get("limit"), 20)
                invoices = await service.invoice_service.get_invoices(
                    user.id, db, status=status, limit=limit
                )
                data = [{"invoice_number": i.invoice_number, "amount": float(i.amount), "status": i.status, "reference": i.reference} for i in invoices]
                formatted = "📋 Invoices:\n" + "\n".join([f"- {i['invoice_number']}: {i['amount']} ({i['status']})" for i in data])
                return {
                    "success": True,
                    "result": formatted,
                    "data": data
                }
            
            elif operation == "get_unmatched":
                # Get unmatched payments
                limit = safe_int(arguments.get("limit"), 10)
                payments = await service.get_unmatched_payments(user.id, db, limit=limit)
                
                if not payments:
                    return {
                        "success": True,
                        "result": "✅ All payments are matched! No unmatched payments found.",
                        "data": []
                    }
                
                formatted_result = f"⚠️ Found {len(payments)} unmatched payment(s):\n\n"
                for i, payment in enumerate(payments[:10], 1):
                    formatted_result += f"{i}. {payment.transaction_id} - KES {float(payment.amount):,.2f} ({payment.phone_number})\n"
                
                return {
                    "success": True,
                    "result": formatted_result,
                    "data": [{
                        "transaction_id": p.transaction_id,
                        "amount": float(p.amount),
                        "phone_number": p.phone_number,
                        "transaction_time": p.transaction_time.isoformat()
                    } for p in payments]
                }
            
            elif operation == "get_payment_by_transaction_id":
                # Get payment by transaction ID
                transaction_id = arguments.get("transaction_id")
                if not transaction_id:
                    return {
                        "success": False,
                        "error": "transaction_id is required"
                    }
                
                payment = await service.get_payment_by_transaction_id(user.id, db, transaction_id)
                
                if not payment:
                    return {
                        "success": True,
                        "result": f"Payment with transaction ID '{transaction_id}' not found.",
                        "data": None
                    }
                
                formatted_result = f"""💳 Payment Details:

Transaction ID: {payment.transaction_id}
Amount: KES {float(payment.amount):,.2f}
Phone Number: {payment.phone_number}
Status: {payment.status}
Date: {payment.transaction_time.strftime('%Y-%m-%d %H:%M:%S')}
Reference: {payment.reference or 'N/A'}
Description: {payment.description or 'N/A'}"""
                
                return {
                    "success": True,
                    "result": formatted_result,
                    "data": {
                        "transaction_id": payment.transaction_id,
                        "amount": float(payment.amount),
                        "phone_number": payment.phone_number,
                        "status": payment.status,
                        "transaction_time": payment.transaction_time.isoformat(),
                        "reference": payment.reference,
                        "description": payment.description
                    }
                }
            
            elif operation == "analyze_fraud":
                payment_id = safe_int(arguments.get("payment_id"), None)
                transaction_id = arguments.get("transaction_id")
                
                if not payment_id and transaction_id:
                    payment = await service.get_payment_by_transaction_id(user.id, db, transaction_id)
                    if payment:
                        payment_id = payment.id
                
                if not payment_id:
                    return {"success": False, "error": "payment_id or transaction_id required"}
                
                from .fraud_detection_service import fraud_detection_service
                result = await fraud_detection_service.analyze_payment(payment_id, db)
                
                return {
                    "success": True,
                    "result": f"🔍 Fraud Analysis: Risk Score {result['risk_score']:.2f} - {'SUSPICIOUS ⚠️' if result['is_suspicious'] else 'SAFE ✅'}",
                    "data": result
                }

            elif operation == "verify_with_daraja":
                payment_id = safe_int(arguments.get("payment_id"), None)
                transaction_id = arguments.get("transaction_id")
                
                if not payment_id and transaction_id:
                    payment = await service.get_payment_by_transaction_id(user.id, db, transaction_id)
                    if payment:
                        payment_id = payment.id
                
                if not payment_id:
                    return {"success": False, "error": "payment_id or transaction_id required"}
                
                from .fraud_detection_service import fraud_detection_service
                result = await fraud_detection_service.verify_with_daraja(payment_id, db)
                
                return {
                    "success": result.get("success", False),
                    "result": f"📡 Daraja Verification: {result.get('verification_status', 'unknown').upper()}",
                    "data": result
                }

            elif operation == "get_fraud_signals":
                payment_id = safe_int(arguments.get("payment_id"), None)
                if not payment_id:
                    return {"success": False, "error": "payment_id required"}
                
                from ..models import FraudSignal
                stmt = select(FraudSignal).where(FraudSignal.payment_id == payment_id)
                res = await db.execute(stmt)
                signals = res.scalars().all()
                
                data = [{
                    "type": s.signal_type,
                    "score": float(s.risk_score),
                    "confidence": float(s.confidence),
                    "detected_at": s.detected_at.isoformat(),
                    "metadata": s.metadata_
                } for s in signals]
                
                formatted = "🚨 Fraud Signals:\n" + "\n".join([f"- {s['type'].title()}: {s['score']} ({s['metadata']})" for s in data])
                return {
                    "success": True,
                    "result": formatted or "No fraud signals found.",
                    "data": data
                }
            
                
        except Exception as e:
            logger.error(f"Error executing M-Pesa tool: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    async def _execute_hr_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute HR Hub related tools."""
        try:
            service = self.services["hr_hub"]
            if tool_name.endswith("_hr_ops"):
                platform = tool_name.replace("_hr_ops", "")
                return await service.handle_hr_operation(platform=platform, **arguments)
            elif tool_name == "hr_leave_management":
                operation = arguments.get("operation")
                if operation == "get_balance":
                    return await service.get_leave_balance(user.id, arguments.get("employee_id", "me"))
                elif operation == "apply_leave":
                    return await service.apply_leave(user.id, arguments)
                elif operation == "get_requests":
                    return {"success": True, "requests": await service.get_pending_requests(user.id)}
            elif tool_name == "hr_policy_lookup":
                return await service.search_policies(arguments.get("query", ""), language=arguments.get("language", "english"))
            
            return {"success": False, "error": f"Unknown HR tool/operation: {tool_name}"}
        except Exception as e:
            logger.error(f"Error in HR tool: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_lead_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute Lead Intelligence related tools."""
        try:
            service = self.services["lead_intelligence"]
            if tool_name == "lead_intelligence_qualification":
                operation = arguments.get("operation")
                if operation == "score_lead":
                    return await service.score_lead(arguments.get("lead_data", {}))
                elif operation == "extract_info":
                    return await service.extract_lead_info(arguments.get("text", ""))
            elif tool_name == "lead_intelligence_followup":
                return await service.draft_followup(arguments.get("lead_id", ""), tone=arguments.get("tone", "professional"))
            
            return {"success": False, "error": f"Unknown Lead tool: {tool_name}"}
        except Exception as e:
            logger.error(f"Error in Lead tool: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_logistics_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute Logistics Hub related tools."""
        try:
            service = self.services["logistics_hub"]
            if tool_name.endswith("_logistics_ops"):
                platform = tool_name.replace("_logistics_ops", "")
                return await service.handle_logistics_operation(platform=platform, **arguments)
            elif tool_name == "logistics_tracking":
                return await service.get_tracking_status(arguments.get("tracking_number", ""), provider=arguments.get("provider", "automatic"))
            elif tool_name == "logistics_delivery":
                return await service.create_delivery_request(arguments)
            
            return {"success": False, "error": f"Unknown Logistics tool: {tool_name}"}
        except Exception as e:
            logger.error(f"Error in Logistics tool: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_context_intelligence_tool(self, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute Context Intelligence (Bilingual) tool."""
        try:
            service = self.services["context_intelligence"]
            operation = arguments.get("operation")
            
            if operation == "translate":
                text = arguments.get("text", "")
                target_lang = arguments.get("target_lang", "English")
                result = await service.translate(text, target_lang)
                return {
                    "success": True,
                    "result": f"Translated to {target_lang}: {result.get('translated_text')}",
                    "data": result
                }
            
            elif operation == "analyze_sentiment":
                text = arguments.get("text", "")
                result = await service.analyze_sentiment_bilingual(text)
                return {
                    "success": True,
                    "result": f"Sentiment: {result.get('sentiment')} (Score: {result.get('score')})",
                    "data": result
                }
            
            elif operation == "verify_kra_pin":
                pin = arguments.get("pin", "")
                result = await service.verify_kra_pin(pin)
                return {
                    "success": result.get("valid", False),
                    "result": f"KRA PIN {'valid' if result.get('valid') else 'invalid'}: {result.get('taxpayer_name', 'N/A')}",
                    "data": result
                }
            
            elif operation == "check_itax_compliance":
                pin = arguments.get("pin", "")
                result = await service.check_itax_compliance(pin)
                return {
                    "success": True,
                    "result": f"Compliance: {'Yes' if result.get('compliant') else 'No'}",
                    "data": result
                }
            
            else:
                return {"success": False, "error": f"Unknown operation: {operation}"}
                
        except Exception as e:
            logger.error(f"Error in context_intelligence tool: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_fintech_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute Fintech related tools."""
        try:
            service = self.services["fintech"]
            platform = tool_name.replace("_payment_ops", "")
            return await service.process_kenyan_payment(
                provider=platform,
                phone_number=arguments.get("phone_number", ""),
                amount=arguments.get("amount", 0),
                operation=arguments.get("operation", "initiate_payment"),
                transaction_id=arguments.get("transaction_id")
            )
        except Exception as e:
            logger.error(f"Error in Fintech tool {tool_name}: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_ecommerce_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute E-commerce related tools."""
        try:
            service = self.services["ecommerce"]
            platform = tool_name.replace("_ecommerce_ops", "")
            return await service.handle_operation(platform=platform, **arguments)
        except Exception as e:
            logger.error(f"Error in E-commerce tool {tool_name}: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_accounting_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute Accounting related tools."""
        try:
            service = self.services["accounting"]
            platform = tool_name.replace("_accounting_ops", "")
            return await service.handle_operation(platform=platform, **arguments)
        except Exception as e:
            logger.error(f"Error in Accounting tool {tool_name}: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_agri_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute Agritech related tools."""
        try:
            service = self.services["agritech"]
            platform = tool_name.replace("_agri_ops", "")
            return await service.handle_operation(platform=platform, **arguments)
        except Exception as e:
            logger.error(f"Error in Agritech tool {tool_name}: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_health_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute Healthtech related tools."""
        try:
            service = self.services["health"]
            platform = tool_name.replace("_health_ops", "")
            return await service.handle_operation(platform=platform, **arguments)
        except Exception as e:
            logger.error(f"Error in Healthtech tool {tool_name}: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_utility_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute Utility related tools."""
        try:
            service = self.services["utility"]
            platform = tool_name.replace("_utility_ops", "")
            return await service.handle_operation(platform=platform, **arguments)
        except Exception as e:
            logger.error(f"Error in Utility tool {tool_name}: {e}")
            return {"success": False, "error": str(e)}


# Global tool executor instance
tool_executor = ToolExecutor()
