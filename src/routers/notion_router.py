"""
Notion OAuth Routes
Handles OAuth 2.0 authorization flow for Notion integration.
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
from ..services.notion_service import NotionService
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notion", tags=["notion-oauth"])

# Notion OAuth configuration
NOTION_CLIENT_ID = os.getenv("NOTION_CLIENT_ID")
NOTION_CLIENT_SECRET = os.getenv("NOTION_CLIENT_SECRET")
# Should match Notion Integration settings
NOTION_REDIRECT_URI = os.getenv("NOTION_REDIRECT_URI", "http://localhost:8000/api/notion/callback")

@router.get("/auth-url")
async def get_auth_url(
    user: User = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Generate Notion OAuth authorization URL
    """
    try:
        # Check tier-based access BEFORE allowing OAuth flow
        from ..services.tier_gate import check_connection_access
        check_connection_access(user, "notion")
        
        service = NotionService()
        await service.initialize() 
        
        if NOTION_CLIENT_ID: service.client_id = NOTION_CLIENT_ID
        
        state = f"user_{user.id}"
        auth_url = service.get_auth_url(redirect_uri=NOTION_REDIRECT_URI, state=state)
        
        return {
            "auth_url": auth_url,
            "state": state
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating Notion auth URL: {e}")
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
        if not NOTION_CLIENT_ID or not NOTION_CLIENT_SECRET:
            error_msg = "Notion OAuth is not configured"
            return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error={error_msg}")
        
        if not state.startswith("user_"):
             return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error=Invalid state parameter")
        
        try:
            import uuid
            user_id = uuid.UUID(state.replace("user_", ""))
        except ValueError:
             return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error=Invalid state format")

        service = NotionService()
        await service.initialize()
        
        service.client_id = NOTION_CLIENT_ID
        service.client_secret = NOTION_CLIENT_SECRET
        
        token_data = await service.exchange_code_for_token(code, NOTION_REDIRECT_URI)
        
        # Notion returns: { "access_token": "...", "workspace_name": "...", "workspace_icon": "...", "bot_id": "...", "owner": { ... } }
        access_token = token_data.get("access_token")
        workspace_name = token_data.get("workspace_name", "Notion Workspace")
        workspace_icon = token_data.get("workspace_icon")
        
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user_id,
                Connection.platform == "notion"
            )
        )
        existing_connection = result.scalars().first()
        
        config = {
            "access_token": access_token,
            "workspace_name": workspace_name,
            "workspace_icon": workspace_icon,
            "bot_id": token_data.get("bot_id"),
            "owner": token_data.get("owner"),
            "duplicated_template_id": token_data.get("duplicated_template_id")
        }

        if existing_connection:
            existing_connection.status = ConnectionStatus.ACTIVE
            existing_connection.config = config
            existing_connection.name = f"Notion ({workspace_name})"
            await db.commit()
        else:
            new_connection = Connection(
                user_id=user_id,
                platform="notion",
                name=f"Notion ({workspace_name})",
                status=ConnectionStatus.ACTIVE,
                config=config
            )
            db.add(new_connection)
            await db.commit()
        
        return RedirectResponse(f"{settings.FRONTEND_URL}/connections?success=notion_connected")
    
    except Exception as e:
        logger.error(f"Error in Notion OAuth callback: {e}")
        return RedirectResponse(f"{settings.FRONTEND_URL}/connections?error={str(e)}")
