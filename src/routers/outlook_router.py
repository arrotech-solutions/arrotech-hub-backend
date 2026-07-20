"""
Outlook OAuth Routes
Handles OAuth 2.0 authorization flow for Microsoft Outlook integration.
"""
import logging
import os
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import RedirectResponse

from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from ..routers.auth_router import get_current_user
from ..services.outlook_service import OutlookService
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/outlook", tags=["outlook-oauth"])

# Outlook OAuth configuration
OUTLOOK_CLIENT_ID = os.getenv("OUTLOOK_CLIENT_ID")
OUTLOOK_CLIENT_SECRET = os.getenv("OUTLOOK_CLIENT_SECRET")
OUTLOOK_TENANT_ID = os.getenv("OUTLOOK_TENANT_ID", "common")
# This should match the URI registered in Azure Portal.
OUTLOOK_REDIRECT_URI = os.getenv("OUTLOOK_REDIRECT_URI", "http://localhost:8000/api/outlook/callback")

@router.get("/auth-url")
async def get_auth_url(
    user: User = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Generate Microsoft Outlook OAuth authorization URL
    """
    try:
        # Check tier-based access BEFORE allowing OAuth flow
        from ..services.tier_gate import check_connection_access
        check_connection_access(user, "microsoft_outlook")
        
        service = OutlookService()
        await service.initialize() 
        
        # Override with specific env vars if available
        if OUTLOOK_CLIENT_ID: service.client_id = OUTLOOK_CLIENT_ID
        if OUTLOOK_TENANT_ID: service.tenant_id = OUTLOOK_TENANT_ID
        
        state = f"user_{user.id}"
        auth_url = service.get_auth_url(redirect_uri=OUTLOOK_REDIRECT_URI, state=state)
        
        return {
            "auth_url": auth_url,
            "state": state
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating Outlook auth URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
async def oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Handle OAuth callback and exchange authorization code for tokens
    """
    try:
        # Handle OAuth errors
        if error:
            logger.error(f"Outlook OAuth Error: {error} - {error_description}")
            return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error={error_description or error}")

        if not code or not state:
            return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error=Missing code or state parameter")

        if not OUTLOOK_CLIENT_ID or not OUTLOOK_CLIENT_SECRET:
            error_msg = "Outlook OAuth is not configured"
            return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error={error_msg}")
        
        # Extract user ID from state
        if not state.startswith("user_"):
             return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error=Invalid state parameter")
        
        try:
            import uuid
            user_id = uuid.UUID(state.replace("user_", ""))
        except ValueError:
             return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error=Invalid state format")

        service = OutlookService()
        await service.initialize()
        
        service.client_id = OUTLOOK_CLIENT_ID
        service.client_secret = OUTLOOK_CLIENT_SECRET
        service.tenant_id = OUTLOOK_TENANT_ID
        
        token_data = await service.exchange_code_for_token(code, OUTLOOK_REDIRECT_URI)
        
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        
        # Check if user already has an Outlook connection
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user_id,
                Connection.platform == "outlook"
            )
        )
        existing_connection = result.scalars().first()
        
        config = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "tenant_id": OUTLOOK_TENANT_ID,
            "client_id": OUTLOOK_CLIENT_ID,
            "client_secret": OUTLOOK_CLIENT_SECRET, 
            "token_type": token_data.get("token_type"),
            "scope": token_data.get("scope"),
            "expires_in": token_data.get("expires_in")
        }

        if existing_connection:
            existing_connection.status = ConnectionStatus.ACTIVE
            existing_connection.config = config
            existing_connection.name = "Outlook"
            await db.commit()
        else:
            new_connection = Connection(
                user_id=user_id,
                platform="outlook",
                name="Outlook",
                status=ConnectionStatus.ACTIVE,
                config=config
            )
            db.add(new_connection)
            await db.commit()
        
        return RedirectResponse(f"{settings.FRONTEND_URL}/connections?success=outlook_connected")
    
    except Exception as e:
        logger.error(f"Error in Outlook OAuth callback: {e}")
        return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error={str(e)}")
