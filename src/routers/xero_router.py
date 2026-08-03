"""
Xero OAuth Routes.
Handles OAuth 2.0 authorization flow for Xero accounting integration.
"""
import logging
import os
from typing import Optional, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..utils.oauth_frontend import (
    connections_redirect,
    frontend_connections_path,
    split_oauth_state,
    with_frontend_origin,
)
from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from ..routers.auth_router import get_current_user
from ..services.xero_service import XeroService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/xero", tags=["xero-oauth"])

XERO_CLIENT_ID = os.getenv("XERO_CLIENT_ID")
XERO_CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET")
XERO_REDIRECT_URI = os.getenv(
    "XERO_REDIRECT_URI", "http://localhost:8000/api/xero/callback"
)


@router.get("/auth-url")
async def get_auth_url(
    frontend_origin: Optional[str] = None,
    user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """Generate Xero OAuth authorization URL."""
    try:
        from ..services.tier_gate import check_connection_access
        check_connection_access(user, "xero")

        service = XeroService()
        await service.initialize()

        if XERO_CLIENT_ID:
            service.client_id = XERO_CLIENT_ID

        state = with_frontend_origin(f"user_{user.id}", frontend_origin)
        auth_url = service.get_auth_url(
            redirect_uri=XERO_REDIRECT_URI, state=state
        )
        return {"auth_url": auth_url, "state": state}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating Xero auth URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
async def oauth_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Handle OAuth callback for Xero. Exchange code for tokens, fetch tenants, upsert connection."""
    try:
        if not XERO_CLIENT_ID or not XERO_CLIENT_SECRET:
            return connections_redirect(state, extra_query="error=Xero OAuth is not configured")

        raw_state, _fe_base = split_oauth_state(state)
        state = raw_state or ""
        if not state.startswith("user_"):
            return connections_redirect(state, extra_query="error=Invalid state parameter")

        try:
            import uuid
            user_id = uuid.UUID(state.replace("user_", ""))
        except ValueError:
            return connections_redirect(state, extra_query="error=Invalid state format")

        service = XeroService()
        await service.initialize()
        service.client_id = XERO_CLIENT_ID
        service.client_secret = XERO_CLIENT_SECRET

        token_data = await service.exchange_code_for_token(code, XERO_REDIRECT_URI)
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        service.access_token = access_token
        service.refresh_token = refresh_token

        # Get tenants (organisations) and use the first one
        connections = await service.get_connections()
        if not connections:
            return connections_redirect(state, extra_query="error=No Xero organisation found")
        tenant_id = connections[0].get("tenantId")
        tenant_name = connections[0].get("tenantName", "Xero Organisation")

        config = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "tenant_id": tenant_id,
            "tenant_name": tenant_name,
        }

        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user_id,
                Connection.platform == "xero",
            )
        )
        existing_connection = result.scalars().first()

        if existing_connection:
            existing_connection.status = ConnectionStatus.ACTIVE
            existing_connection.config = config
            existing_connection.name = f"Xero ({tenant_name})"
            await db.commit()
        else:
            new_connection = Connection(
                user_id=user_id,
                platform="xero",
                name=f"Xero ({tenant_name})",
                status=ConnectionStatus.ACTIVE,
                config=config,
            )
            db.add(new_connection)
            await db.commit()

        return connections_redirect(state, success="xero_connected")

    except Exception as e:
        logger.error(f"Error in Xero OAuth callback: {e}")
        return connections_redirect(state, error=str(e))
