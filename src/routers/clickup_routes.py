
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.clickup_service import ClickUpService
from ..config import settings
from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from ..routers.auth_router import get_current_user

router = APIRouter(prefix="/api/clickup", tags=["clickup"])
clickup_service = ClickUpService()

@router.get("/auth-url")
async def get_auth_url(user: User = Depends(get_current_user)):
    """Get the ClickUp OAuth URL."""
    try:
        state = f"user_{user.id}"
        url = await clickup_service.get_auth_url(state=state)
        return {"url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/callback")
async def clickup_callback(code: str, state: str = None, db: AsyncSession = Depends(get_db)):
    """Handle ClickUp OAuth callback."""
    try:
        print(f"DEBUG: ClickUp Callback - Code: {code}, State: {state}")
        
        # Validate state and extract user_id
        if not state or not state.startswith("user_"):
            print("DEBUG: Invalid state format")
            raise HTTPException(status_code=400, detail="Invalid state parameter")
        
        try:
            user_id = int(state.replace("user_", ""))
            print(f"DEBUG: Extracted user_id: {user_id}")
        except ValueError:
            print("DEBUG: User ID parsing failed")
            raise HTTPException(status_code=400, detail="Invalid state parameter format")

        # Exchange code for token
        print("DEBUG: Exchanging code for token...")
        token_data = await clickup_service.exchange_code_for_token(code)
        access_token = token_data.get("access_token")
        print(f"DEBUG: Access Token received: {access_token is not None}")
        
        if not access_token:
            raise HTTPException(status_code=400, detail="No access token received")
            
        # Get user info for connection name
        print("DEBUG: Getting user info...")
        user_data = await clickup_service.get_user(access_token)
        clickup_user = user_data.get("user", {})
        print(f"DEBUG: ClickUp User: {clickup_user}")
        
        # Get teams (workspaces) for config
        teams_data = await clickup_service.get_teams(access_token)
        teams = teams_data.get("teams", [])
        
        # Check for existing connection
        print("DEBUG: Checking existing connection...")
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user_id,
                Connection.platform == "clickup"
            )
        )
        existing_connection = result.scalars().first()
        print(f"DEBUG: Existing connection found: {existing_connection is not None}")
        
        config = {
            "access_token": access_token,
            "user_id": clickup_user.get("id"),
            "username": clickup_user.get("username"),
            "email": clickup_user.get("email"),
            "teams": teams
        }
        
        connection_name = f"ClickUp ({clickup_user.get('username', 'Workspace')})"

        if existing_connection:
            print("DEBUG: Updating existing connection...")
            existing_connection.status = ConnectionStatus.ACTIVE
            existing_connection.config = config
            existing_connection.name = connection_name
            await db.commit()
            print("DEBUG: Update committed.")
        else:
            print("DEBUG: Creating new connection...")
            new_connection = Connection(
                user_id=user_id,
                platform="clickup",
                name=connection_name,
                status=ConnectionStatus.ACTIVE,
                config=config
            )
            db.add(new_connection)
            await db.commit()
            print("DEBUG: New connection committed.")
        
        frontend_url = f"{settings.FRONTEND_URL}/connections?success=clickup_connected"
        return RedirectResponse(url=frontend_url)
        
    except Exception as e:
        error_url = f"{settings.FRONTEND_URL}/connections?error={str(e)}"
        return RedirectResponse(url=error_url)
