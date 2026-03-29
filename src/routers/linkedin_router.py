from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
import httpx
import logging
import urllib.parse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import os

from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from ..config import settings
from ..routers.auth_router import get_current_user

router = APIRouter(
    prefix="/api/linkedin",
    tags=["linkedin"]
)

logger = logging.getLogger(__name__)

# Constants
LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_API_URL = "https://api.linkedin.com/v2"

# Scopes: openid, profile, and w_member_social to post content
LINKEDIN_SCOPES = "openid profile email w_member_social"

LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")

@router.get("/auth-url")
async def get_auth_url(user: User = Depends(get_current_user)):
    """Generate LinkedIn OAuth URL."""
    # Check tier-based access BEFORE allowing OAuth flow
    from ..services.tier_gate import check_connection_access
    check_connection_access(user, "linkedin")
    
    if not LINKEDIN_CLIENT_ID or not LINKEDIN_CLIENT_SECRET:
        raise HTTPException(
            status_code=500, 
            detail="LinkedIn Client ID or Secret not configured"
        )

    redirect_uri = f"{settings.API_BASE_URL.rstrip('/')}/api/linkedin/callback"
    
    # State includes user_id to link connection back to user
    state = str(user.id)
    
    params = {
        "response_type": "code",
        "client_id": LINKEDIN_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": LINKEDIN_SCOPES
    }
    
    auth_url = f"{LINKEDIN_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return {"url": auth_url}

@router.get("/callback")
async def oauth_callback(
    code: str, 
    state: str, 
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Handle LinkedIn OAuth callback."""
    if error:
        logger.error(f"LinkedIn OAuth error: {error} - {error_description}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/connections?error={error}"
        )

    try:
        user_id = int(state)
        redirect_uri = f"{settings.API_BASE_URL.rstrip('/')}/api/linkedin/callback"
        
        # 1. Exchange code for access token
        async with httpx.AsyncClient() as client:
            data = {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": LINKEDIN_CLIENT_ID,
                "client_secret": LINKEDIN_CLIENT_SECRET,
                "redirect_uri": redirect_uri
            }
            headers = {
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            response = await client.post(LINKEDIN_TOKEN_URL, data=data, headers=headers)
            token_data = response.json()
            
            if response.status_code != 200:
                logger.error(f"Failed to exchange code: {token_data}")
                return RedirectResponse(url=f"{settings.FRONTEND_URL}/connections?error=token_exchange_failed")
                
            access_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in") # Usually 60 days
            
            # 2. Fetch User Profile to get URN and Name
            userinfo_response = await client.get(
                "https://api.linkedin.com/v2/userinfo", 
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            user_info = userinfo_response.json()
            linkedin_sub = user_info.get("sub", "")
            linkedin_name = f"{user_info.get('given_name', '')} {user_info.get('family_name', '')}".strip()
            
            # LinkedIn URN format is commonly ur:li:person:{sub}
            author_urn = f"urn:li:person:{linkedin_sub}"

            # Update or Create Connection
            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user_id,
                    Connection.platform == "linkedin"
                )
            )
            connection = result.scalar_one_or_none()
            
            config_data = {
                "access_token": access_token,
                "author_urn": author_urn,
                "profile_name": linkedin_name,
                "auth_type": "oauth"
            }

            if connection:
                connection.status = ConnectionStatus.ACTIVE
                connection.config = {**connection.config, **config_data} if connection.config else config_data
                connection.name = f"LinkedIn ({linkedin_name})"
            else:
                connection = Connection(
                    user_id=user_id,
                    platform="linkedin",
                    name=linkedin_name or "LinkedIn Account",
                    status=ConnectionStatus.ACTIVE,
                    config=config_data
                )
                db.add(connection)
            
            await db.commit()
            
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/connections?success=linkedin_connected")

    except Exception as e:
        logger.error(f"Error in LinkedIn callback: {e}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/connections?error=internal_error"
        )
