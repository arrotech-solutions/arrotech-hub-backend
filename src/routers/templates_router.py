"""
Workflow templates router for Mini-Hub.
Provides pre-built starter templates for common use cases.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, Workflow, WorkflowStep, WorkflowStatus, WorkflowTriggerType
from ..routers.auth_router import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


# Pre-built workflow templates
WORKFLOW_TEMPLATES = [
    {
        "id": "whatsapp_real_estate_agent",
        "name": "WhatsApp Real Estate Agent",
        "description": "AI-powered WhatsApp real estate agent for lead qualification, listing assistance, and viewing handoff.",
        "icon": "🏠",
        "category": "Customer Support",
        "difficulty": "intermediate",
        "estimated_time": "6 mins",
        "tags": ["whatsapp", "real estate", "ai", "leads", "viewings"],
        "required_connections": ["whatsapp", "rag_pipeline"],
        "trigger_type": WorkflowTriggerType.EVENT,
        "trigger_config": {
            "platform": "whatsapp",
            "event_type": "whatsapp_message_received"
        },
        "steps": [
            {
                "step_number": 1,
                "tool_name": "conversational_agent",
                "tool_parameters": {
                    "session_key": "{{session_key}}",
                    "user_message": "{{whatsapp_message_content}}",
                    "business_config": {
                        "kb_id": "{{variables.kb_id}}",
                        "business_name": "{{variables.business_name}}",
                        "business_phone": "{{variables.business_phone}}",
                        "business_email": "{{variables.business_email}}",
                        "order_type": "real_estate",
                        "currency": "{{variables.currency}}",
                        "service_areas": "{{variables.service_areas}}",
                        "default_listing_type": "{{variables.default_listing_type}}",
                        "crm_provider": "{{variables.crm_provider}}",
                        "crm_spreadsheet_id": "{{variables.crm_spreadsheet_id}}",
                        "scheduling_provider": "{{variables.scheduling_provider}}",
                        "calendar_link": "{{variables.calendar_link}}",
                        "followup_days": "{{variables.followup_days}}",
                        "qualification_fields": "{{variables.qualification_fields}}",
                        "response_style": "{{variables.response_style}}",
                        "enabled_mcp_tools": "{{variables.enabled_mcp_tools}}",
                        "auto_escalation_enabled": "{{variables.auto_escalation_enabled}}",
                        "supported_languages": "{{variables.supported_languages}}",
                        "human_handoff_ttl_hours": "{{variables.human_handoff_ttl_hours}}",
                        "system_prompt": "{{variables.system_prompt}}"
                    }
                },
                "description": "AI handles lead qualification, listing guidance, and viewing flow"
            },
            {
                "step_number": 2,
                "tool_name": "whatsapp_send_message",
                "tool_parameters": {
                    "operation": "send_message",
                    "to_number": "{{whatsapp_contact_phone}}",
                    "message": "{{step_1.response_text}}",
                    "image_urls": "{{step_1.image_urls}}",
                    "send_cart_buttons": "{{step_1.send_cart_buttons}}",
                    "session_key": "{{session_key}}"
                },
                "description": "Send AI response back to customer"
            },
            {
                "step_number": 3,
                "tool_name": "whatsapp_send_message",
                "tool_parameters": {
                    "operation": "send_message",
                    "to_number": "{{variables.business_phone}}",
                    "message": "{{step_1.escalation_notification}}"
                },
                "description": "Notify agency when AI escalates to a human",
                "condition": {
                    "type": "if",
                    "field": "step_1.escalation_triggered",
                    "operator": "equals",
                    "value": True
                },
            }
        ],
        "variables": {
            "kb_id": {
                "type": "string", "required": True, "description": "Knowledge Base ID containing properties", "connection_for": "rag_pipeline"
            },
            "business_name": {
                "type": "string", "required": True, "description": "Agency name (shown to clients)"
            },
            "business_phone": {
                "type": "string", "required": True, "description": "Phone number to receive lead notifications", "connection_for": "whatsapp"
            },
            "business_email": {
                "type": "string", "required": False, "description": "Optional email for lead notifications"
            },
            "currency": {
                "type": "string", "default": "KES"
            },
            "service_areas": {
                "type": "string",
                "description": "Comma-separated areas served by agency",
                "default": "Nairobi, Kiambu, Thika"
            },
            "default_listing_type": {
                "type": "string",
                "enum": ["rent", "sale", "both"],
                "default": "both",
                "description": "Primary property mode for this assistant"
            },
            "crm_provider": {
                "type": "string",
                "description": "CRM target for lead sync",
                "enum": ["none", "hubspot", "google_sheets", "salesforce"],
                "default": "none"
            },
            "crm_spreadsheet_id": {
                "type": "string",
                "description": "If using Google Sheets CRM, select spreadsheet ID",
                "x-dynamic-ui": "google_workspace_drive.list_spreadsheets"
            },
            "scheduling_provider": {
                "type": "string",
                "description": "Viewing scheduling mode",
                "enum": ["native", "calendly", "google_calendar"],
                "default": "native"
            },
            "calendar_link": {
                "type": "string",
                "description": "Calendly or booking link (if external scheduling is used)"
            },
            "followup_days": {
                "type": "string",
                "description": "Days before automated follow-up (0 disables)",
                "default": "2"
            },
            "qualification_fields": {
                "type": "array",
                "items": {"type": "string"},
                "default": ["budget", "location", "property_type", "timeline"],
                "description": "Lead fields to collect progressively in chat"
            },
            "response_style": {
                "type": "string",
                "enum": ["professional", "warm", "concise"],
                "default": "warm"
            },
            "enabled_mcp_tools": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "Optional MCP tools available to this agent"
            },
            "auto_escalation_enabled": {
                "type": "boolean",
                "default": True
            },
            "supported_languages": {
                "type": "string",
                "default": "en,sw"
            },
            "human_handoff_ttl_hours": {
                "type": "number",
                "default": 24
            },
            "system_prompt": {
                "type": "string",
                "required": False,
                "description": "Custom operating instructions for this agency"
            }
        }
    },
    {
        "id": "marketing-email-campaign",
        "name": "Email Marketing Campaign",
        "description": "Automate email campaign creation and sending with HubSpot integration",
        "category": "Marketing",
        "icon": "📧",
        "difficulty": "beginner",
        "estimated_time": "5 mins",
        "tags": ["email", "marketing", "hubspot", "automation"],
        "required_connections": ["hubspot"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "hubspot_create_contact",
                "tool_parameters": {
                    "email": "{{input.email}}",
                    "firstname": "{{input.first_name}}",
                    "lastname": "{{input.last_name}}"
                },
                "description": "Create or update contact in HubSpot"
            },
            {
                "step_number": 2,
                "tool_name": "hubspot_add_to_list",
                "tool_parameters": {
                    "contact_id": "{{step_1.contact_id}}",
                    "list_id": "{{input.campaign_list_id}}"
                },
                "description": "Add contact to campaign list"
            },
            {
                "step_number": 3,
                "tool_name": "hubspot_trigger_workflow",
                "tool_parameters": {
                    "workflow_id": "{{input.hubspot_workflow_id}}",
                    "contact_id": "{{step_1.contact_id}}"
                },
                "description": "Trigger email workflow"
            }
        ],
        "variables": {
            "email": {"type": "string", "required": True, "description": "Contact email"},
            "first_name": {"type": "string", "required": True},
            "last_name": {"type": "string", "required": True},
            "campaign_list_id": {"type": "string", "required": True},
            "hubspot_workflow_id": {"type": "string", "required": True}
        }
    },
    {
        "id": "social-media-scheduler",
        "name": "Social Media Post Scheduler",
        "description": "Schedule and publish posts across multiple social media platforms",
        "category": "Marketing",
        "icon": "📱",
        "difficulty": "intermediate",
        "estimated_time": "10 mins",
        "tags": ["social-media", "scheduling", "automation", "content"],
        "required_connections": ["twitter", "linkedin", "slack"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "generate_social_content",
                "tool_parameters": {
                    "topic": "{{input.topic}}",
                    "tone": "{{input.tone}}",
                    "platforms": "{{input.platforms}}"
                },
                "description": "Generate platform-optimized content"
            },
            {
                "step_number": 2,
                "tool_name": "twitter_post",
                "tool_parameters": {
                    "content": "{{step_1.twitter_content}}",
                    "schedule_time": "{{input.schedule_time}}"
                },
                "description": "Schedule Twitter post",
                "condition": {"if": "twitter in input.platforms"}
            },
            {
                "step_number": 3,
                "tool_name": "linkedin_post",
                "tool_parameters": {
                    "content": "{{step_1.linkedin_content}}",
                    "schedule_time": "{{input.schedule_time}}"
                },
                "description": "Schedule LinkedIn post",
                "condition": {"if": "linkedin in input.platforms"}
            },
            {
                "step_number": 4,
                "tool_name": "slack_notify",
                "tool_parameters": {
                    "channel": "{{input.notification_channel}}",
                    "message": "Posts scheduled for {{input.schedule_time}}"
                },
                "description": "Notify team via Slack"
            }
        ],
        "variables": {
            "topic": {"type": "string", "required": True},
            "tone": {"type": "string", "enum": ["professional", "casual", "humorous"]},
            "platforms": {"type": "array", "items": {"type": "string"}},
            "schedule_time": {"type": "string", "format": "datetime"},
            "notification_channel": {"type": "string", "default": "#marketing"}
        }
    },
    {
        "id": "lead-scoring",
        "name": "Lead Scoring & Qualification",
        "description": "Automatically score and qualify leads based on behavior and demographics",
        "category": "Sales",
        "icon": "🎯",
        "difficulty": "advanced",
        "estimated_time": "15 mins",
        "tags": ["leads", "sales", "scoring", "crm", "hubspot"],
        "required_connections": ["hubspot", "clearbit"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "hubspot_get_contact",
                "tool_parameters": {
                    "email": "{{input.email}}"
                },
                "description": "Get contact from HubSpot"
            },
            {
                "step_number": 2,
                "tool_name": "clearbit_enrich",
                "tool_parameters": {
                    "email": "{{input.email}}"
                },
                "description": "Enrich contact data with Clearbit"
            },
            {
                "step_number": 3,
                "tool_name": "calculate_lead_score",
                "tool_parameters": {
                    "company_size": "{{step_2.company.employees}}",
                    "industry": "{{step_2.company.industry}}",
                    "page_views": "{{step_1.page_views}}",
                    "email_opens": "{{step_1.email_opens}}"
                },
                "description": "Calculate lead score"
            },
            {
                "step_number": 4,
                "tool_name": "hubspot_update_contact",
                "tool_parameters": {
                    "contact_id": "{{step_1.contact_id}}",
                    "properties": {
                        "lead_score": "{{step_3.score}}",
                        "qualification_status": "{{step_3.status}}"
                    }
                },
                "description": "Update lead score in HubSpot"
            }
        ],
        "variables": {
            "email": {"type": "string", "required": True}
        }
    },
    {
        "id": "data-sync-analytics",
        "name": "Analytics Data Sync",
        "description": "Sync analytics data from multiple sources to a central dashboard",
        "category": "Analytics",
        "icon": "📊",
        "difficulty": "intermediate",
        "estimated_time": "10 mins",
        "tags": ["analytics", "data", "sync", "reporting"],
        "required_connections": ["google_analytics", "hubspot", "stripe"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "ga4_get_report",
                "tool_parameters": {
                    "metrics": ["sessions", "users", "pageviews"],
                    "date_range": "{{input.date_range}}"
                },
                "description": "Fetch GA4 analytics"
            },
            {
                "step_number": 2,
                "tool_name": "hubspot_get_analytics",
                "tool_parameters": {
                    "metrics": ["contacts", "deals", "revenue"],
                    "date_range": "{{input.date_range}}"
                },
                "description": "Fetch HubSpot analytics"
            },
            {
                "step_number": 3,
                "tool_name": "stripe_get_metrics",
                "tool_parameters": {
                    "date_range": "{{input.date_range}}"
                },
                "description": "Fetch Stripe revenue data"
            },
            {
                "step_number": 4,
                "tool_name": "aggregate_metrics",
                "tool_parameters": {
                    "ga_data": "{{step_1.data}}",
                    "hubspot_data": "{{step_2.data}}",
                    "stripe_data": "{{step_3.data}}"
                },
                "description": "Aggregate all metrics"
            }
        ],
        "variables": {
            "date_range": {"type": "string", "enum": ["today", "last_7_days", "last_30_days", "this_month"]}
        }
    },
    {
        "id": "customer-onboarding",
        "name": "Customer Onboarding Sequence",
        "description": "Automate customer onboarding with welcome emails, resource sharing, and check-ins",
        "category": "Customer Success",
        "icon": "🎉",
        "difficulty": "beginner",
        "estimated_time": "8 mins",
        "tags": ["onboarding", "customer-success", "email", "automation"],
        "required_connections": ["hubspot", "slack"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "hubspot_create_contact",
                "tool_parameters": {
                    "email": "{{input.customer_email}}",
                    "properties": {
                        "lifecycle_stage": "customer",
                        "signup_date": "{{input.signup_date}}"
                    }
                },
                "description": "Create customer record"
            },
            {
                "step_number": 2,
                "tool_name": "send_welcome_email",
                "tool_parameters": {
                    "to": "{{input.customer_email}}",
                    "template": "welcome_onboarding",
                    "variables": {
                        "name": "{{input.customer_name}}",
                        "plan": "{{input.plan_name}}"
                    }
                },
                "description": "Send welcome email"
            },
            {
                "step_number": 3,
                "tool_name": "slack_notify",
                "tool_parameters": {
                    "channel": "#customer-success",
                    "message": "🎉 New customer: {{input.customer_name}} ({{input.plan_name}})"
                },
                "description": "Notify CS team"
            },
            {
                "step_number": 4,
                "tool_name": "schedule_followup",
                "tool_parameters": {
                    "type": "email",
                    "delay": "3 days",
                    "template": "onboarding_checkin"
                },
                "description": "Schedule 3-day check-in"
            }
        ],
        "variables": {
            "customer_email": {"type": "string", "required": True},
            "customer_name": {"type": "string", "required": True},
            "signup_date": {"type": "string", "format": "date"},
            "plan_name": {"type": "string", "enum": ["starter", "pro", "enterprise"]}
        }
    },
    {
        "id": "invoice-processor",
        "name": "Invoice Processing Automation",
        "description": "Automatically process incoming invoices, extract data, and update accounting",
        "category": "Finance",
        "icon": "💰",
        "difficulty": "advanced",
        "estimated_time": "15 mins",
        "tags": ["invoices", "finance", "automation", "accounting"],
        "required_connections": ["email", "quickbooks"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "extract_invoice_data",
                "tool_parameters": {
                    "file_url": "{{input.invoice_url}}"
                },
                "description": "Extract data from invoice PDF"
            },
            {
                "step_number": 2,
                "tool_name": "validate_vendor",
                "tool_parameters": {
                    "vendor_name": "{{step_1.vendor_name}}",
                    "tax_id": "{{step_1.tax_id}}"
                },
                "description": "Validate vendor details"
            },
            {
                "step_number": 3,
                "tool_name": "quickbooks_create_bill",
                "tool_parameters": {
                    "vendor_id": "{{step_2.vendor_id}}",
                    "amount": "{{step_1.amount}}",
                    "due_date": "{{step_1.due_date}}",
                    "line_items": "{{step_1.line_items}}"
                },
                "description": "Create bill in QuickBooks"
            },
            {
                "step_number": 4,
                "tool_name": "slack_notify",
                "tool_parameters": {
                    "channel": "#finance",
                    "message": "Invoice from {{step_1.vendor_name}} for ${{step_1.amount}} processed"
                },
                "description": "Notify finance team"
            }
        ],
        "variables": {
            "invoice_url": {"type": "string", "required": True}
        }
    },
    {
        "id": "support-ticket-triage",
        "name": "Support Ticket Auto-Triage",
        "description": "Automatically categorize, prioritize, and route support tickets",
        "category": "Customer Support",
        "icon": "🎫",
        "difficulty": "intermediate",
        "estimated_time": "10 mins",
        "tags": ["support", "tickets", "triage", "automation"],
        "required_connections": ["zendesk", "slack"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "analyze_ticket",
                "tool_parameters": {
                    "subject": "{{input.ticket_subject}}",
                    "description": "{{input.ticket_body}}"
                },
                "description": "AI-analyze ticket content"
            },
            {
                "step_number": 2,
                "tool_name": "zendesk_update_ticket",
                "tool_parameters": {
                    "ticket_id": "{{input.ticket_id}}",
                    "category": "{{step_1.category}}",
                    "priority": "{{step_1.priority}}",
                    "tags": "{{step_1.tags}}"
                },
                "description": "Update ticket with categorization"
            },
            {
                "step_number": 3,
                "tool_name": "zendesk_assign",
                "tool_parameters": {
                    "ticket_id": "{{input.ticket_id}}",
                    "group_id": "{{step_1.recommended_group}}"
                },
                "description": "Assign to appropriate team"
            },
            {
                "step_number": 4,
                "tool_name": "slack_notify",
                "tool_parameters": {
                    "channel": "{{step_1.slack_channel}}",
                    "message": "🎫 {{step_1.priority}} ticket: {{input.ticket_subject}}"
                },
                "description": "Alert team on Slack",
                "condition": {"if": "step_1.priority in ['urgent', 'high']"}
            }
        ],
        "variables": {
            "ticket_id": {"type": "string", "required": True},
            "ticket_subject": {"type": "string", "required": True},
            "ticket_body": {"type": "string", "required": True}
        }
    },
    {
        "id": "content-repurposing",
        "name": "Content Repurposing Pipeline",
        "description": "Transform blog posts into social media content, newsletters, and more",
        "category": "Content",
        "icon": "✍️",
        "difficulty": "beginner",
        "estimated_time": "8 mins",
        "tags": ["content", "repurposing", "marketing", "ai"],
        "required_connections": ["openai"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "extract_content",
                "tool_parameters": {
                    "url": "{{input.blog_url}}"
                },
                "description": "Extract content from blog post"
            },
            {
                "step_number": 2,
                "tool_name": "generate_twitter_thread",
                "tool_parameters": {
                    "content": "{{step_1.content}}",
                    "max_tweets": 5
                },
                "description": "Generate Twitter thread"
            },
            {
                "step_number": 3,
                "tool_name": "generate_linkedin_post",
                "tool_parameters": {
                    "content": "{{step_1.content}}",
                    "tone": "professional"
                },
                "description": "Generate LinkedIn post"
            },
            {
                "step_number": 4,
                "tool_name": "generate_newsletter_section",
                "tool_parameters": {
                    "content": "{{step_1.content}}",
                    "max_words": 200
                },
                "description": "Generate newsletter snippet"
            }
        ],
        "variables": {
            "blog_url": {"type": "string", "required": True, "format": "url"}
        }
    },
    {
        "id": "mpesa-verification",
        "name": "M-Pesa Payment Reconciliation",
        "description": "Automatically verify M-Pesa payments and update deal status",
        "category": "Finance",
        "icon": "💸",
        "difficulty": "beginner",
        "estimated_time": "5 mins",
        "tags": ["mpesa", "payments", "reconciliation", "verification"],
        "required_connections": ["mpesa", "hubspot"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "mpesa_payment_reconciliation",
                "tool_parameters": {
                    "operation": "search_payments",
                    "query": "{{input.transaction_id}}"
                },
                "description": "Verify payment on M-Pesa"
            },
            {
                "step_number": 2,
                "tool_name": "hubspot_update_contact",
                "tool_parameters": {
                    "contact_id": "{{input.contact_id}}",
                    "properties": {
                        "payment_status": "verified",
                        "last_mpesa_transaction": "{{step_1.data[0].transaction_id}}"
                    }
                },
                "description": "Update payment status in CRM",
                "condition": {"if": "step_1.success == True and len(step_1.data) > 0"}
            }
        ],
        "variables": {
            "transaction_id": {"type": "string", "required": True, "description": "M-Pesa Transaction ID (e.g., RK92...) "},
            "contact_id": {"type": "string", "required": True}
        }
    },
    {
        "id": "tax-id-verification",
        "name": "Tax ID & Compliance Verification",
        "description": "Instantly verify Tax ID validity and compliance status",
        "category": "Finance",
        "icon": "🛡️",
        "difficulty": "beginner",
        "estimated_time": "3 mins",
        "tags": ["tax", "compliance", "verification"],
        "required_connections": ["context_intelligence"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "context_verification",
                "tool_parameters": {
                    "operation": "verify_pin",
                    "pin": "{{input.tax_id}}"
                },
                "description": "Verify Tax ID validity"
            },
            {
                "step_number": 2,
                "tool_name": "context_verification",
                "tool_parameters": {
                    "operation": "check_compliance",
                    "pin": "{{input.tax_id}}"
                },
                "description": "Check compliance status"
            }
        ],
        "variables": {
            "tax_id": {"type": "string", "required": True, "description": "Business Tax ID (e.g. KRA PIN)"}
        }
    },
    {
        "id": "hr-leave-advisor",
        "name": "HR & Leave Advisor",
        "description": "Bilingual leave management and policy search for regional employees",
        "category": "Human Resources",
        "icon": "⚖️",
        "difficulty": "beginner",
        "estimated_time": "5 mins",
        "tags": ["hr", "policy", "leave", "advisor"],
        "required_connections": ["hr_hub"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "hr_policy_lookup",
                "tool_parameters": {
                    "query": "{{input.question}}",
                    "language": "{{input.language}}"
                },
                "description": "Search company policy in preferred language"
            },
            {
                "step_number": 2,
                "tool_name": "hr_leave_management",
                "tool_parameters": {
                    "operation": "get_balance",
                    "employee_id": "{{input.employee_id}}"
                },
                "description": "Check leave balance",
                "condition": {"if": "'leave' in input.question.lower() or 'likizo' in input.question.lower()"}
            }
        ],
        "variables": {
            "question": {"type": "string", "required": True, "description": "Employee question (supports local languages)"},
            "employee_id": {"type": "string", "default": "me"},
            "language": {"type": "string", "enum": ["english", "swahili"], "default": "english"}
        }
    },
    {
        "id": "lead-qualification-pipeline",
        "name": "Bilingual Lead Qualification",
        "description": "Qualify leads from any source and draft personalized follow-ups",
        "category": "Sales",
        "icon": "⚡",
        "difficulty": "intermediate",
        "estimated_time": "12 mins",
        "tags": ["leads", "sales", "ai", "automation"],
        "required_connections": ["lead_intelligence", "hubspot"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "lead_intelligence_qualification",
                "tool_parameters": {
                    "operation": "extract_info",
                    "text": "{{input.lead_message}}"
                },
                "description": "Extract lead details from message"
            },
            {
                "step_number": 2,
                "tool_name": "lead_intelligence_qualification",
                "tool_parameters": {
                    "operation": "score_lead",
                    "lead_data": "{{step_1.extracted_data}}"
                },
                "description": "Score lead quality"
            },
            {
                "step_number": 3,
                "tool_name": "lead_intelligence_followup",
                "tool_parameters": {
                    "lead_id": "{{step_1.extracted_data.name}}",
                    "tone": "professional"
                },
                "description": "Draft personalized follow-up"
            }
        ],
        "variables": {
            "lead_message": {"type": "string", "required": True, "description": "Raw lead inquiry (WhatsApp, Email, etc.)"}
        }
    },
    {
        "id": "logistics-tracking-hub",
        "name": "Multi-Provider Delivery Tracking",
        "description": "Track shipments across multiple regional logistics providers automatically",
        "category": "Operations",
        "icon": "📦",
        "difficulty": "beginner",
        "estimated_time": "5 mins",
        "tags": ["logistics", "tracking", "shipping"],
        "required_connections": ["logistics_hub"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "logistics_tracking",
                "tool_parameters": {
                    "tracking_number": "{{input.tracking_number}}",
                    "provider": "automatic"
                },
                "description": "Fetch real-time delivery status"
            }
        ],
        "variables": {
            "tracking_number": {"type": "string", "required": True, "description": "Tracking number (e.g. SN-123, G4-ABC)"}
        }
    },
    {
        "id": "mpesa-finance-summary",
        "name": "M-Pesa Daily Financial Summary",
        "description": "Automate daily M-Pesa collections reporting and Slack alerts for finance teams",
        "category": "Finance",
        "icon": "📈",
        "difficulty": "beginner",
        "estimated_time": "5 mins",
        "tags": ["mpesa", "finance", "kenya", "reporting"],
        "required_connections": ["mpesa", "slack"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "mpesa_payment_reconciliation",
                "tool_parameters": {
                    "operation": "search_payments",
                    "query": "today"
                },
                "description": "Fetch today's M-Pesa collections"
            },
            {
                "step_number": 2,
                "tool_name": "slack_team_communication",
                "tool_parameters": {
                    "action": "send_report",
                    "channel": "{{input.report_channel}}",
                    "message": "Daily M-Pesa Collections Summary: {{step_1.total_amount}} KES ({{step_1.transaction_count}} transactions)",
                    "report_type": "finance"
                },
                "description": "Post financial summary to Slack"
            }
        ],
        "variables": {
            "report_channel": {"type": "string", "default": "#finance", "description": "Slack channel for daily reports"}
        }
    },
    {
        "id": "bilingual-support-triage",
        "name": "Bilingual Support Triage",
        "description": "Smart triage system that analyzes sentiment and translates regional inquiries",
        "category": "Customer Support",
        "icon": "🌍",
        "difficulty": "intermediate",
        "estimated_time": "10 mins",
        "tags": ["support", "bilingual", "swahili", "triage"],
        "required_connections": ["context_intelligence", "slack"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "context_sentiment",
                "tool_parameters": {
                    "text": "{{input.customer_message}}"
                },
                "description": "Analyze customer sentiment"
            },
            {
                "step_number": 2,
                "tool_name": "context_translation",
                "tool_parameters": {
                    "text": "{{input.customer_message}}",
                    "target_lang": "{{input.target_lang}}"
                },
                "description": "Translate to target language for internal routing",
                "condition": {"if": "input.message_lang != input.target_lang"}
            },
            {
                "step_number": 3,
                "tool_name": "slack_team_communication",
                "tool_parameters": {
                    "action": "send_alert",
                    "channel": "#customer-service",
                    "message": "Urgent Support Needed ({{step_1.sentiment}}): {{step_2.translated if input.message_lang != input.target_lang else input.customer_message}}"
                },
                "description": "Alert support team on Slack",
                "condition": {"if": "step_1.sentiment == 'negative' or step_1.sentiment == 'frustrated'"}
            }
        ],
        "variables": {
            "customer_message": {"type": "string", "required": True},
            "message_lang": {"type": "string", "enum": ["english", "swahili", "other"], "default": "swahili"},
            "target_lang": {"type": "string", "default": "english", "description": "Language to translate to (e.g. english, french)"}
        }
    },
    {
        "id": "operations-standup-hub",
        "name": "Operations Stand-up Hub",
        "description": "Centralize daily stand-ups with logistics status and team progress insights",
        "category": "Operations",
        "icon": "🏗️",
        "difficulty": "intermediate",
        "estimated_time": "15 mins",
        "tags": ["operations", "logistics", "standup", "kenya"],
        "required_connections": ["slack", "logistics_hub"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "slack_channel_analytics",
                "tool_parameters": {
                    "action": "get_channel_history",
                    "channel": "{{input.standup_channel}}",
                    "limit": 50
                },
                "description": "Gather daily stand-up updates from Slack"
            },
            {
                "step_number": 2,
                "tool_name": "logistics_tracking",
                "tool_parameters": {
                    "tracking_number": "all_active",
                    "provider": "automatic"
                },
                "description": "Check status of active shipments"
            },
            {
                "step_number": 3,
                "tool_name": "slack_team_communication",
                "tool_parameters": {
                    "action": "send_message",
                    "channel": "{{input.ops_channel}}",
                    "message": "Operations Sync Hub:\n- Team Status: {{step_1.summary}}\n- Shipments: {{step_2.active_count}} in transit, {{step_2.delayed_count}} delayed"
                },
                "description": "Post integrated operations report"
            }
        ],
        "variables": {
            "standup_channel": {"type": "string", "default": "#daily-standup"},
            "ops_channel": {"type": "string", "default": "#operations"}
        }
    },
    {
        "id": "hr-onboarding-advisor",
        "name": "HR Onboarding Advisor",
        "description": "Guide new employees through policy lookup and leave balance checks (Bilingual)",
        "category": "Human Resources",
        "icon": "🤝",
        "difficulty": "beginner",
        "estimated_time": "8 mins",
        "tags": ["hr", "onboarding", "policy", "leave"],
        "required_connections": ["hr_hub", "slack"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "hr_policy_lookup",
                "tool_parameters": {
                    "query": "onboarding welcome",
                    "language": "{{input.language}}"
                },
                "description": "Fetch welcoming package info"
            },
            {
                "step_number": 2,
                "tool_name": "hr_leave_management",
                "tool_parameters": {
                    "operation": "get_balance",
                    "employee_id": "{{input.employee_id}}"
                },
                "description": "Verify initial leave allocation"
            },
            {
                "step_number": 3,
                "tool_name": "slack_team_communication",
                "tool_parameters": {
                    "action": "send_message",
                    "channel": "{{input.employee_id}}",
                    "message": "Karibu! Here is your onboarding guide: {{step_1.policy_content}}\nYour current leave balance is {{step_2.balance}} days."
                },
                "description": "DM onboarding details to employee"
            }
        ],
        "variables": {
            "employee_id": {"type": "string", "required": True, "description": "Slack ID of the new employee"},
            "language": {"type": "string", "enum": ["english", "swahili"], "default": "swahili"}
        }
    },
    # ────────────────────────────────────────────────────────────────────────
    # Fintech Workflow Templates (Centiwise & Payment Companies)
    # ────────────────────────────────────────────────────────────────────────
    {
        "id": "fintech-auto-reconciliation",
        "name": "Automated Payment Reconciliation",
        "description": "Pull M-Pesa transactions, match against your Google Sheets ledger, and alert finance on mismatches via Slack — eliminating 80% of manual reconciliation.",
        "category": "Fintech",
        "icon": "🔄",
        "difficulty": "intermediate",
        "estimated_time": "10 mins",
        "tags": ["mpesa", "reconciliation", "fintech", "payments", "google-sheets", "slack"],
        "required_connections": ["mpesa", "google_workspace", "slack"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "mpesa_payment_reconciliation",
                "tool_parameters": {
                    "operation": "get_payments",
                    "status": "all",
                    "limit": 50
                },
                "description": "Pull latest M-Pesa transactions"
            },
            {
                "step_number": 2,
                "tool_name": "google_workspace_sheets",
                "tool_parameters": {
                    "operation": "read_range",
                    "spreadsheet_id": "{{input.ledger_spreadsheet_id}}",
                    "range_name": "{{input.ledger_range}}"
                },
                "description": "Read internal ledger from Google Sheets"
            },
            {
                "step_number": 3,
                "tool_name": "mpesa_payment_reconciliation",
                "tool_parameters": {
                    "operation": "match_payments"
                },
                "description": "Auto-match payments against invoices"
            },
            {
                "step_number": 4,
                "tool_name": "mpesa_payment_reconciliation",
                "tool_parameters": {
                    "operation": "get_unmatched",
                    "limit": 20
                },
                "description": "Identify unmatched/mismatched payments"
            },
            {
                "step_number": 5,
                "tool_name": "google_workspace_sheets",
                "tool_parameters": {
                    "operation": "append_rows",
                    "spreadsheet_id": "{{input.ledger_spreadsheet_id}}",
                    "range_name": "Reconciliation Log!A1",
                    "values": [["{{step_3.matched_count}}", "{{step_4.data}}", "auto-reconciled"]]
                },
                "description": "Log reconciliation results to Google Sheets"
            },
            {
                "step_number": 6,
                "tool_name": "slack_team_communication",
                "tool_parameters": {
                    "action": "send_alert",
                    "channel": "{{input.finance_channel}}",
                    "message": "🔄 Reconciliation Complete\n\n✅ Matched: {{step_3.matched_count}} payments\n⚠️ Unmatched: {{step_3.unmatched_count}} payments\n\nReview unmatched payments in the ledger."
                },
                "description": "Alert finance team on Slack with reconciliation results"
            }
        ],
        "variables": {
            "ledger_spreadsheet_id": {"type": "string", "required": True, "description": "Google Sheets ID of your internal payments ledger"},
            "ledger_range": {"type": "string", "default": "Payments!A1:G1000", "description": "Sheet range containing payment records"},
            "finance_channel": {"type": "string", "default": "#finance", "description": "Slack channel for finance alerts"}
        }
    },
    {
        "id": "fintech-revenue-dashboard",
        "name": "Daily Revenue Dashboard & Alerts",
        "description": "Automatically generate daily M-Pesa revenue summaries with threshold-based alerts — never miss a revenue dip.",
        "category": "Fintech",
        "icon": "📊",
        "difficulty": "beginner",
        "estimated_time": "5 mins",
        "tags": ["revenue", "dashboard", "fintech", "mpesa", "alerts", "daily"],
        "required_connections": ["mpesa", "slack"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "mpesa_payment_reconciliation",
                "tool_parameters": {
                    "operation": "search_payments",
                    "query": "today"
                },
                "description": "Fetch today's M-Pesa revenue summary"
            },
            {
                "step_number": 2,
                "tool_name": "mpesa_payment_reconciliation",
                "tool_parameters": {
                    "operation": "get_summary",
                    "days": 1
                },
                "description": "Get detailed payment breakdown"
            },
            {
                "step_number": 3,
                "tool_name": "slack_team_communication",
                "tool_parameters": {
                    "action": "send_message",
                    "channel": "{{input.dashboard_channel}}",
                    "message": "📊 Daily Revenue Dashboard\n\n💰 Total Revenue: KES {{step_1.total_amount}}\n📈 Transactions: {{step_1.transaction_count}}\n✅ Matched: {{step_2.matched_count}}\n⚠️ Unmatched: {{step_2.unmatched_count}}\n⏳ Pending: {{step_2.pending_count}}"
                },
                "description": "Post revenue dashboard to Slack"
            },
            {
                "step_number": 4,
                "tool_name": "slack_team_communication",
                "tool_parameters": {
                    "action": "send_alert",
                    "channel": "{{input.alert_channel}}",
                    "message": "🚨 REVENUE ALERT: Today's revenue (KES {{step_1.total_amount}}) is below the expected threshold of KES {{input.revenue_threshold}}. Immediate attention required!"
                },
                "description": "Send alert if revenue below threshold",
                "condition": {"if": "step_1.total_amount < input.revenue_threshold"}
            }
        ],
        "variables": {
            "dashboard_channel": {"type": "string", "default": "#finance", "description": "Slack channel for daily dashboard"},
            "alert_channel": {"type": "string", "default": "#finance-alerts", "description": "Slack channel for critical revenue alerts"},
            "revenue_threshold": {"type": "number", "default": 100000, "description": "Minimum expected daily revenue in KES"}
        }
    },
    {
        "id": "fintech-payment-failure-notifications",
        "name": "Payment Failure Notifications",
        "description": "Detect unmatched or failed payments, email customers with payment instructions, and escalate to ops via Slack.",
        "category": "Fintech",
        "icon": "🔔",
        "difficulty": "intermediate",
        "estimated_time": "10 mins",
        "tags": ["payments", "notifications", "fintech", "customer", "email", "escalation"],
        "required_connections": ["mpesa", "google_workspace", "slack"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "mpesa_payment_reconciliation",
                "tool_parameters": {
                    "operation": "get_unmatched",
                    "limit": 10
                },
                "description": "Fetch unmatched/failed payments"
            },
            {
                "step_number": 2,
                "tool_name": "google_workspace_gmail",
                "tool_parameters": {
                    "operation": "send_email",
                    "to": "{{input.finance_email}}",
                    "subject": "⚠️ Unmatched Payments Detected — Action Required",
                    "body": "Hi Finance Team,\n\nWe have detected {{step_1.data.length}} unmatched M-Pesa payments that need review:\n\n{{step_1.result}}\n\nPlease log in to Arrotech Hub to reconcile these transactions.\n\nBest regards,\nArrotech Hub Automation"
                },
                "description": "Email finance team about unmatched payments"
            },
            {
                "step_number": 3,
                "tool_name": "slack_team_communication",
                "tool_parameters": {
                    "action": "send_alert",
                    "channel": "{{input.ops_channel}}",
                    "message": "🔔 Payment Escalation\n\n{{step_1.result}}\n\nFinance team has been emailed. Please review in the reconciliation dashboard."
                },
                "description": "Escalate to ops team on Slack"
            }
        ],
        "variables": {
            "finance_email": {"type": "string", "required": True, "description": "Finance team email for payment failure alerts"},
            "ops_channel": {"type": "string", "default": "#ops-alerts", "description": "Slack channel for ops escalation"}
        }
    },
    {
        "id": "fintech-compliance-audit",
        "name": "Compliance & Audit Trail Report",
        "description": "Generate compliance reports with fraud detection analysis and email them to compliance officers — perfect for regulatory requirements.",
        "category": "Fintech",
        "icon": "🛡️",
        "difficulty": "advanced",
        "estimated_time": "15 mins",
        "tags": ["compliance", "audit", "fraud", "fintech", "regulation", "reporting"],
        "required_connections": ["mpesa", "google_workspace", "slack"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "mpesa_payment_reconciliation",
                "tool_parameters": {
                    "operation": "get_payments",
                    "status": "all",
                    "limit": 100
                },
                "description": "Pull all recent payments for audit period"
            },
            {
                "step_number": 2,
                "tool_name": "mpesa_payment_reconciliation",
                "tool_parameters": {
                    "operation": "get_summary",
                    "days": "{{input.audit_period_days}}"
                },
                "description": "Get payment summary statistics"
            },
            {
                "step_number": 3,
                "tool_name": "mpesa_payment_reconciliation",
                "tool_parameters": {
                    "operation": "match_payments"
                },
                "description": "Run reconciliation for audit trail"
            },
            {
                "step_number": 4,
                "tool_name": "google_workspace_gmail",
                "tool_parameters": {
                    "operation": "send_email",
                    "to": "{{input.compliance_email}}",
                    "subject": "📋 Compliance & Audit Report — {{input.audit_period_days}}-Day Period",
                    "body": "Compliance Report Summary\n\nPeriod: Last {{input.audit_period_days}} days\n\n{{step_2.result}}\n\nReconciliation Results:\n- Total Processed: {{step_3.total_processed}}\n- Successfully Matched: {{step_3.matched_count}}\n- Unmatched (Review Required): {{step_3.unmatched_count}}\n\nFull details available in Arrotech Hub dashboard.\n\nGenerated automatically by Arrotech Hub."
                },
                "description": "Email compliance report to officers"
            },
            {
                "step_number": 5,
                "tool_name": "slack_team_communication",
                "tool_parameters": {
                    "action": "send_message",
                    "channel": "{{input.compliance_channel}}",
                    "message": "📋 Compliance Report Generated\n\nPeriod: Last {{input.audit_period_days}} days\n{{step_2.result}}\n\nFull report emailed to compliance team."
                },
                "description": "Notify compliance channel on Slack"
            }
        ],
        "variables": {
            "audit_period_days": {"type": "number", "default": 30, "description": "Number of days to include in audit report"},
            "compliance_email": {"type": "string", "required": True, "description": "Email address for compliance officer(s)"},
            "compliance_channel": {"type": "string", "default": "#compliance", "description": "Slack channel for compliance notifications"}
        }
    },
    {
        "id": "fintech-ops-ticket",
        "name": "Cross-Platform Ops Ticket Automation",
        "description": "Automatically create Jira tickets for unmatched payments and notify the ops team via Slack — never lose track of payment issues.",
        "category": "Fintech",
        "icon": "🎫",
        "difficulty": "intermediate",
        "estimated_time": "10 mins",
        "tags": ["ops", "jira", "tickets", "fintech", "automation", "payments"],
        "required_connections": ["mpesa", "jira", "slack"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "mpesa_payment_reconciliation",
                "tool_parameters": {
                    "operation": "get_unmatched",
                    "limit": 5
                },
                "description": "Get top unmatched payments requiring attention"
            },
            {
                "step_number": 2,
                "tool_name": "jira_issue_management",
                "tool_parameters": {
                    "operation": "create_issue",
                    "project_key": "{{input.jira_project}}",
                    "summary": "[Auto] Unmatched M-Pesa Payments — Review Required",
                    "description": "The following M-Pesa payments could not be auto-matched to any invoice:\n\n{{step_1.result}}\n\nPlease investigate and manually reconcile.",
                    "issue_type": "Task",
                    "priority": "High",
                    "labels": ["payment-reconciliation", "auto-generated"]
                },
                "description": "Create Jira ticket for unmatched payments"
            },
            {
                "step_number": 3,
                "tool_name": "slack_team_communication",
                "tool_parameters": {
                    "action": "send_message",
                    "channel": "{{input.ops_channel}}",
                    "message": "🎫 New Ops Ticket Created\n\nUnmatched payments detected and Jira ticket created automatically.\n\n{{step_1.result}}\n\nJira ticket: {{step_2.key}}"
                },
                "description": "Notify ops team on Slack about new ticket"
            }
        ],
        "variables": {
            "jira_project": {"type": "string", "required": True, "description": "Jira project key (e.g., FIN, OPS)"},
            "ops_channel": {"type": "string", "default": "#ops-team", "description": "Slack channel for ops notifications"}
        }
    },
    {
        "id": "fintech-executive-kpi",
        "name": "Executive KPI Summary",
        "description": "Generate a comprehensive KPI report including revenue, reconciliation status, and invoice health — delivered to executives via Slack and email.",
        "category": "Fintech",
        "icon": "👔",
        "difficulty": "beginner",
        "estimated_time": "5 mins",
        "tags": ["executive", "kpi", "fintech", "reporting", "leadership"],
        "required_connections": ["mpesa", "slack", "google_workspace"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "mpesa_payment_reconciliation",
                "tool_parameters": {
                    "operation": "get_summary",
                    "days": "{{input.period_days}}"
                },
                "description": "Get revenue summary for the period"
            },
            {
                "step_number": 2,
                "tool_name": "mpesa_payment_reconciliation",
                "tool_parameters": {
                    "operation": "list_invoices",
                    "status": "pending",
                    "limit": 10
                },
                "description": "Get outstanding invoices"
            },
            {
                "step_number": 3,
                "tool_name": "slack_team_communication",
                "tool_parameters": {
                    "action": "send_message",
                    "channel": "{{input.exec_channel}}",
                    "message": "👔 Executive KPI Report (Last {{input.period_days}} days)\n\n{{step_1.result}}\n\n📋 Pending Invoices:\n{{step_2.result}}\n\n💡 Recommendation: Review unmatched payments and follow up on pending invoices."
                },
                "description": "Post KPI summary to executive Slack channel"
            },
            {
                "step_number": 4,
                "tool_name": "google_workspace_gmail",
                "tool_parameters": {
                    "operation": "send_email",
                    "to": "{{input.exec_email}}",
                    "subject": "📊 Executive KPI Report — Last {{input.period_days}} Days",
                    "body": "Executive KPI Summary\n\n{{step_1.result}}\n\nPending Invoices:\n{{step_2.result}}\n\nView full details at hub.arrotechsolutions.com\n\n— Arrotech Hub Automation"
                },
                "description": "Email KPI report to executive",
                "condition": {"if": "input.exec_email"}
            }
        ],
        "variables": {
            "period_days": {"type": "number", "default": 7, "description": "Number of days for the KPI period (e.g., 7, 14, 30)"},
            "exec_channel": {"type": "string", "default": "#leadership", "description": "Slack channel for executive reports"},
            "exec_email": {"type": "string", "required": False, "description": "Executive email for report delivery (optional)"}
        }
    },
    # ────────────────────────────────────────────────────────────────────────
    # Real Estate Workflow Templates (Thika Property Management)
    # ────────────────────────────────────────────────────────────────────────
    {
        "id": "re-auto-inquiry-response",
        "name": "Auto Property Inquiry Response",
        "description": "Automatically classify incoming WhatsApp property inquiries (rent, buy, viewing) and send an instant personalized response with matching listings. Works in English and Swahili.",
        "category": "Real Estate",
        "icon": "🏠",
        "difficulty": "beginner",
        "estimated_time": "5 mins",
        "tags": ["whatsapp", "real-estate", "leads", "auto-reply", "thika", "property"],
        "required_connections": ["whatsapp"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "real_estate_management",
                "tool_parameters": {
                    "operation": "classify_inquiry",
                    "message": "{{input.whatsapp_message_content}}"
                },
                "description": "Classify the incoming message — detect intent (rent/buy/viewing), property type, bedrooms, budget, and location"
            },
            {
                "step_number": 2,
                "tool_name": "whatsapp_messaging",
                "tool_parameters": {
                    "action": "send_message",
                    "to_number": "{{input.whatsapp_contact_phone}}",
                    "message": "Hello {{input.whatsapp_contact_name}}! 👋\n\nThank you for your inquiry. We've noted your interest:\n🏷️ Looking for: {{step_1.property_type}}\n💰 Budget: {{step_1.budget}}\n📍 Area: {{step_1.location}}\n\nOur agent will get back to you shortly with matching properties. In the meantime, reply 'VIEW' to schedule a property viewing.\n\n_{{input.agency_name}}_"
                },
                "description": "Send instant personalized acknowledgment via WhatsApp"
            },
            {
                "step_number": 3,
                "tool_name": "whatsapp_messaging",
                "tool_parameters": {
                    "action": "send_message",
                    "to_number": "{{input.agent_phone}}",
                    "message": "📩 New Lead Alert!\n\n👤 {{input.whatsapp_contact_name}} ({{input.whatsapp_contact_phone}})\n🏷️ Intent: {{step_1.primary_intent}}\n🏠 Type: {{step_1.property_type}}\n💰 Budget: {{step_1.budget}}\n📍 Location: {{step_1.location}}\n⚡ Urgency: {{step_1.urgency}}\n\nOriginal message: {{input.whatsapp_message_content}}"
                },
                "description": "Forward lead details to the property agent for follow-up",
                "condition": {"if": "input.agent_phone"}
            }
        ],
        "variables": {
            "whatsapp_message_content": {"type": "string", "required": True, "description": "Incoming WhatsApp message from the prospect"},
            "whatsapp_contact_phone": {"type": "string", "required": True, "description": "Prospect's phone number"},
            "whatsapp_contact_name": {"type": "string", "default": "Customer", "description": "Prospect's name"},
            "agent_phone": {"type": "string", "required": False, "description": "Agent phone to forward leads to"},
            "agency_name": {"type": "string", "default": "Property Management", "description": "Your agency name for sign-off"}
        }
    },
    {
        "id": "re-rent-collection-pipeline",
        "name": "Rent Collection Pipeline",
        "description": "Automated 3-stage rent collection via WhatsApp: friendly reminder before due date, overdue follow-up, and final notice with escalation to landlord. Includes M-Pesa payment details.",
        "category": "Real Estate",
        "icon": "💰",
        "difficulty": "beginner",
        "estimated_time": "5 mins",
        "tags": ["rent", "collection", "whatsapp", "mpesa", "reminder", "real-estate"],
        "required_connections": ["whatsapp"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "real_estate_management",
                "tool_parameters": {
                    "operation": "format_rent_reminder",
                    "tenant_name": "{{input.tenant_name}}",
                    "amount": "{{input.rent_amount}}",
                    "due_date": "{{input.due_date}}",
                    "unit": "{{input.unit}}",
                    "paybill": "{{input.paybill}}",
                    "account_number": "{{input.account_number}}",
                    "reminder_level": "{{input.reminder_level}}",
                    "landlord_name": "{{input.landlord_name}}",
                    "property_name": "{{input.property_name}}"
                },
                "description": "Generate the appropriate rent reminder message (first, second, or final notice)"
            },
            {
                "step_number": 2,
                "tool_name": "whatsapp_messaging",
                "tool_parameters": {
                    "action": "send_message",
                    "to_number": "{{input.tenant_phone}}",
                    "message": "{{step_1.message}}"
                },
                "description": "Send the rent reminder to the tenant via WhatsApp"
            },
            {
                "step_number": 3,
                "tool_name": "real_estate_management",
                "tool_parameters": {
                    "operation": "format_escalation_notice",
                    "tenant_name": "{{input.tenant_name}}",
                    "issue_type": "rent",
                    "unit": "{{input.unit}}",
                    "phone": "{{input.tenant_phone}}",
                    "details": "Rent of KES {{input.rent_amount}} for {{input.unit}} is overdue. Reminder level: {{input.reminder_level}}"
                },
                "description": "Generate landlord escalation notice (only for final notices)",
                "condition": {"if": "input.reminder_level == 'final'"}
            },
            {
                "step_number": 4,
                "tool_name": "whatsapp_messaging",
                "tool_parameters": {
                    "action": "send_message",
                    "to_number": "{{input.landlord_phone}}",
                    "message": "{{step_3.message}}"
                },
                "description": "Escalate to landlord via WhatsApp (final notice only)",
                "condition": {"if": "input.reminder_level == 'final' and input.landlord_phone"}
            }
        ],
        "variables": {
            "tenant_name": {"type": "string", "required": True, "description": "Tenant's full name"},
            "tenant_phone": {"type": "string", "required": True, "description": "Tenant's WhatsApp number (e.g., 254712345678)"},
            "rent_amount": {"type": "number", "required": True, "description": "Monthly rent in KES"},
            "due_date": {"type": "string", "default": "5th of the month", "description": "Rent due date"},
            "unit": {"type": "string", "required": False, "description": "Unit/house number (e.g., A12)"},
            "paybill": {"type": "string", "required": False, "description": "M-Pesa Paybill number"},
            "account_number": {"type": "string", "required": False, "description": "M-Pesa account number"},
            "reminder_level": {"type": "string", "enum": ["first", "second", "final"], "default": "first"},
            "landlord_name": {"type": "string", "default": "Management"},
            "landlord_phone": {"type": "string", "required": False, "description": "Landlord phone for escalation"},
            "property_name": {"type": "string", "required": False, "description": "Property/building name"}
        }
    },
    {
        "id": "re-maintenance-handler",
        "name": "Maintenance Request Handler",
        "description": "Auto-classify incoming WhatsApp maintenance requests by category and priority, send instant acknowledgment to tenant, and alert the maintenance team or landlord for urgent issues.",
        "category": "Real Estate",
        "icon": "🔧",
        "difficulty": "beginner",
        "estimated_time": "5 mins",
        "tags": ["maintenance", "whatsapp", "real-estate", "auto-reply", "property"],
        "required_connections": ["whatsapp"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "real_estate_management",
                "tool_parameters": {
                    "operation": "classify_maintenance",
                    "message": "{{input.whatsapp_message_content}}"
                },
                "description": "Classify the maintenance request — detect category (plumbing, electrical, etc.) and priority level"
            },
            {
                "step_number": 2,
                "tool_name": "real_estate_management",
                "tool_parameters": {
                    "operation": "format_maintenance_response",
                    "tenant_name": "{{input.whatsapp_contact_name}}",
                    "category": "{{step_1.category}}",
                    "priority": "{{step_1.priority}}"
                },
                "description": "Generate acknowledgment message with ticket ID and estimated response time"
            },
            {
                "step_number": 3,
                "tool_name": "whatsapp_messaging",
                "tool_parameters": {
                    "action": "send_message",
                    "to_number": "{{input.whatsapp_contact_phone}}",
                    "message": "{{step_2.message}}"
                },
                "description": "Send maintenance acknowledgment to tenant"
            },
            {
                "step_number": 4,
                "tool_name": "whatsapp_messaging",
                "tool_parameters": {
                    "action": "send_message",
                    "to_number": "{{input.maintenance_team_phone}}",
                    "message": "🔧 *NEW MAINTENANCE REQUEST*\n\n🆔 Ticket: {{step_2.ticket_id}}\n👤 Tenant: {{input.whatsapp_contact_name}} ({{input.whatsapp_contact_phone}})\n🏷️ Category: {{step_1.category}}\n📊 Priority: {{step_1.priority}}\n⏱️ Response: {{step_1.suggested_response_time}}\n\n📝 Issue: {{input.whatsapp_message_content}}"
                },
                "description": "Alert maintenance team or caretaker (for high/emergency priority)",
                "condition": {"if": "input.maintenance_team_phone"}
            }
        ],
        "variables": {
            "whatsapp_message_content": {"type": "string", "required": True, "description": "Tenant's maintenance request message"},
            "whatsapp_contact_phone": {"type": "string", "required": True, "description": "Tenant's phone number"},
            "whatsapp_contact_name": {"type": "string", "default": "Tenant"},
            "maintenance_team_phone": {"type": "string", "required": False, "description": "Caretaker or maintenance team WhatsApp number"}
        }
    },
    {
        "id": "re-viewing-scheduler",
        "name": "Property Viewing Scheduler",
        "description": "When a prospect requests a viewing, automatically send available time slots and confirm their booking with location details via WhatsApp.",
        "category": "Real Estate",
        "icon": "📅",
        "difficulty": "beginner",
        "estimated_time": "5 mins",
        "tags": ["viewing", "scheduling", "whatsapp", "real-estate", "leads"],
        "required_connections": ["whatsapp"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "real_estate_management",
                "tool_parameters": {
                    "operation": "format_viewing_slots",
                    "property_description": "{{input.property_description}}",
                    "location": "{{input.location}}",
                    "agent_name": "{{input.agent_name}}",
                    "slots": "{{input.available_slots}}"
                },
                "description": "Generate formatted viewing slots message"
            },
            {
                "step_number": 2,
                "tool_name": "whatsapp_messaging",
                "tool_parameters": {
                    "action": "send_message",
                    "to_number": "{{input.prospect_phone}}",
                    "message": "{{step_1.message}}"
                },
                "description": "Send available viewing slots to the prospect"
            },
            {
                "step_number": 3,
                "tool_name": "whatsapp_messaging",
                "tool_parameters": {
                    "action": "send_message",
                    "to_number": "{{input.agent_phone}}",
                    "message": "📅 *Viewing Request*\n\n👤 {{input.prospect_name}} ({{input.prospect_phone}})\n🏠 Property: {{input.property_description}}\n📍 Location: {{input.location}}\n\nSlots sent. Please confirm when they reply."
                },
                "description": "Notify the agent about the viewing request",
                "condition": {"if": "input.agent_phone"}
            }
        ],
        "variables": {
            "prospect_phone": {"type": "string", "required": True, "description": "Prospect's WhatsApp number"},
            "prospect_name": {"type": "string", "default": "Client"},
            "property_description": {"type": "string", "required": True, "description": "Property description (e.g., '2BR Apartment in Ngoingwa')"},
            "location": {"type": "string", "default": "Thika"},
            "agent_name": {"type": "string", "required": False, "description": "Viewing agent name"},
            "agent_phone": {"type": "string", "required": False, "description": "Agent phone for notification"},
            "available_slots": {"type": "array", "items": {"type": "string"}, "description": "Available viewing slots (auto-generated if empty)"}
        }
    },
    {
        "id": "re-tenant-onboarding",
        "name": "Tenant Onboarding Welcome",
        "description": "Send a comprehensive welcome package to new tenants via WhatsApp — including rent details, M-Pesa payment info, house rules, and caretaker contact.",
        "category": "Real Estate",
        "icon": "🎉",
        "difficulty": "beginner",
        "estimated_time": "3 mins",
        "tags": ["onboarding", "tenant", "whatsapp", "welcome", "real-estate"],
        "required_connections": ["whatsapp"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "real_estate_management",
                "tool_parameters": {
                    "operation": "format_tenant_welcome",
                    "tenant_name": "{{input.tenant_name}}",
                    "unit": "{{input.unit}}",
                    "property_name": "{{input.property_name}}",
                    "landlord_name": "{{input.landlord_name}}",
                    "rent_amount": "{{input.rent_amount}}",
                    "due_date": "{{input.due_date}}",
                    "paybill": "{{input.paybill}}",
                    "account_number": "{{input.account_number}}",
                    "caretaker_phone": "{{input.caretaker_phone}}",
                    "rules": "{{input.house_rules}}"
                },
                "description": "Generate a comprehensive welcome message with all move-in details"
            },
            {
                "step_number": 2,
                "tool_name": "whatsapp_messaging",
                "tool_parameters": {
                    "action": "send_message",
                    "to_number": "{{input.tenant_phone}}",
                    "message": "{{step_1.message}}"
                },
                "description": "Send welcome package to new tenant"
            }
        ],
        "variables": {
            "tenant_name": {"type": "string", "required": True, "description": "New tenant's name"},
            "tenant_phone": {"type": "string", "required": True, "description": "Tenant's WhatsApp number"},
            "unit": {"type": "string", "required": True, "description": "Unit/house number"},
            "property_name": {"type": "string", "required": False, "description": "Building/property name"},
            "landlord_name": {"type": "string", "default": "Management"},
            "rent_amount": {"type": "number", "required": True, "description": "Monthly rent in KES"},
            "due_date": {"type": "string", "default": "5th of every month"},
            "paybill": {"type": "string", "required": False, "description": "M-Pesa Paybill"},
            "account_number": {"type": "string", "required": False, "description": "M-Pesa account number"},
            "caretaker_phone": {"type": "string", "required": False, "description": "Caretaker's phone"},
            "house_rules": {"type": "array", "items": {"type": "string"}, "description": "House rules list"}
        }
    },
    {
        "id": "re-landlord-monthly-report",
        "name": "Landlord Monthly Report",
        "description": "Generate and send a comprehensive monthly property report to the landlord via WhatsApp — including occupancy, rent collection rates, maintenance costs, and net income.",
        "category": "Real Estate",
        "icon": "📊",
        "difficulty": "intermediate",
        "estimated_time": "5 mins",
        "tags": ["report", "landlord", "whatsapp", "analytics", "real-estate"],
        "required_connections": ["whatsapp"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "real_estate_management",
                "tool_parameters": {
                    "operation": "generate_landlord_report",
                    "landlord_name": "{{input.landlord_name}}",
                    "property_name": "{{input.property_name}}",
                    "total_units": "{{input.total_units}}",
                    "occupied_units": "{{input.occupied_units}}",
                    "total_rent_expected": "{{input.total_rent_expected}}",
                    "total_rent_collected": "{{input.total_rent_collected}}",
                    "maintenance_count": "{{input.maintenance_count}}",
                    "maintenance_cost": "{{input.maintenance_cost}}",
                    "unpaid_tenants": "{{input.unpaid_tenants}}"
                },
                "description": "Generate comprehensive property performance report"
            },
            {
                "step_number": 2,
                "tool_name": "whatsapp_messaging",
                "tool_parameters": {
                    "action": "send_message",
                    "to_number": "{{input.landlord_phone}}",
                    "message": "{{step_1.message}}"
                },
                "description": "Send monthly report to landlord via WhatsApp"
            }
        ],
        "variables": {
            "landlord_name": {"type": "string", "required": True, "description": "Landlord's name"},
            "landlord_phone": {"type": "string", "required": True, "description": "Landlord's WhatsApp number"},
            "property_name": {"type": "string", "required": True, "description": "Property name"},
            "total_units": {"type": "integer", "required": True, "description": "Total units in property"},
            "occupied_units": {"type": "integer", "required": True, "description": "Currently occupied units"},
            "total_rent_expected": {"type": "number", "required": True, "description": "Total expected rent in KES"},
            "total_rent_collected": {"type": "number", "required": True, "description": "Total collected rent in KES"},
            "maintenance_count": {"type": "integer", "default": 0, "description": "Maintenance requests this month"},
            "maintenance_cost": {"type": "number", "default": 0, "description": "Total maintenance spend in KES"},
            "unpaid_tenants": {"type": "array", "items": {"type": "string"}, "description": "List of tenants with unpaid rent"}
        }
    },
    {
        "id": "re-lease-renewal-tracker",
        "name": "Lease Renewal Tracker",
        "description": "Automatically notify tenants about upcoming lease expiry and collect renewal confirmations via WhatsApp. Includes rent adjustment notices and landlord notification.",
        "category": "Real Estate",
        "icon": "📋",
        "difficulty": "beginner",
        "estimated_time": "5 mins",
        "tags": ["lease", "renewal", "whatsapp", "real-estate", "contract"],
        "required_connections": ["whatsapp"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "real_estate_management",
                "tool_parameters": {
                    "operation": "format_lease_reminder",
                    "tenant_name": "{{input.tenant_name}}",
                    "expiry_date": "{{input.expiry_date}}",
                    "unit": "{{input.unit}}",
                    "current_rent": "{{input.current_rent}}",
                    "new_rent": "{{input.new_rent}}",
                    "days_until_expiry": "{{input.days_until_expiry}}"
                },
                "description": "Generate lease renewal notice with rent adjustment details"
            },
            {
                "step_number": 2,
                "tool_name": "whatsapp_messaging",
                "tool_parameters": {
                    "action": "send_message",
                    "to_number": "{{input.tenant_phone}}",
                    "message": "{{step_1.message}}"
                },
                "description": "Send lease renewal notice to tenant"
            },
            {
                "step_number": 3,
                "tool_name": "whatsapp_messaging",
                "tool_parameters": {
                    "action": "send_message",
                    "to_number": "{{input.landlord_phone}}",
                    "message": "📋 *Lease Renewal Sent*\n\n👤 {{input.tenant_name}} — Unit {{input.unit}}\n📅 Expires: {{input.expiry_date}} ({{input.days_until_expiry}} days)\n💰 Current: KES {{input.current_rent}} → New: KES {{input.new_rent}}\n\nWaiting for tenant confirmation."
                },
                "description": "Notify landlord that renewal notice was sent",
                "condition": {"if": "input.landlord_phone"}
            }
        ],
        "variables": {
            "tenant_name": {"type": "string", "required": True, "description": "Tenant's name"},
            "tenant_phone": {"type": "string", "required": True, "description": "Tenant's WhatsApp number"},
            "expiry_date": {"type": "string", "required": True, "description": "Lease expiry date (e.g., 30 April 2026)"},
            "unit": {"type": "string", "required": False, "description": "Unit number"},
            "current_rent": {"type": "number", "required": True, "description": "Current rent in KES"},
            "new_rent": {"type": "number", "required": False, "description": "New rent after renewal (if changing)"},
            "days_until_expiry": {"type": "integer", "default": 30, "description": "Days until lease expires"},
            "landlord_phone": {"type": "string", "required": False, "description": "Landlord phone for notification"}
        }
    },
    # ────────────────────────────────────────────────────────────────────────
    # RAG / Knowledge Base Workflow Templates
    # ────────────────────────────────────────────────────────────────────────
    {
        "id": "website-knowledge-base",
        "name": "Website Knowledge Base",
        "description": "Scrape a website, ingest it into your AI Knowledge Base, and verify with a test search query — perfect for building customer support or sales-enablement KBs.",
        "category": "Knowledge Management",
        "icon": "🧠",
        "difficulty": "beginner",
        "estimated_time": "5 mins",
        "tags": ["rag", "knowledge-base", "scraping", "ai", "search"],
        "required_connections": ["rag_pipeline"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "rag_ingest_source",
                "tool_parameters": {
                    "url_or_id": "{{input.website_url}}",
                    "kb_id": "{{input.kb_id}}",
                    "source_type": "website"
                },
                "description": "Scrape and ingest website content into Knowledge Base"
            },
            {
                "step_number": 2,
                "tool_name": "rag_search",
                "tool_parameters": {
                    "query": "{{input.test_query}}",
                    "kb_id": "{{input.kb_id}}",
                    "top_k": 3,
                    "rerank": True
                },
                "description": "Run a test search query to verify ingestion"
            },
            {
                "step_number": 3,
                "tool_name": "slack_team_communication",
                "tool_parameters": {
                    "action": "send_message",
                    "channel": "{{input.notification_channel}}",
                    "message": "🧠 *Knowledge Base Updated*\n\n📍 *Source:* {{input.website_url}}\n📁 *KB:* {{input.kb_id}}\n🔍 *Test query:* \"{{input.test_query}}\"\n\n*Top Result Snippet:*\n```{{step_2.results[0].text | truncate(250)}}```"
                },
                "description": "Notify team that KB was updated"
            }
        ],
        "variables": {
            "website_url": {"type": "string", "required": True, "format": "url", "description": "Website URL to scrape and ingest", "placeholder": "https://example.com"},
            "kb_id": {"type": "string", "required": True, "description": "Knowledge Base ID to ingest into", "default": "default", "placeholder": "e.g. default, support-kb, sales-kb", "connection_for": "rag_pipeline"},
            "test_query": {"type": "string", "default": "What does this company do?", "description": "A test query to verify ingestion"},
            "notification_channel": {"type": "string", "default": "#general", "description": "Slack channel for notifications", "connection_for": "slack"}
        }
    },
    {
        "id": "document-ingestion-pipeline",
        "name": "Document Ingestion Pipeline",
        "description": "Parse a PDF or complex document with LlamaParse, then ingest the extracted text into your Knowledge Base for AI-powered search.",
        "category": "Knowledge Management",
        "icon": "📄",
        "difficulty": "beginner",
        "estimated_time": "5 mins",
        "tags": ["rag", "document", "pdf", "llamaparse", "ingestion"],
        "required_connections": ["rag_pipeline"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "rag_ingest_source",
                "tool_parameters": {
                    "url_or_id": "{{input.document_url}}",
                    "kb_id": "{{input.kb_id}}",
                    "source_type": "{{input.source_type}}"
                },
                "description": "Parse and ingest document into Knowledge Base"
            },
            {
                "step_number": 2,
                "tool_name": "rag_search",
                "tool_parameters": {
                    "query": "{{input.verification_query}}",
                    "kb_id": "{{input.kb_id}}",
                    "top_k": 3
                },
                "description": "Verify document was ingested with a search query"
            }
        ],
        "variables": {
            "document_url": {"type": "string", "required": True, "description": "URL or path of the document to ingest", "placeholder": "https://example.com/report.pdf"},
            "kb_id": {"type": "string", "required": True, "description": "Knowledge Base ID", "default": "default", "placeholder": "e.g. default, support-kb", "connection_for": "rag_pipeline"},
            "source_type": {"type": "string", "enum": ["website", "google_drive", "notion"], "default": "website", "description": "Type of document source"},
            "verification_query": {"type": "string", "default": "Summarize the key points", "description": "Query to verify ingestion"}
        }
    },
    {
        "id": "multi-source-knowledge-sync",
        "name": "Multi-Source Knowledge Sync",
        "description": "Pull content from Google Drive and Notion simultaneously, ingest both into your Knowledge Base, and notify the team — keep your KB always up to date.",
        "category": "Knowledge Management",
        "icon": "🔄",
        "difficulty": "intermediate",
        "estimated_time": "10 mins",
        "tags": ["rag", "sync", "google-drive", "notion", "knowledge-base", "multi-source"],
        "required_connections": ["rag_pipeline", "google_workspace", "notion", "slack"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "rag_ingest_source",
                "tool_parameters": {
                    "url_or_id": "{{input.drive_folder_id}}",
                    "kb_id": "{{input.kb_id}}",
                    "source_type": "google_drive"
                },
                "description": "Ingest documents from Google Drive folder"
            },
            {
                "step_number": 2,
                "tool_name": "rag_ingest_source",
                "tool_parameters": {
                    "url_or_id": "{{input.notion_page_id}}",
                    "kb_id": "{{input.kb_id}}",
                    "source_type": "notion"
                },
                "description": "Ingest pages from Notion workspace"
            },
            {
                "step_number": 3,
                "tool_name": "rag_search",
                "tool_parameters": {
                    "query": "{{input.test_query}}",
                    "kb_id": "{{input.kb_id}}",
                    "top_k": 5,
                    "rerank": True,
                    "rerank_top_n": 3
                },
                "description": "Verify both sources are searchable"
            },
            {
                "step_number": 4,
                "tool_name": "slack_team_communication",
                "tool_parameters": {
                    "action": "send_message",
                    "channel": "{{input.notification_channel}}",
                    "message": "🔄 Knowledge Base Sync Complete\n\n📁 Google Drive: {{input.drive_folder_id}}\n📝 Notion: {{input.notion_page_id}}\n📊 Test query returned {{step_3.results.length}} results\n\nYour KB '{{input.kb_id}}' is now up to date!"
                },
                "description": "Notify team that multi-source sync is complete"
            }
        ],
        "variables": {
            "drive_folder_id": {"type": "string", "required": True, "description": "Google Drive folder ID to sync", "ui_hint": "folder_picker", "connection_for": "google_workspace"},
            "notion_page_id": {"type": "string", "required": True, "description": "Notion page or database ID to sync", "placeholder": "e.g. abc123def456", "connection_for": "notion"},
            "kb_id": {"type": "string", "required": True, "description": "Knowledge Base ID", "default": "default", "placeholder": "e.g. default", "connection_for": "rag_pipeline"},
            "test_query": {"type": "string", "default": "What are the latest updates?", "description": "Test query to verify sync"},
            "notification_channel": {"type": "string", "default": "#knowledge-base", "description": "Slack channel for notifications", "connection_for": "slack"}
        }
    },
    {
        "id": "ai-customer-support-kb",
        "name": "AI-Powered Customer Support",
        "description": "When a customer asks a question, search your Knowledge Base for the best answer and deliver it via Slack or WhatsApp — instant, accurate AI support.",
        "category": "Customer Support",
        "icon": "🤖",
        "difficulty": "intermediate",
        "estimated_time": "8 mins",
        "tags": ["rag", "support", "ai", "search", "slack", "whatsapp", "customer-service"],
        "required_connections": ["rag_pipeline", "slack"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "rag_search",
                "tool_parameters": {
                    "query": "{{input.customer_question}}",
                    "kb_id": "{{input.kb_id}}",
                    "top_k": 5,
                    "rerank": True,
                    "rerank_top_n": 3
                },
                "description": "Search Knowledge Base for relevant answers"
            },
            {
                "step_number": 2,
                "tool_name": "content_creation",
                "tool_parameters": {
                    "operation": "generate",
                    "prompt": "Based on the following knowledge base results, write a helpful, concise customer support response to the question: '{{input.customer_question}}'\n\nKB Results:\n{{step_1.results}}",
                    "max_tokens": 500
                },
                "description": "Generate a polished answer from KB results"
            },
            {
                "step_number": 3,
                "tool_name": "slack_team_communication",
                "tool_parameters": {
                    "action": "send_message",
                    "channel": "{{input.response_channel}}",
                    "message": "🤖 *AI Support Response*\n\n❓ *Question:* {{input.customer_question}}\n\n💡 *Answer:* {{step_2.content}}\n\n📚 _Sources: {{step_1.results[0].source}} ({{step_1.results[0].score}} confidence)_"
                },
                "description": "Deliver AI-generated answer to support channel"
            }
        ],
        "variables": {
            "customer_question": {"type": "string", "required": True, "description": "The customer's question", "placeholder": "e.g. How do I reset my password?"},
            "kb_id": {"type": "string", "required": True, "description": "Knowledge Base ID to search", "default": "default", "placeholder": "e.g. default, support-kb", "connection_for": "rag_pipeline"},
            "response_channel": {"type": "string", "default": "#customer-support", "description": "Slack channel to post the answer", "connection_for": "slack"}
        }
    },
    {
        "id": "knowledge-base-maintenance",
        "name": "Knowledge Base Maintenance",
        "description": "Delete stale KB vectors, re-ingest from the original source, and verify with a test query — scheduled KB hygiene made easy.",
        "category": "Knowledge Management",
        "icon": "🔧",
        "difficulty": "advanced",
        "estimated_time": "12 mins",
        "tags": ["rag", "maintenance", "cleanup", "re-index", "knowledge-base"],
        "required_connections": ["rag_pipeline"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "rag_delete_kb",
                "tool_parameters": {
                    "kb_id": "{{input.kb_id}}",
                    "vector_db": "{{input.vector_db}}"
                },
                "description": "Delete all existing vectors for this Knowledge Base"
            },
            {
                "step_number": 2,
                "tool_name": "rag_ingest_source",
                "tool_parameters": {
                    "url_or_id": "{{input.source_url}}",
                    "kb_id": "{{input.kb_id}}",
                    "source_type": "{{input.source_type}}"
                },
                "description": "Re-ingest content from the original source"
            },
            {
                "step_number": 3,
                "tool_name": "rag_search",
                "tool_parameters": {
                    "query": "{{input.verification_query}}",
                    "kb_id": "{{input.kb_id}}",
                    "top_k": 3,
                    "rerank": True
                },
                "description": "Verify re-ingestion with a test search"
            }
        ],
        "variables": {
            "kb_id": {"type": "string", "required": True, "description": "Knowledge Base ID to maintain", "default": "default", "placeholder": "e.g. default, support-kb", "connection_for": "rag_pipeline"},
            "source_url": {"type": "string", "required": True, "description": "Original source URL/ID to re-ingest from", "placeholder": "https://example.com"},
            "source_type": {"type": "string", "enum": ["website", "google_drive", "notion", "airtable"], "default": "website"},
            "vector_db": {"type": "string", "enum": ["pinecone", "qdrant", "weaviate"], "default": "pinecone", "description": "Vector database backend"},
            "verification_query": {"type": "string", "default": "What is the main topic?", "description": "Query to verify re-ingestion"}
        }
    },
    {
        "id": "rag-research-assistant",
        "name": "RAG-Powered Research Assistant",
        "description": "Scrape a URL, ingest it into a temporary KB, search for targeted insights, and generate a research summary — AI-powered desk research in one click.",
        "category": "Content",
        "icon": "🔬",
        "difficulty": "intermediate",
        "estimated_time": "10 mins",
        "tags": ["rag", "research", "scraping", "ai", "summary", "content"],
        "required_connections": ["rag_pipeline"],
        "steps": [
            {
                "step_number": 1,
                "tool_name": "rag_ingest_source",
                "tool_parameters": {
                    "url_or_id": "{{input.research_url}}",
                    "kb_id": "{{input.kb_id}}",
                    "source_type": "website"
                },
                "description": "Scrape and ingest research source"
            },
            {
                "step_number": 2,
                "tool_name": "rag_search",
                "tool_parameters": {
                    "query": "{{input.research_question}}",
                    "kb_id": "{{input.kb_id}}",
                    "top_k": 8,
                    "rerank": True,
                    "rerank_top_n": 5
                },
                "description": "Search for targeted insights"
            },
            {
                "step_number": 3,
                "tool_name": "content_creation",
                "tool_parameters": {
                    "operation": "generate",
                    "prompt": "You are a research analyst. Based on the following search results from '{{input.research_url}}', write a comprehensive research summary answering: '{{input.research_question}}'\n\nSearch Results:\n{{step_2.results}}\n\nProvide:\n1. Key Findings\n2. Supporting Evidence\n3. Recommendations",
                    "max_tokens": 1000
                },
                "description": "Generate research summary from KB results"
            },
            {
                "step_number": 4,
                "tool_name": "slack_team_communication",
                "tool_parameters": {
                    "action": "send_message",
                    "channel": "{{input.output_channel}}",
                    "message": "🔬 *Research Report*\n\n📌 Source: {{input.research_url}}\n❓ Question: {{input.research_question}}\n\n{{step_3.content}}"
                },
                "description": "Post research report to Slack"
            }
        ],
        "variables": {
            "research_url": {"type": "string", "required": True, "format": "url", "description": "URL to research (e.g., competitor website, article)", "placeholder": "https://competitor.com"},
            "research_question": {"type": "string", "required": True, "description": "Specific research question to answer", "placeholder": "e.g. What is their pricing strategy?"},
            "kb_id": {"type": "string", "required": True, "description": "Knowledge Base ID (use a dedicated research KB)", "default": "research", "placeholder": "e.g. research, default", "connection_for": "rag_pipeline"},
            "output_channel": {"type": "string", "default": "#research", "description": "Slack channel for the research report", "connection_for": "slack"}
        }
    },
    {
        "id": "whatsapp_ordering_agent",
        "name": "WhatsApp Ordering Agent",
        "description": "AI-powered WhatsApp ordering agent with menu browsing, conversational order capture, and automatic business notifications.",
        "category": "Sales",
        "icon": "🛒",
        "difficulty": "intermediate",
        "estimated_time": "5 mins",
        "tags": ["whatsapp", "agent", "food", "retail", "ordering"],
        "required_connections": ["whatsapp", "rag_pipeline"],
        "trigger_type": WorkflowTriggerType.EVENT,
        "trigger_config": {
            "platform": "whatsapp",
            "event_type": "whatsapp_message_received"
        },
        "steps": [
            {
                "step_number": 1,
                "tool_name": "conversational_agent",
                "tool_parameters": {
                    "session_key": "{{session_key}}",
                    "user_message": "{{whatsapp_message_content}}",
                    "business_config": {
                        "kb_id": "{{variables.kb_id}}",
                        "business_name": "{{variables.business_name}}",
                        "business_phone": "{{variables.business_phone}}",
                        "order_type": "{{variables.order_type}}",
                        "currency": "{{variables.currency}}",
                        "delivery_methods": "{{variables.delivery_methods}}",
                        "storage_provider": "{{variables.storage_provider}}",
                        "storage_spreadsheet_id": "{{variables.storage_spreadsheet_id}}",
                        "storage_airtable_base_id": "{{variables.storage_airtable_base_id}}",
                        "storage_airtable_orders_table": "{{variables.storage_airtable_orders_table}}",
                        "storage_airtable_customers_table": "{{variables.storage_airtable_customers_table}}",
                        "auto_escalation_enabled": "{{variables.auto_escalation_enabled}}",
                        "supported_languages": "{{variables.supported_languages}}",
                        "human_handoff_ttl_hours": "{{variables.human_handoff_ttl_hours}}"
                    }
                },
                "description": "AI agent handles conversation and order creation"
            },
            {
                "step_number": 2,
                "tool_name": "whatsapp_send_message",
                "tool_parameters": {
                    "operation": "send_message",
                    "to_number": "{{whatsapp_contact_phone}}",
                    "message": "{{step_1.response_text}}",
                    "image_urls": "{{step_1.image_urls}}",
                    "send_cart_buttons": "{{step_1.send_cart_buttons}}",
                    "session_key": "{{session_key}}"
                },
                "description": "Send AI response back to customer"
            },
            {
                "step_number": 3,
                "tool_name": "whatsapp_send_message",
                "tool_parameters": {
                    "operation": "send_message",
                    "to_number": "{{variables.business_phone}}",
                    "message": "{{step_1.order_notification}}"
                },
                "description": "Notify business owner of new order",
                "condition": {"if": "step_1.order_created == True"}
            },
            {
                "step_number": 4,
                "tool_name": "whatsapp_send_message",
                "tool_parameters": {
                    "operation": "send_message",
                    "to_number": "{{variables.business_phone}}",
                    "message": "{{step_1.order_notification}}"
                },
                "description": "Notify business owner of cancelled order",
                "condition": {"if": "step_1.order_cancelled == True"}
            },
            {
                "step_number": 5,
                "tool_name": "whatsapp_send_message",
                "tool_parameters": {
                    "operation": "send_message",
                    "to_number": "{{variables.business_phone}}",
                    "message": "{{step_1.escalation_notification}}"
                },
                "description": "Alert business owner — customer needs a human agent",
                "condition": {"if": "step_1.escalation_triggered == True"}
            }
        ],
        "variables": {
            "kb_id": {
                "type": "string", "required": True, "description": "Knowledge Base ID containing your menu/products", "connection_for": "rag_pipeline"
            },
            "business_name": {
                "type": "string", "required": True, "description": "Your business name (shown to customers)"
            },
            "business_phone": {
                "type": "string", "required": True, "description": "Phone number to receive order notifications", "connection_for": "whatsapp"
            },
            "order_type": {
                "type": "string", "enum": ["food", "clothing", "retail", "general"], "default": "food"
            },
            "currency": {
                "type": "string", "default": "KES"
            },
            "delivery_methods": {
                "type": "array", "items": {"type": "string"}, "default": ["delivery", "pickup"]
            },
            "storage_provider": {
                "type": "string",
                "description": "Where to save orders (none, google_sheets, airtable)",
                "enum": ["none", "google_sheets", "airtable"],
                "default": "none"
            },
            "storage_spreadsheet_id": {
                "type": "string",
                "description": "Google Sheets Spreadsheet ID",
                "x-dynamic-ui": "google_workspace_drive.list_spreadsheets",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_orders_sheet_name": {
                "type": "string",
                "description": "Orders sheet/tab name in selected spreadsheet",
                "default": "Orders",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_customers_sheet_name": {
                "type": "string",
                "description": "Customers sheet/tab name in selected spreadsheet",
                "default": "Customers",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_airtable_base_id": {
                "type": "string",
                "description": "Airtable Base ID",
                "x-dynamic-ui": "airtable_base_management.list_bases",
                "show_if": {"field": "storage_provider", "value": "airtable"}
            },
            "storage_airtable_orders_table": {
                "type": "string",
                "default": "Orders",
                "show_if": {"field": "storage_provider", "value": "airtable"}
            },
            "storage_airtable_customers_table": {
                "type": "string",
                "default": "Customers",
                "show_if": {"field": "storage_provider", "value": "airtable"}
            },
            "auto_escalation_enabled": {
                "type": "boolean",
                "default": True,
                "description": "Automatically hand frustrated or complex chats to a human agent"
            },
            "supported_languages": {
                "type": "string",
                "default": "en,sw,fr,ar,es",
                "description": "Comma-separated language codes the agent supports (e.g. en,sw,fr)"
            },
            "human_handoff_ttl_hours": {
                "type": "number",
                "default": 24,
                "description": "Hours before the AI resumes automatically (0 = never auto-resume)"
            }
        }
    },
    {
        "id": "telegram_ordering_agent",
        "name": "Telegram Ordering Agent",
        "description": "AI-powered Telegram ordering agent with product browsing, conversational order capture, and automatic notifications.",
        "category": "Sales",
        "icon": "🤖",
        "difficulty": "intermediate",
        "estimated_time": "5 mins",
        "tags": ["telegram", "agent", "food", "retail", "ordering"],
        "required_connections": ["telegram", "rag_pipeline"],
        "trigger_type": WorkflowTriggerType.EVENT,
        "trigger_config": {
            "platform": "telegram",
            "event_type": "telegram_message_received"
        },
        "steps": [
            {
                "step_number": 1,
                "tool_name": "conversational_agent",
                "tool_parameters": {
                    "session_key": "{{session_key}}",
                    "user_message": "{{telegram_message}}",
                    "business_config": {
                        "kb_id": "{{variables.kb_id}}",
                        "business_name": "{{variables.business_name}}",
                        "business_phone": "{{variables.business_phone}}",
                        "order_type": "{{variables.order_type}}",
                        "currency": "{{variables.currency}}",
                        "delivery_methods": "{{variables.delivery_methods}}",
                        "storage_provider": "{{variables.storage_provider}}",
                        "storage_spreadsheet_id": "{{variables.storage_spreadsheet_id}}",
                        "storage_orders_sheet_name": "{{variables.storage_orders_sheet_name}}",
                        "storage_customers_sheet_name": "{{variables.storage_customers_sheet_name}}",
                        "storage_airtable_base_id": "{{variables.storage_airtable_base_id}}",
                        "storage_airtable_orders_table": "{{variables.storage_airtable_orders_table}}",
                        "storage_airtable_customers_table": "{{variables.storage_airtable_customers_table}}"
                    }
                },
                "description": "AI agent handles conversation and order creation"
            },
            {
                "step_number": 2,
                "tool_name": "telegram_send_message",
                "tool_parameters": {
                    "chat_id": "{{chat_id}}",
                    "message": "{{step_1.response_text}}",
                    "image_urls": "{{step_1.image_urls}}"
                },
                "description": "Send AI response back to customer"
            }
        ],
        "variables": {
            "kb_id": {
                "type": "string", "required": True, "description": "Knowledge Base ID containing your menu/products", "connection_for": "rag_pipeline"
            },
            "business_name": {
                "type": "string", "required": True, "description": "Your business name (shown to customers)"
            },
            "business_phone": {
                "type": "string", "required": False, "description": "Phone number for notifications (optional)"
            },
            "order_type": {
                "type": "string", "enum": ["food", "clothing", "retail", "general"], "default": "food"
            },
            "currency": {
                "type": "string", "default": "KES"
            },
            "delivery_methods": {
                "type": "array", "items": {"type": "string"}, "default": ["delivery", "pickup"]
            },
            "storage_provider": {
                "type": "string",
                "description": "Where to save orders (none, google_sheets, airtable)",
                "enum": ["none", "google_sheets", "airtable"],
                "default": "none"
            },
            "storage_spreadsheet_id": {
                "type": "string",
                "description": "Google Sheets Spreadsheet ID",
                "x-dynamic-ui": "google_workspace_drive.list_spreadsheets",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_orders_sheet_name": {
                "type": "string",
                "description": "Orders sheet/tab name in selected spreadsheet",
                "default": "Orders",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_customers_sheet_name": {
                "type": "string",
                "description": "Customers sheet/tab name in selected spreadsheet",
                "default": "Customers",
                "show_if": {"field": "storage_provider", "value": "google_sheets"}
            },
            "storage_airtable_base_id": {
                "type": "string",
                "description": "Airtable Base ID",
                "x-dynamic-ui": "airtable_base_management.list_bases",
                "show_if": {"field": "storage_provider", "value": "airtable"}
            },
            "storage_airtable_orders_table": {
                "type": "string",
                "default": "Orders",
                "show_if": {"field": "storage_provider", "value": "airtable"}
            },
            "storage_airtable_customers_table": {
                "type": "string",
                "default": "Customers",
                "show_if": {"field": "storage_provider", "value": "airtable"}
            }
        }
    },
    {
        "id": "whatsapp_support_agent",
        "name": "WhatsApp Support Agent",
        "description": "AI-powered WhatsApp support agent that answers customer questions using your Knowledge Base. No ordering — purely informational.",
        "category": "Customer Support",
        "icon": "💬",
        "difficulty": "beginner",
        "estimated_time": "3 mins",
        "tags": ["whatsapp", "support", "agent", "saas", "services"],
        "required_connections": ["whatsapp", "rag_pipeline"],
        "trigger_type": WorkflowTriggerType.EVENT,
        "trigger_config": {
            "platform": "whatsapp",
            "event_type": "whatsapp_message_received"
        },
        "steps": [
            {
                "step_number": 1,
                "tool_name": "rag_search",
                "tool_parameters": {
                    "query": "{{whatsapp_message_content}}",
                    "kb_id": "{{variables.kb_id}}",
                    "top_k": 5,
                    "session_key": "{{session_key}}"
                },
                "description": "Search knowledge base for relevant information"
            },
            {
                "step_number": 2,
                "tool_name": "ai_text_generation",
                "tool_parameters": {
                    "operation": "generate",
                    "prompt": "{{whatsapp_message_content}}",
                    "context": "{{step_1.result}}",
                    "system_prompt": "You are a helpful customer support assistant for {{variables.business_name}}. Answer based on the provided context. Be concise and friendly (WhatsApp style). {{variables.system_prompt}}",
                    "session_key": "{{session_key}}",
                    "temperature": 0.3,
                    "max_tokens": 500
                },
                "description": "Generate contextual response using KB results"
            },
            {
                "step_number": 3,
                "tool_name": "whatsapp_send_message",
                "tool_parameters": {
                    "operation": "send_message",
                    "to_number": "{{whatsapp_contact_phone}}",
                    "message": "{{step_2.result}}"
                },
                "description": "Reply to customer"
            }
        ],
        "variables": {
            "kb_id": {
                "type": "string",
                "required": True,
                "description": "Knowledge Base ID containing your FAQs/Docs",
                "connection_for": "rag_pipeline"
            },
            "business_name": {
                "type": "string",
                "required": True,
                "description": "Your business name (shown to customers)"
            },
            "system_prompt": {
                "type": "string",
                "required": False,
                "description": "Custom Instructions (Optional, e.g. tone, escalation rules)"
            }
        }
    }
]

# Template categories
CATEGORIES = [
    {"id": "marketing", "name": "Marketing", "icon": "📣", "color": "#8B5CF6"},
    {"id": "sales", "name": "Sales", "icon": "💼", "color": "#10B981"},
    {"id": "analytics", "name": "Analytics", "icon": "📊", "color": "#3B82F6"},
    {"id": "customer-success", "name": "Customer Success", "icon": "🎉", "color": "#F59E0B"},
    {"id": "customer-support", "name": "Customer Support", "icon": "🎫", "color": "#EF4444"},
    {"id": "finance", "name": "Finance", "icon": "💰", "color": "#059669"},
    {"id": "content", "name": "Content", "icon": "✍️", "color": "#EC4899"},
    {"id": "hr", "name": "Human Resources", "icon": "👥", "color": "#6366F1"},
    {"id": "operations", "name": "Operations", "icon": "⚙️", "color": "#64748B"},
    {"id": "fintech", "name": "Fintech", "icon": "💳", "color": "#06B6D4"},
    {"id": "real-estate", "name": "Real Estate", "icon": "🏠", "color": "#D97706"},
    {"id": "knowledge-management", "name": "Knowledge Management", "icon": "🧠", "color": "#7C3AED"},
]


class TemplateResponse(BaseModel):
    success: bool
    data: Any = None
    message: str = None


@router.get("/helpers/drive-folders", response_model=TemplateResponse)
async def list_drive_folders(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List Google Drive folders for folder picker dropdowns."""
    try:
        # Find user's google_workspace connection
        from ..models import Connection, ConnectionStatus
        result = await db.execute(
            select(Connection).where(
                Connection.user_id == current_user.id,
                Connection.platform == "google_workspace",
                Connection.status == ConnectionStatus.ACTIVE,
            )
        )
        connection = result.scalar_one_or_none()

        if not connection:
            return TemplateResponse(
                success=False,
                message="Google Workspace not connected",
                data=[]
            )

        # Build credentials and initialize Drive service (same pattern as tool_executor)
        from ..services.google_workspace.base_client import GoogleWorkspaceBaseClient
        from ..services.google_workspace.drive_service import DriveService

        client_id = connection.config.get("client_id")
        client_secret = connection.config.get("client_secret")
        refresh_token = connection.config.get("refresh_token")

        if not all([client_id, client_secret, refresh_token]):
            return TemplateResponse(
                success=False,
                message="Incomplete Google Workspace credentials",
                data=[]
            )

        credentials_data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "access_token": connection.config.get("access_token"),
            "scopes": connection.config.get("scopes"),
        }
        base_client = GoogleWorkspaceBaseClient(credentials_data)
        drive_service = DriveService(base_client)

        folders_result = await drive_service.list_folders()

        if not folders_result.get("success"):
            return TemplateResponse(
                success=False,
                message=folders_result.get("error", "Failed to list folders"),
                data=[]
            )

        # Map {label, value} from list_folders() to {id, name} for the frontend
        folder_list = [
            {"id": opt.get("value"), "name": opt.get("label")}
            for opt in folders_result.get("options", [])
        ]

        return TemplateResponse(success=True, data=folder_list)

    except Exception as e:
        logger.error(f"Failed to list Drive folders: {e}")
        return TemplateResponse(
            success=False,
            message="Failed to fetch Google Drive folders",
            data=[]
        )


@router.get("/", response_model=TemplateResponse)
async def list_templates(
    category: Optional[str] = Query(None, description="Filter by category"),
    difficulty: Optional[str] = Query(None, description="Filter by difficulty"),
    search: Optional[str] = Query(None, description="Search term"),
    connection: Optional[str] = Query(None, description="Filter by required connection"),
):
    """Get list of all workflow templates."""
    templates = WORKFLOW_TEMPLATES.copy()
    
    # Filter by category
    if category:
        templates = [t for t in templates if t["category"].lower() == category.lower()]
    
    # Filter by difficulty
    if difficulty:
        templates = [t for t in templates if t["difficulty"] == difficulty]
    
    # Filter by required connection
    if connection:
        templates = [t for t in templates if connection.lower() in [c.lower() for c in t.get("required_connections", [])]]
    
    # Search
    if search:
        search_lower = search.lower()
        templates = [
            t for t in templates
            if search_lower in t["name"].lower()
            or search_lower in t["description"].lower()
            or any(search_lower in tag.lower() for tag in t.get("tags", []))
        ]
    
    return TemplateResponse(
        success=True,
        data={
            "templates": templates,
            "total": len(templates)
        }
    )


@router.get("/categories", response_model=TemplateResponse)
async def get_categories():
    """Get all template categories."""
    return TemplateResponse(
        success=True,
        data=CATEGORIES
    )


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(template_id: str):
    """Get a specific template by ID."""
    template = next((t for t in WORKFLOW_TEMPLATES if t["id"] == template_id), None)
    
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )
    
    return TemplateResponse(
        success=True,
        data=template
    )


@router.post("/{template_id}/use", response_model=TemplateResponse)
async def use_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a workflow from a template."""
    template = next((t for t in WORKFLOW_TEMPLATES if t["id"] == template_id), None)
    
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found"
        )
    
    workflow = Workflow(
        name=f"{template['name']} (from template)",
        description=template["description"],
        user_id=current_user.id,
        steps=[WorkflowStep(**step) for step in template["steps"]],
        variables=template.get("variables"),
        trigger_type=template.get("trigger_type", WorkflowTriggerType.MANUAL),
        trigger_config=template.get("trigger_config", {}),
        status=WorkflowStatus.ACTIVE,
        category=template["category"],
        tags=template.get("tags", []),
    )
    
    db.add(workflow)
    await db.commit()
    await db.refresh(workflow)
    
    return TemplateResponse(
        success=True,
        data={
            "workflow_id": workflow.id,
            "message": f"Workflow created from template '{template['name']}'"
        }
    )


@router.get("/featured/list", response_model=TemplateResponse)
async def get_featured_templates():
    """Get featured/recommended templates."""
    # Return first 4 templates as featured
    featured = WORKFLOW_TEMPLATES[:4]
    
    return TemplateResponse(
        success=True,
        data=featured
    )


@router.get("/stats/popular", response_model=TemplateResponse)
async def get_popular_templates(
    db: AsyncSession = Depends(get_db)
):
    """Get most popular templates based on usage."""
    # In a real implementation, this would track actual usage
    # For now, return templates with "beginner" difficulty as popular
    popular = [t for t in WORKFLOW_TEMPLATES if t["difficulty"] == "beginner"]
    
    return TemplateResponse(
        success=True,
        data=popular[:5]
    )

