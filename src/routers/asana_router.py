from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
import logging
from ..services.asana_service import AsanaService
from ..config import settings
from ..routers.auth_router import get_current_user # Import get_current_user
from ..models import User # Import User model

router = APIRouter(prefix="/auth/asana", tags=["auth"])
logger = logging.getLogger(__name__)

asana_service = AsanaService()

@router.get("/url")
async def get_auth_url(current_user: User = Depends(get_current_user)):
    """Get Asana OAuth authorization URL."""
    try:
        # Pass user ID to service to embed in state
        auth_url = asana_service.get_auth_url(str(current_user.id))
        return {"url": auth_url}
    except Exception as e:
        logger.error(f"Error generating Asana auth URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/callback")
async def callback(code: str, state: str = None):
    """Handle Asana OAuth callback."""
    try:
        # Exchange code for token
        token_data = await asana_service.get_token_from_code(code)
        
        if not token_data or "access_token" not in token_data:
            raise HTTPException(status_code=400, detail="Failed to retrieve access token")
            
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        
        # Asana user info
        asana_user_data = token_data.get("data", {})
        asana_user_id = str(asana_user_data.get("id", "unknown"))
        asana_user_name = asana_user_data.get("name", "Asana User")
        workspace_id = None
        
        # Extract system user_id from state
        system_user_id = None
        if state and "::" in state:
            try:
                # Expected format: "asana_connection::{user_id}"
                parts = state.split("::")
                if len(parts) == 2:
                    import uuid
                    system_user_id = uuid.UUID(parts[1])
            except ValueError:
                logger.warning(f"Invalid user_id in state: {state}")
        
        # Database connection
        from ..database import get_session_maker
        from sqlalchemy import text
        import json

        session_maker = get_session_maker()
        async with session_maker() as session:
            
            if not system_user_id:
                # Fallback to default user if state doesn't have it (legacy/direct call)
                logger.warning("No user_id in state, falling back to first user")
                result = await session.execute(text("SELECT id, name FROM users LIMIT 1"))
                system_user = result.first()
                if not system_user:
                    logger.error("No users found in database to link Asana connection")
                    raise HTTPException(status_code=500, detail="No system user found")
                system_user_id = system_user.id

            # Check for existing connection for this system user and platform
            result = await session.execute(
                text("SELECT id, config FROM connections WHERE platform = 'asana' AND user_id = :user_id"),
                {"user_id": system_user_id}
            )
            existing = result.first()
            
            config = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "asana_user_id": asana_user_id,
                "asana_user_name": asana_user_name,
                "workspace_id": workspace_id 
            }
            
            if existing:
                # Update
                await session.execute(
                    text("UPDATE connections SET config = :config, status = 'active', updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
                    {"config": json.dumps(config), "id": existing.id}
                )
            else:
                # Insert
                await session.execute(
                    text("""
                    INSERT INTO connections (user_id, platform, name, config, status)
                    VALUES (:user_id, 'asana', :name, :config, 'active')
                    """),
                    {
                        "user_id": system_user_id,
                        "name": f"Asana ({asana_user_name})",
                        "config": json.dumps(config) 
                    }
                )
            await session.commit()
        
        return JSONResponse(content={"status": "success", "message": "Asana connected successfully"})
        
    except Exception as e:
        logger.error(f"Error in Asana callback: {e}")
        raise HTTPException(status_code=500, detail=str(e))
