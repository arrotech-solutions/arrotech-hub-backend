"""
Main application entry point for Mini-Hub MCP Server.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from .config import settings
from .database import init_db
from .routers import (agent_router, api_router, auth_router, chat_router,
                      connection_router, mcp_router, payment_router,
                      powerbi_router, settings_router, workflow_router)
from .services import (BillingService, ContentCreationService,
                       FileManagementService, GA4Service, HubSpotService,
                       RateLimitService, SlackService, SocialMediaService,
                       WebToolsService)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global services
hubspot_service = HubSpotService()
ga4_service = GA4Service()
slack_service = SlackService()
billing_service = BillingService()
rate_limit_service = RateLimitService()
social_media_service = SocialMediaService()
file_management_service = FileManagementService()
web_tools_service = WebToolsService()
content_creation_service = ContentCreationService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting Mini-Hub MCP Server...")
    await init_db()
    logger.info("Database initialized")

    # Initialize services that need it
    try:
        await ga4_service.initialize()
    except Exception as e:
        logger.warning(f"GA4 service initialization failed: {e}")

    try:
        await slack_service.initialize()
    except Exception as e:
        logger.warning(f"Slack service initialization failed: {e}")

    logger.info("Services ready")

    yield

    # Shutdown
    logger.info("Shutting down Mini-Hub MCP Server...")

# Create FastAPI app
app = FastAPI(
    title="Mini-Hub MCP Server",
    description="Connect AI models to marketing tools with real-time automation",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(payment_router, prefix="/payments", tags=["payments"])
app.include_router(connection_router, prefix="/connections",
                   tags=["connections"])
app.include_router(mcp_router, prefix="/mcp", tags=["mcp"])
app.include_router(api_router, prefix="/api/v1", tags=["api"])
app.include_router(settings_router, prefix="/settings", tags=["settings"])
app.include_router(chat_router, prefix="/chat", tags=["chat"])
app.include_router(workflow_router, prefix="/workflows", tags=["workflows"])
app.include_router(agent_router, prefix="/agents", tags=["agents"])
app.include_router(powerbi_router.router, prefix="/powerbi", tags=["powerbi"])


@app.get("/")
async def root():
    """Root endpoint with server info."""
    return {
        "name": "Mini-Hub MCP Server",
        "version": "1.0.0",
        "description": "Connect AI models to marketing tools",
        "status": "running",
        "pricing_tiers": {
            "free": "$0/month - 100 requests/day",
            "pro": "$49/month - 10,000 requests/day",
            "enterprise": "$299 one-time - white-glove setup"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": "2024-01-01T00:00:00Z"}


async def run_mcp_server():
    """Run the MCP server."""
    server = Server("mini-hub")

    # Register tools
    @server.list_tools()
    async def list_tools() -> list[Dict[str, Any]]:
        """List available tools."""
        return [
            {
                "name": "hubspot_read_contacts",
                "description": "Get contacts from HubSpot",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 10},
                        "properties": {"type": "array", "items": {"type": "string"}}
                    }
                }
            },
            {
                "name": "hubspot_write_contact",
                "description": "Create a new contact in HubSpot",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string"},
                        "first_name": {"type": "string"},
                        "last_name": {"type": "string"},
                        "company": {"type": "string"},
                        "phone": {"type": "string"}
                    },
                    "required": ["email"]
                }
            },
            {
                "name": "hubspot_add_deal_note",
                "description": "Add a note to a HubSpot deal",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "deal_id": {"type": "string"},
                        "note": {"type": "string"}
                    },
                    "required": ["deal_id", "note"]
                }
            },
            {
                "name": "ga4_get_traffic",
                "description": "Get traffic data from Google Analytics 4",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "date_range": {"type": "string", "default": "7d"},
                        "dimensions": {"type": "array", "items": {"type": "string"}},
                        "metrics": {"type": "array", "items": {"type": "string"}}
                    }
                }
            },
            {
                "name": "ga4_get_conversions",
                "description": "Get conversion data from Google Analytics 4",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "date_range": {"type": "string", "default": "7d"},
                        "conversion_events": {"type": "array", "items": {"type": "string"}}
                    }
                }
            },
            {
                "name": "slack_send_message",
                "description": "Send a message to a Slack channel",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string"},
                        "message": {"type": "string"},
                        "attachments": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["channel", "message"]
                }
            },
            {
                "name": "slack_send_report",
                "description": "Send a formatted report to Slack",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string"},
                        "title": {"type": "string"},
                        "data": {"type": "object"},
                        "format": {"type": "string", "enum": ["text", "blocks", "attachments"]}
                    },
                    "required": ["channel", "title", "data"]
                }
            },
            {
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
                }
            },
            {
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
                }
            },
            {
                "name": "content_creation",
                "description": "Generate images, create content from templates, and optimize for SEO",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["generate_image", "create_from_template", "generate_bulk_content", "optimize_seo", "generate_calendar"]},
                        "text": {"type": "string"},
                        "style": {"type": "string"},
                        "size": {"type": "object"},
                        "template_name": {"type": "string"},
                        "variables": {"type": "object"},
                        "base_content": {"type": "string"},
                        "variations": {"type": "integer"},
                        "content_type": {"type": "string"},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                        "start_date": {"type": "string"},
                        "end_date": {"type": "string"}
                    },
                    "required": ["operation"]
                }
            }
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call."""
        # Check rate limits
        user_id = "default"  # In production, get from auth
        if not await rate_limit_service.check_limit(user_id):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        try:
            if name == "hubspot_read_contacts":
                return await hubspot_service.get_contacts(**arguments)
            elif name == "hubspot_write_contact":
                return await hubspot_service.create_contact(**arguments)
            elif name == "hubspot_add_deal_note":
                return await hubspot_service.add_deal_note(**arguments)
            elif name == "ga4_get_traffic":
                return await ga4_service.get_traffic(**arguments)
            elif name == "ga4_get_conversions":
                return await ga4_service.get_conversions(**arguments)
            elif name == "slack_send_message":
                return await slack_service.send_message(**arguments)
            elif name == "slack_send_report":
                return await slack_service.send_report(**arguments)
            elif name == "file_management":
                return await file_management_service.execute_operation(**arguments)
            elif name == "web_tools":
                return await web_tools_service.execute_operation(**arguments)
            elif name == "content_creation":
                return await content_creation_service.execute_operation(**arguments)
            else:
                raise HTTPException(
                    status_code=400, detail=f"Unknown tool: {name}")
        except Exception as e:
            logger.error(f"Tool call failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # Run the server
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="mini-hub",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=None,
                    experimental_capabilities=None,
                ),
            ),
        )


def main():
    """Main entry point."""
    if settings.ENVIRONMENT == "development":
        # Run FastAPI server for development
        uvicorn.run(
            "src.main:app",
            host=settings.HOST,
            port=settings.PORT,
            reload=settings.RELOAD,
            log_level=settings.LOG_LEVEL.lower()
        )
    else:
        # Run MCP server for production
        asyncio.run(run_mcp_server())


if __name__ == "__main__":
    main()
