"""
Jira OAuth Routes (Atlassian)
Handles OAuth 2.0 authorization flow for Jira integration.
"""
import logging
import os
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import RedirectResponse

from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from ..routers.auth_router import get_current_user
from ..services.jira_service import JiraService
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jira", tags=["jira-oauth"])

# Jira (Atlassian) configuration
JIRA_CLIENT_ID = os.getenv("JIRA_CLIENT_ID")
JIRA_CLIENT_SECRET = os.getenv("JIRA_CLIENT_SECRET")
JIRA_REDIRECT_URI = os.getenv("JIRA_REDIRECT_URI", "http://localhost:8000/api/jira/callback")

@router.get("/auth-url")
async def get_auth_url(
    user: User = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Generate Jira OAuth authorization URL
    """
    try:
        # Check tier-based access BEFORE allowing OAuth flow
        from ..services.tier_gate import check_connection_access
        check_connection_access(user, "jira")
        
        service = JiraService()
        await service.initialize() 
        
        if JIRA_CLIENT_ID: service.client_id = JIRA_CLIENT_ID
        
        state = f"user_{user.id}"
        auth_url = service.get_auth_url(redirect_uri=JIRA_REDIRECT_URI, state=state)
        
        return {
            "auth_url": auth_url,
            "state": state
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating Jira auth URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
async def oauth_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Handle OAuth callback for Jira
    """
    try:
        if not JIRA_CLIENT_ID or not JIRA_CLIENT_SECRET:
            error_msg = "Jira OAuth is not configured"
            return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error={error_msg}")
        
        if not state.startswith("user_"):
             return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error=Invalid state parameter")
        
        try:
            import uuid
            user_id = uuid.UUID(state.replace("user_", ""))
        except ValueError:
             return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error=Invalid state format")

        service = JiraService()
        await service.initialize()
        
        service.client_id = JIRA_CLIENT_ID
        service.client_secret = JIRA_CLIENT_SECRET
        
        token_data = await service.exchange_code_for_token(code, JIRA_REDIRECT_URI)
        
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        
        service.access_token = access_token
        
        # Get Cloud Resources
        resources = await service.get_accessible_resources()
        if not resources:
             return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error=No Jira sites found")
             
        # Pick the first one for now
        # Ideally we let user choose if multiple
        target_site = resources[0]
        cloud_id = target_site.get("id")
        site_name = target_site.get("name")
        site_url = target_site.get("url")
        
        config = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "cloud_id": cloud_id, 
            "site_name": site_name,
            "site_url": site_url,
            "scopes": token_data.get("scope")
        }

        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user_id,
                Connection.platform == "jira"
            )
        )
        existing_connection = result.scalars().first()
        
        if existing_connection:
            existing_connection.status = ConnectionStatus.ACTIVE
            existing_connection.config = config
            existing_connection.name = f"Jira ({site_name})"
            await db.commit()
        else:
            new_connection = Connection(
                user_id=user_id,
                platform="jira",
                name=f"Jira ({site_name})",
                status=ConnectionStatus.ACTIVE,
                config=config
            )
            db.add(new_connection)
            await db.commit()
        
        return RedirectResponse(f"{settings.FRONTEND_URL}/connections?success=jira_connected")
    
    except Exception as e:
        logger.error(f"Error in Jira OAuth callback: {e}")
        return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error={str(e)}")
