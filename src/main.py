"""
Main application entry point for Mini-Hub MCP Server
"""

import asyncio
import logging
import json
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from .config import settings
from .database import init_db
from .routers import (access_router, agent_router, analytics_router, api_router, assistant_router, auth_router, chat_router,
                      connection_router, creator_router, favorites_router, google_workspace_router, marketplace_router, 
                      mcp_router, mpesa_agent_router, notification_router, payment_router, preferences_router,
                      security_router, settings_router, slack_agent_router, slack_router, subscription_router, templates_router, whatsapp_router, workflow_router, facebook_router, instagram_router, telegram_router, twitter_router, clickup_router, teams_router, zoom_router,
                      outlook_router, notion_router, trello_router, jira_router, whatsapp_webhook, whatsapp_contacts, whatsapp_broadcast, tiktok_router, ai_router, support_router, kra_router, productivity_router, asana_router,
                       blog_router, employee_router, gmail_webhook, google_drive_webhook, hubspot_router, ws_router, organization_router, quickbooks_router, airtable_router, xero_router, zoho_router, zoho_webhook, linkedin_router, rag_router, public_forms_router, github_router)
from .services import (BillingService, ContentCreationService,
                       FileManagementService, HubSpotService,
                       RateLimitService, SlackService, SocialMediaService, TelegramService,
                       WebToolsService, WorkflowSchedulerService,
                       cache_service)
from .services.coding_agent_sandbox import coding_agent_sandbox
from .observability.logger import setup_observability_logging, db_log_worker, log_cleanup_job
from .observability.middleware import ObservabilityMiddleware
from .routers.internal_router import router as internal_router
from .core.skills import SkillRegistry, load_skill
from pathlib import Path


# setup_observability_logging replaces the old manual logging setup below

logger = setup_observability_logging()

# Global services
hubspot_service = HubSpotService()

slack_service = SlackService()
billing_service = BillingService()
rate_limit_service = RateLimitService()
social_media_service = SocialMediaService()
file_management_service = FileManagementService()
web_tools_service = WebToolsService()
content_creation_service = ContentCreationService()
workflow_scheduler_service = WorkflowSchedulerService()
telegram_service = TelegramService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    # NOTE: Background workers (db_log_worker, log_cleanup_job) are now
    # handled by Celery Beat periodic tasks. See src/tasks/maintenance_tasks.py.
    
    logger.info("Starting Mini-Hub MCP Server...")
    
    # Load Skills Runtime
    try:
        from .core.runtime.bootstrap import validate_runtime_integrity
        validate_runtime_integrity()
        logger.info("Runtime integrity validation passed")
        
        registry = SkillRegistry()
        # Reset registry to avoid issues if lifespan is called multiple times (e.g. tests)
        registry._clear_for_testing()
        
        skills_dir = Path(__file__).parent / "skills"
        for yaml_path in skills_dir.glob("**/skill.yaml"):
            skill = load_skill(yaml_path)
            registry.register(skill)
            logger.info(f"Loaded skill: {skill.name}")
    except Exception as e:
        logger.critical(f"Skill initialization failed: {e}")
        # FAIL ENTIRE APPLICATION STARTUP
        raise SystemExit(1)
    
    # Initialize database with timeout
    try:
        await asyncio.wait_for(init_db(), timeout=30.0)
        logger.info("Database initialized")
    except asyncio.TimeoutError:
        logger.error("Database initialization timed out after 30s")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

    # Initialize services that need it (with timeouts)


    try:
        await asyncio.wait_for(slack_service.initialize(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning("Slack service initialization timed out")
    except Exception as e:
        logger.warning(f"Slack service initialization failed: {e}")

    try:
        await asyncio.wait_for(telegram_service.initialize(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.warning("Telegram service webhook registration timed out")
    except Exception as e:
        logger.warning(f"Telegram service webhook registration failed: {e}")

    try:
        await asyncio.wait_for(cache_service.initialize(), timeout=5.0)
    except asyncio.TimeoutError:
        logger.warning("Cache service initialization timed out")
    except Exception as e:
        logger.warning(f"Cache service initialization failed: {e}")

    # Attach services to app state for dependency injection in routers
    app.state.rate_limit_service = rate_limit_service
    app.state.slack_service = slack_service
    app.state.hubspot_service = hubspot_service
    app.state.cache_service = cache_service

    # NOTE: Workflow scheduling is now handled by Celery Beat.
    # See src/tasks/workflow_tasks.py and src/celery_app.py beat_schedule.
    # APScheduler (workflow_scheduler_service) is retained as a fallback
    # but no longer started here.

    # Initialize Async Redis for Coding Agent
    try:
        import redis.asyncio as aioredis
        app.state.redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await app.state.redis.ping()
        logger.info("Async Redis for Coding Agent initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Async Redis: {e}")
        app.state.redis = None

    # Background task for orphan cleanup
    async def orphan_cleanup_loop():
        await asyncio.sleep(60)  # Wait for startup
        while True:
            if hasattr(app.state, "redis") and app.state.redis:
                try:
                    cleaned = await coding_agent_sandbox.cleanup_orphaned_workspaces(app.state.redis)
                    if cleaned > 0:
                        logger.info(f"Orphan cleanup: removed {cleaned} workspaces")
                except Exception as e:
                    logger.warning(f"Orphan cleanup failed: {e}")
            await asyncio.sleep(600)  # Run every 10 minutes

    cleanup_task = asyncio.create_task(orphan_cleanup_loop())

    from .services.ws_event_bus import run_inbox_subscriber

    ws_stop = asyncio.Event()
    ws_subscriber_task = asyncio.create_task(run_inbox_subscriber(ws_stop))

    logger.info("Services ready - app is now accepting requests")

    yield

    # Shutdown
    logger.info("Shutting down Mini-Hub MCP Server...")
    ws_stop.set()
    ws_subscriber_task.cancel()
    try:
        await ws_subscriber_task
    except asyncio.CancelledError:
        pass
    if hasattr(app.state, "redis") and app.state.redis:
        await app.state.redis.close()
    
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

# Create FastAPI app
app = FastAPI(
    title="Mini-Hub MCP Server",
    description="Connect AI models to marketing tools with real-time automation",
    version="1.0.0",
    lifespan=lifespan
)

# Add GZip compression middleware (compress responses > 500 bytes)
app.add_middleware(GZipMiddleware, minimum_size=500)


# ─── In-Memory Rate Limiting Middleware ───────────────────────────────────────
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory sliding-window rate limiter.
    Auth endpoints: 10 requests/minute
    Authenticated API: 600 requests/minute (dashboards burst many parallel calls)
    Unauthenticated API: 60 requests/minute
    """
    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._auth_paths = {"/auth/login", "/auth/register", "/auth/forgot-password"}

    def _cleanup(self, key: str, window: float):
        now = time.time()
        self._hits[key] = [t for t in self._hits[key] if now - t < window]

    async def dispatch(self, request, call_next):
        # Skip rate limiting in test environment
        if os.getenv("TESTING") or os.getenv("ENVIRONMENT") == "testing":
            return await call_next(request)

        path = request.url.path

        # Health checks and WebSocket upgrades are never rate-limited
        if path == "/health" or path.startswith("/ws/"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        # Choose limits based on endpoint
        if path in self._auth_paths:
            key = f"auth:{client_ip}"
            limit, window = 10, 60.0
        elif path.startswith("/auth/") or path.startswith("/api/"):
            auth_header = request.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                key = f"api-auth:{client_ip}"
                limit, window = 600, 60.0
            else:
                key = f"api:{client_ip}"
                limit, window = 60, 60.0
        else:
            return await call_next(request)

        self._cleanup(key, window)

        if len(self._hits[key]) >= limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."},
                headers={"Retry-After": str(int(window))}
            )

        self._hits[key].append(time.time())
        return await call_next(request)

app.add_middleware(RateLimitMiddleware)


# ─── Cache-Control Headers for Read-Only Endpoints ────────────────────────────
class CacheHeaderMiddleware(BaseHTTPMiddleware):
    """Add Cache-Control headers to cacheable read-only endpoints."""
    # path prefix → max-age in seconds
    CACHE_RULES = {
        "/health": 10,
        "/templates": 300,       # 5 minutes
        "/": 60,                 # root info endpoint
    }

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path

        if request.method == "GET":
            for prefix, max_age in self.CACHE_RULES.items():
                if path == prefix or (prefix != "/" and path.startswith(prefix)):
                    response.headers["Cache-Control"] = (
                        f"public, max-age={max_age}, stale-while-revalidate={max_age * 2}"
                    )
                    break

        return response

app.add_middleware(CacheHeaderMiddleware)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add ProxyHeaders middleware for secure redirects behind proxy (Fly.io)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# Add Observability Middleware (at the end to wrap everything)
app.add_middleware(ObservabilityMiddleware)

# --- Consolidated Router Setup (Fixes FastAPI Lifespan Recursion) ---
from fastapi import APIRouter
main_router = APIRouter()

main_router.include_router(access_router.router)
main_router.include_router(internal_router)
main_router.include_router(auth_router, prefix="/auth", tags=["auth"])
main_router.include_router(payment_router, prefix="/payments", tags=["payments"])
main_router.include_router(connection_router, prefix="/connections", tags=["connections"])
main_router.include_router(mcp_router, prefix="/mcp", tags=["mcp"])
main_router.include_router(api_router, prefix="/api/v1", tags=["api"])
main_router.include_router(settings_router, prefix="/settings", tags=["settings"])
main_router.include_router(security_router.router, prefix="/api/v1/security", tags=["security"])
main_router.include_router(chat_router, prefix="/chat", tags=["chat"])
main_router.include_router(workflow_router, prefix="/workflows", tags=["workflows"])
main_router.include_router(agent_router, prefix="/agents", tags=["agents"])
main_router.include_router(mpesa_agent_router)
main_router.include_router(slack_agent_router)
main_router.include_router(marketplace_router, tags=["marketplace"])
main_router.include_router(creator_router, tags=["creators"])
main_router.include_router(analytics_router, tags=["analytics"])
main_router.include_router(notification_router, tags=["notifications"])
main_router.include_router(templates_router, prefix="/templates", tags=["templates"])
main_router.include_router(favorites_router, prefix="/favorites", tags=["favorites"])
main_router.include_router(preferences_router, prefix="/preferences", tags=["preferences"])
main_router.include_router(subscription_router.router)
main_router.include_router(google_workspace_router)
main_router.include_router(slack_router)
main_router.include_router(whatsapp_router)
main_router.include_router(whatsapp_webhook.router)
main_router.include_router(whatsapp_contacts.router)
main_router.include_router(whatsapp_broadcast.router)
main_router.include_router(facebook_router)
main_router.include_router(instagram_router)
main_router.include_router(telegram_router.router)
main_router.include_router(twitter_router)
main_router.include_router(linkedin_router.router)
main_router.include_router(clickup_router.router)
main_router.include_router(teams_router.router)
main_router.include_router(zoom_router.router)
main_router.include_router(outlook_router)
main_router.include_router(notion_router)
main_router.include_router(trello_router)
main_router.include_router(jira_router)
main_router.include_router(tiktok_router.router)
main_router.include_router(ai_router.router)
main_router.include_router(support_router.router)
main_router.include_router(gmail_webhook.router)
main_router.include_router(google_drive_webhook.router)
# Note: kra_router is already included via api_router
main_router.include_router(productivity_router.router)
main_router.include_router(ws_router.router)
main_router.include_router(asana_router.router)
main_router.include_router(blog_router)
main_router.include_router(employee_router)
main_router.include_router(hubspot_router)
main_router.include_router(quickbooks_router)
main_router.include_router(airtable_router)
main_router.include_router(xero_router)
main_router.include_router(organization_router.router, prefix="/api/v1/organizations", tags=["organizations"])
main_router.include_router(zoho_router.router)
main_router.include_router(zoho_webhook.router)
main_router.include_router(github_router.router)
main_router.include_router(rag_router.router)
main_router.include_router(assistant_router.router)
main_router.include_router(public_forms_router.router)

# Coding Agent
from .routers.coding_agent_router import router as coding_agent_router
main_router.include_router(coding_agent_router)

# Product Catalog Builder (photo -> Google Sheet)
from .routers.catalog_builder_router import router as catalog_builder_router
main_router.include_router(catalog_builder_router)
from .routers.rent_collection_router import router as rent_collection_router
main_router.include_router(rent_collection_router)

# Harness Engineering
try:
    from .routers.harness_router import router as harness_router
    main_router.include_router(harness_router)
except ImportError as e:
    logging.warning(f"Harness router not available: {e}")

# Finally, include the consolidated router into the app once.
# This prevents the deep recursion in merged_lifespan.
app.include_router(main_router)




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
    """Enhanced health check with dependency status."""
    import datetime

    checks = {}
    overall = "healthy"

    # Check Redis
    try:
        if cache_service.redis_client:
            cache_service.redis_client.ping()
            checks["redis"] = "connected"
        else:
            checks["redis"] = "disconnected"
    except Exception:
        checks["redis"] = "error"

    # Check DB pool
    try:
        from .database import get_engine
        engine = get_engine()
        pool = engine.pool
        checks["db_pool"] = {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
        }
    except Exception:
        checks["db_pool"] = "error"
        overall = "degraded"

    return {
        "status": overall,
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "environment": settings.ENVIRONMENT,
        "checks": checks
    }


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
                        "use_selenium": {"type": "boolean", "description": "Use full headless browser (slower but loads JS)"},
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
        # Check rate limits
        # For MCP server mode (stdio), we might not have a full user context yet
        # In a real deployment, we'd validate an auth token passed in arguments or headers
        user_id = arguments.get("user_id", "default")
        
        if not await rate_limit_service.check_limit(user_id):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        try:
            if name == "hubspot_read_contacts":
                return await hubspot_service.get_contacts(**arguments)
            elif name == "hubspot_write_contact":
                return await hubspot_service.create_contact(**arguments)
            elif name == "hubspot_add_deal_note":
                return await hubspot_service.add_deal_note(**arguments)

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
    import os

    # Check if we should run in MCP mode (for Claude Desktop integration)
    run_mode = os.getenv("RUN_MODE", "web").lower()

    if run_mode == "mcp":
        # Run MCP server for Claude Desktop integration
        logger.info("Starting in MCP server mode...")
        asyncio.run(run_mcp_server())
    else:
        # Run FastAPI web server (Railway, Fly.io, Docker, etc.)
        port = int(os.getenv("PORT", settings.PORT))

        # Detect production: Railway sets PORT env var
        is_prod = os.getenv("PORT") or settings.ENVIRONMENT == "production"

        # Force single process by removing WEB_CONCURRENCY if it exists
        os.environ.pop("WEB_CONCURRENCY", None)

        uvicorn.run(
            "src.main:app",
            host="0.0.0.0",
            port=port,
            reload=False if is_prod else settings.RELOAD,
            log_level="info" if is_prod else settings.LOG_LEVEL.lower()
        )


if __name__ == "__main__":
    main()
