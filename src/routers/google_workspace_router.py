"""
Google Workspace OAuth Routes
Handles OAuth 2.0 authorization flow for Google Workspace integration.
"""
import logging
import os
from typing import Dict, Any
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from ..routers.auth_router import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/google-workspace", tags=["google-workspace"])

# Google OAuth configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_WORKSPACE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_WORKSPACE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_WORKSPACE_REDIRECT_URI", "http://localhost:3000/connections/callback")

# OAuth scopes for Google Workspace
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/analytics.readonly",
]


@router.get("/auth-url")
async def get_auth_url(
    user: User = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Generate Google OAuth authorization URL
    """
    try:
        # Check tier-based access BEFORE allowing OAuth flow
        from ..services.tier_gate import check_connection_access
        check_connection_access(user, "google_workspace")
        
        if not GOOGLE_CLIENT_ID:
            raise HTTPException(
                status_code=500,
                detail="Google Workspace OAuth is not configured. Please set GOOGLE_WORKSPACE_CLIENT_ID."
            )
        
        # Build OAuth URL
        from urllib.parse import urlencode
        
        params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": f"user_{user.id}",  # Include user ID in state for validation
        }
        
        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        
        return {
            "auth_url": auth_url,
            "state": params["state"]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating Google Workspace auth URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
async def oauth_callback(
    code: str,
    state: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Handle OAuth callback and exchange authorization code for tokens
    """
    try:
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            raise HTTPException(
                status_code=500,
                detail="Google Workspace OAuth is not configured"
            )
        
        # Extract user ID from state
        if not state.startswith("user_"):
            raise HTTPException(status_code=400, detail="Invalid state parameter")
        
        import uuid
        user_id = uuid.UUID(state.replace("user_", ""))
        
        # Exchange authorization code for tokens
        import requests
        
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }
        
        token_response = requests.post(token_url, data=token_data)
        
        if token_response.status_code != 200:
            logger.error(f"Token exchange failed: {token_response.text}")
            raise HTTPException(
                status_code=400,
                detail="Failed to exchange authorization code for tokens"
            )
        
        tokens = token_response.json()
        
        # Get user info to display email
        import google.auth.transport.requests
        from google.oauth2.credentials import Credentials
        
        creds = Credentials(token=tokens.get("access_token"))
        user_info_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        headers = {"Authorization": f"Bearer {tokens.get('access_token')}"}
        user_info_response = requests.get(user_info_url, headers=headers)
        user_info = user_info_response.json()
        
        # Check if user already has a Google Workspace connection
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user_id,
                Connection.platform == "google_workspace"
            )
        )
        existing_connection = result.scalars().first()
        
        if existing_connection:
            # Update existing connection
            existing_connection.status = ConnectionStatus.ACTIVE
            existing_connection.config = {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "refresh_token": tokens.get("refresh_token") or existing_connection.config.get("refresh_token"),
                "access_token": tokens.get("access_token"),
                "email": user_info.get("email"),
                "name": user_info.get("name"),
                "scopes": SCOPES,
            }
            await db.commit()
            connection_id = existing_connection.id
        else:
            # Create new connection
            new_connection = Connection(
                user_id=user_id,
                platform="google_workspace",
                name=user_info.get("name") or user_info.get("email") or "Google Workspace",
                status=ConnectionStatus.ACTIVE,
                config={
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "refresh_token": tokens.get("refresh_token"),
                    "access_token": tokens.get("access_token"),
                    "email": user_info.get("email"),
                    "name": user_info.get("name"),
                    "scopes": SCOPES,
                }
            )
            db.add(new_connection)
            await db.commit()
            await db.refresh(new_connection)
            connection_id = new_connection.id
        
        return {
            "success": True,
            "message": "Google Workspace connected successfully",
            "connection_id": connection_id,
            "email": user_info.get("email"),
            "name": user_info.get("name"),
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in Google Workspace OAuth callback: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/disconnect/{connection_id}")
async def disconnect_google_workspace(
    connection_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Disconnect Google Workspace by deleting the connection
    """
    try:
        result = await db.execute(
            select(Connection).filter(
                Connection.id == connection_id,
                Connection.user_id == user.id,
                Connection.platform == "google_workspace"
            )
        )
        connection = result.scalars().first()
        
        if not connection:
            raise HTTPException(status_code=404, detail="Connection not found")
        
        await db.delete(connection)
        await db.commit()
        
        return {
            "success": True,
            "message": "Google Workspace disconnected successfully"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disconnecting Google Workspace: {e}")
        raise HTTPException(status_code=500, detail=str(e))
