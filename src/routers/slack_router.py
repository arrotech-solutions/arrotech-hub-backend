"""
Slack OAuth Routes
Handles OAuth 2.0 authorization flow for Slack integration.
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/slack", tags=["slack-oauth"])

# Slack OAuth configuration
SLACK_CLIENT_ID = os.getenv("SLACK_CLIENT_ID")
SLACK_CLIENT_SECRET = os.getenv("SLACK_CLIENT_SECRET")
SLACK_REDIRECT_URI = os.getenv("SLACK_REDIRECT_URI", "http://localhost:3000/connections")

# OAuth scopes for Slack
# Based on what is likely needed for the agent functionalities seen in code
SCOPES = [
    "chat:write",
    "channels:read",
    "groups:read",
    "im:read",
    "mpim:read",
    "users:read",
    "incoming-webhook",
    "commands",
    "files:write"
]

@router.get("/auth-url")
async def get_auth_url(
    user: User = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Generate Slack OAuth authorization URL
    """
    try:
        if not SLACK_CLIENT_ID:
            raise HTTPException(
                status_code=500,
                detail="Slack OAuth is not configured. Please set SLACK_CLIENT_ID."
            )
        
        # Build OAuth URL
        from urllib.parse import urlencode
        
        params = {
            "client_id": SLACK_CLIENT_ID,
            "scope": " ".join(SCOPES),
            "redirect_uri": SLACK_REDIRECT_URI,
            "state": f"user_{user.id}",  # Include user ID in state for validation
        }
        
        auth_url = f"https://slack.com/oauth/v2/authorize?{urlencode(params)}"
        
        return {
            "auth_url": auth_url,
            "state": params["state"]
        }
    
    except Exception as e:
        logger.error(f"Error generating Slack auth URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
async def oauth_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Handle OAuth callback and exchange authorization code for tokens
    """
    try:
        if not SLACK_CLIENT_ID or not SLACK_CLIENT_SECRET:
            raise HTTPException(
                status_code=500,
                detail="Slack OAuth is not configured"
            )
        
        # Extract user ID from state
        if not state.startswith("user_"):
            raise HTTPException(status_code=400, detail="Invalid state parameter")
        
        try:
            import uuid
            user_id = uuid.UUID(state.replace("user_", ""))
        except ValueError:
             raise HTTPException(status_code=400, detail="Invalid state parameter format")

        
        # Exchange authorization code for tokens
        import requests
        
        token_url = "https://slack.com/api/oauth.v2.access"
        token_data = {
            "code": code,
            "client_id": SLACK_CLIENT_ID,
            "client_secret": SLACK_CLIENT_SECRET,
            "redirect_uri": SLACK_REDIRECT_URI,
        }
        
        token_response = requests.post(token_url, data=token_data)
        
        if token_response.status_code != 200:
            logger.error(f"Token exchange failed: {token_response.text}")
            raise HTTPException(
                status_code=400,
                detail="Failed to exchange authorization code for tokens"
            )
        
        data = token_response.json()
        
        if not data.get("ok"):
             logger.error(f"Slack API error: {data.get('error')}")
             raise HTTPException(
                status_code=400,
                detail=f"Slack API error: {data.get('error')}"
            )

        # Extract useful info
        access_token = data.get("access_token") # This is the bot token for modern Slack apps
        team = data.get("team", {})
        authed_user = data.get("authed_user", {})
        
        # Check if user already has a Slack connection
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user_id,
                Connection.platform == "slack"
            )
        )
        existing_connection = result.scalars().first()
        
        # Prepare config object
        # CRITICAL: We map 'access_token' to 'bot_token' as required by the user
        config = {
            "bot_token": access_token, 
            "team_id": team.get("id"),
            "team_name": team.get("name"),
            "bot_user_id": data.get("bot_user_id"), # Important for mention detection
            "user_id": authed_user.get("id"),
            "scopes": data.get("scope", "").split(","),
            "is_enterprise_install": data.get("is_enterprise_install", False),
            "token_type": data.get("token_type")
        }
        
        # Add incoming webhook if available
        if "incoming_webhook" in data:
            config["incoming_webhook"] = data["incoming_webhook"]

        if existing_connection:
            # Update existing connection
            existing_connection.status = ConnectionStatus.ACTIVE
            existing_connection.config = config
            existing_connection.name = team.get("name") or "Slack Workspace"
            await db.commit()
            connection_id = existing_connection.id
        else:
            # Create new connection
            new_connection = Connection(
                user_id=user_id,
                platform="slack",
                name=team.get("name") or "Slack Workspace",
                status=ConnectionStatus.ACTIVE,
                config=config
            )
            db.add(new_connection)
            await db.commit()
            await db.refresh(new_connection)
            connection_id = new_connection.id
        
        return {
            "success": True,
            "message": "Slack connected successfully",
            "connection_id": connection_id,
            "team_name": team.get("name"),
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in Slack OAuth callback: {e}")
        raise HTTPException(status_code=500, detail=str(e))
