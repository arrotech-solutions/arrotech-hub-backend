"""
Dynamic Tool Registry Service for generating tools based on user connections.
"""

import logging
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
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
            # Code Mode Execution
            "execute_python_code": {
                "name": "execute_python_code",
                "description": "Execute a Python script to perform complex logic, data transformation, or orchestrate multiple tool calls. DO NOT return raw python code to the user, execute it and return the result. Use this when you need to combine multiple tools, iterate over data, or run custom logic. The environment includes a 'call_tool(tool_name: str, params: dict)' function, and standard libraries (json, math, datetime, re, hashlib, uuid). IMPORTANT: You must assign your final output to a variable named `result` for it to be captured and returned. You can also use print() for intermediate logging.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "The python code to execute. Use 'await call_tool(name, params)' to invoke tools. Assign final output to `result`. Wrap code in standard python syntax."}
                    },
                    "required": ["code"]
                },
                "category": "system",
                "always_available": True
            },
            # Code Mode Discovery Meta-Tools
            "search_tools": {
                "name": "search_tools",
                "description": "Search for available tools by keyword. Returns matching tool names and descriptions. Use this to discover what tools are available before writing code.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query (e.g., 'send message', 'create contact', 'payment')"},
                        "category": {"type": "string", "description": "Optional category filter (e.g., 'messaging', 'crm', 'finance')"}
                    },
                    "required": ["query"]
                },
                "category": "system",
                "always_available": True
            },
            "get_tool_schema": {
                "name": "get_tool_schema",
                "description": "Get the full parameter schema for a specific tool. Use this to inspect what parameters a tool accepts before writing code to call it.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "tool_name": {"type": "string", "description": "Exact tool name (e.g., 'slack_send_message')"}
                    },
                    "required": ["tool_name"]
                },
                "category": "system",
                "always_available": True
            },
            "list_tool_categories": {
                "name": "list_tool_categories",
                "description": "List all available tool categories with tool counts. Use this to understand what capabilities are available.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                },
                "category": "system",
                "always_available": True
            },
            # Maps Capability Layer - Always available
            "maps.geocode": {
                "name": "maps.geocode",
                "description": "Convert address into coordinates (latitude/longitude)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "address": {"type": "string", "description": "Address to geocode"}
                    },
                    "required": ["address"]
                },
                "category": "maps",
                "always_available": True
            },
            "maps.reverse_geocode": {
                "name": "maps.reverse_geocode",
                "description": "Convert coordinates into address and landmark",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lng": {"type": "number"}
                    },
                    "required": ["lat", "lng"]
                },
                "category": "maps",
                "always_available": True
            },
            "maps.distance_matrix": {
                "name": "maps.distance_matrix",
                "description": "Calculate distance and ETA between origin and destinations",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "origin": {
                            "type": "object",
                            "properties": {"lat": {"type": "number"}, "lng": {"type": "number"}},
                            "required": ["lat", "lng"]
                        },
                        "destinations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"lat": {"type": "number"}, "lng": {"type": "number"}}
                            }
                        }
                    },
                    "required": ["origin", "destinations"]
                },
                "category": "maps",
                "always_available": True
            },
            "maps.route": {
                "name": "maps.route",
                "description": "Generate route and navigation data",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "origin": {
                            "type": "object",
                            "properties": {"lat": {"type": "number"}, "lng": {"type": "number"}},
                            "required": ["lat", "lng"]
                        },
                        "destination": {
                            "type": "object",
                            "properties": {"lat": {"type": "number"}, "lng": {"type": "number"}},
                            "required": ["lat", "lng"]
                        }
                    },
                    "required": ["origin", "destination"]
                },
                "category": "maps",
                "always_available": True
            },
            "maps.track_location": {
                "name": "maps.track_location",
                "description": "Fetch live entity location from external source statelessly",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string"},
                        "source": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["webhook", "api", "sheet", "airtable", "custom"]},
                                "config": {"type": "object"}
                            },
                            "required": ["type", "config"]
                        }
                    },
                    "required": ["entity_id", "source"]
                },
                "category": "maps",
                "always_available": True
            },
            "maps.geofence_check": {
                "name": "maps.geofence_check",
                "description": "Check if a point is inside a delivery zone",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "point": {
                            "type": "object",
                            "properties": {"lat": {"type": "number"}, "lng": {"type": "number"}},
                            "required": ["lat", "lng"]
                        },
                        "zone": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["circle", "polygon"]},
                                "radius_km": {"type": "number"},
                                "center": {
                                    "type": "object",
                                    "properties": {"lat": {"type": "number"}, "lng": {"type": "number"}}
                                }
                            },
                            "required": ["type"]
                        }
                    },
                    "required": ["point", "zone"]
                },
                "category": "maps",
                "always_available": True
            },
            "maps.static_map": {
                "name": "maps.static_map",
                "description": "Generate map preview image URL",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "markers": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "lat": {"type": "number"}, "lng": {"type": "number"}, "label": {"type": "string"}
                                },
                                "required": ["lat", "lng"]
                            }
                        }
                    },
                    "required": ["markers"]
                },
                "category": "maps",
                "always_available": True
            },
            # MCP Operations (Workflows)
            "maps.assign_nearest_rider": {
                "name": "maps.assign_nearest_rider",
                "description": "Find and assign nearest rider based on external config list",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "order_location": {
                            "type": "object",
                            "properties": {"lat": {"type": "number"}, "lng": {"type": "number"}},
                            "required": ["lat", "lng"]
                        },
                        "riders_source": {"type": "object", "description": "External source config for riders"}
                    },
                    "required": ["order_location", "riders_source"]
                },
                "category": "maps",
                "always_available": True
            },
            "maps.estimate_delivery_time": {
                "name": "maps.estimate_delivery_time",
                "description": "Estimate ETA via route calculation",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "origin": {
                            "type": "object",
                            "properties": {"lat": {"type": "number"}, "lng": {"type": "number"}},
                            "required": ["lat", "lng"]
                        },
                        "destination": {
                            "type": "object",
                            "properties": {"lat": {"type": "number"}, "lng": {"type": "number"}},
                            "required": ["lat", "lng"]
                        }
                    },
                    "required": ["origin", "destination"]
                },
                "category": "maps",
                "always_available": True
            },
            "maps.track_order_live": {
                "name": "maps.track_order_live",
                "description": "Fetch rider location and compute ETA dynamically to user destination",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string"},
                        "source": {"type": "object"},
                        "destination": {
                            "type": "object",
                            "properties": {"lat": {"type": "number"}, "lng": {"type": "number"}},
                            "required": ["lat", "lng"]
                        }
                    },
                    "required": ["entity_id", "source", "destination"]
                },
                "category": "maps",
                "always_available": True
            },
            "maps.validate_delivery_zone": {
                "name": "maps.validate_delivery_zone",
                "description": "Check if user address is within business delivery zone",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "customer_location": {
                            "type": "object",
                            "properties": {"lat": {"type": "number"}, "lng": {"type": "number"}},
                            "required": ["lat", "lng"]
                        },
                        "zone": {"type": "object"}
                    },
                    "required": ["customer_location", "zone"]
                },
                "category": "maps",
                "always_available": True
            },
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
                        "use_selenium": {"type": "boolean", "description": "Use full headless browser (slower but loads JS)"},
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
            "web_search": {
                "name": "web_search",
                "description": "Perform live web searches using DuckDuckGo to answer user queries with up-to-date and real-time internet information. Useful for current events, news, specific facts, or deep research.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query to look up on the internet"},
                        "max_results": {"type": "integer", "description": "Maximum number of search results to return", "default": 5}
                    },
                    "required": ["query"]
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
                "_meta": {
                    "ui": {
                        "resourceUri": "ui://mpesa-dashboard/index.html"
                    }
                },
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
            },
            # Order Management - Always available
            "order_management": {
                "name": "order_management",
                "description": "Order processing and capture tools for food, clothing, and retail. Operations: create_order, update_order_status, get_orders, capture_customer_input, validate_order, cancel_order, calculate_order_total, format_order_receipt, format_order_notification.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": [
                                "create_order", "update_order_status", "get_orders", 
                                "capture_customer_input", "validate_order", "cancel_order", 
                                "calculate_order_total", "format_order_receipt", "format_order_notification"
                            ],
                            "description": "The order operation to perform"
                        },
                        "customer_name": {"type": "string"},
                        "items": {"type": "array", "items": {"type": "object"}},
                        "order_id": {"type": "string"},
                        "new_status": {"type": "string"},
                        "order_type": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                "category": "commerce",
                "always_available": True,
                "few_shot_examples": [
                    {
                        "user": "Create an order for John Doe with 2 kg ribeye steak",
                        "tool_call": 'order_management(operation="create_order", customer_name="John Doe", items=[{"name": "Ribeye Steak", "quantity": 2, "unit": "kg", "unit_price": 1500}], order_type="food")',
                        "response": "Order ORD-2026-X created for John Doe"
                    }
                ]
            },
            # Inventory Management - Always available
            "inventory_management": {
                "name": "inventory_management",
                "description": "Inventory and product catalog management tools. Operations: create_product, list_products, update_stock, get_product_by_category, check_stock_availability, search_products.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": [
                                "create_product", "list_products", "update_stock",
                                "get_product_by_category", "check_stock_availability", "search_products"
                            ],
                            "description": "The inventory operation to perform"
                        },
                        "name": {"type": "string"},
                        "category": {"type": "string"},
                        "price": {"type": "number"},
                        "product_id": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                "category": "commerce",
                "always_available": True,
                "few_shot_examples": [
                    {
                        "user": "Create a new product Ribeye Steak under meat category for 1500 per kg",
                        "tool_call": 'inventory_management(operation="create_product", name="Ribeye Steak", category="meat", price=1500, unit_type="kg", cuts=["ribeye"])',
                        "response": "Product Ribeye Steak created successfully"
                    }
                ]
            },
            # Real Estate Management - Always available
            "real_estate_management": {
                "name": "real_estate_management",
                "description": "Real estate workflow tools for property management, rent collection, tenant communication, maintenance tracking, and listing management via WhatsApp. Operations: classify_inquiry, format_rent_reminder, format_payment_receipt, format_listing, classify_maintenance, format_maintenance_response, format_viewing_slots, format_viewing_confirmation, generate_rent_statement, generate_landlord_report, format_tenant_welcome, format_lease_reminder, parse_mpesa_confirmation, format_broadcast_listing, format_escalation_notice.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": [
                                "classify_inquiry",
                                "format_rent_reminder",
                                "format_payment_receipt",
                                "format_listing",
                                "classify_maintenance",
                                "format_maintenance_response",
                                "format_viewing_slots",
                                "format_viewing_confirmation",
                                "generate_rent_statement",
                                "generate_landlord_report",
                                "format_tenant_welcome",
                                "format_lease_reminder",
                                "parse_mpesa_confirmation",
                                "format_broadcast_listing",
                                "format_escalation_notice"
                            ],
                            "description": "The real estate operation to perform"
                        },
                        "message": {"type": "string", "description": "Message text for classify_inquiry, classify_maintenance, or parse_mpesa_confirmation"},
                        "tenant_name": {"type": "string", "description": "Tenant name for formatted messages"},
                        "amount": {"type": "number", "description": "Amount in KES (rent, payment, etc.)"},
                        "unit": {"type": "string", "description": "Property unit identifier"},
                        "due_date": {"type": "string", "description": "Payment due date"},
                        "paybill": {"type": "string", "description": "M-Pesa Paybill number"},
                        "account_number": {"type": "string", "description": "M-Pesa account number"},
                        "reminder_level": {"type": "string", "enum": ["first", "second", "final"], "description": "Rent reminder escalation level"},
                        "property_type": {"type": "string", "description": "Type of property (apartment, house, plot, commercial)"},
                        "bedrooms": {"type": "integer", "description": "Number of bedrooms"},
                        "price": {"type": "number", "description": "Property price"},
                        "location": {"type": "string", "description": "Property location"},
                        "amenities": {"type": "array", "items": {"type": "string"}, "description": "Property amenities"},
                        "listing_type": {"type": "string", "enum": ["rent", "sale"], "description": "Listing type"},
                        "contact_phone": {"type": "string", "description": "Contact phone number"},
                        "contact_name": {"type": "string", "description": "Contact person name"},
                        "landlord_name": {"type": "string", "description": "Landlord or agency name"},
                        "property_name": {"type": "string", "description": "Property or building name"},
                        "payment_method": {"type": "string", "description": "Payment method (default: M-Pesa)"},
                        "transaction_id": {"type": "string", "description": "M-Pesa transaction ID"},
                        "period": {"type": "string", "description": "Billing period (e.g., March 2026)"},
                        "monthly_rent": {"type": "number", "description": "Monthly rent amount"},
                        "payments": {"type": "array", "items": {"type": "object"}, "description": "List of payment records"},
                        "total_units": {"type": "integer", "description": "Total units in property"},
                        "occupied_units": {"type": "integer", "description": "Occupied units count"},
                        "total_rent_expected": {"type": "number", "description": "Total expected rent"},
                        "total_rent_collected": {"type": "number", "description": "Total collected rent"},
                        "maintenance_count": {"type": "integer", "description": "Maintenance request count"},
                        "maintenance_cost": {"type": "number", "description": "Total maintenance cost"},
                        "listings": {"type": "array", "items": {"type": "object"}, "description": "List of property listings for broadcast"},
                        "slots": {"type": "array", "items": {"type": "string"}, "description": "Available viewing time slots"},
                        "rules": {"type": "array", "items": {"type": "string"}, "description": "House rules for tenant welcome"},
                        "expiry_date": {"type": "string", "description": "Lease expiry date"},
                        "days_until_expiry": {"type": "integer", "description": "Days until lease expires"},
                        "issue_type": {"type": "string", "enum": ["rent", "maintenance", "lease"], "description": "Escalation issue type"}
                    },
                    "required": ["operation"]
                },
                "category": "real_estate",
                "always_available": True,
                "few_shot_examples": [
                    {
                        "user": "I need a 2 bedroom apartment in Thika for about 15k",
                        "tool_call": 'real_estate_management(operation="classify_inquiry", message="I need a 2 bedroom apartment in Thika for about 15k")',
                        "response": "Classified as rental_inquiry for apartment (2BR, budget KES 15,000, Thika)"
                    },
                    {
                        "user": "Send a rent reminder to John for 25000 due on 5th",
                        "tool_call": 'real_estate_management(operation="format_rent_reminder", tenant_name="John", amount=25000, due_date="5th March", reminder_level="first")',
                        "response": "Generated friendly first rent reminder for KES 25,000"
                    },
                    {
                        "user": "Create a listing for a 3BR house in Ngoingwa for 35k per month",
                        "tool_call": 'real_estate_management(operation="format_listing", property_type="house", bedrooms=3, price=35000, location="Ngoingwa", listing_type="rent")',
                        "response": "Formatted WhatsApp listing: 3BR House in Ngoingwa — KES 35,000/month"
                    }
                ]
            },
            # RAG & Knowledge Base Tools - Always available
            "rag_ingest_content": {
                "name": "rag_ingest_content",
                "description": "Universal Knowledge Ingestion: Ingest any text, markdown, or JSON data into a specific Knowledge Base. Supports single items or lists from Google, Zoho, Slack, etc.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "any", "description": "Text, JSON, or list of items to ingest"},
                        "kb_id": {"type": "string", "description": "The UUID of the Knowledge Base"},
                        "namespace": {"type": "string", "description": "Vector namespace (optional)"},
                        "source_url": {"type": "string", "description": "Optional source override"}
                    },
                    "required": ["content", "kb_id"]
                },
                "category": "advanced",
                "always_available": True
            },
            "rag_search": {
                "name": "rag_search",
                "description": "Knowledge Search: Search your Knowledge Base using semantic queries to retrieve relevant context. When session_key is provided (from WhatsApp/Telegram triggers), vague follow-up queries are automatically rewritten using conversation history for accurate retrieval.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The semantic search query"},
                        "kb_id": {"type": "string", "description": "The UUID of the Knowledge Base"},
                        "namespace": {"type": "string"},
                        "top_k": {"type": "integer", "default": 5},
                        "session_key": {
                            "type": "string",
                            "description": "Conversation session key for context-aware search. Use {{session_key}} from WhatsApp/Telegram trigger data to automatically resolve vague follow-up queries (e.g. 'How much does it cost?' → 'What is the price of men plain tshirt?')."
                        }
                    },
                    "required": ["query", "kb_id"]
                },
                "category": "advanced",
                "always_available": True
            },
            # AI Text Generation — The "Brain" for workflows
            "ai_text_generation": {
                "name": "ai_text_generation",
                "description": "AI Text Generation Brain — Use AI to generate responses, summarize content, classify text, extract information, or transform data using context from previous workflow steps. Perfect as the 'Brain' between data retrieval (e.g. RAG Search) and output actions (e.g. Send Message). Operations: generate, summarize, classify, extract, translate.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["generate", "summarize", "classify", "extract", "translate"],
                            "description": "The AI operation to perform: 'generate' for free-form responses, 'summarize' to condense text, 'classify' to categorize input, 'extract' to pull structured data, 'translate' to convert between languages"
                        },
                        "prompt": {
                            "type": "string",
                            "description": "The user question, instruction, or text to process"
                        },
                        "context": {
                            "type": "any",
                            "description": "Context from previous workflow steps (e.g. RAG search results, database rows, API responses). Accepts text string, list of objects, or dict."
                        },
                        "system_prompt": {
                            "type": "string",
                            "description": "System-level instructions that control AI behavior and personality (e.g. 'You are a helpful sales assistant for a butchery. Always include prices and stock levels.')"
                        },
                        "temperature": {
                            "type": "number",
                            "description": "Creativity level: 0.0 = deterministic/factual, 1.0 = creative/varied. Use 0.1-0.3 for factual answers, 0.7-1.0 for creative content.",
                            "default": 0.3
                        },
                        "max_tokens": {
                            "type": "integer",
                            "description": "Maximum length of AI response in tokens (~4 chars per token). Use 150 for short replies, 500 for detailed answers, 1000+ for long-form content.",
                            "default": 500
                        },
                        "target_language": {
                            "type": "string",
                            "description": "Target language for translate operation (e.g. 'Swahili', 'French', 'Spanish')"
                        },
                        "session_key": {
                            "type": "string",
                            "description": "Conversation session key for multi-turn context memory. Use {{session_key}} from WhatsApp/Telegram trigger data to enable context-aware responses across messages."
                        }
                    },
                    "required": ["operation", "prompt"]
                },
                "category": "ai",
                "always_available": True,
                "few_shot_examples": [
                    {
                        "user": "Use AI to answer a customer question using RAG context with conversation memory",
                        "tool_call": 'ai_text_generation(operation="generate", prompt="{{telegram_message}}", context="{{step_1.result}}", system_prompt="You are a helpful sales assistant. Always include product price, stock status, and image links.", session_key="{{session_key}}")',
                        "response": "AI-generated response based on knowledge base context with conversation history for multi-turn follow-ups"
                    },
                    {
                        "user": "Summarize the search results from step 1",
                        "tool_call": 'ai_text_generation(operation="summarize", prompt="Summarize these product results for a customer", context="{{step_1.result}}")',
                        "response": "Concise summary of the retrieved product information"
                    },
                    {
                        "user": "Classify this customer message as inquiry, complaint, or order",
                        "tool_call": 'ai_text_generation(operation="classify", prompt="{{telegram_message}}", system_prompt="Classify this message into: inquiry, complaint, order, greeting, or other. Respond with only the category.")',
                        "response": "inquiry"
                    }
                ]
            },
            # Conversational Agent — Agentic AI for WhatsApp/Telegram
            "conversational_agent": {
                "name": "conversational_agent",
                "description": "AI-powered conversational agent with inner tool-calling. Autonomously browses your Knowledge Base, captures customer details, creates orders, and notifies the business — all within a single workflow step. Perfect for WhatsApp/Telegram ordering bots.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "user_message": {
                            "type": "string",
                            "description": "The incoming customer message. Use {{whatsapp_message_content}} or {{telegram_message}} from trigger data."
                        },
                        "session_key": {
                            "type": "string",
                            "description": "Conversation session key for multi-turn context. Use {{session_key}} from trigger data."
                        },
                        "business_config": {
                            "type": "object",
                            "description": "Business-specific configuration",
                            "properties": {
                                "kb_id": {"type": "string", "description": "Knowledge Base ID for product/menu search"},
                                "business_name": {"type": "string", "description": "Business name shown to customers"},
                                "business_phone": {"type": "string", "description": "Business owner phone for notifications"},
                                "business_email": {"type": "string", "description": "Business email for notifications"},
                                "order_type": {"type": "string", "enum": ["food", "clothing", "retail", "general"]},
                                "currency": {"type": "string", "default": "KES"},
                                "delivery_methods": {"type": "array", "items": {"type": "string"}},
                                "system_prompt": {"type": "string", "description": "Additional AI instructions"}
                            }
                        }
                    },
                    "required": ["user_message", "session_key", "business_config"]
                },
                "category": "ai",
                "always_available": True,
                "few_shot_examples": [
                    {
                        "user": "Deploy an ordering agent for a meat shop on WhatsApp",
                        "tool_call": 'conversational_agent(user_message="{{whatsapp_message_content}}", session_key="{{session_key}}", business_config={"kb_id": "tians-menu-kb", "business_name": "Tians Meat & Grill", "order_type": "food", "currency": "KES"})',
                        "response": "AI agent processes the message, searches menu, and handles ordering"
                    }
                ]
            }
        }
    
    async def get_user_tools(self, user_id: uuid.UUID, db: AsyncSession, include_all: bool = False) -> List[Dict[str, Any]]:
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
            elif connection.platform == "whatsapp":
                tools.extend(self._get_whatsapp_tools(connection))
            elif connection.platform == "instagram":
                tools.extend(self._get_instagram_tools(connection))
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
            elif connection.platform == "xero":
                tools.extend(self._get_xero_tools(connection))
            elif connection.platform == "clickup":
                tools.extend(self._get_clickup_tools(connection))
            elif connection.platform == "quickbooks":
                tools.extend(self._get_quickbooks_tools(connection))
            elif connection.platform in platform_registry.platforms:
                # Dynamically fetch tools for regional platforms (hr_hub, logistics_hub, etc.)
                p_tools = platform_registry.get_platform_tools(connection.platform)
                for tool in p_tools:
                    tool["connection_id"] = connection.id
                    tool["status"] = "available"
                    tool["id"] = tool["name"]
                    tools.append(tool)
        
        # Add Telegram tools if configured globally
        if settings.TELEGRAM_BOT_TOKEN:
            tools.extend(self._get_telegram_tools())
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
                "instagram_send_dm",
                "telegram_send_message",
                "context_intelligence",
                "marketing_campaign_automation",
                "campaign_performance_tracking",
                "file_management",
                "web_tools",
                "web_search",
                "content_creation",
                "email_template",
                "real_estate_management",
                "order_management",
                "inventory_management",
                "rag_ingest_content",
                "rag_search",
                "conversational_agent",
                "whatsapp_send_message"
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
    
    def _get_instagram_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get Instagram tools for a connection."""
        return [
            {
                "name": "instagram_send_dm",
                "description": "Send a direct message to an Instagram user via Meta Graph API",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "recipient_id": {"type": "string", "description": "The Instagram Scoped ID (IGSID) of the recipient"},
                        "message": {"type": "string", "description": "Message context to send"}
                    },
                    "required": ["recipient_id", "message"]
                },
                "connection_id": connection.id,
                "platform": "instagram",
                "status": "available",
                "id": "instagram_send_dm"
            }
        ]

    def _get_whatsapp_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get WhatsApp tools for a connection."""
        return [
            {
                "name": "whatsapp_send_message",
                "description": "Send a text message or auto-reply to a WhatsApp contact.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "to_number": {
                            "type": "string",
                            "description": "The recipient's phone number (e.g. {{whatsapp_contact_phone}} from trigger variables)"
                        },
                        "message": {
                            "type": "string",
                            "description": "The text message content to send"
                        }
                    },
                    "required": ["to_number", "message"]
                },
                "connection_id": connection.id,
                "platform": "whatsapp",
                "status": "available",
                "id": "whatsapp_send_message"
            }
        ]

    def _get_telegram_tools(self, connection: Connection = None) -> List[Dict[str, Any]]:
        """Get Telegram tools for a connection or global bot."""
        return [
            {
                "name": "telegram_send_message",
                "description": "Send a text message to a Telegram chat",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "chat_id": {"type": "string", "description": "The Telegram Chat ID to send the message to"},
                        "message": {"type": "string", "description": "Message context to send"}
                    },
                    "required": ["chat_id", "message"]
                },
                "connection_id": connection.id if connection else "global",
                "platform": "telegram",
                "status": "available",
                "id": "telegram_send_message"
            }
        ]

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
                "description": "Send a message to a Slack channel, or reply to a thread if thread_ts is provided",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string", "description": "Channel name or ID"},
                        "message": {"type": "string", "description": "Message to send"},
                        "thread_ts": {"type": "string", "description": "Timestamp of the parent message to reply to"}
                    },
                    "required": ["channel", "message"]
                },
                "connection_id": connection.id,
                "platform": "slack",
                "status": "available",
                "id": "slack_send_message"
            },
            {
                "name": "slack_update_message",
                "description": "Update an existing Slack message",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string", "description": "Channel ID"},
                        "ts": {"type": "string", "description": "Timestamp of the message to update"},
                        "message": {"type": "string", "description": "New message content"}
                    },
                    "required": ["channel", "ts", "message"]
                },
                "connection_id": connection.id,
                "platform": "slack",
                "status": "available",
                "id": "slack_update_message"
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
                "description": "Comprehensive HubSpot contact management - read, create, update, search, segment, and associate contacts",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["read", "create", "update", "search", "segment", "associate"]},
                        "contact_data": {"type": "object", "description": "Contact fields: email (required), firstname, lastname, company, phone"},
                        "filters": {"type": "object", "description": "Filters for search/segment operations"},
                        "limit": {"type": "integer", "default": 50},
                        "contact_id": {"type": "string", "description": "Contact ID for update/associate operations"},
                        "properties": {"type": "array", "items": {"type": "string"}, "description": "Contact properties to include"},
                        "to_object_type": {"type": "string", "description": "Target object type for association"},
                        "to_object_id": {"type": "string", "description": "Target object ID for association"},
                        "association_type": {"type": "string", "description": "Association type definition"}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "hubspot",
                "status": "available",
                "id": "hubspot_contact_operations"
            },
            {
                "name": "hubspot_company_operations",
                "description": "Manage HubSpot companies",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["get"]},
                        "company_id": {"type": "string", "description": "Company ID"}
                    },
                    "required": ["operation", "company_id"]
                },
                "connection_id": connection.id,
                "platform": "hubspot",
                "status": "available",
                "id": "hubspot_company_operations"
            },
            {
                "name": "hubspot_engagement_operations",
                "description": "Create HubSpot engagements (notes, tasks, calls, emails, meetings)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create"]},
                        "engagement_data": {"type": "object", "description": "Engagement details (type, owner, etc.)"},
                        "associations": {"type": "object", "description": "Entity associations (contacts, deals, etc.)"}
                    },
                    "required": ["operation", "engagement_data"]
                },
                "connection_id": connection.id,
                "platform": "hubspot",
                "status": "available",
                "id": "hubspot_engagement_operations"
            },
            {
                "name": "hubspot_sequence_operations",
                "description": "Enroll contacts in HubSpot sequences",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["enroll", "get_enrollment"]},
                        "contact_id": {"type": "string"},
                        "sequence_id": {"type": "string"},
                        "sender_email": {"type": "string"},
                        "enrollment_id": {"type": "string"}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "hubspot",
                "status": "available",
                "id": "hubspot_sequence_operations"
            },
            {
                "name": "hubspot_email_templates",
                "description": "Create HubSpot email templates",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create"]},
                        "template_data": {"type": "object", "description": "Template data: name, subject, html"}
                    },
                    "required": ["operation", "template_data"]
                },
                "connection_id": connection.id,
                "platform": "hubspot",
                "status": "available",
                "id": "hubspot_email_templates"
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
                "name": "salesforce_general_operations",
                "description": "General Salesforce CRM operations - Create, Update, Get, or Convert records dynamically.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["create", "update", "get", "convert_lead"]},
                        "object_name": {"type": "string", "description": "Salesforce object name (e.g., Lead, Opportunity, Account, Task, Activity)"},
                        "record_id": {"type": "string", "description": "ID of the record to update/get/convert"},
                        "record_data": {"type": "object", "description": "Data to create or update"},
                        "fields": {"type": "array", "items": {"type": "string"}, "description": "Fields to retrieve on 'get'"}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "salesforce",
                "status": "available",
                "id": "salesforce_general_operations"
            },
            {
                "name": "salesforce_query",
                "description": "Execute a custom SOQL query in Salesforce CRM",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The exact SOQL query string"}
                    },
                    "required": ["query"]
                },
                "connection_id": connection.id,
                "platform": "salesforce",
                "status": "available",
                "id": "salesforce_query"
            },
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
                "description": "Gmail operations: send emails, read inbox, search emails, manage labels, create drafts, list drafts, get draft, update draft, watch inbox for push notifications, and mark emails as read. Supports operations: send_email, read_emails, search_emails, create_label, apply_label, create_draft, list_drafts, get_draft, update_draft, delete_email, get_email_details, watch_inbox, stop_watch, mark_as_read.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["send_email", "read_emails", "search_emails", "create_label", "apply_label", "create_draft", "list_drafts", "get_draft", "update_draft", "delete_email", "get_email_details", "watch_inbox", "stop_watch", "mark_as_read"],
                            "description": "Gmail operation to perform"
                        },
                        "to": {"type": "string", "description": "Recipient email (for send_email, create_draft, update_draft)"},
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
                "_meta": {
                    "ui": {
                        "resourceUri": "ui://google-workspace/index.html"
                    }
                },
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
                "_meta": {
                    "ui": {
                        "resourceUri": "ui://google-workspace/index.html"
                    }
                },
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
                            "enum": ["upload_file", "download_file", "list_files", "create_folder", "delete_file", "share_file", "search_files", "get_metadata", "move_file", "list_folders"],
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
                "description": "Google Sheets operations: create spreadsheets, read/write ranges, append rows, clear ranges, batch update, get spreadsheet info, update spreadsheet properties.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["create_spreadsheet", "read_range", "write_range", "append_rows", "clear_range", "batch_update", "get_info", "update_spreadsheet_properties"],
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
                            "enum": ["create_document", "read_document", "read_all_documents", "insert_text", "append_text", "replace_text", "format_text", "insert_table", "batch_update", "export_pdf"],
                            "description": "Docs operation to perform"
                        },
                        "document_id": {"type": "string"},
                        "title": {"type": "string"},
                        "text": {"type": "string"},
                        "folder_id": {
                            "type": "string", 
                            "description": "Folder ID to restrict search",
                            "x-dynamic-options": "google_workspace_drive.list_folders"
                        },
                        "query": {"type": "string", "description": "Search query for documents"}
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
    
    def _get_xero_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get Xero Accounting tools for a connection."""
        return [
            {
                "name": "xero_accounting",
                "description": "Xero Accounting operations: get company info, invoices, contacts, accounts, payments, and financial reports (Profit & Loss, Balance Sheet).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": [
                                "get_company_info",
                                "get_invoices",
                                "create_invoice",
                                "get_contacts",
                                "get_accounts",
                                "create_payment",
                                "get_profit_loss",
                                "get_balance_sheet"
                            ],
                            "description": "Xero accounting operation to perform"
                        },
                        "start_date": {"type": "string", "description": "Start date filter (YYYY-MM-DD)"},
                        "end_date": {"type": "string", "description": "End date filter (YYYY-MM-DD)"},
                        "status": {"type": "string", "description": "Invoice status filter (DRAFT, SUBMITTED, AUTHORISED, PAID)"},
                        "contact_id": {"type": "string", "description": "Contact/customer ID for filtering"},
                        "max_results": {"type": "integer", "description": "Maximum results to return", "default": 100},
                        "line_items": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Line items for invoice creation (each with description, quantity, unit_price, account_code)"
                        },
                        "due_date": {"type": "string", "description": "Due date for invoice (YYYY-MM-DD)"},
                        "reference": {"type": "string", "description": "Reference text for invoice or payment"},
                        "invoice_id": {"type": "string", "description": "Invoice ID for payment recording"},
                        "account_id": {"type": "string", "description": "Account ID for payment recording"},
                        "amount": {"type": "number", "description": "Payment amount"},
                        "date": {"type": "string", "description": "Payment or report date (YYYY-MM-DD)"},
                        "account_type": {"type": "string", "description": "Account type filter for get_accounts"}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "xero",
                "status": "available",
                "id": "xero_accounting"
            }
        ]

    def _get_clickup_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get ClickUp tools for a connection."""
        return [
            {
                "name": "clickup_task_management",
                "description": "ClickUp task management: get tasks, create tasks, update tasks, delete tasks, add comments, and manage task statuses.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["get_tasks", "create_task", "update_task", "delete_task", "add_comment", "get_task"],
                            "description": "ClickUp task operation to perform"
                        },
                        "list_id": {"type": "string", "description": "ClickUp List ID to get/create tasks in"},
                        "task_id": {"type": "string", "description": "Task ID for update/delete/get operations"},
                        "name": {"type": "string", "description": "Task name"},
                        "description": {"type": "string", "description": "Task description"},
                        "status": {"type": "string", "description": "Task status"},
                        "priority": {"type": "integer", "description": "Task priority (1=Urgent, 2=High, 3=Normal, 4=Low)"},
                        "assignees": {"type": "array", "items": {"type": "integer"}, "description": "List of assignee user IDs"},
                        "due_date": {"type": "string", "description": "Due date (Unix timestamp in ms or ISO string)"},
                        "comment_text": {"type": "string", "description": "Comment text to add"},
                        "include_closed": {"type": "boolean", "description": "Include closed tasks", "default": False}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "clickup",
                "status": "available",
                "id": "clickup_task_management"
            },
            {
                "name": "clickup_resource_management",
                "description": "ClickUp resource management: get spaces, folders, lists, and workspace hierarchy.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["get_spaces", "get_folders", "get_lists", "get_workspace"],
                            "description": "ClickUp resource operation to perform"
                        },
                        "space_id": {"type": "string", "description": "Space ID"},
                        "folder_id": {"type": "string", "description": "Folder ID"}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "clickup",
                "status": "available",
                "id": "clickup_resource_management"
            }
        ]

    def _get_quickbooks_tools(self, connection: Connection) -> List[Dict[str, Any]]:
        """Get QuickBooks Accounting tools for a connection."""
        return [
            {
                "name": "quickbooks_accounting",
                "description": "QuickBooks Accounting operations: get invoices, create invoices, get customers, create customers, get expenses, get vendors, get payments, and financial reports.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": [
                                "get_company_info",
                                "get_invoices",
                                "create_invoice",
                                "get_customers",
                                "create_customer",
                                "get_expenses",
                                "get_vendors",
                                "get_payments",
                                "get_profit_loss",
                                "get_balance_sheet"
                            ],
                            "description": "QuickBooks accounting operation to perform"
                        },
                        "start_date": {"type": "string", "description": "Start date filter (YYYY-MM-DD)"},
                        "end_date": {"type": "string", "description": "End date filter (YYYY-MM-DD)"},
                        "customer_id": {"type": "string", "description": "Customer ID for filtering"},
                        "max_results": {"type": "integer", "description": "Maximum results to return", "default": 100},
                        "line_items": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Line items for invoice creation"
                        },
                        "due_date": {"type": "string", "description": "Due date for invoice (YYYY-MM-DD)"},
                        "customer_data": {"type": "object", "description": "Customer data for creation"},
                        "invoice_id": {"type": "string", "description": "Invoice ID"},
                        "amount": {"type": "number", "description": "Payment amount"}
                    },
                    "required": ["operation"]
                },
                "connection_id": connection.id,
                "platform": "quickbooks",
                "status": "available",
                "id": "quickbooks_accounting"
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
            "zoho": self._get_zoho_tools,
            "xero": self._get_xero_tools,
            "clickup": self._get_clickup_tools,
            "quickbooks": self._get_quickbooks_tools
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
    
    async def get_tools_for_llm(self, user_id: uuid.UUID = None, db: AsyncSession = None) -> List[Dict[str, Any]]:
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
    
    async def get_available_tools(self, user_id: uuid.UUID = None, db: AsyncSession = None) -> List[Dict[str, Any]]:
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

    async def get_tool_descriptions(self, user_id: uuid.UUID = None, db: AsyncSession = None) -> str:
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

    # ===== Code Mode v2 Helper Methods =====

    def search_tools_by_query(self, query: str, category: str = None, limit: int = 20) -> List[Dict[str, str]]:
        """
        Search for tools matching a query string (for Code Mode discovery).
        
        Uses keyword matching across tool names and descriptions.
        Returns compact results (name + description only).
        """
        from .tool_discovery_service import tool_discovery_service
        
        # Build cache from all known tools
        all_tools = list(self.base_tools.values())
        try:
            all_tools.extend(platform_registry.get_all_tools())
        except Exception:
            pass
        
        tool_discovery_service.update_cache(all_tools)
        return tool_discovery_service.search_tools(query, category, limit)

    def get_tool_schema_by_name(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Get the full schema for a specific tool (for Code Mode discovery).
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return None
        return {
            "name": tool.get("name"),
            "description": tool.get("description", ""),
            "category": tool.get("category", "general"),
            "inputSchema": tool.get("inputSchema", {}),
        }

    def list_tool_categories(self) -> List[Dict[str, Any]]:
        """
        List all available tool categories with tool counts (for Code Mode discovery).
        """
        from .tool_discovery_service import tool_discovery_service
        
        all_tools = list(self.base_tools.values())
        try:
            all_tools.extend(platform_registry.get_all_tools())
        except Exception:
            pass
        
        tool_discovery_service.update_cache(all_tools)
        return tool_discovery_service.list_categories()


# Global dynamic tool registry instance
dynamic_tool_registry = DynamicToolRegistry() 