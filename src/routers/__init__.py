"""
Routers package for Mini-Hub MCP Server.
"""

from .api_router import router as api_router
from .auth_router import router as auth_router
from .chat_router import router as chat_router
from .connection_router import router as connection_router
from .mcp_router import router as mcp_router
from .payment_router import router as payment_router
from .settings_router import router as settings_router
from .workflow_router import router as workflow_router
from .agent_router import router as agent_router

__all__ = [
    "mcp_router", "api_router", "auth_router", "chat_router",
    "connection_router", "payment_router", "settings_router", "workflow_router",
    "agent_router"
]
