"""
Workflow Templates — Pre-built agent blueprints for multi-business deployment.

Provides template definitions and instantiation logic so any business can
deploy a WhatsApp/Telegram ordering agent by filling in their config
(KB ID, business name, notification phone, etc.) instead of manually
wiring workflow steps.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Workflow, WorkflowStep, WorkflowStatus, WorkflowTriggerType

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# TEMPLATE DEFINITIONS
# ═══════════════════════════════════════════════════════════════

AGENT_TEMPLATES: Dict[str, Dict[str, Any]] = {

    # ── WhatsApp Rent Collection Agent ──────────────────────────────
    "whatsapp_rent_collection_agent": {
        "name": "WhatsApp Rent Collection Agent",
        "description": (
            "AI-powered WhatsApp agent for property managers. Automates rent collection, "
            "utility billing (water, electricity, garbage), tenant inquiries, and M-Pesa payments."
        ),
        "icon": "🏢",
        "industry_tags": ["real_estate", "property_management", "rent_collection"],
        "platform": "whatsapp",
        
        "estimated_setup": "5 minutes",
        "trigger": {
            "type": "event",
            "platform": "whatsapp",
            "event_type": "whatsapp_message_received"
        },
        "required_config": {
            "property_name": {
                "label": "Property Name",
                "type": "text",
                "description": "Name of the property/estate",
                "required": True
            },
            "landlord_name": {
                "label": "Landlord / Manager Name",
                "type": "text",
                "required": True
            },
            "business_phone": {
                "label": "Notification Phone",
                "type": "phone",
                "description": "Phone number to receive collection reports",
                "required": True
            },
            "paybill_number": {
                "label": "M-Pesa Paybill / Till Number",
                "type": "text",
                "description": "Your M-Pesa collection Paybill or Till number",
                "required": True
            },
            "kb_id": {
                "label": "Knowledge Base (Optional)",
                "type": "kb_select",
                "description": "KB with property rules, FAQs, lease terms",
                "required": False
            },
            "water_billing_enabled": { "type": "boolean", "default": True, "label": "Enable Water Billing" },
            "electricity_billing_enabled": { "type": "boolean", "default": True, "label": "Enable Electricity Billing" },
            "garbage_billing_enabled": { "type": "boolean", "default": True, "label": "Enable Garbage Billing" },
            "water_flat_rate": { "type": "number", "default": 0, "description": "Flat water rate per unit (0 = meter-based)", "label": "Water Flat Rate" },
            "garbage_monthly_fee": { "type": "number", "default": 300, "label": "Garbage Monthly Fee" },
            "rent_due_day": { "type": "number", "default": 5, "description": "Day of month rent is due", "label": "Rent Due Day" },
            "storage_provider": {
                "label": "Tenant Data Storage",
                "type": "select",
                "description": "Where to store tenant records and payments",
                "required": True,
                "options": [
                    {"value": "google_sheets", "label": "📊 Google Sheets"},
                    {"value": "airtable",      "label": "🔲 Airtable"}
                ],
                "default": "google_sheets"
            },
            "storage_spreadsheet_id": {
                "label": "Google Sheets Spreadsheet ID",
                "type": "text",
                "required": False,
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_tenants_sheet_name": { 
                "label": "Tenants Sheet Name", "type": "text", "default": "Tenants",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_payments_sheet_name": { 
                "label": "Payments Sheet Name", "type": "text", "default": "Payments",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "currency": { "label": "Currency", "type": "text", "default": "KES" },
            "supported_languages": { "label": "Languages", "type": "text", "default": "en,sw" },
            "reminder_schedule": {
                "type": "select",
                "label": "Reminder Schedule",
                "options": [
                    {"value": "5_before_due_after", "label": "5 days before + on due date + 5 days after"},
                    {"value": "on_due_only", "label": "On due date only"},
                    {"value": "manual_only", "label": "Manual only (no auto-reminders)"}
                ],
                "default": "5_before_due_after"
            }
        }
    },

    # ── WhatsApp Ordering Agent ──────────────────────────────
    "whatsapp_ordering_agent": {
        "name": "WhatsApp Ordering Agent",
        "description": (
            "AI-powered WhatsApp ordering agent with menu/catalog browsing, "
            "conversational order capture, and automatic business notifications. "
            "Supports food, clothing, and retail businesses."
        ),
        "icon": "🛒",
        "industry_tags": ["food", "retail", "clothing", "restaurant", "ecommerce"],
        "platform": "whatsapp",
        
        "estimated_setup": "5 minutes",
        "trigger": {
            "type": "event",
            "platform": "whatsapp",
            "event_type": "whatsapp_message_received"
        },
        "required_config": {
            "kb_id": {
                "label": "Knowledge Base",
                "type": "kb_select",
                "description": "Select the Knowledge Base containing your products/menu",
                "required": True
            },
            "business_name": {
                "label": "Business Name",
                "type": "text",
                "description": "Your business name (shown to customers)",
                "required": True
            },
            "business_phone": {
                "label": "Notification Phone",
                "type": "phone",
                "description": "Phone number to receive order notifications (with country code)",
                "required": True,
                "placeholder": "+254..."
            },
            "business_email": {
                "label": "Notification Email",
                "type": "email",
                "description": "Email to receive order notifications",
                "required": False,
                "placeholder": "orders@yourbusiness.com"
            },
            "order_type": {
                "label": "Business Type",
                "type": "select",
                "description": "Your industry — affects the AI assistant's personality",
                "required": True,
                "options": [
                    {"value": "food", "label": "🍖 Food / Restaurant"},
                    {"value": "clothing", "label": "👕 Clothing / Fashion"},
                    {"value": "retail", "label": "🏪 General Retail"},
                    {"value": "general", "label": "📦 Other"}
                ],
                "default": "food"
            },
            "currency": {
                "label": "Currency",
                "type": "text",
                "description": "Currency code for prices",
                "required": True,
                "default": "KES"
            },
            "delivery_methods": {
                "label": "Delivery Methods",
                "type": "multi_select",
                "description": "How customers can receive their orders",
                "required": True,
                "options": [
                    {"value": "delivery", "label": "🚚 Delivery"},
                    {"value": "pickup", "label": "📍 Pickup"},
                    {"value": "dine_in", "label": "🍽️ Dine In"}
                ],
                "default": ["delivery", "pickup"]
            },
            "reservations_enabled": {
                "label": "Table Reservations",
                "type": "boolean",
                "description": "Let customers book a table (date, time, party size). Best for restaurants.",
                "required": False,
                "default": False,
                "show_if": {"field": "order_type", "value": "food"},
            },
            "system_prompt": {
                "label": "Custom Instructions (Optional)",
                "type": "textarea",
                "description": "Additional instructions for the AI agent (e.g. business hours, special offers)",
                "required": False,
                "placeholder": "e.g. We are open Mon-Sat 8am-8pm. Free delivery for orders over KES 2000."
            },
            "storage_provider": {
                "label": "Order Storage",
                "type": "select",
                "description": "Where to save orders and customer data for record-keeping",
                "required": False,
                "options": [
                    {"value": "none",          "label": "📝 No Storage (notifications only)"},
                    {"value": "google_sheets", "label": "📊 Google Sheets"},
                    {"value": "airtable",      "label": "🔲 Airtable"}
                ],
                "default": "none"
            },
            "storage_spreadsheet_id": {
                "label": "Google Sheets Spreadsheet ID",
                "type": "text",
                "description": "The spreadsheet ID from your Google Sheets URL",
                "required": False,
                "placeholder": "e.g. 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_orders_sheet_name": {
                "label": "Orders Sheet Name",
                "type": "text",
                "description": "Tab name for saving orders in Google Sheets",
                "required": False,
                "placeholder": "Orders",
                "default": "Orders",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_customers_sheet_name": {
                "label": "Customers Sheet Name",
                "type": "text",
                "description": "Tab name for saving customers in Google Sheets",
                "required": False,
                "placeholder": "Customers",
                "default": "Customers",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_transactions_sheet_name": {
                "label": "Transactions Sheet Name",
                "type": "text",
                "description": "Tab name for saving successful payment transactions in Google Sheets",
                "required": False,
                "placeholder": "Transactions",
                "default": "Transactions",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_airtable_base_id": {
                "label": "Airtable Base ID",
                "type": "text",
                "description": "Your Airtable base ID (starts with 'app')",
                "required": False,
                "placeholder": "e.g. appXXXXXXXXXXXXXX",
                "show_if": {"field": "storage_provider", "value": "airtable"}
            },
            "storage_airtable_orders_table": {
                "label": "Airtable Orders Table Name",
                "type": "text",
                "description": "Table name for storing orders",
                "required": False,
                "placeholder": "Orders",
                "default": "Orders",
                "show_if": {"field": "storage_provider", "value": "airtable"}
            },
            "storage_airtable_customers_table": {
                "label": "Airtable Customers Table Name",
                "type": "text",
                "description": "Table name for storing customers",
                "required": False,
                "placeholder": "Customers",
                "default": "Customers",
                "show_if": {"field": "storage_provider", "value": "airtable"}
            },
            "storage_airtable_transactions_table": {
                "label": "Airtable Transactions Table Name",
                "type": "text",
                "description": "Table name for storing successful payment transactions",
                "required": False,
                "placeholder": "Transactions",
                "default": "Transactions",
                "show_if": {"field": "storage_provider", "value": "airtable"}
            },
            "storage_reservations_sheet_name": {
                "label": "Reservations Sheet Name",
                "type": "text",
                "description": "Tab name for saving table reservations in Google Sheets",
                "required": False,
                "placeholder": "Reservations",
                "default": "Reservations",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_airtable_reservations_table": {
                "label": "Airtable Reservations Table Name",
                "type": "text",
                "description": "Table name for storing table reservations",
                "required": False,
                "placeholder": "Reservations",
                "default": "Reservations",
                "show_if": {"field": "storage_provider", "value": "airtable"}
            },
            "enabled_mcp_tools": {
                "label": "Enabled MCP Tools",
                "type": "multi_select",
                "description": "Select additional MCP tools the agent can use",
                "required": False,
                "options": [],
                "default": []
            },
            "auto_escalation_enabled": {
                "label": "Smart Escalation",
                "type": "boolean",
                "description": "Automatically hand frustrated or complex chats to a human agent",
                "required": False,
                "default": True
            },
            "supported_languages": {
                "label": "Supported Languages",
                "type": "text",
                "description": "Comma-separated codes: en,sw,fr,ar,es",
                "required": False,
                "default": "en,sw,fr,ar,es"
            },
            "human_handoff_ttl_hours": {
                "label": "Handoff Auto-Resume (hours)",
                "type": "number",
                "description": "Resume AI after this many hours (0 = manual release only)",
                "required": False,
                "default": 24
            }
        },
        "steps": [
            {
                "tool_name": "conversational_agent",
                "description": "AI agent handles conversation, menu browsing, and order creation",
                "parameters": {
                    "session_key": "{{session_key}}",
                    "user_message": "{{whatsapp_message_content}}",
                    "business_config": {
                        "kb_id": "{{config.kb_id}}",
                        "business_name": "{{config.business_name}}",
                        "business_phone": "{{config.business_phone}}",
                        "business_email": "{{config.business_email}}",
                        "order_type": "{{config.order_type}}",
                        "currency": "{{config.currency}}",
                        "delivery_methods": "{{config.delivery_methods}}",
                        "reservations_enabled": "{{config.reservations_enabled}}",
                        "system_prompt": "{{config.system_prompt}}",
                        "storage_provider": "{{config.storage_provider}}",
                        "storage_spreadsheet_id": "{{config.storage_spreadsheet_id}}",
                        "storage_orders_sheet_name": "{{config.storage_orders_sheet_name}}",
                        "storage_customers_sheet_name": "{{config.storage_customers_sheet_name}}",
                        "storage_transactions_sheet_name": "{{config.storage_transactions_sheet_name}}",
                        "storage_reservations_sheet_name": "{{config.storage_reservations_sheet_name}}",
                        "storage_airtable_base_id": "{{config.storage_airtable_base_id}}",
                        "storage_airtable_orders_table": "{{config.storage_airtable_orders_table}}",
                        "storage_airtable_customers_table": "{{config.storage_airtable_customers_table}}",
                        "storage_airtable_transactions_table": "{{config.storage_airtable_transactions_table}}",
                        "storage_airtable_reservations_table": "{{config.storage_airtable_reservations_table}}",
                        "enabled_mcp_tools": "{{config.enabled_mcp_tools}}",
                        "auto_escalation_enabled": "{{config.auto_escalation_enabled}}",
                        "supported_languages": "{{config.supported_languages}}",
                        "human_handoff_ttl_hours": "{{config.human_handoff_ttl_hours}}"
                    }
                }
            },
            {
                "tool_name": "whatsapp_send_message",
                "description": "Send AI response back to customer",
                "parameters": {
                    "operation": "send_message",
                    "to_number": "{{whatsapp_contact_phone}}",
                    "message": "{{step_1.response_text}}",
                    "image_urls": "{{step_1.image_urls}}",
                    "send_cart_buttons": "{{step_1.send_cart_buttons}}",
                    "session_key": "{{session_key}}"
                }
            },
            {
                "tool_name": "whatsapp_send_message",
                "description": "Notify business owner of new order (WhatsApp)",
                "condition": {
                    "type": "if",
                    "field": "step_1.order_created",
                    "operator": "equals",
                    "value": True
                },
                "parameters": {
                    "operation": "send_message",
                    "to_number": "{{config.business_phone}}",
                    "message": "{{step_1.order_notification}}"
                }
            },
            {
                "tool_name": "whatsapp_send_message",
                "description": "Notify business owner of cancelled order (WhatsApp)",
                "condition": {
                    "type": "if",
                    "field": "step_1.order_cancelled",
                    "operator": "equals",
                    "value": True
                },
                "parameters": {
                    "operation": "send_message",
                    "to_number": "{{config.business_phone}}",
                    "message": "{{step_1.order_notification}}"
                }
            },
            {
                "tool_name": "whatsapp_send_message",
                "description": "Alert business owner — customer needs a human agent",
                "condition": {
                    "type": "if",
                    "field": "step_1.escalation_triggered",
                    "operator": "equals",
                    "value": True
                },
                "parameters": {
                    "operation": "send_message",
                    "to_number": "{{config.business_phone}}",
                    "message": "{{step_1.escalation_notification}}"
                }
            }
        ]
    },

    # ── Telegram Ordering Agent ──────────────────────────────
    "telegram_ordering_agent": {
        "name": "Telegram Ordering Agent",
        "description": (
            "AI-powered Telegram ordering agent with product browsing, "
            "conversational order capture, and automatic business notifications."
        ),
        "icon": "🤖",
        "industry_tags": ["food", "retail", "clothing", "restaurant", "ecommerce"],
        "platform": "telegram",
        "estimated_setup": "5 minutes",
        "trigger": {
            "type": "event",
            "platform": "telegram",
            "event_type": "telegram_message_received"
        },
        "required_config": {
            "kb_id": {
                "label": "Knowledge Base",
                "type": "kb_select",
                "description": "Select the Knowledge Base containing your products/menu",
                "required": True
            },
            "business_name": {
                "label": "Business Name",
                "type": "text",
                "description": "Your business name (shown to customers)",
                "required": True
            },
            "business_phone": {
                "label": "Notification Phone",
                "type": "phone",
                "description": "Phone number for SMS/WhatsApp order notifications",
                "required": False,
                "placeholder": "+254..."
            },
            "business_email": {
                "label": "Notification Email",
                "type": "email",
                "description": "Email to receive order notifications",
                "required": False,
                "placeholder": "orders@yourbusiness.com"
            },
            "order_type": {
                "label": "Business Type",
                "type": "select",
                "description": "Your industry — affects the AI assistant's personality",
                "required": True,
                "options": [
                    {"value": "food", "label": "🍖 Food / Restaurant"},
                    {"value": "clothing", "label": "👕 Clothing / Fashion"},
                    {"value": "retail", "label": "🏪 General Retail"},
                    {"value": "general", "label": "📦 Other"}
                ],
                "default": "food"
            },
            "currency": {
                "label": "Currency",
                "type": "text",
                "description": "Currency code for prices",
                "required": True,
                "default": "KES"
            },
            "delivery_methods": {
                "label": "Delivery Methods",
                "type": "multi_select",
                "description": "How customers can receive their orders",
                "required": True,
                "options": [
                    {"value": "delivery", "label": "🚚 Delivery"},
                    {"value": "pickup", "label": "📍 Pickup"},
                    {"value": "dine_in", "label": "🍽️ Dine In"}
                ],
                "default": ["delivery", "pickup"]
            },
            "system_prompt": {
                "label": "Custom Instructions (Optional)",
                "type": "textarea",
                "description": "Additional instructions for the AI agent",
                "required": False,
                "placeholder": "e.g. We deliver within Nakuru CBD only."
            },
            "storage_provider": {
                "label": "Order Storage",
                "type": "select",
                "description": "Where to save orders and customer data for record-keeping",
                "required": False,
                "options": [
                    {"value": "none",          "label": "📝 No Storage (notifications only)"},
                    {"value": "google_sheets", "label": "📊 Google Sheets"},
                    {"value": "airtable",      "label": "🔲 Airtable"}
                ],
                "default": "none"
            },
            "storage_spreadsheet_id": {
                "label": "Google Sheets Spreadsheet ID",
                "type": "text",
                "description": "The spreadsheet ID from your Google Sheets URL",
                "required": False,
                "placeholder": "e.g. 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_orders_sheet_name": {
                "label": "Orders Sheet Name",
                "type": "text",
                "description": "Tab name for saving orders in Google Sheets",
                "required": False,
                "placeholder": "Orders",
                "default": "Orders",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_customers_sheet_name": {
                "label": "Customers Sheet Name",
                "type": "text",
                "description": "Tab name for saving customers in Google Sheets",
                "required": False,
                "placeholder": "Customers",
                "default": "Customers",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_transactions_sheet_name": {
                "label": "Transactions Sheet Name",
                "type": "text",
                "description": "Tab name for saving successful payment transactions in Google Sheets",
                "required": False,
                "placeholder": "Transactions",
                "default": "Transactions",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_airtable_base_id": {
                "label": "Airtable Base ID",
                "type": "text",
                "description": "Your Airtable base ID (starts with 'app')",
                "required": False,
                "placeholder": "e.g. appXXXXXXXXXXXXXX",
                "show_if": {"field": "storage_provider", "value": "airtable"}
            },
            "storage_airtable_orders_table": {
                "label": "Airtable Orders Table Name",
                "type": "text",
                "description": "Table name for storing orders",
                "required": False,
                "placeholder": "Orders",
                "default": "Orders",
                "show_if": {"field": "storage_provider", "value": "airtable"}
            },
            "storage_airtable_customers_table": {
                "label": "Airtable Customers Table Name",
                "type": "text",
                "description": "Table name for storing customers",
                "required": False,
                "placeholder": "Customers",
                "default": "Customers",
                "show_if": {"field": "storage_provider", "value": "airtable"}
            },
            "storage_airtable_transactions_table": {
                "label": "Airtable Transactions Table Name",
                "type": "text",
                "description": "Table name for storing successful payment transactions",
                "required": False,
                "placeholder": "Transactions",
                "default": "Transactions",
                "show_if": {"field": "storage_provider", "value": "airtable"}
            },
            "enabled_mcp_tools": {
                "label": "Enabled MCP Tools",
                "type": "multi_select",
                "description": "Select additional MCP tools the agent can use",
                "required": False,
                "options": [],
                "default": []
            }
        },
        "steps": [
            {
                "tool_name": "conversational_agent",
                "description": "AI agent handles conversation, product browsing, and order creation",
                "parameters": {
                    "session_key": "{{session_key}}",
                    "user_message": "{{telegram_message}}",
                    "business_config": {
                        "kb_id": "{{config.kb_id}}",
                        "business_name": "{{config.business_name}}",
                        "business_phone": "{{config.business_phone}}",
                        "business_email": "{{config.business_email}}",
                        "order_type": "{{config.order_type}}",
                        "currency": "{{config.currency}}",
                        "delivery_methods": "{{config.delivery_methods}}",
                        "system_prompt": "{{config.system_prompt}}",
                        "storage_provider": "{{config.storage_provider}}",
                        "storage_spreadsheet_id": "{{config.storage_spreadsheet_id}}",
                        "storage_orders_sheet_name": "{{config.storage_orders_sheet_name}}",
                        "storage_customers_sheet_name": "{{config.storage_customers_sheet_name}}",
                        "storage_transactions_sheet_name": "{{config.storage_transactions_sheet_name}}",
                        "storage_airtable_base_id": "{{config.storage_airtable_base_id}}",
                        "storage_airtable_orders_table": "{{config.storage_airtable_orders_table}}",
                        "storage_airtable_customers_table": "{{config.storage_airtable_customers_table}}",
                        "storage_airtable_transactions_table": "{{config.storage_airtable_transactions_table}}",
                        "enabled_mcp_tools": "{{config.enabled_mcp_tools}}"
                    }
                }
            },
            {
                "tool_name": "telegram_send_message",
                "description": "Send AI response back to customer",
                "parameters": {
                    "chat_id": "{{chat_id}}",
                    "message": "{{step_1.response_text}}",
                    "image_urls": "{{step_1.image_urls}}"
                }
            }
        ]
    },

    # ── WhatsApp Customer Support Agent ──────────────────────
    "whatsapp_support_agent": {
        "name": "WhatsApp Support Agent",
        "description": (
            "AI-powered WhatsApp support agent that answers customer questions "
            "using your Knowledge Base. No ordering — purely informational."
        ),
        "icon": "💬",
        "industry_tags": ["support", "saas", "services", "general"],
        "platform": "whatsapp",
        "estimated_setup": "3 minutes",
        "trigger": {
            "type": "event",
            "platform": "whatsapp",
            "event_type": "whatsapp_message_received"
        },
        "required_config": {
            "kb_id": {
                "label": "Knowledge Base",
                "type": "kb_select",
                "description": "Select the Knowledge Base with your FAQs, docs, or product info",
                "required": True
            },
            "business_name": {
                "label": "Business Name",
                "type": "text",
                "description": "Your business name",
                "required": True
            },
            "system_prompt": {
                "label": "Custom Instructions (Optional)",
                "type": "textarea",
                "description": "Instructions for the AI (e.g. tone, escalation rules)",
                "required": False,
                "placeholder": "e.g. Be professional and concise. If the customer asks for a refund, direct them to support@company.com."
            }
        },
        "steps": [
            {
                "tool_name": "rag_search",
                "description": "Search knowledge base for relevant information",
                "parameters": {
                    "query": "{{whatsapp_message_content}}",
                    "kb_id": "{{config.kb_id}}",
                    "top_k": 5,
                    "session_key": "{{session_key}}"
                }
            },
            {
                "tool_name": "ai_text_generation",
                "description": "Generate contextual response using KB results",
                "parameters": {
                    "operation": "generate",
                    "prompt": "{{whatsapp_message_content}}",
                    "context": "{{step_1.result}}",
                    "system_prompt": "You are a helpful customer support assistant for {{config.business_name}}. Answer based on the provided context. Be concise and friendly (WhatsApp style). {{config.system_prompt}}",
                    "session_key": "{{session_key}}",
                    "temperature": 0.3,
                    "max_tokens": 500
                }
            },
            {
                "tool_name": "whatsapp_send_message",
                "description": "Reply to customer",
                "parameters": {
                    "operation": "send_message",
                    "to_number": "{{whatsapp_contact_phone}}",
                    "message": "{{step_2.result}}",
                }
            }
        ]
    }
}


# ═══════════════════════════════════════════════════════════════
# TEMPLATE SERVICE
# ═══════════════════════════════════════════════════════════════

class WorkflowTemplateService:
    """Service for managing and instantiating workflow templates."""

    def list_templates(
        self, platform: Optional[str] = None, industry: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List available agent templates with optional filtering."""
        templates = []

        for template_id, template in AGENT_TEMPLATES.items():
            # Apply platform filter
            if platform and template.get("platform") != platform:
                continue

            # Apply industry filter
            if industry and industry not in template.get("industry_tags", []):
                continue

            templates.append({
                "id": template_id,
                "name": template["name"],
                "description": template["description"],
                "icon": template.get("icon", "🤖"),
                "platform": template.get("platform", ""),
                "industry_tags": template.get("industry_tags", []),
                "estimated_setup": template.get("estimated_setup", ""),
                "required_config": template.get("required_config", {}),
                "steps_count": len(template.get("steps", [])),
                "tools_used": [s["tool_name"] for s in template.get("steps", [])]
            })

        return templates

    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Get a single template definition by ID."""
        template = AGENT_TEMPLATES.get(template_id)
        if not template:
            return None

        return {
            "id": template_id,
            **template
        }

    async def create_workflow_from_template(
        self,
        template_id: str,
        config: Dict[str, Any],
        user_id: uuid.UUID,
        db: AsyncSession,
        workflow_name: Optional[str] = None
    ) -> Workflow:
        """
        Instantiate a workflow from a template with user-provided config.

        Args:
            template_id: The template to use
            config: Business-specific config values (kb_id, business_name, etc.)
            user_id: The business owner's user ID
            db: Database session
            workflow_name: Optional custom workflow name

        Returns:
            The created Workflow ORM object
        """
        template = AGENT_TEMPLATES.get(template_id)
        if not template:
            raise ValueError(f"Unknown template: {template_id}")

        # Validate required config
        required = template.get("required_config", {})
        for field_name, field_def in required.items():
            if field_def.get("required", False) and not config.get(field_name):
                raise ValueError(
                    f"Missing required config: {field_def.get('label', field_name)}"
                )

        # Apply defaults for missing optional config
        for field_name, field_def in required.items():
            if field_name not in config and "default" in field_def:
                config[field_name] = field_def["default"]

        # Build workflow name
        business_name = config.get("business_name", "My Business")
        name = workflow_name or f"{template['name']} — {business_name}"

        # Create the workflow
        workflow = Workflow(
            user_id=user_id,
            name=name,
            description=template["description"],
            status=WorkflowStatus.ACTIVE,
            trigger_type=WorkflowTriggerType.EVENT,
            trigger_config={
                "platform": template["trigger"]["platform"],
                "event_type": template["trigger"]["event_type"]
            },
            variables={
                "config": config,
                "template_id": template_id,
                "created_from_template": True
            },
            workflow_metadata={
                "template_id": template_id,
                "template_name": template["name"],
                "business_name": business_name,
                "platform": template.get("platform", ""),
                "industry_tags": template.get("industry_tags", []),
                "created_at": datetime.utcnow().isoformat()
            },
            version=1,
            is_template=False
        )

        db.add(workflow)
        await db.flush()

        # Create workflow steps
        for i, step_def in enumerate(template.get("steps", []), start=1):
            step = WorkflowStep(
                workflow_id=workflow.id,
                step_number=i,
                tool_name=step_def["tool_name"],
                tool_parameters=step_def.get("parameters", {}),
                description=step_def.get("description", ""),
                condition=step_def.get("condition"),
                retry_config=step_def.get("retry_config", {"max_retries": 2, "retry_delay": 3}),
                timeout=step_def.get("timeout", 60)
            )
            db.add(step)

        await db.commit()
        await db.refresh(workflow)

        logger.info(
            f"[TEMPLATES] Created workflow '{name}' from template "
            f"'{template_id}' for user {user_id}"
        )

        return workflow


# Global instance
workflow_template_service = WorkflowTemplateService()
