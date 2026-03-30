"""
Teams OAuth Routes
Handles OAuth 2.0 authorization flow for Microsoft Teams integration.
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
from ..services.teams_service import TeamsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/teams", tags=["teams-oauth"])

# Teams OAuth configuration
TEAMS_CLIENT_ID = os.getenv("TEAMS_CLIENT_ID")
TEAMS_CLIENT_SECRET = os.getenv("TEAMS_CLIENT_SECRET")
TEAMS_TENANT_ID = os.getenv("TEAMS_TENANT_ID")
TEAMS_REDIRECT_URI = os.getenv("TEAMS_REDIRECT_URI", "http://localhost:3000/connections")

from fastapi.responses import RedirectResponse
from ..config import settings

@router.get("/auth-url")
async def get_auth_url(
    user: User = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Generate Microsoft Teams OAuth authorization URL
    """
    try:
        # Check tier-based access BEFORE allowing OAuth flow
        from ..services.tier_gate import check_connection_access
        check_connection_access(user, "microsoft_teams")
        
        service = TeamsService()
        await service.initialize() 
        
        if TEAMS_CLIENT_ID: service.client_id = TEAMS_CLIENT_ID
        if TEAMS_TENANT_ID: service.tenant_id = TEAMS_TENANT_ID
        
        # Use backend redirect URI
        final_redirect_uri = TEAMS_REDIRECT_URI
        
        state = f"user_{user.id}"
        auth_url = service.get_auth_url(redirect_uri=final_redirect_uri, state=state)
        
        return {
            "auth_url": auth_url,
            "state": state
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating Teams auth URL: {e}")
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
        if not TEAMS_CLIENT_ID or not TEAMS_CLIENT_SECRET:
            error_msg = "Teams OAuth is not configured"
            return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error={error_msg}")
        
        # Extract user ID from state
        if not state.startswith("user_"):
             return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error=Invalid state parameter")
        
        try:
            import uuid
            user_id = uuid.UUID(state.replace("user_", ""))
        except ValueError:
             return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error=Invalid state format")

        service = TeamsService()
        await service.initialize()
        
        # Ensure credentials are set
        service.client_id = TEAMS_CLIENT_ID
        service.client_secret = TEAMS_CLIENT_SECRET
        service.tenant_id = TEAMS_TENANT_ID
        
        # Use backend redirect URI
        final_redirect_uri = TEAMS_REDIRECT_URI
        
        token_data = await service.exchange_code_for_token(code, final_redirect_uri)
        
        # Extract useful info
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        
        # Check if user already has a Teams connection
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user_id,
                Connection.platform == "teams"
            )
        )
        existing_connection = result.scalars().first()
        
        config = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "tenant_id": TEAMS_TENANT_ID,
            "client_id": TEAMS_CLIENT_ID,
            "client_secret": TEAMS_CLIENT_SECRET, 
            "token_type": token_data.get("token_type"),
            "scope": token_data.get("scope"),
            "expires_in": token_data.get("expires_in")
        }

        if existing_connection:
            # Update existing connection
            existing_connection.status = ConnectionStatus.ACTIVE
            existing_connection.config = config
            existing_connection.name = "Microsoft Teams"
            await db.commit()
        else:
            # Create new connection
            new_connection = Connection(
                user_id=user_id,
                platform="teams",
                name="Microsoft Teams",
                status=ConnectionStatus.ACTIVE,
                config=config
            )
            db.add(new_connection)
            await db.commit()
        
        return RedirectResponse(f"{settings.FRONTEND_URL}/connections?success=teams_connected")
    
    except Exception as e:
        logger.error(f"Error in Teams OAuth callback: {e}")
        return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error={str(e)}")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in Teams OAuth callback: {e}")
        raise HTTPException(status_code=500, detail=str(e))
