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

from .hubspot_service import HubSpotService
from .mpesa_reconciliation_service import MpesaReconciliationService
from .powerbi_service import PowerBIService
from .salesforce_service import SalesforceService
from .slack_service import SlackService
from .zoho_service import ZohoService
from .kb_autopilot_service import KBAutopilotService
from .social_media_service import SocialMediaService
from .teams_service import TeamsService
from .outlook_service import OutlookService
from .notion_service import NotionService
from .trello_service import TrelloService
from .jira_service import JiraService
from .web_tools_service import WebToolsService
from .whatsapp_service import WhatsAppService
from .zoom_service import ZoomService
from .hr_service import HRService
from .lead_intelligence_service import LeadIntelligenceService
from .logistics_service import LogisticsService
from .bilingual_service import BilingualService
from .kra_service import KraService
from .payment_service import PaymentService
from .ecommerce_service import EcommerceService
from .accounting_service import AccountingService
from .email_template_service import email_template_service
from .agritech_service import AgritechService
from .health_service import HealthService
from .utilities_service import UtilitiesService
from .workflow_service import WorkflowService
from .llm_service import LLMService
from .quickbooks_service import QuickBooksService
from .xero_service import XeroService
from .airtable_service import AirtableService
from .clickup_service import ClickUpService
from .google_workspace import (
    GoogleWorkspaceBaseClient,
    GmailService,
    CalendarService,
    DriveService,
    SheetsService,
    DocsService,
    AnalyticsService
)
from .rag_pipeline_service import RAGPipelineService
from .feature_flags import FeatureGate
from .openai_service import OpenAIEmbeddingService
from .cohere_service import CohereService
from .huggingface_service import HuggingFaceService
from .order_service import OrderService
from .inventory_service import InventoryService
from .real_estate_service import RealEstateService
from .conversational_agent_service import ConversationalAgentService

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
            "outlook": OutlookService(),
            "notion": NotionService(),
            "trello": TrelloService(),
            "jira": JiraService(),
            "zoom": ZoomService(),
            "zoho": ZohoService(),
            "kb_autopilot": KBAutopilotService(ZohoService()),

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
            "order": OrderService(),
            "inventory": InventoryService(),
            "real_estate": RealEstateService(),
            "ecommerce": EcommerceService(),
            "accounting": AccountingService(),
            "agritech": AgritechService(),
            "health": HealthService(),
            "ai_embeddings": {
                "openai": OpenAIEmbeddingService(),
                "cohere": CohereService(),
                "huggingface": HuggingFaceService()
            },
            "utility": UtilitiesService(),
            "workflow": WorkflowService(),
            "clickup": ClickUpService(),
            "kra": KraService(),
            "quickbooks": QuickBooksService(),
            "xero": XeroService(),
            "airtable": AirtableService(),
            "rag": RAGPipelineService(),
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
                    if service_name in ["slack", "teams", "outlook", "notion", "trello", "jira", "zoom", "whatsapp", "social_media", "file_management", "web_tools", "content_creation", "rate_limit", "billing"]:
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
            
            # Check feature access for write operations (FREE tier = read-only)
            write_access_denied = self._check_write_operation_access(tool_name, arguments, user)
            if write_access_denied:
                return write_access_denied


            # Route to appropriate service based on tool name
            if tool_name.startswith("instagram_"):
                return await self._execute_instagram_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("telegram_"):
                return await self._execute_telegram_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("slack_"):
                return await self._execute_slack_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("teams_"):
                return await self._execute_teams_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("outlook_"):
                return await self._execute_outlook_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("notion_"):
                return await self._execute_notion_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("trello_"):
                return await self._execute_trello_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("jira_"):
                return await self._execute_jira_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("zoom_"):
                return await self._execute_zoom_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("zoho_"):
                return await self._execute_zoho_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("hubspot_"):
                return await self._execute_hubspot_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("salesforce_"):
                return await self._execute_salesforce_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("linkedin_"):
                return await self._execute_linkedin_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("airtable_"):
                return await self._execute_airtable_tool(tool_name, arguments, user, db)

            elif tool_name.startswith("marketing_"):
                return await self._execute_marketing_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("whatsapp_"):
                return await self._execute_whatsapp_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("social_media_"):
                return await self._execute_social_media_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("asana_"):
                return await self._execute_asana_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("google_workspace_"):
                return await self._execute_google_workspace_tool(tool_name, arguments, user, db)
            elif tool_name == "email_template":
                return await self._execute_email_template_tool(arguments, user, db)
            elif tool_name.startswith("powerbi_"):
                return await self._execute_powerbi_tool(tool_name, arguments, user, db)
            elif tool_name == "file_management":
                return await self._execute_file_management_tool(arguments, user, db, getattr(self, '_tools_called', []))
            elif tool_name == "web_tools":
                return await self._execute_web_tools_tool(arguments, user, db)
            elif tool_name == "web_search":
                return await self._execute_web_search_tool(arguments, user, db)
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
            elif tool_name.startswith("clickup_"):
                return await self._execute_clickup_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("kra_"):
                return await self._execute_kra_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("xero_"):
                return await self._execute_xero_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("llamaparse_"):
                return await self._execute_llamaparse_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("firecrawl_"):
                return await self._execute_firecrawl_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("pinecone_"):
                return await self._execute_pinecone_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("qdrant_"):
                return await self._execute_qdrant_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("weaviate_"):
                return await self._execute_weaviate_tool(tool_name, arguments, user, db)
            elif tool_name.startswith("unstructured_"):
                return await self._execute_unstructured_tool(tool_name, arguments, user, db)
            elif tool_name == "ai_embeddings":
                return await self._execute_ai_embeddings_tool(arguments)
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
            elif tool_name == "ai_text_generation":
                return await self._execute_ai_text_generation_tool(arguments, user, db)
            elif tool_name.startswith("rag_"):
                return await self._execute_rag_tool(tool_name, arguments, user, db)
            elif tool_name == "workflow_management":
                return await self._execute_system_tool(tool_name, arguments, user, db)
            elif tool_name == "order_management":
                return await self._execute_order_management_tool(arguments, user, db)
            elif tool_name == "inventory_management":
                return await self._execute_inventory_management_tool(arguments, user, db)
            elif tool_name == "real_estate_management":
                return await self._execute_real_estate_tool(arguments, user, db)
            elif tool_name == "conversational_agent":
                return await self._execute_conversational_agent_tool(arguments, user, db)
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
    
    def _check_write_operation_access(self, tool_name: str, arguments: Dict[str, Any], user: User) -> Optional[Dict[str, Any]]:
        """
        Check if user has access to perform write operations based on their tier.
        Returns None if access granted, or error dict if denied.
        
        FREE tier users can only READ. This method blocks:
        - Email sending (inbox_send)
        - Calendar creating/editing (calendar_create_edit)
        - Task creating/updating (tasks_create_update)
        
        Checks both tool name AND the 'operation'/'action' argument.
        """
        # Get operation from arguments (different tools use different keys)
        operation = arguments.get("operation", "").lower() if arguments else ""
        action = arguments.get("action", "").lower() if arguments else ""
        
        # DEBUG LOGGING
        print(f"🔍 [FEATURE GATE DEBUG] Tool: {tool_name}, Operation: {operation}, Action: {action}")
        print(f"🔍 [FEATURE GATE DEBUG] User ID: {user.id}, Tier: {user.subscription_tier}")
        
        # Define write operations and their required feature flags
        # Format: (tool_prefix, [operations_or_actions_that_are_write])
        WRITE_CHECKS = {
            "inbox_send": {
                # Google Workspace Gmail
                "google_workspace_gmail": ["send_email", "send", "reply", "forward", "compose"],
                # Outlook
                "outlook_email": ["send_email", "send", "reply", "forward"],
                "outlook": ["send_email", "reply_email"],
                # Slack
                "slack": ["send_message", "post_message"],
                # Teams
                "teams": ["send_message", "post_message"],
                # WhatsApp
                "whatsapp": ["send_message", "send_template"],
            },
            "calendar_create_edit": {
                # Google Workspace Calendar
                "google_workspace_calendar": ["create", "create_event", "update", "update_event", "delete", "delete_event"],
                # Outlook Calendar
                "outlook_calendar": ["create_event", "update_event", "delete_event"],
                "outlook": ["create_event", "update_event"],
            },
            "tasks_create_update": {
                # Jira
                "jira": ["create_issue", "update_issue", "add_comment", "transition_issue", "create", "update"],
                # Trello
                "trello": ["create_card", "update_card", "move_card", "create", "update"],
                # Asana
                "asana": ["create_task", "update_task", "create_project", "add_comment", "create", "update"],
                # ClickUp
                "clickup": ["create_task", "update_task", "create", "update"],
            },
        }
        
        # Check each feature category
        for feature_flag, tool_operations in WRITE_CHECKS.items():
            for tool_prefix, blocked_operations in tool_operations.items():
                # Check if tool matches this prefix
                if tool_name.startswith(tool_prefix) or tool_name == tool_prefix:
                    print(f"🔍 [FEATURE GATE DEBUG] Tool prefix match: {tool_prefix}")
                    print(f"🔍 [FEATURE GATE DEBUG] Blocked operations: {blocked_operations}")
                    print(f"🔍 [FEATURE GATE DEBUG] Checking: '{operation}' in {blocked_operations} = {operation in blocked_operations}")
                    print(f"🔍 [FEATURE GATE DEBUG] Checking: '{action}' in {blocked_operations} = {action in blocked_operations}")
                    
                    # Check if operation or action is a write operation
                    if operation in blocked_operations or action in blocked_operations:
                        # Check if user has this feature
                        has_access = FeatureGate.has_feature(user, feature_flag)
                        print(f"🔍 [FEATURE GATE DEBUG] Checking has_feature({user.subscription_tier}, {feature_flag}) = {has_access}")
                        
                        if not has_access:
                            upgrade_msg = FeatureGate.get_upgrade_message(user.subscription_tier, feature_flag)
                            logger.info(f"Feature gate blocked {tool_name}/{operation or action} for user {user.id} (tier: {user.subscription_tier}, required: {feature_flag})")
                            print(f"🚫 [FEATURE GATE] BLOCKED: {tool_name}/{operation or action} for {user.subscription_tier} tier")
                            return {
                                "success": False,
                                "error": upgrade_msg,
                                "upgrade_required": True,
                                "required_feature": feature_flag,
                                "current_tier": user.subscription_tier,
                                "result": None
                            }
                        else:
                            print(f"✅ [FEATURE GATE] ALLOWED: {tool_name}/{operation or action} - user has {feature_flag}")
        
        print(f"✅ [FEATURE GATE] No write operation detected, allowing: {tool_name}")
        return None  # Access granted

    def _get_platform_from_tool(self, tool_name: str) -> Optional[str]:
        """Map tool name to platform string."""
        if tool_name.startswith("slack_"): return "slack"
        if tool_name.startswith("teams_"): return "teams"
        if tool_name.startswith("zoom_"): return "zoom"
        if tool_name.startswith("zoho_"): return "zoho"
        if tool_name.startswith("hubspot_"): return "hubspot"
        if tool_name.startswith("salesforce_"): return "salesforce"
        if tool_name.startswith("linkedin_"): return "linkedin"
        if tool_name.startswith("airtable_"): return "airtable"
        if tool_name.startswith("social_media_"): return "social_media"
        if tool_name.startswith("asana_"): return "asana"
        if tool_name.startswith("google_workspace_"): return "google_workspace"
        if tool_name.startswith("powerbi_"): return "powerbi"
        if tool_name.startswith("mpesa_"): return "mpesa"
        if tool_name.startswith("hr_"): return "hr_hub"
        if tool_name.startswith("lead_intelligence_"): return "lead_intelligence"
        if tool_name.startswith("lead_intelligence_"): return "lead_intelligence"
        if tool_name.startswith("logistics_"): return "logistics_hub"
        if tool_name.startswith("clickup_"): return "clickup"
        if tool_name.startswith("kra_"): return "kra_portal"
        if tool_name.startswith("xero_"): return "xero"
        if tool_name.startswith("rag_"): return "rag_pipeline"
        if tool_name.startswith("pinecone_"): return "vector_databases"
        if tool_name.startswith("qdrant_"): return "vector_databases"
        if tool_name.startswith("weaviate_"): return "vector_databases"
        if tool_name.startswith("llamaparse_"): return "document_parsers"
        if tool_name.startswith("unstructured_"): return "document_parsers"
        if tool_name.startswith("firecrawl_"): return "document_parsers"
        if tool_name == "ai_embeddings": return "ai_models"
        
        # Kenyan Specific Mappings
        if tool_name.endswith("_payment_ops"): return tool_name.replace("_payment_ops", "")
        if tool_name.endswith("_ecommerce_ops"): return tool_name.replace("_ecommerce_ops", "")
        if tool_name.endswith("_accounting_ops"): return tool_name.replace("_accounting_ops", "")
        if tool_name.endswith("_agri_ops"): return tool_name.replace("_agri_ops", "")
        if tool_name.endswith("_health_ops"): return tool_name.replace("_health_ops", "")
        if tool_name.endswith("_utility_ops"): return tool_name.replace("_utility_ops", "")
        
        return None

    async def _execute_llamaparse_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        from .llamaparse_service import LlamaParseService
        service = LlamaParseService()
        operation = arguments.get("operation", "")
        # Handle both "llamaparse_operations" (registry name) and individual tool names
        if tool_name == "llamaparse_operations":
            if operation == "parse_document":
                res = await service.llamaparse_parse_document(arguments.get("url", arguments.get("file_path_or_url")))
                return {"success": True, "result": res}
            elif operation == "parse_from_url":
                res = await service.llamaparse_parse_document(arguments.get("url", arguments.get("file_path_or_url")))
                return {"success": True, "result": res}
            elif operation == "get_job_result":
                res = await service.llamaparse_get_job_result(arguments.get("job_id"))
                return {"success": True, "result": res}
            return {"success": False, "error": f"Unknown llamaparse operation: {operation}"}
        elif tool_name == "llamaparse_parse_document" or tool_name == "llamaparse_parse_from_url":
            res = await service.llamaparse_parse_document(arguments.get("file_path_or_url"))
            return {"success": True, "result": res}
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    async def _execute_firecrawl_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        from .firecrawl_service import FirecrawlService
        service = FirecrawlService()
        operation = arguments.get("operation", "")
        # Handle both "firecrawl_operations" (registry name) and individual tool names
        if tool_name == "firecrawl_operations":
            if operation == "scrape_url":
                res = await service.firecrawl_scrape_url(arguments.get("url", arguments.get("start_url")))
                return {"success": True, "result": res}
            elif operation == "crawl_website":
                res = await service.firecrawl_crawl_website(arguments.get("url", arguments.get("start_url")), arguments.get("max_depth", 2))
                return {"success": True, "result": res}
            elif operation == "map_sitemap":
                res = await service.firecrawl_crawl_website(arguments.get("url"), arguments.get("max_depth", 1))
                return {"success": True, "result": res}
            return {"success": False, "error": f"Unknown firecrawl operation: {operation}"}
        elif tool_name == "firecrawl_crawl_website":
            res = await service.firecrawl_crawl_website(arguments.get("start_url"), arguments.get("max_depth", 2))
            return {"success": True, "result": res}
        elif tool_name == "firecrawl_scrape_url":
            res = await service.firecrawl_scrape_url(arguments.get("start_url"))
            return {"success": True, "result": res}
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    async def _execute_pinecone_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        from .pinecone_service import PineconeService
        service = PineconeService()
        operation = arguments.get("operation", "")
        # Handle both "pinecone_operations" (registry name) and individual tool names
        if tool_name == "pinecone_operations":
            if operation == "upsert":
                res = await service.pinecone_upsert_vectors(arguments.get("index_name"), arguments.get("namespace"), arguments.get("vectors", []))
                return {"success": True, "result": res}
            elif operation == "query":
                res = await service.pinecone_query(arguments.get("index_name"), arguments.get("namespace"), arguments.get("query_vector", []))
                return {"success": True, "result": res}
            elif operation == "delete_namespace":
                res = await service.pinecone_delete_namespace(arguments.get("index_name"), arguments.get("namespace"))
                return {"success": True, "result": res}
            return {"success": False, "error": f"Unknown pinecone operation: {operation}"}
        elif tool_name == "pinecone_upsert_vectors":
            res = await service.pinecone_upsert_vectors(arguments.get("index_name"), arguments.get("namespace"), [])
            return {"success": True, "result": res}
        elif tool_name == "pinecone_query":
            res = await service.pinecone_query(arguments.get("index_name"), arguments.get("namespace"), [])
            return {"success": True, "result": res}
        elif tool_name == "pinecone_delete_namespace":
            res = await service.pinecone_delete_namespace(arguments.get("index_name"), arguments.get("namespace"))
            return {"success": True, "result": res}
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    async def _execute_qdrant_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute Qdrant vector DB operations."""
        try:
            from .qdrant_service import QdrantService
            service = QdrantService()
            operation = arguments.get("operation", "")
            collection = arguments.get("collection_name", "")

            if operation == "upsert":
                res = await service.qdrant_upsert_points(collection, arguments.get("points", []))
                return {"success": True, "result": res}
            elif operation == "search":
                res = await service.qdrant_search(collection, arguments.get("query_vector", []), arguments.get("limit", 5))
                return {"success": True, "result": res}
            elif operation == "delete_collection":
                res = await service.qdrant_delete_collection(collection)
                return {"success": True, "result": res}
            return {"success": False, "error": f"Unknown qdrant operation: {operation}"}
        except ImportError:
            return {"success": False, "error": "Qdrant service is not available. Please install qdrant-client."}
        except Exception as e:
            return {"success": False, "error": f"Qdrant error: {str(e)}"}

    async def _execute_weaviate_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute Weaviate vector DB operations."""
        try:
            from .weaviate_service import WeaviateService
            service = WeaviateService()
            operation = arguments.get("operation", "")
            class_name = arguments.get("class_name", "")

            if operation == "add_objects":
                res = await service.weaviate_add_objects(class_name, arguments.get("objects", []), arguments.get("tenant"))
                return {"success": True, "result": res}
            elif operation == "hybrid_search":
                res = await service.weaviate_hybrid_search(class_name, arguments.get("query", ""), arguments.get("vector"), arguments.get("limit", 5), arguments.get("tenant"))
                return {"success": True, "result": res}
            elif operation == "delete_tenant":
                res = await service.weaviate_delete_tenant(class_name, arguments.get("tenant"))
                return {"success": True, "result": res}
            return {"success": False, "error": f"Unknown weaviate operation: {operation}"}
        except ImportError:
            return {"success": False, "error": "Weaviate service is not available. Please install weaviate-client."}
        except Exception as e:
            return {"success": False, "error": f"Weaviate error: {str(e)}"}

    async def _execute_unstructured_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute Unstructured document parsing operations."""
        try:
            from .unstructured_service import UnstructuredService
            service = UnstructuredService()
            operation = arguments.get("operation", "")

            if operation == "partition_document":
                res = await service.unstructured_partition_document(arguments.get("filename", ""))
                return {"success": True, "result": res}
            elif operation == "chunk_elements":
                res = await service.unstructured_chunk_elements(arguments.get("elements", []))
                return {"success": True, "result": res}
            return {"success": False, "error": f"Unknown unstructured operation: {operation}"}
        except ImportError:
            return {"success": False, "error": "Unstructured service is not available. Please install unstructured."}
        except Exception as e:
            return {"success": False, "error": f"Unstructured error: {str(e)}"}

    async def _execute_instagram_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Instagram-related tools."""
        result = await db.execute(
            select(Connection)
            .filter(
                Connection.user_id == user.id,
                Connection.platform == "instagram",
                Connection.status == ConnectionStatus.ACTIVE
            )
        )
        connection = result.scalar_one_or_none()

        if not connection:
            return {
                "success": False,
                "error": "No active Instagram connection found",
                "result": None
            }

        access_token = connection.config.get("access_token")
        if not access_token:
            return {
                "success": False,
                "error": "No access token found in Instagram connection",
                "result": None
            }
            
        from .instagram_service import InstagramService
        ig_service = InstagramService(access_token)
        
        if tool_name == "instagram_send_dm":
            recipient_id = arguments.get("recipient_id")
            message = arguments.get("message")
            result = await ig_service.send_dm(recipient_id=recipient_id, message=message)
            return {"success": result.get("success"), "error": result.get("error"), "result": result}
            
        return {"success": False, "error": f"Unknown Instagram tool: {tool_name}"}

    async def _execute_telegram_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Telegram-related tools."""
        from .telegram_service import TelegramService
        tg_service = TelegramService()
        
        if tool_name == "telegram_send_message":
            chat_id = arguments.get("chat_id")
            message = arguments.get("message", "")

            # ── Smart Image Dispatcher (Telegram) ──────────────
            # Detect image URLs and send them as native Telegram photos.
            from .conversational_agent_service import extract_image_urls, strip_image_urls

            image_urls = arguments.get("image_urls", [])
            if not image_urls:
                image_urls = extract_image_urls(message)

            clean_message = strip_image_urls(message, image_urls) if image_urls else message

            # 1) Send text message first (if any text remains)
            text_result = None
            if clean_message.strip():
                text_result = await tg_service.send_message(chat_id=chat_id, message=clean_message)

            # 2) Send each image as a native Telegram photo
            media_results = []
            for img_url in image_urls:
                try:
                    photo_res = await tg_service.send_photo(
                        chat_id=chat_id,
                        photo_url=img_url,
                        caption=""
                    )
                    media_results.append({"url": img_url, "result": photo_res})
                    logger.info(f"[TG_SMART_DISPATCH] Sent photo to {chat_id}: {img_url[:80]}")
                except Exception as img_err:
                    logger.warning(f"[TG_SMART_DISPATCH] Failed to send photo {img_url[:80]}: {img_err}")
                    media_results.append({"url": img_url, "error": str(img_err)})

            images_sent = len([r for r in media_results if "result" in r])
            result_data = text_result or {"success": True}

            result_summary = "Message sent"
            if images_sent:
                result_summary += f" + {images_sent} photo(s) sent"

            return {
                "success": result_data.get("success", True),
                "error": result_data.get("error"),
                "result": result_summary,
                "images_sent": images_sent,
                "media_results": media_results,
                "data": result_data
            }
            
        return {"success": False, "error": f"Unknown Telegram tool: {tool_name}"}

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
            thread_ts = arguments.get("thread_ts") # Get thread_ts for threaded replies

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
                    print(f"💬 Sending message to Slack channel {channel}: {message}" + (f" (thread: {thread_ts})" if thread_ts else ""))
                    
                    # Check for attachments from frontend (base64 encoded)
                    attachments = arguments.get("attachments", [])
                    upload_results = []
                    
                    if attachments:
                        print(f"📎 Uploading {len(attachments)} attachment(s) to Slack...")
                        for attachment in attachments:
                            filename = attachment.get("filename", "file")
                            content = attachment.get("content", "")
                            if content:
                                upload_result = await slack_service.upload_file_from_content(
                                    channel=channel,
                                    filename=filename,
                                    content=content,
                                    comment=None,  # Don't add comment for each file
                                    thread_ts=thread_ts
                                )
                                upload_results.append(upload_result)
                                print(f"📤 Uploaded {filename}: {upload_result.get('success', False)}")
                    
                    # Send the message
                    result = await slack_service.send_message(
                        channel, message, thread_ts=thread_ts
                    )
                    
                    # Combine results
                    if upload_results:
                        result["attachments_uploaded"] = len([r for r in upload_results if r.get("success")])
                        result["attachment_errors"] = [r.get("error") for r in upload_results if not r.get("success")]
                    
                    return {
                        "success": result.get("success", False),
                        "result": result.get("message") or result.get("error") or f"Message sent to {channel}" + (f" with {len(upload_results)} attachment(s)" if upload_results else "") + (" as thread reply" if thread_ts else ""),
                        "data": result,
                        "processed_arguments": {
                            "channel": channel,
                            "message": message,
                            "thread_ts": thread_ts,
                            "attachments": len(attachments) if attachments else 0
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
            elif action == "get_channel_history":
                channel = arguments.get("channel")
                limit = arguments.get("limit", 20)

                if not channel:
                     return {
                        "success": False,
                        "error": "Channel name or ID is required",
                        "result": None
                    }
                
                # Check if input is likely an ID (starts with C, G, D) or name
                # Simple check: if it starts with C/G/D and has numbers, treat as ID, else Name
                # But safer to just pass both to the service method which resolves it
                
                result = await slack_service.get_channel_history(channel_name=channel, limit=limit)
                return {
                    "success": result.get("success", False),
                    "result": f"Found {result.get('total_found', 0)} messages",
                    "data": result
                }
            elif action == "get_recent_messages":
                limit = arguments.get("limit", 20)
                
                result = await slack_service.get_recent_messages_across_channels(limit=limit)
                return {
                    "success": result.get("success", False),
                    "result": f"Found {result.get('total_found', 0)} recent overall messages",
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
            action = arguments.get("action", "search_messages")
            limit = arguments.get("limit", 20)
            
            if action == "get_recent_chats":
                print(f"💬 Getting recent Teams chats for user {user.id}")
                result = await teams_service.get_recent_chats(limit=limit)
                return {
                    "success": result.get("success", False),
                    "result": f"Retrieved {result.get('count', 0)} recent chats",
                    "data": result
                }
                
            elif action == "search_messages":
                query = arguments.get("query")
                channel_id = arguments.get("channel_id")

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
            else:
                 return {
                    "success": False,
                    "error": f"Unknown Teams message action: {action}",
                    "result": None
                }

        return {
            "success": False,
            "error": f"Unknown Teams tool: {tool_name}",
            "result": None
        }

    async def _execute_outlook_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Outlook-related tools."""
        # Get user's Outlook connection
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user.id,
                Connection.platform == "outlook",
                Connection.status == ConnectionStatus.ACTIVE
            )
        )
        connection = result.scalars().first()

        if not connection:
            return {
                "success": False,
                "error": "Outlook is not connected. Please connect your Outlook account first.",
                "result": None
            }

        # Configure service with user's specific access token
        outlook_service = self.services["outlook"]
        config = connection.config
        
        # We need to manually inject token, service expects 'access_token' in config usually or we set it directly
        # The OutlookService I wrote has self.access_token.
        # It also has initialize() which reads ENV vars for client_id.
        # But for request-specific action, we need to set access_token.
        outlook_service.access_token = config.get("access_token")
        
        # Check if we should use refresh token? Not implemented in Service yet, 
        # but the Router saved it. 
        # For now assume access token is valid or we'd need a refresh mechanism.

        if tool_name == "outlook_email_management":
            action = arguments.get("action")
            
            if action == "read_emails":
                limit = arguments.get("limit", 10)
                result = await outlook_service.get_recent_emails(limit)
                return {
                    "success": result.get("success", False),
                    "result": f"Retrieved {result.get('count', 0)} emails",
                    "data": result
                }
            elif action == "search_emails":
                query = arguments.get("query")
                limit = arguments.get("limit", 10)
                if not query:
                    return {"success": False, "error": "Query required for search_emails"}
                result = await outlook_service.search_emails(query, limit)
                return {
                    "success": result.get("success", False),
                    "result": f"Found {result.get('count', 0)} emails for query '{query}'",
                    "data": result
                }
            elif action == "send_email":
                to_email = arguments.get("to_email")
                subject = arguments.get("subject")
                content = arguments.get("content")
                content_type = arguments.get("content_type", "text")
                cc_email = arguments.get("cc")
                bcc_email = arguments.get("bcc")
                
                if not to_email or not subject or not content:
                     return {"success": False, "error": "To, Subject, and Content required for send_email"}
                
                result = await outlook_service.send_email(
                    to_email=to_email, 
                    subject=subject, 
                    content=content, 
                    content_type=content_type,
                    cc=cc_email,
                    bcc=bcc_email
                )
                return {
                    "success": result.get("success", False),
                    "result": "Email sent",
                    "data": result
                }
            else:
                 return {"success": False, "error": f"Unknown Outlook action: {action}"}

        return {
            "success": False,
            "error": f"Unknown Outlook tool: {tool_name}",
            "result": None
        }

    async def _execute_notion_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Notion-related tools."""
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user.id,
                Connection.platform == "notion",
                Connection.status == ConnectionStatus.ACTIVE
            )
        )
        connection = result.scalars().first()

        if not connection:
            return {
                "success": False,
                "error": "Notion is not connected. Please connect your Notion account first.",
                "result": None
            }

        notion_service = self.services["notion"]
        config = connection.config
        notion_service.access_token = config.get("access_token")

        if tool_name == "notion_workspace_management":
            action = arguments.get("action")
            
            if action == "search_pages":
                query = arguments.get("query", "")
                limit = arguments.get("limit", 10)
                result = await notion_service.search_pages(query, limit)
                return {
                    "success": result.get("success", False),
                    "result": f"Found {result.get('count', 0)} pages",
                    "data": result
                }
            elif action == "create_page":
                title = arguments.get("title")
                parent_id = arguments.get("parent_id")
                content = arguments.get("content", "")
                
                if not title or not parent_id:
                     return {"success": False, "error": "Title and Parent ID required for create_page"}
                
                result = await notion_service.create_page(parent_id, title, content)
                return {
                    "success": result.get("success", False),
                    "result": "Page created",
                    "data": result
                }
            else:
                 return {"success": False, "error": f"Unknown Notion action: {action}"}

        return {
            "success": False,
            "error": f"Unknown Notion tool: {tool_name}",
            "result": None
        }

    async def _execute_trello_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Trello-related tools."""
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user.id,
                Connection.platform == "trello",
                Connection.status == ConnectionStatus.ACTIVE
            )
        )
        connection = result.scalars().first()

        if not connection:
            return {
                "success": False,
                "error": "Trello is not connected. Please connect your Trello account first.",
                "result": None
            }

        trello_service = self.services["trello"]
        config = connection.config
        trello_service.access_token = config.get("access_token")

        if tool_name == "trello_project_management":
            action = arguments.get("action")
            
            if action == "get_boards":
                result = await trello_service.get_boards()
                return {
                    "success": result.get("success", False),
                    "result": f"Found {result.get('count', 0)} boards",
                    "data": result
                }
            elif action == "get_board_members":
                board_id = arguments.get("board_id")
                if not board_id:
                     return {"success": False, "error": "Board ID required for get_board_members"}
                result = await trello_service.get_board_members(board_id)
                return {
                    "success": result.get("success", False),
                    "result": f"Found {result.get('count', 0)} members",
                    "data": result
                }
            elif action == "search_cards":
                query = arguments.get("query", "")
                limit = arguments.get("limit", 10)
                if not query:
                     return {"success": False, "error": "Query required for search_cards"}
                result = await trello_service.search_cards(query, limit)
                return {
                    "success": result.get("success", False),
                    "result": f"Found {result.get('count', 0)} cards",
                    "data": result
                }
            elif action == "get_lists":
                board_id = arguments.get("board_id")
                if not board_id:
                     return {"success": False, "error": "Board ID required for get_lists"}
                result = await trello_service.get_lists(board_id)
                return {
                    "success": result.get("success", False),
                    "result": f"Found {result.get('count', 0)} lists",
                    "data": result
                }
            elif action == "create_card":
                list_id = arguments.get("list_id")
                name = arguments.get("name")
                desc = arguments.get("desc", "")
                due = arguments.get("due")
                
                start = arguments.get("start")
                idMembers = arguments.get("idMembers")
                
                if not list_id or not name:
                     return {"success": False, "error": "List ID and Name required for create_card"}
                
                result = await trello_service.create_card(list_id, name, desc, due, start, idMembers)
                return {
                    "success": result.get("success", False),
                    "result": "Card created",
                    "data": result
                }
            elif action == "update_card":
                card_id = arguments.get("card_id")
                list_id = arguments.get("list_id")
                name = arguments.get("name")
                desc = arguments.get("desc")
                closed = arguments.get("closed")
                
                due = arguments.get("due")
                start = arguments.get("start")
                idMembers = arguments.get("idMembers")
                
                if not card_id:
                     return {"success": False, "error": "Card ID required for update_card"}
                
                result = await trello_service.update_card(card_id, list_id, name, desc, closed, due, start, idMembers)
                return {
                    "success": result.get("success", False),
                    "result": "Card updated",
                    "data": result
                }
            else:
                 return {"success": False, "error": f"Unknown Trello action: {action}"}

        return {
            "success": False,
            "error": f"Unknown Trello tool: {tool_name}",
            "result": None
        }

    async def _execute_jira_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Jira-related tools."""
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user.id,
                Connection.platform == "jira",
                Connection.status == ConnectionStatus.ACTIVE
            )
        )
        connection = result.scalars().first()

        if not connection:
            return {
                "success": False,
                "error": "Jira is not connected. Please connect your Jira account first.",
                "result": None
            }

        jira_service = self.services["jira"]
        config = connection.config
        jira_service.access_token = config.get("access_token")
        jira_service.cloud_id = config.get("cloud_id")
        refresh_token = config.get("refresh_token")

        async def execute_with_retry(func, *args, **kwargs):
            # First attempt
            res = await func(*args, **kwargs)
            
            # Check for 401 Unauthorized
            error_msg = str(res.get("error", ""))
            if not res.get("success") and "401" in error_msg and refresh_token:
                logger.info("Jira token expired (401). Attempting refresh...")
                try:
                    # Refresh token
                    new_tokens = await jira_service.refresh_access_token(refresh_token)
                    new_access_token = new_tokens.get("access_token")
                    new_refresh_token = new_tokens.get("refresh_token")
                    
                    if new_access_token:
                        # Update DB
                        config["access_token"] = new_access_token
                        if new_refresh_token:
                            config["refresh_token"] = new_refresh_token
                        
                        connection.config = config
                        # We need to explicitly flag modified for JSON types sometimes, but reassignment usually works
                        # Ensure SQLAlchemy detects change
                        from sqlalchemy.orm.attributes import flag_modified
                        flag_modified(connection, "config")
                        
                        await db.commit()
                        logger.info("Jira token refreshed and saved to DB.")
                        
                        # Update Service instance
                        jira_service.access_token = new_access_token
                        
                        # Retry operation
                        return await func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Failed to refresh Jira token: {e}")
                    # Fall through to return original 401 response
                    
            return res

        if tool_name == "jira_issue_tracking":
            action = arguments.get("action")
            
            if action == "get_projects":
                result = await execute_with_retry(jira_service.get_projects)
                return {
                    "success": result.get("success", False),
                    "result": f"Found {result.get('count', 0)} projects",
                    "data": result
                }
            elif action == "get_users":
                project_key = arguments.get("project_key") # Optional
                result = await execute_with_retry(jira_service.get_users, project_key)
                return {
                    "success": result.get("success", False),
                    "result": f"Found {result.get('count', 0)} users",
                    "data": result
                }
            elif action == "search_issues":
                jql = arguments.get("jql", "")
                limit = arguments.get("limit", 10)
                if not jql:
                     return {"success": False, "error": "JQL required for search_issues"}
                result = await execute_with_retry(jira_service.search_issues, jql, limit)
                return {
                    "success": result.get("success", False),
                    "result": f"Found {result.get('count', 0)} issues",
                    "data": result
                }
            elif action == "create_issue":
                project_key = arguments.get("project_key")
                summary = arguments.get("summary")
                description = arguments.get("description", "")
                issuetype = arguments.get("issuetype", "Task")
                status = arguments.get("status", "To Do")
                assignee_id = arguments.get("assignee_id")
                priority = arguments.get("priority")
                duedate = arguments.get("duedate")
                
                if not project_key or not summary:
                     return {"success": False, "error": "Project Key and Summary required for create_issue"}
                
                result = await execute_with_retry(jira_service.create_issue, project_key, summary, description, issuetype, status, assignee_id, priority, duedate)
                return {
                    "success": result.get("success", False),
                    "result": "Issue created",
                    "data": result
                }
            elif action == "update_issue":
                issue_key = arguments.get("issue_key")
                status = arguments.get("status")
                summary = arguments.get("summary")
                description = arguments.get("description")
                due_date = arguments.get("due_date")
                
                if not issue_key:
                     return {"success": False, "error": "Issue Key required for update_issue"}
                
                results = []
                success = True
                
                # Update status if provided
                if status:
                    res = await execute_with_retry(jira_service._transition_issue, issue_key, status)
                    results.append(res)
                    if not res.get("success"):
                        success = False
                
                # Update summary/description/due_date/priority/assignee if provided
                if summary or description or due_date or arguments.get("priority") or arguments.get("assignee_id"):
                    res = await execute_with_retry(
                        jira_service.update_issue, 
                        issue_key=issue_key, 
                        summary=summary, 
                        description=description, 
                        assignee_id=arguments.get("assignee_id"),
                        priority=arguments.get("priority"),
                        due_date=due_date
                    )
                    results.append(res)
                    if not res.get("success"):
                        success = False
                
                if not status and not summary and not description and not due_date and not arguments.get("assignee_id") and not arguments.get("priority"):
                    return {"success": False, "error": "At least one field (status, summary, description, due_date, assignee_id, priority) must be provided to update"}

                return {
                    "success": success,
                    "result": f"Issue updated" if success else "Issue update failed partially or fully",
                    "data": results[0] if len(results) == 1 else results
                }
            else:
                 return {"success": False, "error": f"Unknown Jira action: {action}"}

        return {
            "success": False,
            "error": f"Unknown Jira tool: {tool_name}",
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
        # We pass the entire config dict which may contain client_id, client_secret, account_id, AND access_token
        # Ensure we are passing what the service expects
        service_config = connection.config.copy() if connection.config else {}
        
        # Initialize the service with the user's credentials
        # The initialize method expects a dictionary 'config'
        await zoom_service.initialize(config=service_config)
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
            elif operation == "associate":
                contact_id = arguments.get("contact_id")
                target_type = arguments.get("target_type")
                target_id = arguments.get("target_id")
                result = await hubspot_service.associate_contact(contact_id, target_type, target_id)
                return {
                    "success": result.get("success", False),
                    "result": result.get("message", "Contact associated successfully"),
                    "data": result
                }
            else:
                return {
                    "success": False,
                    "error": f"Unknown HubSpot operation: {operation}",
                    "result": None
                }

        elif tool_name == "hubspot_company_operations":
            operation = arguments.get("operation")
            if operation == "read":
                company_id = arguments.get("company_id")
                result = await hubspot_service.get_company(company_id)
                return {
                    "success": result.get("success", False),
                    "result": result.get("message", "Company retrieved successfully"),
                    "data": result
                }
            return {"success": False, "error": f"Unknown operation: {operation}"}

        elif tool_name == "hubspot_engagement_operations":
            operation = arguments.get("operation")
            if operation == "create":
                result = await hubspot_service.create_engagement(arguments)
                return {
                    "success": result.get("success", False),
                    "result": result.get("message", "Engagement created successfully"),
                    "data": result
                }
            return {"success": False, "error": f"Unknown operation: {operation}"}

        elif tool_name == "hubspot_sequence_operations":
            operation = arguments.get("operation")
            if operation == "enroll":
                result = await hubspot_service.enroll_sequence(arguments.get("sequence_id"), arguments.get("contact_id"), arguments.get("user_id"))
                return {
                    "success": result.get("success", False),
                    "result": result.get("message", "Sequence enrolled successfully"),
                    "data": result
                }
            elif operation == "read_enrollment":
                result = await hubspot_service.get_sequence_enrollment(arguments.get("contact_id"))
                return {
                    "success": result.get("success", False),
                    "result": result.get("message", "Enrollment retrieved successfully"),
                    "data": result
                }
            return {"success": False, "error": f"Unknown operation: {operation}"}

        elif tool_name == "hubspot_email_templates":
            operation = arguments.get("operation")
            if operation == "create":
                result = await hubspot_service.create_email_template(arguments.get("name"), arguments.get("subject"), arguments.get("html_content"))
                return {
                    "success": result.get("success", False),
                    "result": result.get("message", "Email template created successfully"),
                    "data": result
                }
            return {"success": False, "error": f"Unknown operation: {operation}"}

        elif tool_name == "hubspot_deal_management":
            operation = arguments.get("operation")
            if operation == "create":
                result = await hubspot_service.create_deal(**arguments.get("deal_data", {}))
                return {"success": result.get("success", False), "result": "Deal created", "data": result}
            elif operation == "read":
                result = await hubspot_service.get_deals(limit=arguments.get("limit", 20))
                return {"success": result.get("success", False), "result": "Deals retrieved", "data": result}
            elif operation == "update":
                result = await hubspot_service.update_deal(arguments.get("deal_id"), arguments.get("properties", {}))
                return {"success": result.get("success", False), "result": "Deal updated", "data": result}
            elif operation == "analyze":
                result = await hubspot_service.analyze_deals(filters=arguments.get("filters", {}))
                return {"success": result.get("success", False), "result": "Deals analyzed", "data": result}
            return {"success": False, "error": f"Unknown operation: {operation}"}

        elif tool_name == "hubspot_analytics":
            result = await hubspot_service.get_analytics(
                start_date=arguments.get("start_date"), 
                end_date=arguments.get("end_date")
            )
            return {
                "success": result.get("success", False),
                "result": "Analytics retrieved successfully",
                "data": result
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
        elif tool_name == "salesforce_general_operations":
            operation = arguments.get("operation")
            object_name = arguments.get("object_name")
            if operation == "create":
                result = await salesforce_service.create_record(object_name, arguments.get("record_data", {}))
                return {
                    "success": result.get("success", False),
                    "result": result.get("message", "Record created successfully"),
                    "data": result
                }
            elif operation == "update":
                result = await salesforce_service.update_record(object_name, arguments.get("record_id"), arguments.get("record_data", {}))
                return {
                    "success": result.get("success", False),
                    "result": result.get("message", "Record updated successfully"),
                    "data": result
                }
            elif operation == "read":
                result = await salesforce_service.get_record(object_name, arguments.get("record_id"))
                return {
                    "success": result.get("success", False),
                    "result": result.get("message", "Record retrieved successfully"),
                    "data": result
                }
            return {"success": False, "error": f"Unknown operation: {operation}"}
        elif tool_name == "salesforce_query":
            operation = arguments.get("operation")
            if operation == "execute_soql":
                result = await salesforce_service.execute_soql_query(arguments.get("query_string"))
                return {
                    "success": result.get("success", False),
                    "result": f"Query returned {len(result.get('records', []))} records",
                    "data": result
                }
            return {"success": False, "error": f"Unknown operation: {operation}"}
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

    async def _execute_zoho_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Zoho-related tools."""
        result = await db.execute(
            select(Connection)
            .filter(
                Connection.user_id == user.id,
                Connection.platform == "zoho",
                Connection.status == ConnectionStatus.ACTIVE
            )
        )
        connection = result.scalar_one_or_none()

        if not connection:
            return {
                "success": False,
                "error": "No active Zoho connection found",
                "result": None
            }

        zoho_service = self.services["zoho"]
        config = connection.config
        
        if config:
            zoho_service.access_token = config.get("access_token")
            zoho_service.api_domain = config.get("api_domain", "https://www.zohoapis.com")
            zoho_service.refresh_token = config.get("refresh_token")

        try:
            if tool_name == "zoho_crm_operations":
                operation = arguments.get("operation")
                if operation == "get_contacts":
                    return await zoho_service.get_contacts(arguments.get("limit", 50), arguments.get("page", 1))
                elif operation == "create_contact":
                    return await zoho_service.create_contact(arguments.get("contact_data", {}))
                elif operation == "get_deals":
                    return await zoho_service.get_deals(arguments.get("limit", 50), arguments.get("page", 1))
                elif operation == "create_deal":
                    return await zoho_service.create_deal(arguments.get("deal_data", {}))
                elif operation == "update_deal_stage":
                    return await zoho_service.update_deal_stage(arguments.get("deal_id", ""), arguments.get("stage", ""))
                else:
                    return {"success": False, "error": f"Unknown Zoho CRM operation: {operation}"}
            
            elif tool_name == "zoho_finance_operations":
                operation = arguments.get("operation")
                org_id = arguments.get("org_id")
                if operation == "create_customer":
                    return await zoho_service.create_customer(arguments.get("customer_data", {}), org_id)
                elif operation == "get_invoices":
                    return await zoho_service.get_invoices(arguments.get("limit", 50), org_id)
                elif operation == "create_invoice":
                    return await zoho_service.create_invoice(arguments.get("invoice_data", {}), org_id)
                elif operation == "record_payment":
                    return await zoho_service.record_payment(arguments.get("payment_data", {}), org_id)
                elif operation == "get_expenses":
                    return await zoho_service.get_expenses(arguments.get("limit", 50), org_id)
                elif operation == "create_expense":
                    return await zoho_service.create_expense(arguments.get("expense_data", {}), org_id)
                else:
                    return {"success": False, "error": f"Unknown Zoho Finance operation: {operation}"}
                    
            elif tool_name == "zoho_desk_operations":
                operation = arguments.get("operation")
                if operation == "get_tickets":
                    return await zoho_service.get_tickets(arguments.get("limit", 50), arguments.get("department_id"))
                elif operation == "create_ticket":
                    return await zoho_service.create_ticket(arguments.get("ticket_data", {}))
                elif operation == "reply_ticket":
                    ticket_id = arguments.get("ticket_id", "")
                    reply_text = arguments.get("reply_text", "")
                    if not ticket_id:
                        return {"success": False, "error": "ticket_id is required"}
                    if not reply_text:
                        return {"success": True, "message": "No reply text provided, skipping reply generation."}
                    return await zoho_service.reply_ticket(ticket_id, reply_text)
                elif operation == "get_articles":
                    return await zoho_service.get_articles(arguments.get("limit", 50), arguments.get("category_id"))
                elif operation == "search_articles":
                    return await zoho_service.search_articles(arguments.get("query", ""))
                elif operation == "create_article":
                    return await zoho_service.create_article(arguments.get("article_data", {}))
                elif operation == "draft_article_from_ticket":
                    kb_autopilot = self.services["kb_autopilot"]
                    kb_autopilot.zoho.access_token = zoho_service.access_token
                    kb_autopilot.zoho.api_domain = zoho_service.api_domain
                    kb_autopilot.zoho.refresh_token = zoho_service.refresh_token
                    return await kb_autopilot.draft_article_from_ticket(arguments.get("ticket_id", ""))
                elif operation == "auto_resolve_ticket":
                    kb_autopilot = self.services["kb_autopilot"]
                    kb_autopilot.zoho.access_token = zoho_service.access_token
                    kb_autopilot.zoho.api_domain = zoho_service.api_domain
                    kb_autopilot.zoho.refresh_token = zoho_service.refresh_token
                    return await kb_autopilot.auto_resolve_ticket(arguments.get("ticket_id", ""))
                elif operation == "analyze_knowledge_gaps":
                    kb_autopilot = self.services["kb_autopilot"]
                    kb_autopilot.zoho.access_token = zoho_service.access_token
                    kb_autopilot.zoho.api_domain = zoho_service.api_domain
                    kb_autopilot.zoho.refresh_token = zoho_service.refresh_token
                    return await kb_autopilot.analyze_knowledge_gaps(arguments.get("department_id"))
                else:
                    return {"success": False, "error": f"Unknown Zoho Desk operation: {operation}"}
                    
            elif tool_name == "zoho_mail_operations":
                return {"success": False, "error": "Zoho Mail operations not fully implemented yet."}
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown Zoho tool: {tool_name}",
                    "result": None
                }
        except Exception as e:
            logger.error(f"Error executing Zoho tool {tool_name}: {str(e)}")
            return {
                "success": False,
                "error": f"Zoho error: {str(e)}",
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

        if tool_name in ("whatsapp_messaging", "whatsapp_send_message"):
            action = arguments.get("action", arguments.get("operation", "send_message"))
            to_number = arguments.get("to_number", "")

            if action == "send_message":
                message = arguments.get("message", "")
                if not to_number or not message:
                    return {
                        "success": False,
                        "error": "Phone number and message are required",
                        "result": None
                    }

                # ── Smart Image Dispatcher ──────────────────────────
                # Detect image URLs in the message text and send them
                # as native WhatsApp image messages for full previews.
                from .conversational_agent_service import extract_image_urls, strip_image_urls

                # Prefer explicit image_urls from upstream (e.g. conversational agent)
                image_urls = arguments.get("image_urls", [])
                if not image_urls:
                    image_urls = extract_image_urls(message)

                # Strip image URLs from text so the text message is clean
                clean_message = strip_image_urls(message, image_urls) if image_urls else message

                # 1) Send text message first (if any text remains after stripping)
                text_result = None
                if clean_message.strip():
                    text_result = await whatsapp_service.send_message(
                        to_number, clean_message
                    )

                # 2) Send each image as a native WhatsApp image message
                media_results = []
                for img_url in image_urls:
                    try:
                        media_res = await whatsapp_service.send_media_message(
                            to_number=to_number,
                            media_url=img_url,
                            media_type="image",
                            caption=""
                        )
                        media_results.append({"url": img_url, "result": media_res})
                        logger.info(f"[WA_SMART_DISPATCH] Sent image to {to_number}: {img_url[:80]}")
                    except Exception as img_err:
                        logger.warning(f"[WA_SMART_DISPATCH] Failed to send image {img_url[:80]}: {img_err}")
                        media_results.append({"url": img_url, "error": str(img_err)})

                images_sent = len([r for r in media_results if "result" in r])
                result_summary = f"Message sent to {to_number}"
                if images_sent:
                    result_summary += f" + {images_sent} image(s) sent as media"

                return {
                    "success": True,
                    "result": result_summary,
                    "data": text_result,
                    "images_sent": images_sent,
                    "media_results": media_results,
                    "processed_arguments": {
                        "to_number": to_number,
                        "message": clean_message,
                        "image_urls": image_urls
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
            
            # Get refresh token for auto-refresh capability
            refresh_token = connection.config.get("refresh_token")
            
            # ===== AUTO TOKEN REFRESH WRAPPER =====
            async def execute_with_token_refresh(func, *args, **kwargs):
                """Execute Asana function with automatic token refresh on expiration."""
                # First attempt
                res = await func(*args, **kwargs)
                
                # Check for token expiration errors
                error_msg = str(res.get("error", ""))
                is_token_expired = (
                    not res.get("success") and 
                    ("expired" in error_msg.lower() or "401" in error_msg or "bearer token" in error_msg.lower())
                )
                
                if is_token_expired and refresh_token:
                    logger.info(f"Asana token expired for user {user.id}. Attempting refresh...")
                    try:
                        # Refresh the token
                        new_tokens = await asana_service.refresh_access_token(refresh_token)
                        new_access_token = new_tokens.get("access_token")
                        new_refresh_token = new_tokens.get("refresh_token")
                        
                        if new_access_token:
                            # Update DB connection config
                            config_update = connection.config.copy()
                            config_update["access_token"] = new_access_token
                            if new_refresh_token:
                                config_update["refresh_token"] = new_refresh_token
                            
                            connection.config = config_update
                            from sqlalchemy.orm.attributes import flag_modified
                            flag_modified(connection, "config")
                            await db.commit()
                            logger.info(f"Asana token refreshed and saved for user {user.id}")
                            
                            # Re-initialize the service with new token
                            asana_service.access_token = new_access_token
                            asana_service._initialized = True
                            
                            # Retry the operation
                            return await func(*args, **kwargs)
                        else:
                            logger.error("Token refresh returned no access_token")
                    except Exception as e:
                        logger.error(f"Failed to refresh Asana token: {e}")
                        # Return user-friendly error for reconnection
                        return {
                            "success": False,
                            "error": "Asana token expired. Please reconnect your Asana account in Settings > Connections."
                        }
                
                return res
            # ===== END TOKEN REFRESH WRAPPER =====
            
            # Route to specific Asana tool (with auto-refresh)
            if tool_name == "asana_create_project":
                return await execute_with_token_refresh(
                    self._execute_asana_create_project, arguments, asana_service, connection
                )
            elif tool_name == "asana_list_projects":
                return await execute_with_token_refresh(
                    self._execute_asana_list_projects, arguments, asana_service, connection
                )
            elif tool_name == "asana_create_task":
                return await execute_with_token_refresh(
                    self._execute_asana_create_task, arguments, asana_service, connection
                )
            elif tool_name == "asana_list_tasks":
                return await execute_with_token_refresh(
                    self._execute_asana_list_tasks, arguments, asana_service, connection
                )
            elif tool_name == "asana_add_comment":
                return await execute_with_token_refresh(
                    self._execute_asana_add_comment, arguments, asana_service, connection
                )
            elif tool_name == "asana_get_teams":
                return await execute_with_token_refresh(
                    self._execute_asana_get_teams, arguments, asana_service, connection
                )
            elif tool_name == "asana_get_workspaces":
                return await execute_with_token_refresh(
                    self._execute_asana_get_workspaces, arguments, asana_service, connection
                )
            elif tool_name == "asana_get_users":
                return await execute_with_token_refresh(
                    self._execute_asana_get_users, arguments, asana_service, connection
                )
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
    


    async def _execute_google_workspace_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Google Workspace tools."""
        try:
            # Get user's Google Workspace connection
            result = await db.execute(
                select(Connection)
                .filter(
                    Connection.user_id == user.id,
                    Connection.platform == "google_workspace",
                    Connection.status == ConnectionStatus.ACTIVE
                )
            )
            connection = result.scalars().first()
            
            if not connection:
                return {
                    "success": False,
                    "error": "No active Google Workspace connection found. Please connect your Google Workspace account first."
                }
            
            # Get OAuth credentials from connection
            client_id = connection.config.get("client_id")
            client_secret = connection.config.get("client_secret")
            refresh_token = connection.config.get("refresh_token")
            
            if not all([client_id, client_secret, refresh_token]):
                return {
                    "success": False,
                    "error": "Incomplete Google Workspace credentials in connection"
                }
            
            # Initialize base client
            credentials_data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "access_token": connection.config.get("access_token"),
                "scopes": connection.config.get("scopes")
            }
            base_client = GoogleWorkspaceBaseClient(credentials_data)
            
            # Check for token refresh and persist if changed
            try:
                if base_client.refresh_token_if_needed():
                    updated_creds = base_client.get_updated_credentials()
                    # Check if access token changed
                    if updated_creds.get("access_token") != connection.config.get("access_token"):
                        # Update connection config with new credentials
                        new_config = dict(connection.config)
                        new_config.update(updated_creds)
                        connection.config = new_config
                        await db.commit()
                        await db.refresh(connection)
            except Exception as e:
                # Log error but proceed; tool execution specific errors will be caught later
                if 'logger' in locals() or 'logger' in globals():
                    logger.warning(f"Error persisting Google Workspace token: {e}")
            
            operation = arguments.get("operation")
            
            # Route to appropriate service based on tool name
            if tool_name == "google_workspace_gmail":
                service = GmailService(base_client)
                
                if operation == "send_email":
                    return await service.send_email(
                        to=arguments.get("to"),
                        subject=arguments.get("subject"),
                        body=arguments.get("body"),
                        cc=arguments.get("cc"),
                        bcc=arguments.get("bcc"),
                        attachments=arguments.get("attachments"),
                        html=arguments.get("html", False)
                    )
                elif operation == "read_emails":
                    return await service.read_emails(
                        max_results=arguments.get("max_results", 10),
                        label_ids=arguments.get("label_ids"),
                        query=arguments.get("query")
                    )
                elif operation == "search_emails":
                    return await service.search_emails(
                        query=arguments.get("query"),
                        max_results=arguments.get("max_results", 50)
                    )
                elif operation == "create_label":
                    return await service.create_label(
                        name=arguments.get("label_name")
                    )
                elif operation == "apply_label":
                    return await service.apply_label(
                        message_ids=arguments.get("message_ids"),
                        label_ids=arguments.get("label_ids")
                    )
                elif operation == "create_draft":
                    return await service.create_draft(
                        to=arguments.get("to"),
                        subject=arguments.get("subject"),
                        body=arguments.get("body"),
                        cc=arguments.get("cc"),
                        html=arguments.get("html", False)
                    )
                elif operation == "delete_email":
                    return await service.delete_email(
                        message_id=arguments.get("message_id"),
                        permanent=arguments.get("permanent", False)
                    )
                elif operation == "get_email_details":
                    return await service.get_email_details(
                        message_id=arguments.get("message_id")
                    )
                elif operation == "watch_inbox":
                    return await service.watch_inbox(
                        topic_name=arguments.get("topic_name"),
                        label_ids=arguments.get("label_ids", ["INBOX"]),
                        label_filter_action=arguments.get("label_filter_action", "include")
                    )
                elif operation == "stop_watch":
                    return await service.stop_watch()
                elif operation == "mark_as_read":
                    return await service.mark_as_read(
                        message_ids=arguments.get("message_ids")
                    )
            
            elif tool_name == "google_workspace_calendar":
                service = CalendarService(base_client)
                
                if operation == "create_event":
                    return await service.create_event(
                        summary=arguments.get("summary"),
                        start_time=arguments.get("start_time"),
                        end_time=arguments.get("end_time"),
                        description=arguments.get("description"),
                        location=arguments.get("location"),
                        attendees=arguments.get("attendees"),
                        timezone=arguments.get("timezone", "Africa/Nairobi")
                    )
                elif operation == "list_events":
                    return await service.list_events(
                        time_min=arguments.get("time_min"),
                        time_max=arguments.get("time_max"),
                        max_results=arguments.get("max_results", 10)
                    )
                elif operation == "update_event":
                    return await service.update_event(
                        event_id=arguments.get("event_id"),
                        summary=arguments.get("summary"),
                        start_time=arguments.get("start_time"),
                        end_time=arguments.get("end_time"),
                        description=arguments.get("description"),
                        location=arguments.get("location")
                    )
                elif operation == "delete_event":
                    return await service.delete_event(
                        event_id=arguments.get("event_id")
                    )
                elif operation == "check_availability":
                    return await service.check_availability(
                        time_min=arguments.get("time_min"),
                        time_max=arguments.get("time_max"),
                        attendees=arguments.get("attendees")
                    )
                elif operation == "create_meeting":
                    return await service.create_meeting(
                        summary=arguments.get("summary"),
                        start_time=arguments.get("start_time"),
                        end_time=arguments.get("end_time"),
                        attendees=arguments.get("attendees"),
                        description=arguments.get("description")
                    )
            
            elif tool_name == "google_workspace_drive":
                service = DriveService(base_client)
                
                if operation == "upload_file":
                    # Convert content string to bytes if needed
                    content = arguments.get("content")
                    if isinstance(content, str):
                        content = content.encode("utf-8")
                    return await service.upload_file(
                        filename=arguments.get("filename"),
                        content=content,
                        mime_type=arguments.get("mime_type", "application/octet-stream"),
                        folder_id=arguments.get("folder_id")
                    )
                elif operation == "download_file":
                    return await service.download_file(
                        file_id=arguments.get("file_id")
                    )
                elif operation == "list_files":
                    return await service.list_files(
                        folder_id=arguments.get("folder_id"),
                        query=arguments.get("query"),
                        max_results=arguments.get("max_results", 100)
                    )
                elif operation == "create_folder":
                    return await service.create_folder(
                        name=arguments.get("filename"),
                        parent_folder_id=arguments.get("folder_id")
                    )
                elif operation == "delete_file":
                    return await service.delete_file(
                        file_id=arguments.get("file_id")
                    )
                elif operation == "share_file":
                    return await service.share_file(
                        file_id=arguments.get("file_id"),
                        email=arguments.get("email"),
                        role=arguments.get("role", "reader")
                    )
                elif operation == "search_files":
                    return await service.search_files(
                        query=arguments.get("query"),
                        max_results=arguments.get("max_results", 50)
                    )
                elif operation == "get_metadata":
                    return await service.get_file_metadata(
                        file_id=arguments.get("file_id")
                    )
                elif operation == "move_file":
                    return await service.move_file(
                        file_id=arguments.get("file_id"),
                        target_folder_id=arguments.get("folder_id")
                    )
                elif operation == "list_folders":
                    return await service.list_folders()
                elif operation == "list_spreadsheets":
                    return await service.list_spreadsheets()
            
            elif tool_name == "google_workspace_sheets":
                service = SheetsService(base_client)
                
                if operation == "create_spreadsheet":
                    return await service.create_spreadsheet(
                        title=arguments.get("title"),
                        sheets=arguments.get("sheets")
                    )
                elif operation == "read_range":
                    return await service.read_range(
                        spreadsheet_id=arguments.get("spreadsheet_id"),
                        range_name=arguments.get("range_name")
                    )
                elif operation == "write_range":
                    return await service.write_range(
                        spreadsheet_id=arguments.get("spreadsheet_id"),
                        range_name=arguments.get("range_name"),
                        values=arguments.get("values"),
                        value_input_option=arguments.get("value_input_option", "USER_ENTERED")
                    )
                elif operation == "append_rows":
                    return await service.append_rows(
                        spreadsheet_id=arguments.get("spreadsheet_id"),
                        range_name=arguments.get("range_name"),
                        values=arguments.get("values")
                    )
                elif operation == "clear_range":
                    return await service.clear_range(
                        spreadsheet_id=arguments.get("spreadsheet_id"),
                        range_name=arguments.get("range_name")
                    )
                elif operation == "batch_update":
                    return await service.batch_update(
                        spreadsheet_id=arguments.get("spreadsheet_id"),
                        requests=arguments.get("requests")
                    )
                elif operation == "get_info":
                    return await service.get_spreadsheet_info(
                        spreadsheet_id=arguments.get("spreadsheet_id")
                    )
            
            elif tool_name == "google_workspace_docs":
                service = DocsService(base_client)
                
                if operation == "create_document":
                    return await service.create_document(
                        title=arguments.get("title")
                    )
                elif operation == "read_document":
                    return await service.read_document(
                        document_id=arguments.get("document_id")
                    )
                elif operation == "read_all_documents":
                    return await service.read_all_documents(
                        folder_id=arguments.get("folder_id"),
                        query=arguments.get("query")
                    )
                elif operation == "insert_text":
                    return await service.insert_text(
                        document_id=arguments.get("document_id"),
                        text=arguments.get("text"),
                        index=arguments.get("index", 1)
                    )
                elif operation == "append_text":
                    return await service.append_text(
                        document_id=arguments.get("document_id"),
                        text=arguments.get("text")
                    )
                elif operation == "replace_text":
                    return await service.replace_text(
                        document_id=arguments.get("document_id"),
                        find_text=arguments.get("find_text"),
                        replace_text=arguments.get("replace_text"),
                        match_case=arguments.get("match_case", False)
                    )
                elif operation == "format_text":
                    return await service.format_text(
                        document_id=arguments.get("document_id"),
                        start_index=arguments.get("start_index"),
                        end_index=arguments.get("end_index"),
                        bold=arguments.get("bold"),
                        italic=arguments.get("italic"),
                        font_size=arguments.get("font_size"),
                        foreground_color=arguments.get("foreground_color")
                    )
                elif operation == "insert_table":
                    return await service.insert_table(
                        document_id=arguments.get("document_id"),
                        rows=arguments.get("rows"),
                        columns=arguments.get("columns"),
                        index=arguments.get("index", 1)
                    )
                elif operation == "batch_update":
                    return await service.batch_update(
                        document_id=arguments.get("document_id"),
                        requests=arguments.get("requests")
                    )
                elif operation == "export_pdf":
                    return await service.export_as_pdf(
                        document_id=arguments.get("document_id")
                    )

            elif tool_name == "google_workspace_analytics":
                service = AnalyticsService(base_client)
                # Use configured default property ID if not provided in arguments
                property_id = arguments.get("property_id") or connection.config.get("default_property_id")
                
                if operation == "get_traffic":
                    return await service.get_traffic(
                        property_id=property_id,
                        hours=arguments.get("hours", 24)
                    )
                elif operation == "get_conversions":
                    return await service.get_conversions(
                        property_id=property_id,
                        hours=arguments.get("hours", 24),
                        conversion_events=arguments.get("conversion_events")
                    )
                elif operation == "get_user_behavior":
                    return await service.get_user_behavior(
                        property_id=property_id,
                        hours=arguments.get("hours", 24),
                        user_segments=arguments.get("user_segments"),
                        engagement_metrics=arguments.get("engagement_metrics")
                    )
                elif operation == "get_custom_report":
                    return await service.get_custom_report(
                        property_id=property_id,
                        metrics=arguments.get("metrics"),
                        dimensions=arguments.get("dimensions"),
                        filters=arguments.get("filters")
                    )
                elif operation == "get_ecommerce_data":
                    return await service.get_ecommerce_data(
                        property_id=property_id,
                        hours=arguments.get("hours", 24)
                    )
            
            return {
                "success": False,
                "error": f"Unknown Google Workspace tool or operation: {tool_name} - {operation}"
            }
        
        except Exception as e:
            logger.error(f"Error executing Google Workspace tool {tool_name}: {e}")
            return {
                "success": False,
                "error": f"Google Workspace tool execution failed: {str(e)}"
            }

    async def _execute_email_template_tool(
        self,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute email template operations for the auto-responder workflow."""
        try:
            operation = arguments.get("operation")

            if operation == "get_template":
                return await email_template_service.get_template(
                    category=arguments.get("category", "general")
                )
            elif operation == "list_templates":
                return await email_template_service.list_templates()
            elif operation == "create_template":
                return await email_template_service.create_template(
                    category=arguments.get("category"),
                    body=arguments.get("body"),
                    subject_prefix=arguments.get("subject_prefix", "Re: "),
                    priority=arguments.get("priority", "medium")
                )
            elif operation == "delete_template":
                return await email_template_service.delete_template(
                    category=arguments.get("category")
                )
            elif operation == "render_template":
                return await email_template_service.render_template(
                    category=arguments.get("category", "general"),
                    variables=arguments.get("variables", {})
                )
            else:
                return {
                    "success": False,
                    "error": f"Unknown email template operation: {operation}"
                }
        except Exception as e:
            logger.error(f"Error executing email template tool: {e}")
            return {
                "success": False,
                "error": f"Email template tool execution failed: {str(e)}"
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

            # Support 'projects' list or single 'project_id'
            projects = arguments.get("projects")
            if not projects and project_id:
                projects = [project_id]

            result = await asana_service.create_task(
                name=name,
                notes=notes,
                workspace_id=workspace_id,
                projects=projects,
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

            opt_fields = arguments.get("opt_fields")
            
            # Ensure we have workspace_id for task listing
            if not workspace_id:
                # Try to get workspace_id from the service's initialized config
                if asana_service.workspace_id:
                    workspace_id = asana_service.workspace_id
                else:
                    # improved fallback: try to fetch user's workspaces and use the first one
                    debug_info = "No attempts made"
                    try:
                        workspaces_result = await asana_service.get_workspaces()
                        debug_info = f"Fetch result: {workspaces_result}"
                        
                        if workspaces_result.get("success"):
                            workspaces_data = workspaces_result.get("data")
                            workspaces_list = []

                            if isinstance(workspaces_data, list):
                                workspaces_list = workspaces_data
                            elif isinstance(workspaces_data, dict) and "data" in workspaces_data:
                                workspaces_list = workspaces_data.get("data")
                            
                            if workspaces_list and isinstance(workspaces_list, list) and len(workspaces_list) > 0:
                                workspace_id = workspaces_list[0].get("gid")
                                logger.info(f"Auto-selected workspace {workspace_id} for task listing")
                            else:
                                debug_info += f", No workspaces found (parsed list: {workspaces_list})"
                    except Exception as ws_e:
                        logger.warning(f"Failed to auto-fetch workspaces: {ws_e}")
                        debug_info = f"Exception: {repr(ws_e)}"

                    if not workspace_id:
                        return {
                            "success": False,
                            "error": f"workspace_id is required for task listing. Please ensure your Asana connection includes a workspace_id. Debug: {debug_info}"
                        }

            # Asana requires either project, tag, section, or (assignee + workspace)
            if not project_id and not assignee:
                assignee = "me"

            result = await asana_service.list_tasks(
                workspace_id=workspace_id,
                project_id=project_id,
                assignee=assignee,
                opt_fields=opt_fields,
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

    async def _execute_asana_get_users(
        self,
        arguments: Dict[str, Any],
        asana_service: AsanaService,
        connection: Connection
    ) -> Dict[str, Any]:
        """Execute Asana get users tool."""
        workspace_id = arguments.get("workspace_id")
        team_id = arguments.get("team_id")
        
        result = await asana_service.get_users(workspace_id, team_id)
        
        users = result.get("data", [])
        return {
            "success": result.get("success", False),
            "result": f"Found {len(users)} users",
            "data": result
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

    async def _execute_web_search_tool(self, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute web search using DuckDuckGo."""
        try:
            from .web_tools_service import web_tools_service
            
            query = arguments.get("query")
            if not query:
                return {
                    "success": False,
                    "error": "Missing required 'query' parameter for web search"
                }
                
            max_results = arguments.get("max_results", 5)
            
            return await web_tools_service.perform_web_search(
                query=query, 
                max_results=max_results
            )
            
        except Exception as e:
            logger.error(f"Error executing web search: {e}")
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
            
            elif operation == "generate":
                # LLM-powered text generation (used by RAG pipelines and general workflows)
                # Accept multiple parameter name conventions for the prompt
                prompt = (
                    arguments.get("prompt")
                    or arguments.get("question")
                    or arguments.get("text")
                    or arguments.get("customer_question")
                    or ""
                )
                if not prompt:
                    return {
                        "success": False,
                        "error": "Missing required 'prompt' (or 'question'/'text') parameter for text generation."
                    }

                # Build context string from various possible sources
                context = arguments.get("context", "")

                # If context looks like a list of KB results, flatten to readable text
                if isinstance(context, list):
                    context_parts = []
                    for i, item in enumerate(context, 1):
                        if isinstance(item, dict):
                            text = item.get("text", item.get("content", str(item)))
                            source = item.get("source", item.get("file", ""))
                            score = item.get("score", "")
                            header = f"[Source {i}]"
                            if source:
                                header += f" ({source})"
                            if score:
                                header += f" [score: {score}]"
                            context_parts.append(f"{header}\n{text}")
                        else:
                            context_parts.append(str(item))
                    context = "\n\n---\n\n".join(context_parts)
                elif isinstance(context, dict):
                    # Handle dict context (e.g. raw step_1 output)
                    results = context.get("results", context.get("data", []))
                    if isinstance(results, list) and results:
                        context_parts = []
                        for i, item in enumerate(results, 1):
                            if isinstance(item, dict):
                                text = item.get("text", item.get("content", str(item)))
                                source = item.get("source", "")
                                context_parts.append(f"[Source {i}] ({source})\n{text}")
                            else:
                                context_parts.append(str(item))
                        context = "\n\n---\n\n".join(context_parts)
                    else:
                        context = str(context)

                max_tokens = int(arguments.get("max_tokens", 500))
                system_prompt = arguments.get("system_prompt", "")
                temperature = float(arguments.get("temperature", 0.3))

                return await content_creation_service.generate_text(
                    prompt=prompt,
                    context=context,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                    temperature=temperature,
                )

            else:
                return {
                    "success": False,
                    "error": f"Unknown content creation operation: {operation}"
                }
        except Exception as e:
            logger.error(f"Error executing content creation tool: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_ai_text_generation_tool(self, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute AI Text Generation tool — the workflow 'Brain'.
        
        Supports operations: generate, summarize, classify, extract, translate.
        All operations route through content_creation_service.generate_text() which
        calls llm_service.chat_completion() under the hood.
        
        When a session_key is provided (from WhatsApp/Telegram triggers), the
        generate_text() call will load conversation history from the CCM and
        inject it into the LLM messages for multi-turn context.
        """
        try:
            from .content_creation_service import content_creation_service

            operation = arguments.get("operation", "generate")

            # ── Resolve prompt (accept multiple naming conventions) ──
            prompt = (
                arguments.get("prompt")
                or arguments.get("question")
                or arguments.get("text")
                or arguments.get("message")
                or arguments.get("input")
                or ""
            )
            if not prompt:
                return {
                    "success": False,
                    "error": "Missing required 'prompt' parameter. Provide the text or question for the AI to process."
                }

            # ── Flatten context from previous steps ──
            context = arguments.get("context", "")

            if isinstance(context, list):
                context_parts = []
                for i, item in enumerate(context, 1):
                    if isinstance(item, dict):
                        text = item.get("text", item.get("content", str(item)))
                        source = item.get("source", item.get("file", ""))
                        score = item.get("score", "")
                        header = f"[Source {i}]"
                        if source:
                            header += f" ({source})"
                        if score:
                            header += f" [relevance: {score}]"
                        context_parts.append(f"{header}\n{text}")
                    else:
                        context_parts.append(str(item))
                context = "\n\n---\n\n".join(context_parts)
            elif isinstance(context, dict):
                # Handle raw step output (e.g. {{step_1}} which is the full result dict)
                results = context.get("results", context.get("data", context.get("result", [])))
                if isinstance(results, list) and results:
                    context_parts = []
                    for i, item in enumerate(results, 1):
                        if isinstance(item, dict):
                            text = item.get("text", item.get("content", str(item)))
                            source = item.get("source", "")
                            context_parts.append(f"[Source {i}] ({source})\n{text}")
                        else:
                            context_parts.append(str(item))
                    context = "\n\n---\n\n".join(context_parts)
                elif isinstance(results, str):
                    context = results
                else:
                    # Fallback: serialize the whole dict
                    import json as _json
                    try:
                        context = _json.dumps(context, indent=2, default=str)
                    except Exception:
                        context = str(context)

            # ── Extract session_key for CCM context (from trigger input_data) ──
            session_key = arguments.get("session_key", "")

            # ── Build operation-specific system prompts (if user didn't provide one) ──
            system_prompt = arguments.get("system_prompt", "")

            if not system_prompt:
                if operation == "generate":
                    system_prompt = (
                        "You are a helpful AI assistant. Answer the user's question "
                        "accurately and concisely using the provided context. "
                    )
                    if session_key:
                        system_prompt += "You must also use the conversation history to understand context and answer follow-up questions. "
                    system_prompt += (
                        "If the context and history do not contain enough information, say so clearly. "
                        "Do not make up information."
                    )
                elif operation == "summarize":
                    system_prompt = (
                        "You are a summarization expert. Provide a clear, concise summary "
                        "of the provided context. Highlight the most important points. "
                        "Keep the summary brief but comprehensive."
                    )
                elif operation == "classify":
                    system_prompt = (
                        "You are a text classification expert. Analyze the provided text "
                        "and classify it into the most appropriate category. "
                        "Respond with ONLY the category name unless additional context is requested."
                    )
                elif operation == "extract":
                    system_prompt = (
                        "You are a data extraction expert. Extract the requested information "
                        "from the provided context. Return the extracted data in a structured, "
                        "clear format. If the information is not found, say so."
                    )
                elif operation == "translate":
                    target_lang = arguments.get("target_language", "English")
                    system_prompt = (
                        f"You are a professional translator. Translate the provided text "
                        f"into {target_lang}. Maintain the original meaning, tone, and formatting. "
                        f"Provide ONLY the translation without explanations."
                    )

            # ── Call the LLM ──
            max_tokens = int(arguments.get("max_tokens", 500))
            temperature = float(arguments.get("temperature", 0.3))

            result = await content_creation_service.generate_text(
                prompt=prompt,
                context=context,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                temperature=temperature,
                session_key=session_key,
            )

            # Add operation metadata to the result
            if result.get("success"):
                result["operation"] = operation
                result["tool"] = "ai_text_generation"

            return result

        except Exception as e:
            logger.error(f"Error executing AI text generation tool: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_workflow_management_tool(
        self,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute workflow management tools."""
        return await self.services["workflow"].execute_tool(arguments, user, db)

    async def _execute_kra_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute KRA-related tools."""
        kra_service = self.services["kra"]
        operation = arguments.get("operation")
        
        if tool_name == "kra_pin_checker" or operation == "check_pin":
            pin = arguments.get("pin")
            if not pin:
                return {"success": False, "error": "PIN is required"}
            return await kra_service.check_pin(pin)
            
        elif tool_name == "kra_id_checker" or operation == "check_id":
            id_number = arguments.get("id_number")
            if not id_number:
                return {"success": False, "error": "ID Number is required"}
            return await kra_service.get_pin_by_id(id_number)
            
        elif tool_name == "kra_nil_return" or operation == "file_nil_return":
            pin = arguments.get("pin")
            tax_obligation = arguments.get("tax_obligation", "Income Tax - Resident Individual")
            period_from = arguments.get("period_from")
            period_to = arguments.get("period_to")
            
            if not all([pin, period_from, period_to]):
                return {"success": False, "error": "PIN, period_from, and period_to are required"}
                
            return await kra_service.file_nil_return(pin, tax_obligation, period_from, period_to)
            
        else:
             return {"success": False, "error": f"Unknown KRA operation: {operation}"}

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
                payment_list: List[Dict[str, Any]] = []
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



    async def _execute_clickup_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute ClickUp tools."""
        try:
            # Get user's ClickUp connection
            # We don't have the Connection model imported here usually with enough context, 
            # but we can query it.
            # Assuming 'connection' logic is similar to slack.
            
            result = await db.execute(
                select(Connection)
                .filter(
                    Connection.user_id == user.id,
                    Connection.platform == "clickup",
                    Connection.status == ConnectionStatus.ACTIVE
                )
            )
            connection = result.scalar_one_or_none()
            
            if not connection:
                return {
                    "success": False,
                    "error": "No active ClickUp connection found. Please connect ClickUp in Settings > Connections.",
                    "result": None
                }
            
            access_token = connection.config.get("access_token")
            if not access_token:
                 return {
                    "success": False,
                    "error": "ClickUp connection is missing access token. Please reconnect.",
                    "result": None
                }

            clickup_service = ClickUpService()
            operation = arguments.get("operation")
            
            if tool_name == "clickup_resource_management":
                if operation == "get_spaces":
                    team_id = arguments.get("team_id")
                    if not team_id:
                        teams = connection.config.get("teams", [])
                        if teams:
                            team_id = teams[0].get("id")
                    return await clickup_service.get_spaces(access_token, team_id)
                elif operation == "get_folders":
                    return await clickup_service.get_folders(access_token, arguments.get("space_id"))
                elif operation == "get_lists":
                    return await clickup_service.get_lists(access_token, arguments.get("folder_id"))
                elif operation == "get_folderless_lists":
                    return await clickup_service.get_folderless_lists(access_token, arguments.get("space_id"))
            
            elif tool_name == "clickup_task_management":
                if operation == "create_task":
                    return await clickup_service.create_task(
                        access_token,
                        arguments.get("list_id"),
                        arguments.get("name"),
                        arguments.get("description"),
                        arguments.get("assignees"),
                        arguments.get("priority"),
                        arguments.get("due_date"),
                        arguments.get("start_date")
                    )
                elif operation == "update_task":
                    # ClickUp requires assignees in {add: [...], rem: [...]} format for updates
                    raw_assignees = arguments.get("assignees")
                    formatted_assignees = None
                    if raw_assignees:
                        # If already in dict format with add/rem keys, use as-is
                        if isinstance(raw_assignees, dict) and ("add" in raw_assignees or "rem" in raw_assignees):
                            formatted_assignees = raw_assignees
                        # If it's a list, convert to {add: [...]} format
                        elif isinstance(raw_assignees, list):
                            formatted_assignees = {"add": raw_assignees}
                    
                    return await clickup_service.update_task(
                        access_token,
                        arguments.get("task_id"),
                        arguments.get("status"),
                        arguments.get("name"),
                        arguments.get("description"),
                        arguments.get("due_date"),
                        arguments.get("start_date"),
                        formatted_assignees,
                        arguments.get("priority")
                    )
                elif operation == "get_tasks":
                    return await clickup_service.get_tasks(
                        access_token,
                        arguments.get("list_id"),
                        arguments.get("include_closed", False)
                    )
                elif operation == "get_team_tasks":
                    team_id = arguments.get("team_id")
                    if not team_id:
                         teams = connection.config.get("teams", [])
                         if teams:
                             team_id = teams[0].get("id")
                    return await clickup_service.get_team_tasks(
                        access_token,
                        team_id,
                        arguments.get("assignee_id"),
                        arguments.get("include_closed", False)
                    )
                elif operation == "get_teams":
                    return await clickup_service.get_teams(access_token)
                elif operation == "get_team_members":
                    team_id = arguments.get("team_id")
                    if not team_id:
                         # Default to first team if not provided
                         teams_res = await clickup_service.get_teams(access_token)
                         if teams_res.get("success") and teams_res.get("data", {}).get("teams"):
                             team_id = teams_res.get("data", {}).get("teams")[0].get("id")
                    
                    if not team_id:
                        return {"success": False, "error": "Team ID required or could not be determined"}
                        
                    return await clickup_service.get_team_members(access_token, team_id)
                else:
                    return {"success": False, "error": f"Unsupported operation: {operation}"}
            
            return {"success": False, "error": f"Unknown ClickUp tool: {tool_name}"}
            
        except Exception as e:
            logger.error(f"Error executing ClickUp tool: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_kra_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute KRA-related tools."""
        try:
            kra_service = self.services["kra"]
            
            # Get user's KRA connection to retrieve the PIN
            result = await db.execute(
                select(Connection)
                .filter(
                    Connection.user_id == user.id,
                    Connection.platform == "kra_portal",
                    Connection.status == ConnectionStatus.ACTIVE
                )
            )
            connection = result.scalar_one_or_none()
            
            # PIN can be provided in arguments OR retrieved from connection config
            pin = arguments.get("pin")
            if not pin and connection:
                pin = connection.config.get("pin")
                
            if not pin:
                return {
                    "success": False,
                    "error": "KRA PIN not found. Please connect your KRA account or provide a PIN.",
                    "result": None
                }
                
            if tool_name == "kra_pin_check":
                result = await kra_service.check_pin(pin)
                return {
                    "success": result.get("success", False),
                    "result": f"PIN Verification result for {pin}",
                    "data": result
                }
                
            elif tool_name == "kra_tcc_validator":
                result = await kra_service.validate_tcc(pin)
                return {
                    "success": result.get("success", False),
                    "result": f"TCC Validation result for {pin}",
                    "data": result
                }
                
            elif tool_name == "kra_nil_return_filer":
                result = await kra_service.file_nil_return(pin)
                return {
                    "success": result.get("success", False),
                    "result": f"NIL Return Filing result for {pin}",
                    "data": result
                }
                
            elif tool_name == "kra_eslip_verifier":
                eslip_number = arguments.get("eslip_number")
                if not eslip_number:
                    return {"success": False, "error": "e-Slip number is required"}
                result = await kra_service.verify_eslip(eslip_number)
                return {
                    "success": result.get("success", False),
                    "result": f"e-Slip Verification result for {eslip_number}",
                    "data": result
                }
                
            elif tool_name == "kra_etims_activator":
                result = await kra_service.activate_etims(pin)
                return {
                    "success": result.get("success", False),
                    "result": f"eTIMS Activation result for {pin}",
                    "data": result
                }
                
            return {"success": False, "error": f"Unknown KRA tool: {tool_name}"}
            
        except Exception as e:
            logger.error(f"Error executing KRA tool: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_xero_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Xero-related tools."""
        try:
            result = await db.execute(
                select(Connection)
                .filter(
                    Connection.user_id == user.id,
                    Connection.platform == "xero",
                    Connection.status == ConnectionStatus.ACTIVE
                )
            )
            connection = result.scalar_one_or_none()

            if not connection:
                return {
                    "success": False,
                    "error": "No active Xero connection found. Please connect Xero in Settings > Connections.",
                    "result": None
                }

            config = connection.config or {}
            xero_service = self.services["xero"]
            xero_service._configure_from_connection(config)

            operation = arguments.get("operation")
            if tool_name == "xero_get_company_info":
                return await xero_service.handle_operation("get_company_info", config=config)
            if tool_name == "xero_invoices":
                if operation == "get_invoices":
                    return await xero_service.handle_operation(
                        "get_invoices",
                        config=config,
                        start_date=arguments.get("start_date"),
                        end_date=arguments.get("end_date"),
                        status=arguments.get("status"),
                        contact_id=arguments.get("contact_id") or arguments.get("customer_id"),
                        max_results=arguments.get("max_results", 100),
                    )
                if operation == "create_invoice":
                    return await xero_service.handle_operation(
                        "create_invoice",
                        config=config,
                        customer_id=arguments.get("customer_id"),
                        contact_id=arguments.get("contact_id"),
                        line_items=arguments.get("line_items", []),
                        due_date=arguments.get("due_date"),
                        reference=arguments.get("reference"),
                    )
                return {"success": False, "error": f"Unknown invoices operation: {operation}"}
            if tool_name == "xero_reports":
                if operation == "get_profit_loss":
                    return await xero_service.handle_operation(
                        "get_profit_loss",
                        config=config,
                        start_date=arguments.get("start_date"),
                        end_date=arguments.get("end_date"),
                    )
                if operation == "get_balance_sheet":
                    return await xero_service.handle_operation(
                        "get_balance_sheet",
                        config=config,
                        date=arguments.get("date"),
                    )
                return {"success": False, "error": f"Unknown reports operation: {operation}"}
            if tool_name == "xero_lists":
                if operation == "get_accounts":
                    return await xero_service.handle_operation(
                        "get_accounts",
                        config=config,
                        account_type=arguments.get("account_type"),
                        max_results=arguments.get("max_results", 100),
                    )
                if operation in ("get_customers", "get_contacts"):
                    return await xero_service.handle_operation(
                        "get_contacts",
                        config=config,
                        max_results=arguments.get("max_results", 100),
                    )
                return {"success": False, "error": f"Unknown lists operation: {operation}"}

            return {"success": False, "error": f"Unknown Xero tool: {tool_name}"}
        except Exception as e:
            logger.error(f"Error executing Xero tool: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_system_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute system-related tools."""
        try:
            workflow_service = self.services["workflow"]
            
            if tool_name == "workflow_management":
                operation = arguments.get("operation")
                
                if operation == "create_draft":
                    title = arguments.get("title", "New Workflow")
                    description = arguments.get("description", "")
                    steps = arguments.get("steps", [])
                    return await workflow_service.create_draft_workflow(user.id, title, description, steps, db)
                
                elif operation == "list_workflows":
                    return await workflow_service.list_workflows(user.id, db)
                
                elif operation == "get_workflow":
                    workflow_id = arguments.get("workflow_id")
                    if not workflow_id:
                        return {"success": False, "error": "Workflow ID is required"}
                    return await workflow_service.get_workflow(workflow_id, db)
            
            return {"success": False, "error": f"Unknown system tool: {tool_name}"}
        except Exception as e:
            logger.error(f"Error executing system tool: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_zoho_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Execute Zoho-related tools."""
        try:
            # Get user's Zoho connection
            result = await db.execute(
                select(Connection)
                .filter(
                    Connection.user_id == user.id,
                    Connection.platform == "zoho",
                    Connection.status == ConnectionStatus.ACTIVE
                )
            )
            connection = result.scalar_one_or_none()

            if not connection:
                return {
                    "success": False,
                    "error": "No active Zoho connection found. Please connect your Zoho account first."
                }

            zoho_service = self.services["zoho"]
            if connection.config:
                zoho_service.access_token = connection.config.get("access_token")
                zoho_service.api_domain = connection.config.get("api_domain", "https://www.zohoapis.com")
                zoho_service.refresh_token = connection.config.get("refresh_token")
            
            # The tool_name format is e.g. zoho_crm_operations, zoho_finance_operations
            # We will route to the methods inside zoho_service
            operation = arguments.get("operation")

            if tool_name == "zoho_crm_operations":
                if operation == "get_contacts":
                    result = await zoho_service.get_contacts(arguments.get("per_page", 200), arguments.get("page", 1))
                    if zoho_service.access_token != connection.config.get("access_token"):
                        connection.config["access_token"] = zoho_service.access_token
                        from sqlalchemy.orm.attributes import flag_modified
                        flag_modified(connection, "config")
                        await db.commit()
                    return result
                elif operation == "create_contact":
                    # If passed as single object
                    contact_data = arguments.get("contact_data", {})
                    # If mapped as flat args
                    if not contact_data and arguments.get("last_name"):
                        contact_data = {
                            "Last_Name": arguments.get("last_name"),
                            "First_Name": arguments.get("first_name", ""),
                            "Email": arguments.get("email", ""),
                            "Phone": arguments.get("phone", "")
                        }
                    if not contact_data:
                        return {"success": False, "error": "Contact data is required (must contain at least last_name)"}
                    result = await zoho_service.create_contact(contact_data)
                elif operation == "get_deals":
                    result = await zoho_service.get_deals(arguments.get("per_page", 200), arguments.get("page", 1))
                elif operation == "create_deal":
                    deal_data = arguments.get("deal_data", {})
                    if not deal_data and arguments.get("deal_name"):
                        deal_data = {
                            "Deal_Name": arguments.get("deal_name"),
                            "Amount": arguments.get("amount"),
                            "Closing_Date": arguments.get("closing_date"),
                            "Stage": arguments.get("stage", "Qualification")
                        }
                    if not deal_data:
                        return {"success": False, "error": "Deal data is required"}
                    result = await zoho_service.create_deal(deal_data)
                elif operation == "update_deal_stage":
                    deal_id = arguments.get("deal_id")
                    stage = arguments.get("stage")
                    if not deal_id or not stage:
                        return {"success": False, "error": "Both deal_id and stage are required"}
                    result = await zoho_service.update_deal_stage(deal_id, stage)
                else:
                    return {"success": False, "error": f"Unknown CRM operation: {operation}"}
                
                if zoho_service.access_token != connection.config.get("access_token"):
                    connection.config["access_token"] = zoho_service.access_token
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(connection, "config")
                    await db.commit()
                return result
                    
            elif tool_name == "zoho_finance_operations":
                if operation == "create_customer":
                    customer_data = arguments.get("customer_data", {})
                    if not customer_data and (arguments.get("contact_name") or arguments.get("customer_name")):
                        customer_data = {
                            "contact_name": arguments.get("contact_name") or arguments.get("customer_name"),
                            "company_name": arguments.get("company_name", ""),
                            "email": arguments.get("email", "")
                        }
                    if not customer_data:
                         return {"success": False, "error": "Customer data is required (must contain at least contact_name)"}
                    result = await zoho_service.create_customer(customer_data)
                elif operation == "create_invoice":
                    invoice_data = arguments.get("invoice_data", {})
                    if not invoice_data and arguments.get("customer_id") and arguments.get("items"):
                        invoice_data = {
                            "customer_id": arguments.get("customer_id"),
                            "line_items": arguments.get("items", []),
                            "date": arguments.get("date"),
                            "due_date": arguments.get("due_date", "")
                        }
                    if not invoice_data:
                         return {"success": False, "error": "Invoice data is required"}
                    result = await zoho_service.create_invoice(invoice_data)
                elif operation == "get_invoices":
                    result = await zoho_service.get_invoices(limit=arguments.get("limit", 50))
                elif operation == "record_payment":
                    payment_data = arguments.get("payment_data", {})
                    if not payment_data and arguments.get("invoice_id") and arguments.get("amount"):
                        payment_data = {
                            "invoice_id": arguments.get("invoice_id"),
                            "customer_id": arguments.get("customer_id", ""),
                            "amount": arguments.get("amount"),
                            "date": arguments.get("date"),
                            "payment_mode": arguments.get("payment_mode", "Cash")
                        }
                    if not payment_data:
                        return {"success": False, "error": "Payment data is required (invoice_id and amount)"}
                    result = await zoho_service.record_payment(payment_data)
                elif operation == "create_expense":
                    expense_data = arguments.get("expense_data", {})
                    if not expense_data and arguments.get("amount") and arguments.get("account_id"):
                        expense_data = {
                            "account_id": arguments.get("account_id"),
                            "date": arguments.get("date"),
                            "amount": arguments.get("amount"),
                            "description": arguments.get("description", "")
                        }
                    if not expense_data:
                        return {"success": False, "error": "Expense data is required (amount and account_id)"}
                    result = await zoho_service.create_expense(expense_data)
                elif operation == "get_expenses":
                    result = await zoho_service.get_expenses(limit=arguments.get("limit", 50))
                else:
                    return {"success": False, "error": f"Unknown Finance operation: {operation}"}
                    
                if zoho_service.access_token != connection.config.get("access_token"):
                    connection.config["access_token"] = zoho_service.access_token
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(connection, "config")
                    await db.commit()
                return result
            
            elif tool_name == "zoho_desk_operations":
                if operation == "get_tickets":
                    result = await zoho_service.get_tickets(limit=arguments.get("limit", 50), department_id=arguments.get("department_id", ""))
                elif operation == "create_ticket":
                    ticket_data = arguments.get("ticket_data", {})
                    if not ticket_data and arguments.get("subject") and arguments.get("department_id") and arguments.get("contact_id"):
                        ticket_data = {
                            "departmentId": arguments.get("department_id"),
                            "contactId": arguments.get("contact_id"),
                            "subject": arguments.get("subject"),
                            "description": arguments.get("description", ""),
                            "status": arguments.get("status", "Open")
                        }
                    if not ticket_data:
                        return {"success": False, "error": "Ticket data is required"}
                    result = await zoho_service.create_ticket(ticket_data)
                elif operation == "reply_ticket":
                    ticket_id = arguments.get("ticket_id")
                    reply_text = arguments.get("reply_text")
                    if not ticket_id:
                        return {"success": False, "error": "ticket_id is required"}
                    if not reply_text:
                        # If reply_text is empty, the autonomous agent decided not to reply.
                        # Do not fail the workflow step, just skip it gracefully.
                        return {"success": True, "message": "No reply text provided, skipping reply generation."}
                    result = await zoho_service.reply_ticket(ticket_id, reply_text)
                elif operation == "get_articles":
                    result = await zoho_service.get_articles(limit=arguments.get("limit", 50), category_id=arguments.get("category_id"))
                elif operation == "search_articles":
                    query = arguments.get("query")
                    if not query:
                        return {"success": False, "error": "query is required for search_articles"}
                    result = await zoho_service.search_articles(query)
                elif operation == "create_article":
                    article_data = arguments.get("article_data")
                    if not article_data:
                        return {"success": False, "error": "article_data is required"}
                    result = await zoho_service.create_article(article_data)
                elif operation == "draft_article_from_ticket":
                    ticket_id = arguments.get("ticket_id")
                    if not ticket_id:
                        return {"success": False, "error": "ticket_id is required"}
                    kb_autopilot = self.services["kb_autopilot"]
                    kb_autopilot.zoho = zoho_service # Ensure current token is used
                    result = await kb_autopilot.draft_article_from_ticket(ticket_id)
                elif operation == "analyze_knowledge_gaps":
                    kb_autopilot = self.services["kb_autopilot"]
                    kb_autopilot.zoho = zoho_service
                    result = await kb_autopilot.analyze_knowledge_gaps(department_id=arguments.get("department_id"))
                elif operation == "auto_resolve_ticket":
                    ticket_id = arguments.get("ticket_id")
                    if not ticket_id:
                        return {"success": False, "error": "ticket_id is required"}
                    kb_autopilot = self.services["kb_autopilot"]
                    kb_autopilot.zoho = zoho_service
                    result = await kb_autopilot.auto_resolve_ticket(ticket_id)
                else:
                    return {"success": False, "error": f"Unknown Desk operation: {operation}"}
                
                if zoho_service.access_token != connection.config.get("access_token"):
                    connection.config["access_token"] = zoho_service.access_token
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(connection, "config")
                    await db.commit()
                return result
                    
            elif tool_name == "zoho_mail_operations":
                if operation == "get_messages":
                    result = await zoho_service.get_messages(limit=arguments.get("limit", 20), folder_id=arguments.get("folder_id", ""))
                elif operation == "send_email":
                    to_address = arguments.get("to_address")
                    subject = arguments.get("subject")
                    content = arguments.get("content")
                    if not to_address or not subject or not content:
                        return {"success": False, "error": "to_address, subject, and content are required"}
                    result = await zoho_service.send_email(None, to_address, subject, content)
                else:
                    return {"success": False, "error": f"Unknown Mail operation: {operation}"}
                
                if zoho_service.access_token != connection.config.get("access_token"):
                    connection.config["access_token"] = zoho_service.access_token
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(connection, "config")
                    await db.commit()
                return result
            else:
                return {
                    "success": False,
                    "error": f"Unknown Zoho tool: {tool_name}"
                }

        except Exception as e:
            logger.error(f"Error executing Zoho tool {tool_name}: {e}")
            return {
                "success": False,
                "error": f"Internal error executing Zoho tool: {str(e)}"
            }

    async def _execute_linkedin_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute LinkedIn-related tools."""
        result = await db.execute(
            select(Connection)
            .filter(Connection.user_id == user.id, Connection.platform == "linkedin", Connection.status == ConnectionStatus.ACTIVE)
        )
        connection = result.scalar_one_or_none()

        if not connection:
            return {"success": False, "error": "No active LinkedIn connection found", "result": None}

        from .linkedin_service import LinkedinService
        linkedin_service = LinkedinService()
        linkedin_service.access_token = connection.config.get("access_token")

        if tool_name == "linkedin_network_management":
            operation = arguments.get("operation")
            if operation == "search_people":
                return await linkedin_service.search_people(arguments.get("keywords", ""), arguments.get("limit", 10))
            elif operation == "get_profile":
                return await linkedin_service.get_profile(arguments.get("profile_id", "me"))
            elif operation == "search_companies":
                return await linkedin_service.search_companies(arguments.get("keywords", ""), arguments.get("limit", 10))
            elif operation == "get_company":
                return await linkedin_service.get_company(arguments.get("company_id", ""))
            elif operation == "get_connections":
                return await linkedin_service.get_connections(arguments.get("limit", 50))
            else:
                return {"success": False, "error": f"Unknown LinkedIn operation: {operation}", "result": None}
        elif tool_name == "linkedin_content_management":
            operation = arguments.get("operation", "create_post")
            if operation == "create_post":
                return await linkedin_service.create_post(
                    arguments.get("text", ""),
                    arguments.get("visibility", "PUBLIC")
                )
            else:
                return {"success": False, "error": f"Unknown LinkedIn content operation: {operation}", "result": None}
        elif tool_name == "linkedin_analytics":
            operation = arguments.get("operation", "get_analytics")
            if operation == "get_analytics":
                return await linkedin_service.get_analytics(arguments.get("metric_type", "visitors"))
            else:
                return {"success": False, "error": f"Unknown LinkedIn analytics operation: {operation}", "result": None}
        else:
            return {"success": False, "error": f"Unknown LinkedIn tool: {tool_name}", "result": None}

    async def _execute_airtable_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute Airtable-related tools."""
        result = await db.execute(
            select(Connection)
            .filter(Connection.user_id == user.id, Connection.platform == "airtable", Connection.status == ConnectionStatus.ACTIVE)
        )
        connection = result.scalar_one_or_none()

        if not connection:
            return {"success": False, "error": "No active Airtable connection found", "result": None}

        from .airtable_service import AirtableService
        airtable_service = AirtableService(access_token=connection.config.get("access_token"))
        
        operation = arguments.get("operation")
        base_id = arguments.get("base_id")
        table_name = arguments.get("table_name")

        if tool_name == "airtable_base_management":
            if operation == "list_bases":
                return await airtable_service.list_bases()
            elif operation == "get_base_schema":
                return await airtable_service.get_base_schema(base_id)
            else:
                return {"success": False, "error": f"Unknown Airtable base operation: {operation}"}
        
        elif tool_name == "airtable_record_management":
            if operation == "list_records":
                return await airtable_service.list_records(base_id, table_name, max_records=arguments.get("max_records", 100))
            elif operation == "create_records":
                return await airtable_service.create_records(base_id, table_name, arguments.get("records_data", []))
            elif operation == "update_records":
                return await airtable_service.update_records(base_id, table_name, arguments.get("records_data", []))
            elif operation == "delete_records":
                return await airtable_service.delete_records(base_id, table_name, arguments.get("record_ids", []))
            elif operation == "create_view":
                return await airtable_service.create_view(base_id, table_name, arguments.get("view_name"), arguments.get("view_type", "grid"))
            else:
                return {"success": False, "error": f"Unknown Airtable record operation: {operation}"}
        
        return {"success": False, "error": f"Unknown Airtable tool: {tool_name}", "result": None}

    async def _execute_rag_tool(self, tool_name: str, arguments: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute RAG-related tools with correct signatures."""
        service = self.services["rag"]
        user_id = str(user.id) if user else "internal"
        
        if tool_name == "rag_ingest_content":
            res = await service.rag_ingest_content(
                content=arguments.get("content"),
                kb_id=arguments.get("kb_id"),
                user_id=user_id,
                source_url=arguments.get("source_url", "workflow_step"),
                source_name=arguments.get("source_name"),
                source_tool=arguments.get("source_tool", "custom"),
                user=user,
                db=db
            )
            return {"success": res.get("status") == "success", "result": res.get("message"), "data": res}
            
        elif tool_name == "rag_ingest_source":
            res = await service.rag_ingest_source(
                url_or_id=arguments.get("url_or_id", arguments.get("url", arguments.get("id", ""))),
                kb_id=arguments.get("kb_id"),
                user_id=user_id,
                source_type=arguments.get("source_type", "website"),
                user=user,
                db=db
            )
            return {"success": res.get("status") == "success", "result": res.get("message"), "data": res}
            
        elif tool_name == "rag_search":
            res = await service.rag_search_query(
                query=arguments.get("query"),
                kb_id=arguments.get("kb_id"),
                user_id=user_id,
                top_k=arguments.get("top_k", 5),
                rerank=arguments.get("rerank", False),
                rerank_top_n=arguments.get("rerank_top_n", 3),
                user=user,
                db=db,
                session_key=arguments.get("session_key", ""),
            )
            
            # Synthesize a human-readable answer from the retrieved KB chunks
            results = res.get("results", [])
            query = res.get("effective_query", arguments.get("query", ""))
            answer = f"Found {len(results)} relevant matches"
            
            if results and query:
                try:
                    # Build context from non-empty search results
                    context_chunks = "\n\n---\n\n".join(
                        f"Source: {r.get('file', 'Unknown')}\n{r.get('text', '')}"
                        for r in results
                        if r.get("text") and r.get("text") != "NO_CONTENT_HERE"
                    )
                    
                    if context_chunks:
                        llm = LLMService()
                        llm_response = await llm.chat_completion(
                            messages=[
                                {
                                    "role": "system",
                                    "content": (
                                        "You are a helpful assistant. Answer the user's question based ONLY on the "
                                        "provided context from the knowledge base. Be concise, direct, and helpful. "
                                        "If the context doesn't contain relevant information to answer the question, "
                                        "say so clearly. Do not make up information."
                                    )
                                },
                                {
                                    "role": "user",
                                    "content": f"Question: {query}\n\nKnowledge Base Context:\n{context_chunks}"
                                }
                            ],
                            temperature=0.3,
                            max_tokens=500,
                            use_background_model=True
                        )
                        
                        if llm_response.content:
                            answer = llm_response.content
                        else:
                            logger.warning(f"LLM returned empty response for RAG synthesis: {llm_response.error}")
                except Exception as llm_err:
                    logger.error(f"Failed to synthesize RAG answer via LLM: {llm_err}")
                    # Fall back to the match count string — don't break the workflow
            
            return {"success": res.get("success"), "result": answer, "data": res}

        elif tool_name == "rag_delete_kb":
            res = await service.rag_delete_knowledge_base(
                kb_id=arguments.get("kb_id"),
                user_id=user_id,
                vector_db=arguments.get("vector_db", "pinecone")
            )
            return {"success": res.get("success", False), "result": "Knowledge base deleted", "data": res}
            
        elif tool_name == "ai_embeddings":
            return await self._execute_ai_embeddings_tool(arguments)
            
        return {"success": False, "error": f"Unknown RAG tool: {tool_name}"}

    async def _execute_ai_embeddings_tool(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Routes embedding requests to the appropriate service."""
        operation = parameters.get("operation")
        input_data = parameters.get("input")
        
        if not operation or not input_data:
            return {"success": False, "error": "Operation and input are required"}

        texts = input_data if isinstance(input_data, list) else [input_data]
        ai_services = self.services.get("ai_embeddings", {})

        try:
            if operation == "openai_small":
                return await ai_services["openai"].openai_batch_create_embeddings(texts, model="text-embedding-3-small")
            elif operation == "openai_large":
                return await ai_services["openai"].openai_batch_create_embeddings(texts, model="text-embedding-3-large")
            elif operation == "cohere_multilingual":
                return await ai_services["cohere"].cohere_embed(texts, model="embed-multilingual-v3.0")
            elif operation == "huggingface_local":
                return await ai_services["huggingface"].huggingface_batch_embed(texts, model="sentence-transformers/all-MiniLM-L6-v2")
            else:
                return {"success": False, "error": f"Unsupported embedding operation: {operation}"}
        except Exception as e:
            logger.error(f"Error in AI Embeddings tool: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_order_management_tool(self, parameters: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute order management tools using OrderService."""
        operation = parameters.get("operation")
        if not operation:
            return {"success": False, "error": "Operation is required for order tools"}
        return await self.services["order"].handle_operation(operation, **parameters)

    async def _execute_inventory_management_tool(self, parameters: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute inventory management tools using InventoryService."""
        operation = parameters.get("operation")
        if not operation:
            return {"success": False, "error": "Operation is required for inventory tools"}
        return await self.services["inventory"].handle_operation(operation, **parameters)

    async def _execute_real_estate_tool(self, parameters: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute real estate tools using RealEstateService."""
        operation = parameters.get("operation")
        if not operation:
            return {"success": False, "error": "Operation is required for real estate tools"}
        return await self.services["real_estate"].handle_operation(operation, **parameters)


    async def _execute_conversational_agent_tool(self, parameters: Dict[str, Any], user: User, db: AsyncSession) -> Dict[str, Any]:
        """Execute the conversational agent tool for agentic AI workflows."""
        try:
            agent = ConversationalAgentService()

            user_message = parameters.get("user_message", "")
            session_key = parameters.get("session_key", "")
            business_config = parameters.get("business_config", {})

            if not user_message:
                return {"success": False, "error": "No user message provided", "result": None}

            result = await agent.execute(
                user_message=user_message,
                session_key=session_key,
                business_config=business_config,
                user=user,
                db=db
            )

            return {
                "success": True,
                "result": result.get("response_text", ""),
                "response_text": result.get("response_text", ""),
                "image_urls": result.get("image_urls", []),
                "order_created": result.get("order_created", False),
                "order_data": result.get("order_data"),
                "order_notification": result.get("order_notification", ""),
                "actions_taken": result.get("actions_taken", []),
                "data": result
            }

        except Exception as e:
            logger.error(f"Conversational agent error: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Agent error: {str(e)}",
                "result": None
            }


# Global tool executor instance
tool_executor = ToolExecutor()

