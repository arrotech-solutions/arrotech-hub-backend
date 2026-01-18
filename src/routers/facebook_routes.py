from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
import httpx
import logging
import urllib.parse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from ..config import settings
from ..routers.auth_router import get_current_user

router = APIRouter(
    prefix="/api/facebook",
    tags=["facebook"]
)

logger = logging.getLogger(__name__)

# Constants
FACEBOOK_GRAPH_URL = "https://graph.facebook.com/v22.0"
# Scopes for managing pages and reading insights
FACEBOOK_SCOPES = "pages_show_list,pages_read_engagement"

@router.get("/auth-url")
async def get_auth_url(user: User = Depends(get_current_user)):
    """Generate Facebook OAuth URL."""
    if not settings.FACEBOOK_APP_ID or not settings.FACEBOOK_APP_SECRET:
        raise HTTPException(
            status_code=500, 
            detail="Facebook App ID or Secret not configured"
        )

    redirect_uri = f"{settings.API_BASE_URL}/api/facebook/callback"
    
    # State includes user_id to link connection back to user
    state = str(user.id)
    
    params = {
        "client_id": settings.FACEBOOK_APP_ID,
        "redirect_uri": redirect_uri,
        "scope": FACEBOOK_SCOPES,
        "response_type": "code",
        "state": state
    }
    
    auth_url = f"https://www.facebook.com/v22.0/dialog/oauth?{urllib.parse.urlencode(params)}"
    return {"url": auth_url}

@router.get("/callback")
async def oauth_callback(
    code: str, 
    state: str, 
    error: Optional[str] = None,
    error_reason: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Handle Facebook OAuth callback."""
    if error:
        logger.error(f"Facebook OAuth error: {error} - {error_reason}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/connections?error={error}&reason={error_reason}"
        )

    try:
        user_id = int(state)
        redirect_uri = f"{settings.API_BASE_URL}/api/facebook/callback"
        
        # 1. Exchange code for short-lived token
        async with httpx.AsyncClient() as client:
            token_url = f"{FACEBOOK_GRAPH_URL}/oauth/access_token"
            params = {
                "client_id": settings.FACEBOOK_APP_ID,
                "client_secret": settings.FACEBOOK_APP_SECRET,
                "redirect_uri": redirect_uri,
                "code": code
            }
            
            response = await client.get(token_url, params=params)
            data = response.json()
            
            if response.status_code != 200:
                logger.error(f"Failed to exchange code: {data}")
                raise HTTPException(status_code=400, detail="Failed to exchange authorization code")
                
            short_lived_token = data.get("access_token")
            
            # 2. Exchange for long-lived token (60 days)
            exchange_url = f"{FACEBOOK_GRAPH_URL}/oauth/access_token"
            exchange_params = {
                "grant_type": "fb_exchange_token",
                "client_id": settings.FACEBOOK_APP_ID,
                "client_secret": settings.FACEBOOK_APP_SECRET,
                "fb_exchange_token": short_lived_token
            }
            
            exchange_resp = await client.get(exchange_url, params=exchange_params)
            exchange_data = exchange_resp.json()
            
            if exchange_resp.status_code != 200:
                logger.warning(f"Failed to exchange for long-lived token: {exchange_data}")
                access_token = short_lived_token
            else:
                access_token = exchange_data.get("access_token")

            # Update or Create Connection
            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user_id,
                    Connection.platform == "facebook"
                )
            )
            connection = result.scalar_one_or_none()
            
            config_data = {
                "access_token": access_token,
                "auth_type": "oauth"
            }

            if connection:
                connection.status = ConnectionStatus.ACTIVE
                connection.config = {**connection.config, **config_data} if connection.config else config_data
            else:
                connection = Connection(
                    user_id=user_id,
                    platform="facebook",
                    name="Facebook Pages",
                    status=ConnectionStatus.ACTIVE,
                    config=config_data
                )
                db.add(connection)
            
            await db.commit()
            
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/connections?success=facebook_connected")

    except Exception as e:
        logger.error(f"Error in Facebook callback: {e}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/connections?error=internal_error"
        )
