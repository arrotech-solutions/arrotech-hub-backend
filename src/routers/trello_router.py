"""
Trello OAuth Routes (via Atlassian)
Handles OAuth 2.0 authorization flow for Trello integration.
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
from ..services.trello_service import TrelloService
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trello", tags=["trello-oauth"])

# Trello (Power-Up) OAuth 1.0a configuration
TRELLO_CLIENT_ID = os.getenv("TRELLO_CLIENT_ID")
TRELLO_CLIENT_SECRET = os.getenv("TRELLO_CLIENT_SECRET")
TRELLO_REDIRECT_URI = os.getenv("TRELLO_REDIRECT_URI", "http://localhost:8000/api/trello/callback")

# Simple in-memory store for request token secrets (oauth_token -> oauth_token_secret)
# In production, use Redis with TTL
request_token_store: Dict[str, str] = {}

@router.get("/auth-url")
async def get_auth_url(
    user: User = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Generate Trello OAuth 1.0a authorization URL
    """
    try:
        # Check tier-based access BEFORE allowing OAuth flow
        from ..services.tier_gate import check_connection_access
        check_connection_access(user, "trello")
        
        service = TrelloService()
        await service.initialize() 
        
        # 1. Get Request Token
        # We pass the callback URI here
        token_data = await service.get_request_token(redirect_uri=TRELLO_REDIRECT_URI)
        
        request_token = token_data.get("oauth_token")
        request_token_secret = token_data.get("oauth_token_secret")
        
        if not request_token or not request_token_secret:
             raise HTTPException(status_code=500, detail="Failed to retrieve request token from Trello")

        # Store secret for callback verification
        request_token_store[request_token] = request_token_secret
        
        # 2. Generate Auth URL
        # Trello doesn't support 'state' param in OAuth 1.0a authorize URL in the same way 2.0 does,
        # but we can try appending it or just relying on the user session if cookies were used.
        # Since we use Bearer tokens, we can't easily persist 'user_id' through the Trello redirect 
        # unless we encode it in the callback URI dynamically, but we set a static one.
        # However, we can store user_id mapped to the request_token too.
        request_token_store[f"{request_token}_user"] = str(user.id)

        auth_url = service.get_auth_url(resource_owner_key=request_token)
        
        return {
            "auth_url": auth_url,
            "state": request_token # Returning token as state for frontend ref
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating Trello auth URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
async def oauth_callback(
    oauth_token: str,
    oauth_verifier: str,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Handle OAuth 1.0a callback for Trello
    """
    try:
        if not TRELLO_CLIENT_ID or not TRELLO_CLIENT_SECRET:
            error_msg = "Trello OAuth is not configured"
            return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error={error_msg}")
        
        # Retrieve the secret and user_id for this token
        request_token_secret = request_token_store.get(oauth_token)
        user_id_str = request_token_store.get(f"{oauth_token}_user")
        
        if not request_token_secret or not user_id_str:
             return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error=Invalid or expired session command")

        user_id = int(user_id_str)
        
        # Clean up store
        del request_token_store[oauth_token]
        del request_token_store[f"{oauth_token}_user"]

        service = TrelloService()
        await service.initialize()
        
        # Exchange for Access Token
        access_token_data = await service.exchange_token(
            resource_owner_key=oauth_token,
            resource_owner_secret=request_token_secret,
            verifier=oauth_verifier
        )
        
        access_token = access_token_data.get("oauth_token")
        access_token_secret = access_token_data.get("oauth_token_secret")
        
        if not access_token:
             return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error=Failed to obtain access token")

        # Get User Info
        service.access_token = access_token
        service.access_token_secret = access_token_secret
        
        me_response = await service._request("GET", "members/me")
        
        if isinstance(me_response, dict) and "error" in me_response:
             logger.error(f"Failed to fetch Trello profile: {me_response}")
             trello_username = "Trello User"
             trello_id = None
        else:
             trello_username = me_response.get("username") or me_response.get("fullName") or "Trello User"
             trello_id = me_response.get("id")
        
        config = {
            "access_token": access_token,
            "access_token_secret": access_token_secret,
            "trello_username": trello_username,
            "trello_id": trello_id
        }

        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user_id,
                Connection.platform == "trello"
            )
        )
        existing_connection = result.scalars().first()
        
        if existing_connection:
            existing_connection.status = ConnectionStatus.ACTIVE
            existing_connection.config = config
            existing_connection.name = f"Trello ({trello_username})"
            await db.commit()
        else:
            new_connection = Connection(
                user_id=user_id,
                platform="trello",
                name=f"Trello ({trello_username})",
                status=ConnectionStatus.ACTIVE,
                config=config
            )
            db.add(new_connection)
            await db.commit()
        
        return RedirectResponse(f"{settings.FRONTEND_URL}/connections?success=trello_connected")
    
    except Exception as e:
        logger.error(f"Error in Trello OAuth callback: {e}")
        return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error={str(e)}")
