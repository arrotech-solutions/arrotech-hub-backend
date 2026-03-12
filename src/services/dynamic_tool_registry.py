"""
Dynamic Tool Registry Service for generating tools based on user connections.
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Connection, ConnectionStatus, User, SubscriptionTier
from .platform_registry import platform_registry

logger = logging.getLogger(__name__)


class DynamicToolRegistry:
    """Dynamic registry for MCP tools based on user connections."""
    
    def __init__(self):
        self.base_tools: Dict[str, Dict[str, Any]] = {}
        self._initialize_base_tools()
    
    def _initialize_base_tools(self):
        """Initialize base tools that are always available."""
        self.base_tools = {
            # Marketing Campaign Automation - Always available
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
                },
                "category": "marketing",
                "always_available": True
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
                },
                "category": "marketing",
                "always_available": True
            },
            # Advanced Features - Always available
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
                },
                "category": "advanced",
                "always_available": True
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
                },
                "category": "advanced",
                "always_available": True
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
                },
                "category": "advanced",
                "always_available": True
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
                },
                "category": "advanced",
                "always_available": True
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
                },
                "category": "marketing",
                "always_available": True
            },
            # File Management Tools - Always available
            "file_management": {
                "name": "file_management",
                "description": "Upload, download, and manage files with PDF generation and document conversion",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["upload", "download", "list", "delete", "generate_pdf", "convert_document", "generate_qr"]},
                        "filename": {"type": "string"},
                        "content": {"type": "string"},
                        "from_format": {"type": "string"},
                        "to_format": {"type": "string"},
                        "template": {"type": "string"},
                        "qr_data": {"type": "string"},
                        "qr_size": {"type": "integer"}
                    },
                    "required": ["operation"]
                },
                "category": "file_management",
                "always_available": True
            },
            # Web Tools - Always available
            "web_tools": {
                "name": "web_tools",
                "description": "Web scraping, link generation, and web automation tools",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["scrape_website", "extract_data", "generate_short_link", "generate_tracking_link", "automate_task", "check_status", "extract_emails"]},
                        "url": {"type": "string"},
                        "selectors": {"type": "object"},
                        "original_url": {"type": "string"},
                        "custom_alias": {"type": "string"},
                        "campaign": {"type": "string"},
                        "source": {"type": "string"},
                        "task_config": {"type": "object"}
                    },
                    "required": ["operation"]
                },
                "category": "web_tools",
                "always_available": True
            },
            # Content Creation Tools - Always available
            "content_creation": {
                "name": "content_creation",
                "description": "Generate images, create content from templates, optimize SEO, and generate bulk content",
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
                            "description": "Text description for image generation or content creation"
                        },
                        "style": {
                            "type": "string",
                            "description": "Style specification for image generation (e.g., 'realistic', 'cartoon', 'abstract')"
                        },
                        "size": {
                            "type": "object",
                            "description": "Size specification for image generation (e.g., {'width': 512, 'height': 512})"
                        },
                        "template_name": {
                            "type": "string",
                            "description": "Name of the template to use for content creation"
                        },
                        "variables": {
                            "type": "object",
                            "description": "Variables to substitute in the template"
                        },
                        "base_content": {
                            "type": "string",
                            "description": "Base content for optimization or bulk generation"
                        },
                        "variations": {
                            "type": "integer",
                            "description": "Number of content variations to generate"
                        },
                        "content_type": {
                            "type": "string",
                            "description": "Type of content to generate (e.g., 'blog', 'social', 'email')"
                        },
                        "keywords": {
                            "type": "array", 
                            "items": {"type": "string"},
                            "description": "Keywords for SEO optimization or content generation"
                        },
                        "start_date": {
                            "type": "string",
                            "description": "Start date for calendar generation"
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date for calendar generation"
                        }
                    },
                    "required": ["operation"]
                },
                "category": "content_creation",
                "always_available": True
            },
            # Enterprise Features - Always available
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
                },
                "category": "enterprise",
                "always_available": True
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
                },
                "category": "enterprise",
                "always_available": True
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
                },
                "category": "enterprise",
                "always_available": True
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
                },
                "category": "enterprise",
                "always_available": True
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
                },
                "category": "enterprise",
                "always_available": True
            },
            # M-Pesa Payment Reconciliation Agent - Always available
            "mpesa_payment_reconciliation": {
                "name": "mpesa_payment_reconciliation",
                "description": "M-Pesa Payment Reconciliation and Invoice Tool. Use for payments, summaries, and INVOICE management. Operations: 'get_summary', 'match_payment' (reconcile), 'create_invoice', 'list_invoices'.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": [
                                "get_summary",
                                "get_payments",
                                "get_unmatched",
                                "get_payment_by_transaction_id",
                                "match_payment",
                                "match_payments",
                                "create_invoice",
                                "list_invoices",
                                "analyze_fraud",
                                "verify_with_daraja",
                                "get_fraud_signals"
                            ],
                            "description": "Operation to perform."
                        },
                        "days": {
                            "type": "integer",
                            "description": "Number of days for summary",
                            "default": 1
                        },
                        "status": {
                            "type": "string",
                            "enum": ["all", "pending", "matched", "unmatched", "verified", "draft", "sent", "paid", "overdue"],
                            "description": "Filter by status (payment or invoice)",
                            "default": "all"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Limit results",
                            "default": 20
                        },
                        "transaction_id": {
                            "type": "string",
                            "description": "M-Pesa transaction ID"
                        },
                        "payment_id": {
                            "type": "integer",
                            "description": "Internal Payment ID"
                        },
                        "invoice_number": {
                            "type": "string",
                            "description": "Invoice Number (for creation)"
                        },
                        "amount": {
                            "type": "number",
                            "description": "Amount (for invoice creation)"
                        },
                        "customer_name": {
                            "type": "string",
                            "description": "Customer Name (for invoice)"
                        }
                    },
                    "required": ["operation"]
                },
                "category": "payments",
                "always_available": True,
                "few_shot_examples": [
                    {
                        "user": "Show me today's M-Pesa payments",
                        "tool_call": 'mpesa_payment_reconciliation(operation="get_summary", days=1)',
                        "response": "Here is the summary of today's payments..."
                    },
                    {
                        "user": "Find unmatched payments from last week",
                        "tool_call": 'mpesa_payment_reconciliation(operation="get_unmatched", days=7)',
                        "response": "Found 3 unmatched payments..."
                    },
                    {
                         "user": "Create an invoice for 5000 shillings for John Doe",
                         "tool_call": 'mpesa_payment_reconciliation(operation="create_invoice", amount=5000, customer_name="John Doe")',
                         "response": "Invoice created for John Doe for KES 5,000."
                    }
                ]
            },
            # Bilingual & Context Intelligence - Always available
            "context_intelligence": {
                "name": "context_intelligence",
                "description": "Bilingual Translation & Context Intelligence. Translate between English and Swahili, analyze sentiment, verify KRA PINs. Operations: 'translate', 'analyze_sentiment', 'verify_kra_pin'.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": [
                                "translate",
                                "analyze_sentiment",
                                "verify_kra_pin",
                                "check_itax_compliance"
                            ],
                            "description": "Operation: translate (EN↔SW), analyze_sentiment, verify_kra_pin, check_itax_compliance"
                        },
                        "text": {
                            "type": "string",
                            "description": "Text to translate or analyze"
                        },
                        "target_lang": {
                            "type": "string",
                            "enum": ["English", "Swahili"],
                            "description": "Target language for translation",
                            "default": "English"
                        },
                        "pin": {
                            "type": "string",
                            "description": "KRA PIN to verify (11 characters, e.g., A012345678Z)"
                        }
                    },
                    "required": ["operation"]
                },
                "category": "localization",
                "always_available": True
            },
            # Email Template Management - Always available
            "email_template": {
                "name": "email_template",
                "description": "Manage email auto-reply templates. Create, update, render, and list templates by category (support, sales, billing, general, partnership, feedback). Templates support variable substitution for sender_name, original_subject, ticket_id, and company_name.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["get_template", "list_templates", "create_template", "delete_template", "render_template"],
                            "description": "Operation to perform"
                        },
                        "category": {
                            "type": "string",
                            "description": "Template category (e.g., 'support', 'sales', 'billing', 'general')"
                        },
                        "body": {
                            "type": "string",
                            "description": "Template body with {variable} placeholders (for create_template)"
                        },
                        "subject_prefix": {
                            "type": "string",
                            "description": "Prefix for reply subject line",
                            "default": "Re: "
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "description": "Template priority level"
                        },
                        "variables": {
                            "type": "object",
                            "description": "Variables for template rendering (e.g., {sender_name: 'John', company_name: 'Acme'})"
                        }
                    },
                    "required": ["operation"]
                },
                "category": "email",
                "always_available": True
            }
        }
    
    async def get_user_tools(self, user_id: int, db: AsyncSession, include_all: bool = False) -> List[Dict[str, Any]]:
        """Get tools available for a specific user based on their connections."""
        tools = []
        
        # Add base tools that are always available
        for tool_name, tool_config in self.base_tools.items():
            t = tool_config.copy()
            # Add status field for frontend compatibility
            t["status"] = "available"
            t["id"] = tool_name  # Add id field for frontend
            tools.append(t)
        
        # Get user's active connections
        result = await db.execute(
            select(Connection)
            .filter(Connection.user_id == user_id, Connection.status == ConnectionStatus.ACTIVE)
        )
        connections = result.scalars().all()
        active_platforms = {c.platform: c.id for c in connections}
        
        # Generate tools based on user's connections
        for connection in connections:
            if connection.platform == "slack":
                tools.extend(self._get_slack_tools(connection))
            elif connection.platform == "hubspot":
                tools.extend(self._get_hubspot_tools(connection))
            elif connection.platform == "salesforce":
                tools.extend(self._get_salesforce_tools(connection))
            elif connection.platform == "ga4":
                tools.extend(self._get_ga4_tools(connection))
            elif connection.platform == "asana":
                tools.extend(self._get_asana_tools(connection))
            elif connection.platform == "powerbi":
                tools.extend(self._get_powerbi_tools(connection))
            elif connection.platform == "outlook":
                tools.extend(self._get_outlook_tools(connection))
            elif connection.platform == "notion":
                tools.extend(self._get_notion_tools(connection))
            elif connection.platform == "trello":
                tools.extend(self._get_trello_tools(connection))
            elif connection.platform == "jira":
                tools.extend(self._get_jira_tools(connection))
            elif connection.platform == "google_workspace":
                tools.extend(self._get_google_workspace_tools(connection))
            elif connection.platform == "zoho":
                tools.extend(self._get_zoho_tools(connection))
            elif connection.platform in platform_registry.platforms:
                # Dynamically fetch tools for regional platforms (hr_hub, logistics_hub, etc.)
                p_tools = platform_registry.get_platform_tools(connection.platform)
                for tool in p_tools:
                    tool["connection_id"] = connection.id
                    tool["status"] = "available"
                    tool["id"] = tool["name"]
                    tools.append(tool)
        
        # If discovery mode, add all other available platform tools
        if include_all:
            processed_tool_names = {t["name"] for t in tools}
            for platform in platform_registry.list_platforms():
                if platform.id not in active_platforms:
                    p_tools = platform_registry.get_platform_tools(platform.id)
                    for tool in p_tools:
                        if tool["name"] not in processed_tool_names:
                            tool["status"] = "connection_required"
                            tool["id"] = tool["name"]
                            tools.append(tool)
        
        # Filter for Free Tier limitations (except in discovery mode where we want to show everything)
        user = await db.get(User, user_id)
        if user and user.subscription_tier == SubscriptionTier.FREE:
            allowed_tools = {
                "mpesa_payment_reconciliation", 
                "slack_send_message", 
                "context_intelligence",
                "marketing_campaign_automation",
                "campaign_performance_tracking",
                "file_management",
                "web_tools",
                "content_creation",
                "email_template"
            }
            
            if include_all:
                # In discovery mode, we keep all tools but mark tiered ones as upgrade_required
                for tool in tools:
                    if tool["name"] not in allowed_tools and tool.get("status") == "available":
                        tool["status"] = "upgrade_required"
            else:
                # In strict mode, filter out tools not allowed implicitly by the tier
                tools = [t for t in tools if t["name"] in allowed_tools]
        
        return tools
    
    def _get_slack_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get Slack tools for a connection."""
        return [
            {
                "name": "slack_list_channels",
                "description": "List all Slack channels in the workspace",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                "connection_id": connection.id,
                "platform": "slack",
                "status": "available",
                "id": "slack_list_channels"
            },
            {
                "name": "slack_send_message",
                "description": "Send a message to a Slack channel",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string", "description": "Channel name or ID"},
                        "message": {"type": "string", "description": "Message to send"}
                    },
                    "required": ["channel", "message"]
                },
                "connection_id": connection.id,
                "platform": "slack",
                "status": "available",
                "id": "slack_send_message"
            },
            {
                "name": "slack_get_channel_members",
                "description": "Get members of a Slack channel",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel_name": {"type": "string", "description": "Channel name"}
                    },
                    "required": ["channel_name"]
                },
                "connection_id": connection.id,
                "platform": "slack",
                "status": "available",
                "id": "slack_get_channel_members"
            },
            {
                "name": "slack_create_channel",
                "description": "Create a new Slack channel",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel_name": {
                            "type": "string", 
                            "description": "Name of the channel to create (without # prefix, lowercase letters, numbers, hyphens, and underscores only)"
                        }
                    },
                    "required": ["channel_name"]
                },
                "connection_id": connection.id,
                "platform": "slack",
                "status": "available",
                "id": "slack_create_channel"
            }
        ]
    
    def _get_hubspot_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get HubSpot tools for a connection."""
        return [
            {
                "name": "hubspot_contact_operations",
                "description": "Comprehensive HubSpot contact management - read, create, update, search, and segment contacts",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["read", "create", "update", "search", "segment"]},
                        "contact_data": {"type": "object", "description": "Contact fields: email (required), firstname, lastname, company, phone"},
                        "filters": {"type": "object", "description": "Filters for search/segment operations"},
                        "limit": {"type": "integer", "default": 50},
                        "contact_id": {"type": "string", "description": "Contact ID for update operations"},
                        "properties": {"type": "array", "items": {"type": "string"}, "description": "Contact properties to include"}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "hubspot",
                "status": "available",
                "id": "hubspot_contact_operations"
            },
            {
                "name": "hubspot_deal_management",
                "description": "Manage HubSpot deals - create, update, track, and analyze deal pipeline",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["read", "create", "update", "analyze", "add_note"]},
                        "deal_data": {"type": "object", "description": "Deal fields: dealname, amount, dealstage, pipeline, etc."},
                        "deal_id": {"type": "string", "description": "Deal ID for update/note operations"},
                        "note": {"type": "string", "description": "Note text for add_note operation"},
                        "filters": {"type": "object"},
                        "limit": {"type": "integer", "default": 20}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "hubspot",
                "status": "available",
                "id": "hubspot_deal_management"
            },
            {
                "name": "hubspot_analytics",
                "description": "Get HubSpot analytics and performance metrics",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                        "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                        "metrics": {"type": "array", "items": {"type": "string"}}
                    }
                },
                "connection_id": connection.id,
                "platform": "hubspot",
                "status": "available",
                "id": "hubspot_analytics"
            }
        ]
    
    def _get_salesforce_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get Salesforce tools for a connection."""
        return [
            {
                "name": "salesforce_create_contact",
                "description": "Create a new contact in Salesforce CRM",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "FirstName": {"type": "string", "description": "Contact's first name"},
                        "LastName": {"type": "string", "description": "Contact's last name"},
                        "Email": {"type": "string", "description": "Contact's email address"},
                        "Phone": {"type": "string", "description": "Contact's phone number"},
                        "Company": {"type": "string", "description": "Contact's company"},
                        "Title": {"type": "string", "description": "Contact's job title"},
                        "Description": {"type": "string", "description": "Additional notes about the contact"}
                    },
                    "required": ["FirstName", "LastName"]
                },
                "connection_id": connection.id,
                "platform": "salesforce",
                "status": "available",
                "id": "salesforce_create_contact"
            },
            {
                "name": "salesforce_search_contacts",
                "description": "Search contacts in Salesforce CRM",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query for contacts"},
                        "limit": {"type": "integer", "description": "Number of contacts to retrieve", "default": 50}
                    },
                    "required": ["query"]
                },
                "connection_id": connection.id,
                "platform": "salesforce",
                "status": "available",
                "id": "salesforce_search_contacts"
            },
            {
                "name": "salesforce_create_lead",
                "description": "Create a new lead in Salesforce CRM",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "FirstName": {"type": "string", "description": "Lead's first name"},
                        "LastName": {"type": "string", "description": "Lead's last name"},
                        "Company": {"type": "string", "description": "Lead's company"},
                        "Email": {"type": "string", "description": "Lead's email address"},
                        "Phone": {"type": "string", "description": "Lead's phone number"},
                        "LeadSource": {"type": "string", "description": "Source of the lead"},
                        "Status": {"type": "string", "description": "Lead status", "default": "New"}
                    },
                    "required": ["FirstName", "LastName", "Company"]
                },
                "connection_id": connection.id,
                "platform": "salesforce",
                "status": "available",
                "id": "salesforce_create_lead"
            },
            {
                "name": "salesforce_get_leads",
                "description": "Get leads from Salesforce CRM",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "description": "Filter by lead status"},
                        "limit": {"type": "integer", "description": "Number of leads to retrieve", "default": 50}
                    },
                    "required": []
                },
                "connection_id": connection.id,
                "platform": "salesforce",
                "status": "available",
                "id": "salesforce_get_leads"
            },
            {
                "name": "salesforce_create_opportunity",
                "description": "Create a new opportunity in Salesforce CRM",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "Name": {"type": "string", "description": "Opportunity name"},
                        "Amount": {"type": "number", "description": "Opportunity amount"},
                        "StageName": {"type": "string", "description": "Opportunity stage", "default": "Prospecting"},
                        "CloseDate": {"type": "string", "description": "Expected close date (YYYY-MM-DD)"},
                        "AccountId": {"type": "string", "description": "Associated account ID"},
                        "Description": {"type": "string", "description": "Opportunity description"}
                    },
                    "required": ["Name", "CloseDate"]
                },
                "connection_id": connection.id,
                "platform": "salesforce",
                "status": "available",
                "id": "salesforce_create_opportunity"
            },
            {
                "name": "salesforce_get_opportunities",
                "description": "Get opportunities from Salesforce CRM",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "stage": {"type": "string", "description": "Filter by opportunity stage"},
                        "limit": {"type": "integer", "description": "Number of opportunities to retrieve", "default": 50}
                    },
                    "required": []
                },
                "connection_id": connection.id,
                "platform": "salesforce",
                "status": "available",
                "id": "salesforce_get_opportunities"
            },
            {
                "name": "salesforce_get_pipeline_report",
                "description": "Get sales pipeline report from Salesforce",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "date_range": {"type": "string", "description": "Date range in days", "default": "30"}
                    },
                    "required": []
                },
                "connection_id": connection.id,
                "platform": "salesforce",
                "status": "available",
                "id": "salesforce_get_pipeline_report"
            },
            {
                "name": "salesforce_sync_from_hubspot",
                "description": "Sync contacts from HubSpot to Salesforce",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "hubspot_contacts": {"type": "array", "description": "Array of HubSpot contacts to sync"}
                    },
                    "required": ["hubspot_contacts"]
                },
                "connection_id": connection.id,
                "platform": "salesforce",
                "status": "available",
                "id": "salesforce_sync_from_hubspot"
            }
        ]
    
    def _get_ga4_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get GA4 tools for a connection."""
        return [
            {
                "name": "ga4_get_traffic",
                "description": "Get Google Analytics 4 traffic data",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "hours": {"type": "integer", "description": "Hours of data to retrieve", "default": 24}
                    },
                    "required": []
                },
                "connection_id": connection.id,
                "platform": "ga4",
                "status": "available",
                "id": "ga4_get_traffic"
            },
            {
                "name": "ga4_get_conversions",
                "description": "Get Google Analytics 4 conversion data",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "hours": {"type": "integer", "description": "Hours of data to retrieve", "default": 24}
                    },
                    "required": []
                },
                "connection_id": connection.id,
                "platform": "ga4",
                "status": "available",
                "id": "ga4_get_conversions"
            }
        ]
    
    def _get_asana_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get Asana tools for a connection."""
        return [
            {
                "name": "asana_create_project",
                "description": "Create a new Asana project",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name of the project"},
                        "notes": {"type": "string", "description": "Project description"},
                        "team_id": {"type": "string", "description": "Team ID for the project"},
                        "workspace_id": {"type": "string", "description": "Workspace ID (optional, uses default if not provided)"}
                    },
                    "required": ["name"]
                },
                "connection_id": connection.id,
                "platform": "asana",
                "status": "available",
                "id": "asana_create_project"
            },
            {
                "name": "asana_list_projects",
                "description": "List all Asana projects",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string", "description": "Workspace ID to list projects from"},
                        "team_id": {"type": "string", "description": "Team ID to filter projects"},
                        "limit": {"type": "integer", "description": "Number of projects to retrieve", "default": 50}
                    },
                    "required": []
                },
                "connection_id": connection.id,
                "platform": "asana",
                "status": "available",
                "id": "asana_list_projects"
            },
            {
                "name": "asana_create_task",
                "description": "Create a new Asana task",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name of the task"},
                        "notes": {"type": "string", "description": "Task description"},
                        "project_id": {"type": "string", "description": "Project ID to add task to"},
                        "projects": {"type": "array", "items": {"type": "string"}, "description": "List of project IDs to add task to"},
                        "assignee": {"type": "string", "description": "User ID to assign task to"},
                        "due_date": {"type": "string", "description": "Due date (YYYY-MM-DD format)"}
                    },
                    "required": ["name"]
                },
                "connection_id": connection.id,
                "platform": "asana",
                "status": "available",
                "id": "asana_create_task"
            },
            {
                "name": "asana_list_tasks",
                "description": "List Asana tasks",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID to list tasks from"},
                        "assignee": {"type": "string", "description": "User ID to filter tasks by assignee"},
                        "limit": {"type": "integer", "description": "Number of tasks to retrieve", "default": 50},
                        "opt_fields": {"type": "array", "items": {"type": "string"}, "description": "List of fields to include in the response"}
                    },
                    "required": []
                },
                "connection_id": connection.id,
                "platform": "asana",
                "status": "available",
                "id": "asana_list_tasks"
            },
            {
                "name": "asana_add_comment",
                "description": "Add a comment to an Asana task",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task ID to add comment to"},
                        "comment_text": {"type": "string", "description": "Comment text to add"}
                    },
                    "required": ["task_id", "comment_text"]
                },
                "connection_id": connection.id,
                "platform": "asana",
                "status": "available",
                "id": "asana_add_comment"
            },
            {
                "name": "asana_get_teams",
                "description": "Get all teams in the workspace",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string", "description": "Workspace ID to get teams from"}
                    },
                    "required": []
                },
                "connection_id": connection.id,
                "platform": "asana",
                "status": "available",
                "id": "asana_get_teams"
            },
            {
                "name": "asana_get_workspaces",
                "description": "Get all workspaces accessible to the user",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                "connection_id": connection.id,
                "platform": "asana",
                "status": "available",
                "status": "available",
                "id": "asana_get_workspaces"
            },
            {
                "name": "asana_get_users",
                "description": "Get all users in the workspace or team",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string", "description": "Workspace ID to get users from"},
                        "team_id": {"type": "string", "description": "Team ID to filter users"}
                    },
                    "required": []
                },
                "connection_id": connection.id,
                "platform": "asana",
                "status": "available",
                "id": "asana_get_users"
            }
        ]
    
    def _get_powerbi_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get Power BI tools for a connection."""
        return [
            {
                "name": "powerbi_list_workspaces",
                "description": "List all Power BI workspaces accessible to the user",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                "connection_id": connection.id,
                "platform": "powerbi",
                "status": "available",
                "id": "powerbi_list_workspaces"
            },
            {
                "name": "powerbi_list_datasets",
                "description": "List datasets in a Power BI workspace",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string", "description": "Workspace ID to list datasets from"}
                    },
                    "required": ["workspace_id"]
                },
                "connection_id": connection.id,
                "platform": "powerbi",
                "status": "available",
                "id": "powerbi_list_datasets"
            },
            {
                "name": "powerbi_list_reports",
                "description": "List reports in a Power BI workspace",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string", "description": "Workspace ID to list reports from"}
                    },
                    "required": ["workspace_id"]
                },
                "connection_id": connection.id,
                "platform": "powerbi",
                "status": "available",
                "id": "powerbi_list_reports"
            },
            {
                "name": "powerbi_list_dashboards",
                "description": "List dashboards in a Power BI workspace",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string", "description": "Workspace ID to list dashboards from"}
                    },
                    "required": ["workspace_id"]
                },
                "connection_id": connection.id,
                "platform": "powerbi",
                "status": "available",
                "id": "powerbi_list_dashboards"
            },
            {
                "name": "powerbi_execute_dax_query",
                "description": "Execute a DAX query on a Power BI dataset",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string", "description": "Workspace ID containing the dataset"},
                        "dataset_id": {"type": "string", "description": "Dataset ID to query"},
                        "dax_query": {"type": "string", "description": "DAX query to execute"}
                    },
                    "required": ["workspace_id", "dataset_id", "dax_query"]
                },
                "connection_id": connection.id,
                "platform": "powerbi",
                "status": "available",
                "id": "powerbi_execute_dax_query"
            },
            {
                "name": "powerbi_refresh_dataset",
                "description": "Refresh a Power BI dataset",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string", "description": "Workspace ID containing the dataset"},
                        "dataset_id": {"type": "string", "description": "Dataset ID to refresh"}
                    },
                    "required": ["workspace_id", "dataset_id"]
                },
                "connection_id": connection.id,
                "platform": "powerbi",
                "status": "available",
                "id": "powerbi_refresh_dataset"
            },
            {
                "name": "powerbi_get_embed_token",
                "description": "Get an embed token for a Power BI report",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string", "description": "Workspace ID containing the report"},
                        "report_id": {"type": "string", "description": "Report ID to get embed token for"}
                    },
                    "required": ["workspace_id", "report_id"]
                },
                "connection_id": connection.id,
                "platform": "powerbi",
                "status": "available",
                "id": "powerbi_get_embed_token"
            },
            {
                "name": "powerbi_get_analytics_summary",
                "description": "Get comprehensive Power BI analytics summary",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string", "description": "Workspace ID to get analytics for"},
                        "include_activity_logs": {"type": "boolean", "default": True, "description": "Include activity logs in summary"},
                        "start_date": {"type": "string", "description": "Start date for analytics (YYYY-MM-DD)"},
                        "end_date": {"type": "string", "description": "End date for analytics (YYYY-MM-DD)"}
                    },
                    "required": []
                },
                "connection_id": connection.id,
                "platform": "powerbi",
                "status": "available",
                "id": "powerbi_get_analytics_summary"
            }
        ]

    def _get_outlook_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get Outlook tools for a connection."""
        return [
            {
                "name": "outlook_read_emails",
                "description": "Read emails from Outlook",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 20},
                        "query": {"type": "string"}
                    },
                    "required": []
                },
                "connection_id": connection.id,
                "platform": "outlook",
                "status": "available",
                "id": "outlook_read_emails"
            },
            {
                "name": "outlook_send_email",
                "description": "Send an email via Outlook",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "to_email": {"type": "string"},
                        "subject": {"type": "string"},
                        "content": {"type": "string"},
                        "content_type": {"type": "string", "enum": ["text", "html"], "default": "text"}
                    },
                    "required": ["to_email", "subject", "content"]
                },
                "connection_id": connection.id,
                "platform": "outlook",
                "status": "available",
                "id": "outlook_send_email"
            },
            {
                "name": "outlook_search_emails",
                "description": "Search for emails in Outlook",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 20}
                    },
                    "required": ["query"]
                },
                "connection_id": connection.id,
                "platform": "outlook",
                "status": "available",
                "id": "outlook_search_emails"
            }
        ]

    def _get_notion_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get Notion tools for a connection."""
        return [
            {
                "name": "notion_search_pages",
                "description": "Search pages in Notion",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 10}
                    },
                    "required": ["query"]
                },
                "connection_id": connection.id,
                "platform": "notion",
                "status": "available",
                "id": "notion_search_pages"
            },
            {
                "name": "notion_create_page",
                "description": "Create a new page in Notion",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "parent_id": {"type": "string", "description": "Parent Page or Database ID"}
                    },
                    "required": ["title", "parent_id"]
                },
                "connection_id": connection.id,
                "platform": "notion",
                "status": "available",
                "id": "notion_create_page"
            }
        ]

    def _get_trello_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get Trello tools for a connection."""
        return [
            {
                "name": "trello_get_boards",
                "description": "Get Trello boards",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                "connection_id": connection.id,
                "platform": "trello",
                "status": "available",
                "id": "trello_get_boards"
            },
            {
                "name": "trello_search_cards",
                "description": "Search Trello cards",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 10}
                    },
                    "required": ["query"]
                },
                "connection_id": connection.id,
                "platform": "trello",
                "status": "available",
                "id": "trello_search_cards"
            },
            {
                "name": "trello_create_card",
                "description": "Create a Trello card",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "list_id": {"type": "string"},
                        "name": {"type": "string"},
                        "desc": {"type": "string"},
                        "due": {"type": "string"}
                    },
                    "required": ["list_id", "name"]
                },
                "connection_id": connection.id,
                "platform": "trello",
                "status": "available",
                "id": "trello_create_card"
            }
        ]

    def _get_jira_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get Jira tools for a connection."""
        return [
            {
                "name": "jira_get_projects",
                "description": "Get Jira projects",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                "connection_id": connection.id,
                "platform": "jira",
                "status": "available",
                "id": "jira_get_projects"
            },
            {
                "name": "jira_search_issues",
                "description": "Search Jira issues using JQL",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "jql": {"type": "string"},
                        "limit": {"type": "integer", "default": 10}
                    },
                    "required": ["jql"]
                },
                "connection_id": connection.id,
                "platform": "jira",
                "status": "available",
                "id": "jira_search_issues"
            },
            {
                "name": "jira_create_issue",
                "description": "Create a Jira issue",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_key": {"type": "string"},
                        "summary": {"type": "string"},
                        "description": {"type": "string"},
                        "issuetype": {"type": "string"}
                    },
                    "required": ["project_key", "summary"]
                },
                "connection_id": connection.id,
                "platform": "jira",
                "status": "available",
                "id": "jira_create_issue"
            }
        ]

    def _get_google_workspace_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get Google Workspace tools for a connection."""
        return [
            {
                "name": "google_workspace_gmail",
                "description": "Gmail operations: send emails, read inbox, search emails, manage labels, create drafts, watch inbox for push notifications, and mark emails as read. Supports operations: send_email, read_emails, search_emails, create_label, apply_label, create_draft, delete_email, get_email_details, watch_inbox, stop_watch, mark_as_read.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["send_email", "read_emails", "search_emails", "create_label", "apply_label", "create_draft", "delete_email", "get_email_details", "watch_inbox", "stop_watch", "mark_as_read"],
                            "description": "Gmail operation to perform"
                        },
                        "to": {"type": "string", "description": "Recipient email (for send_email, create_draft)"},
                        "subject": {"type": "string", "description": "Email subject"},
                        "body": {"type": "string", "description": "Email body (plain text or HTML)"},
                        "cc": {"type": "string", "description": "CC recipients (comma-separated)"},
                        "bcc": {"type": "string", "description": "BCC recipients"},
                        "html": {"type": "boolean", "description": "Whether body is HTML", "default": False},
                        "query": {"type": "string", "description": "Gmail search query (for read/search)"},
                        "max_results": {"type": "integer", "description": "Max emails to retrieve", "default": 10},
                        "label_ids": {"type": "array", "items": {"type": "string"}, "description": "Label IDs"},
                        "label_name": {"type": "string", "description": "Label name (for create_label)"},
                        "message_id": {"type": "string", "description": "Message ID"},
                        "message_ids": {"type": "array", "items": {"type": "string"}, "description": "Message IDs (for apply_label, mark_as_read)"},
                        "topic_name": {"type": "string", "description": "Pub/Sub topic (for watch_inbox)"},
                        "label_filter_action": {"type": "string", "enum": ["include", "exclude"], "default": "include"}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "google_workspace",
                "status": "available",
                "id": "google_workspace_gmail"
            },
            {
                "name": "google_workspace_calendar",
                "description": "Google Calendar operations: create events, list events, update events, delete events, check availability, and create meetings with Google Meet.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create_event", "list_events", "update_event", "delete_event", "check_availability", "create_meeting"],
                            "description": "Calendar operation to perform"
                        },
                        "summary": {"type": "string", "description": "Event title"},
                        "start_time": {"type": "string", "description": "Start time (ISO 8601)"},
                        "end_time": {"type": "string", "description": "End time (ISO 8601)"},
                        "description": {"type": "string", "description": "Event description"},
                        "location": {"type": "string"},
                        "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee email addresses"},
                        "timezone": {"type": "string", "default": "Africa/Nairobi"},
                        "event_id": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "google_workspace",
                "status": "available",
                "id": "google_workspace_calendar"
            },
            {
                "name": "google_workspace_drive",
                "description": "Google Drive operations: upload, download, list, search, create folders, share, move, and get metadata for files.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["upload_file", "download_file", "list_files", "create_folder", "delete_file", "share_file", "search_files", "get_metadata", "move_file"],
                            "description": "Drive operation to perform"
                        },
                        "filename": {"type": "string"},
                        "content": {"type": "string", "description": "File content (for upload)"},
                        "mime_type": {"type": "string", "default": "application/octet-stream"},
                        "file_id": {"type": "string"},
                        "folder_id": {"type": "string"},
                        "query": {"type": "string"},
                        "email": {"type": "string", "description": "Email to share with"},
                        "role": {"type": "string", "enum": ["reader", "writer", "commenter"], "default": "reader"}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "google_workspace",
                "status": "available",
                "id": "google_workspace_drive"
            },
            {
                "name": "google_workspace_sheets",
                "description": "Google Sheets operations: create spreadsheets, read/write ranges, append rows, clear ranges, batch update, and get spreadsheet info.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create_spreadsheet", "read_range", "write_range", "append_rows", "clear_range", "batch_update", "get_info"],
                            "description": "Sheets operation to perform"
                        },
                        "spreadsheet_id": {"type": "string"},
                        "range_name": {"type": "string"},
                        "values": {"type": "array"},
                        "title": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "google_workspace",
                "status": "available",
                "id": "google_workspace_sheets"
            },
            {
                "name": "google_workspace_docs",
                "description": "Google Docs operations: create documents, read content, insert/append text, find-replace, format text, insert tables, batch update, and export as PDF.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create_document", "read_document", "insert_text", "append_text", "replace_text", "format_text", "insert_table", "batch_update", "export_pdf"],
                            "description": "Docs operation to perform"
                        },
                        "document_id": {"type": "string"},
                        "title": {"type": "string"},
                        "text": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "google_workspace",
                "status": "available",
                "id": "google_workspace_docs"
            },
            {
                "name": "google_workspace_analytics",
                "description": "Google Analytics 4 operations: get traffic data, conversions, user behavior, custom reports, and e-commerce data.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["get_traffic", "get_conversions", "get_user_behavior", "get_custom_report", "get_ecommerce_data"],
                            "description": "Analytics operation to perform"
                        },
                        "property_id": {"type": "string"},
                        "hours": {"type": "integer", "default": 24}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "google_workspace",
                "status": "available",
                "id": "google_workspace_analytics"
            }
        ]

    def _get_zoho_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get Zoho tools for a connection."""
        return [
            {
                "name": "zoho_crm_operations",
                "description": "Comprehensive Zoho CRM operations: read/create contacts, deals, and update deal stages.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["get_contacts", "create_contact", "get_deals", "create_deal", "update_deal_stage"],
                            "description": "CRM operation to perform"
                        },
                        "limit": {"type": "integer", "default": 50},
                        "page": {"type": "integer", "default": 1},
                        "contact_data": {"type": "object", "description": "Contact data for creation"},
                        "deal_data": {"type": "object", "description": "Deal data for creation"},
                        "deal_id": {"type": "string", "description": "Deal ID for update"},
                        "stage": {"type": "string", "description": "New Deal stage"}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "zoho",
                "status": "available",
                "id": "zoho_crm_operations"
            },
            {
                "name": "zoho_finance_operations",
                "description": "Zoho Finance operations targeting Books/Invoice/Expense: create/read customers, invoices, record payments, and manage expenses.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create_customer", "get_invoices", "create_invoice", "record_payment", "get_expenses", "create_expense"],
                            "description": "Finance operation to perform"
                        },
                        "limit": {"type": "integer", "default": 50},
                        "customer_data": {"type": "object", "description": "Customer payload"},
                        "invoice_data": {"type": "object", "description": "Invoice payload"},
                        "payment_data": {"type": "object", "description": "Payment payload"},
                        "expense_data": {"type": "object", "description": "Expense payload"},
                        "org_id": {"type": "string", "description": "Optional: Specific Finance Organization ID"}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "zoho",
                "status": "available",
                "id": "zoho_finance_operations"
            },
            {
                "name": "zoho_desk_operations",
                "description": "Zoho Desk support ticket operations: get tickets, create new tickets, and send replies.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["get_tickets", "create_ticket", "reply_ticket", "get_articles", "search_articles", "create_article", "draft_article_from_ticket", "analyze_knowledge_gaps", "auto_resolve_ticket"],
                            "description": "Desk operation to perform"
                        },
                        "limit": {"type": "integer", "default": 50},
                        "department_id": {"type": "string"},
                        "ticket_data": {"type": "object", "description": "Ticket payload for creation"},
                        "ticket_id": {"type": "string", "description": "Ticket ID to reply to"},
                        "reply_text": {"type": "string", "description": "Reply content"},
                        "category_id": {"type": "string", "description": "Category ID for articles"},
                        "query": {"type": "string", "description": "Search query for articles"},
                        "article_data": {"type": "object", "description": "Article payload for creation"}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "zoho",
                "status": "available",
                "id": "zoho_desk_operations"
            },
            {
                "name": "zoho_mail_operations",
                "description": "Zoho Mail operations: fetch messages and send new emails.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["get_messages", "send_email"],
                            "description": "Mail operation to perform"
                        },
                        "limit": {"type": "integer", "default": 50},
                        "account_id": {"type": "string", "description": "Specific Mail Account ID"},
                        "folder_id": {"type": "string", "description": "Folder ID for getting messages"},
                        "to_address": {"type": "string", "description": "Recipient email address"},
                        "subject": {"type": "string", "description": "Email subject"},
                        "content": {"type": "string", "description": "Email content (HTML or Text)"}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "zoho",
                "status": "available",
                "id": "zoho_mail_operations"
            }
        ]
    
    async def get_all_tools(self, db: AsyncSession) -> List[Dict[str, Any]]:
        """Get all tools (base tools + all platform tools)."""
        tools = []
        
        # Add base tools
        for tool_name, tool_config in self.base_tools.items():
            tools.append(tool_config)
        
        # Add all platform tools
        platform_tools = platform_registry.get_all_tools()
        tools.extend(platform_tools)
        
        return tools
    
    
    def _find_internal_tool(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Try to find a tool definition in the internal tool generation methods."""
        # Map of platform keys to their generation methods
        # This matches the logic in get_user_tools
        platform_methods = {
            "slack": self._get_slack_tools,
            "hubspot": self._get_hubspot_tools,
            "salesforce": self._get_salesforce_tools,
            "ga4": self._get_ga4_tools,
            "asana": self._get_asana_tools,
            "powerbi": self._get_powerbi_tools,
            "outlook": self._get_outlook_tools,
            "notion": self._get_notion_tools,
            "trello": self._get_trello_tools,
            "jira": self._get_jira_tools,
            "google_workspace": self._get_google_workspace_tools,
            "zoho": self._get_zoho_tools
        }

        # Check if tool name starts with any known platform prefix to optimize
        # This is a heuristic, but most internal tools follow {platform}_{action}
        target_platform = None
        for platform in platform_methods.keys():
            if tool_name.startswith(f"{platform}_"):
                target_platform = platform
                break
        
        # If we identified a potential platform, check it first
        platforms_to_check = [target_platform] if target_platform else platform_methods.keys()

        # Create a dummy connection for schema generation
        # We only need the ID to be present, the actual ID doesn't matter for validation
        dummy_connection = Connection(
            id="dummy_validation_id",
            platform="dummy",
            config={},
            status=ConnectionStatus.ACTIVE
        )

        for platform in platforms_to_check:
            if not platform: continue
            
            generator = platform_methods.get(platform)
            if generator:
                try:
                    dummy_connection.platform = platform
                    tools = generator(dummy_connection)
                    for tool in tools:
                        if tool["name"] == tool_name:
                            return tool
                except Exception as e:
                    logger.warning(f"Error checking internal tools for platform {platform}: {e}")
                    continue
        
        return None

    def get_tool(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific tool by name."""
        # Check base tools first
        if tool_name in self.base_tools:
            return self.base_tools[tool_name]
        
        # Check internal dynamic tools (Slack, Asana, etc.)
        # This fixes the issue where fine-grained tools used by frontend (e.g. asana_list_tasks)
        # weren't found because PlatformRegistry uses coarse-grained tools (e.g. asana_task_management)
        internal_tool = self._find_internal_tool(tool_name)
        if internal_tool:
            return internal_tool

        # Check generic platform tools from registry
        for platform_id in platform_registry.platforms:
            platform_tools = platform_registry.get_platform_tools(platform_id)
            for tool in platform_tools:
                if tool["name"] == tool_name:
                    return tool
        
        return None
    
    async def get_tools_for_llm(self, user_id: int = None, db: AsyncSession = None) -> List[Dict[str, Any]]:
        """Get tools in format suitable for LLM function calling."""
        if user_id and db:
            # Get user-specific tools, including unconnected ones (so AI can see what's possible)
            return await self.get_user_tools(user_id, db, include_all=True)
        else:
            # Get all tools
            return await self.get_all_tools(db)
    
    def convert_tools_to_openai_format(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert internal tool format to OpenAI function calling format."""
        openai_tools = []
        for tool in tools:
            openai_tool = {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool.get("inputSchema", {})
                }
            }
            openai_tools.append(openai_tool)
        return openai_tools
    
    async def get_available_tools(self, user_id: int = None, db: AsyncSession = None) -> List[Dict[str, Any]]:
        """Get all available tools for workflow creation."""
        # For workflow creation, return all possible tools (base + platform tools)
        # This gives the LLM the full context of what's possible
        # User-specific filtering happens during execution
        tools = []
        
        # Add base tools that are always available
        for tool_name, tool_config in self.base_tools.items():
            tools.append({
                "name": tool_name,
                "description": tool_config["description"],
                "inputSchema": tool_config.get("inputSchema", {}),
                "category": tool_config.get("category", "general"),
                "always_available": tool_config.get("always_available", False)
            })
        
        # Add all platform tools from the Platform Registry
        # This ensures new specialized tools (HR, Logistics, etc.) are available for design
        platform_tools = platform_registry.get_all_tools()
        
        # Add category and platform info if missing
        formatted_platform_tools = []
        for tool in platform_tools:
            formatted_tool = {
                "name": tool["name"],
                "description": tool["description"],
                "inputSchema": tool.get("inputSchema", tool.get("input_schema", {})),
                "category": tool.get("category", "automation"),
                "platform": tool.get("platform", "regional_hub")
            }
            formatted_platform_tools.append(formatted_tool)
            
        tools.extend(formatted_platform_tools)
        return tools

    async def get_tool_descriptions(self, user_id: int = None, db: AsyncSession = None) -> str:
        """Get a human-readable description of all available tools."""
        tools = await self.get_tools_for_llm(user_id, db)
        descriptions = []
        for tool in tools:
            desc = f"- {tool['name']}: {tool['description']}"
            if 'platform' in tool:
                desc += f" (via {tool['platform']})"
            descriptions.append(desc)
        return "\n".join(descriptions)

    def get_relevant_examples(self, user_query: str, tools: List[Dict[str, Any]]) -> str:
        """
        Get relevant few-shot examples based on user query keywords.
        Returns formatted string of examples appropriate for the system prompt.
        """
        if not user_query:
            return ""

        relevant_examples = []
        user_terms = set(user_query.lower().split())
        
        # Stopwords to ignore
        stopwords = {"the", "a", "an", "is", "are", "to", "for", "of", "in", "on", "with", "please", "can", "you", "i", "need"}
        keywords = user_terms - stopwords
        
        for tool in tools:
            # Handle both nested 'function' format and flat format
            actual_tool = tool.get('function', tool)
            examples = actual_tool.get('few_shot_examples', tool.get('few_shot_examples', []))
            
            if not examples:
                continue
                
            # Score this tool's relevance
            tool_name = actual_tool.get('name', '').lower()
            tool_desc = actual_tool.get('description', '').lower()
            
            # Simple keyword matching score
            score = 0
            if any(k in tool_name for k in keywords):
                score += 3
            if any(k in tool_desc for k in keywords):
                score += 1
            
            # If relevant (score > 0) or we have very few keywords, include examples
            # High threshold to avoid noise, but ensure at least some context if vague
            if score > 0 or not keywords:
                for ex in examples:
                    # Also check if example text matches keywords
                    ex_text = str(ex).lower()
                    if any(k in ex_text for k in keywords):
                        score += 1
                    
                    relevant_examples.append((score, actual_tool.get('name'), ex))

        # Sort by score desc
        relevant_examples.sort(key=lambda x: x[0], reverse=True)
        
        # Take top 5 most relevant
        top_examples = relevant_examples[:5]
        
        examples_text = ""
        for _, name, ex in top_examples:
            examples_text += f"### Example ({name}):\n"
            if isinstance(ex, dict):
                examples_text += f"User: \"{ex.get('user', '')}\"\n"
                if "Thought" in ex: # Support existing ReAct examples if present
                    examples_text += f"Thought: {ex.get('Thought')}\n"
                else:
                    # Generate a synthetic thought for the example if missing (Self-Consistency)
                    examples_text += f"Thought: User wants to perform action with {name}. I will call the tool with the provided arguments.\n"
                    
                examples_text += f"Tool Call: {ex.get('tool_call', '')}\n"
                examples_text += f"Response: {ex.get('response', '')}\n\n"
            else:
                examples_text += f"{ex}\n\n"
                
        return examples_text


# Global dynamic tool registry instance
dynamic_tool_registry = DynamicToolRegistry() 