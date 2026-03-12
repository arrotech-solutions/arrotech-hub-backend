"""
Routers package for Mini-Hub MCP Server.
"""

from .analytics_router import router as analytics_router
from .api_router import router as api_router
from .auth_router import router as auth_router
from .chat_router import router as chat_router
from .connection_router import router as connection_router
from .creator_router import router as creator_router
from .marketplace_router import router as marketplace_router
from .mcp_router import router as mcp_router
from .mpesa_agent_router import router as mpesa_agent_router
from .favorites_router import router as favorites_router
from .notification_router import router as notification_router
from .payment_router import router as payment_router
from .preferences_router import router as preferences_router
from .settings_router import router as settings_router
from .slack_agent_router import router as slack_agent_router
from .templates_router import router as templates_router
from .workflow_router import router as workflow_router
from .agent_router import router as agent_router
from .google_workspace_router import router as google_workspace_router
from .slack_router import router as slack_router
from .whatsapp_router import router as whatsapp_router
from . import whatsapp_webhook  # WhatsApp incoming messages webhook
from . import whatsapp_contacts  # WhatsApp contacts, messages, auto-reply API
from . import whatsapp_broadcast  # WhatsApp broadcast campaigns
from .facebook_router import router as facebook_router
from .instagram_router import router as instagram_router
from .twitter_router import router as twitter_router
from .outlook_router import router as outlook_router
from .notion_router import router as notion_router
from .trello_router import router as trello_router
from .jira_router import router as jira_router
from .hubspot_router import router as hubspot_router
from .blog_router import router as blog_router
from .employee_router import router as employee_router
from .quickbooks_router import router as quickbooks_router
from .airtable_router import router as airtable_router
from . import gmail_webhook  # Gmail Pub/Sub push notifications webhook
from . import zoho_webhook  # Zoho real-time events webhook

__all__ = [
    "analytics_router", "mcp_router", "api_router", "auth_router", "chat_router",
    "connection_router", "creator_router", "favorites_router", "marketplace_router", 
    "mpesa_agent_router", "notification_router", "payment_router", "preferences_router", 
    "settings_router", "slack_agent_router", "templates_router", "workflow_router", "agent_router",
    "google_workspace_router", "slack_router", "whatsapp_router", "whatsapp_webhook", "whatsapp_contacts",
    "whatsapp_broadcast", "facebook_router", "instagram_router", "twitter_router",
    "outlook_router", "notion_router", "trello_router", "jira_router",
    "blog_router", "employee_router", "quickbooks_router", "airtable_router", "gmail_webhook", "hubspot_router", "zoho_webhook"
]
