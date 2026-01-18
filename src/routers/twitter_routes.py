from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
import httpx
import logging
import urllib.parse
import secrets
import hashlib
import base64
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from ..config import settings
from ..routers.auth_router import get_current_user

router = APIRouter(
    prefix="/api/twitter",
    tags=["twitter"]
)

logger = logging.getLogger(__name__)

# Constants
TWITTER_AUTH_URL = "https://twitter.com/i/oauth2/authorize"
TWITTER_TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
# Scopes for Twitter API v2
TWITTER_SCOPES = "tweet.read tweet.write users.read offline.access"

# Simple in-memory store for PKCE verifiers
# Structure: {state_token: {"verifier": code_verifier, "user_id": user_id}}
# In production with multiple workers, this should be Redis
PKCE_STORE = {}

def create_code_verifier():
    token = secrets.token_urlsafe(100)
    return token

def create_code_challenge(code_verifier):
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip('=')

@router.get("/auth-url")
async def get_auth_url(user: User = Depends(get_current_user)):
    """Generate Twitter OAuth 2.0 URL with PKCE."""
    if not settings.TWITTER_CLIENT_ID or not settings.TWITTER_CLIENT_SECRET:
        raise HTTPException(
            status_code=500, 
            detail="Twitter Client ID or Secret not configured"
        )

    redirect_uri = f"{settings.API_BASE_URL}/api/twitter/callback"
    
    # Generate a random state token for security and storage key
    state_token = secrets.token_urlsafe(16)
    
    # PKCE Generation
    code_verifier = create_code_verifier()
    code_challenge = create_code_challenge(code_verifier)
    
    # Store verifier and user_id in memory (short-lived)
    PKCE_STORE[state_token] = {
        "verifier": code_verifier,
        "user_id": user.id
    }
    
    params = {
        "response_type": "code",
        "client_id": settings.TWITTER_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": TWITTER_SCOPES,
        "state": state_token,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256"
    }
    
    auth_url = f"{TWITTER_AUTH_URL}?{urllib.parse.urlencode(params)}"
    
    # Return JSON directly
    return {"url": auth_url}

@router.get("/callback")
async def oauth_callback(
    request: Request,
    code: str, 
    state: str, 
    error: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Handle Twitter OAuth callback."""
    if error:
        logger.error(f"Twitter OAuth error: {error}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/connections?error={error}"
        )

    try:
        # Retrieve stored PKCE data
        pkce_data = PKCE_STORE.pop(state, None)
        
        if not pkce_data:
            logger.error(f"Missing or invalid state: {state}")
            return RedirectResponse(
                url=f"{settings.FRONTEND_URL}/connections?error=invalid_state"
            )

        user_id = pkce_data["user_id"]
        code_verifier = pkce_data["verifier"]
        
        redirect_uri = f"{settings.API_BASE_URL}/api/twitter/callback"

        # Exchange code for token
        async with httpx.AsyncClient() as client:
            auth = (settings.TWITTER_CLIENT_ID, settings.TWITTER_CLIENT_SECRET)
            data = {
                "code": code,
                "grant_type": "authorization_code",
                "client_id": settings.TWITTER_CLIENT_ID,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier
            }
            
            response = await client.post(
                TWITTER_TOKEN_URL, 
                data=data, 
                auth=auth,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            token_data = response.json()
            
            if response.status_code != 200:
                logger.error(f"Failed to exchange code: {token_data}")
                raise HTTPException(status_code=400, detail="Failed to exchange authorization code")
                
            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")
            
            # Update or Create Connection
            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user_id,
                    Connection.platform == "twitter"
                )
            )
            connection = result.scalar_one_or_none()
            
            config_data = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "auth_type": "oauth_pkce"
            }

            if connection:
                connection.status = ConnectionStatus.ACTIVE
                connection.config = {**connection.config, **config_data} if connection.config else config_data
            else:
                connection = Connection(
                    user_id=user_id,
                    platform="twitter",
                    name="Twitter (X)",
                    status=ConnectionStatus.ACTIVE,
                    config=config_data
                )
                db.add(connection)
            
            await db.commit()
            
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/connections?success=twitter_connected")

    except Exception as e:
        logger.error(f"Error in Twitter callback: {e}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/connections?error=internal_error"
        )
