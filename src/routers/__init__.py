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
from .favorites_router import router as favorites_router
from .notification_router import router as notification_router
from .payment_router import router as payment_router
from .preferences_router import router as preferences_router
from .settings_router import router as settings_router
from .templates_router import router as templates_router
from .workflow_router import router as workflow_router
from .agent_router import router as agent_router

__all__ = [
    "analytics_router", "mcp_router", "api_router", "auth_router", "chat_router",
    "connection_router", "creator_router", "favorites_router", "marketplace_router", 
    "notification_router", "payment_router", "preferences_router", "settings_router", 
    "templates_router", "workflow_router", "agent_router"
]
