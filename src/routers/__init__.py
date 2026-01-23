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
from .google_workspace_routes import router as google_workspace_router
from .slack_routes import router as slack_routes
from .whatsapp_routes import router as whatsapp_routes
from .facebook_routes import router as facebook_routes
from .instagram_routes import router as instagram_routes
from .twitter_routes import router as twitter_routes
from .outlook_router import router as outlook_router
from .notion_router import router as notion_router
from .trello_router import router as trello_router
from .jira_router import router as jira_router

__all__ = [
    "analytics_router", "mcp_router", "api_router", "auth_router", "chat_router",
    "connection_router", "creator_router", "favorites_router", "marketplace_router", 
    "mpesa_agent_router", "notification_router", "payment_router", "preferences_router", 
    "settings_router", "slack_agent_router", "templates_router", "workflow_router", "agent_router",
    "google_workspace_router", "slack_routes", "whatsapp_routes", "facebook_routes", "instagram_routes", "twitter_routes",
    "outlook_router", "notion_router", "trello_router", "jira_router"
]
