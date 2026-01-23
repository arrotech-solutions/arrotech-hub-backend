"""
Zoom OAuth Routes
Handles OAuth 2.0 authorization flow for Zoom integration.
"""
import logging
import os
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from ..routers.auth_router import get_current_user
from ..services.zoom_service import ZoomService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/zoom", tags=["zoom-oauth"])

# Zoom OAuth configuration
ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID")
ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET")
ZOOM_REDIRECT_URI = os.getenv("ZOOM_REDIRECT_URI", "http://localhost:3000/connections")

from fastapi.responses import RedirectResponse
from ..config import settings

@router.get("/auth-url")
async def get_auth_url(
    user: User = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Generate Zoom OAuth authorization URL
    """
    try:
        # Check tier-based access BEFORE allowing OAuth flow
        from ..services.tier_gate import check_connection_access
        check_connection_access(user, "zoom")
        
        service = ZoomService()
        await service.initialize()
        
        # Ensure config
        if ZOOM_CLIENT_ID: service.client_id = ZOOM_CLIENT_ID
        
        # Use backend redirect URI
        final_redirect_uri = ZOOM_REDIRECT_URI
        
        state = f"user_{user.id}"
        auth_url = service.get_auth_url(redirect_uri=final_redirect_uri, state=state)
        
        return {
            "auth_url": auth_url,
            "state": state
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating Zoom auth URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
async def oauth_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Handle OAuth callback and exchange authorization code for tokens
    """
    try:
        if not ZOOM_CLIENT_ID or not ZOOM_CLIENT_SECRET:
            error_msg = "Zoom OAuth is not configured"
            return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error={error_msg}")
        
        # Extract user ID from state
        if not state.startswith("user_"):
            return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error=Invalid state parameter")
        
        try:
            user_id = int(state.replace("user_", ""))
        except ValueError:
             return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error=Invalid state format")

        service = ZoomService()
        await service.initialize()
        
        service.client_id = ZOOM_CLIENT_ID
        service.client_secret = ZOOM_CLIENT_SECRET
        
        # Use backend redirect URI
        final_redirect_uri = ZOOM_REDIRECT_URI
        
        token_data = await service.exchange_code_for_token(code, final_redirect_uri)
        
        # Extract useful info
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        
        # Check existing connection
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user_id,
                Connection.platform == "zoom"
            )
        )
        existing_connection = result.scalars().first()
        
        config = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "client_id": ZOOM_CLIENT_ID,
            "client_secret": ZOOM_CLIENT_SECRET,
            "token_type": token_data.get("token_type"),
            "scope": token_data.get("scope"),
            "expires_in": token_data.get("expires_in")
        }

        if existing_connection:
            existing_connection.status = ConnectionStatus.ACTIVE
            existing_connection.config = config
            existing_connection.name = "Zoom"
            await db.commit()
        else:
            new_connection = Connection(
                user_id=user_id,
                platform="zoom",
                name="Zoom",
                status=ConnectionStatus.ACTIVE,
                config=config
            )
            db.add(new_connection)
            await db.commit()
        
        return RedirectResponse(f"{settings.FRONTEND_URL}/connections?success=zoom_connected")
    
    except Exception as e:
        logger.error(f"Error in Zoom OAuth callback: {e}")
        return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error={str(e)}")
