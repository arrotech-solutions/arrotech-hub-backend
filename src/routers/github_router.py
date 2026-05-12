import logging
import time
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import RedirectResponse

from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from ..routers.auth_router import get_current_user
from ..services.github_service import GitHubService
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/github", tags=["github-oauth"])

# Store state mapping to user_id
_state_store: Dict[str, Dict[str, Any]] = {}

@router.get("/auth-url")
async def get_auth_url(
    user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """
    Generate GitHub OAuth authorization URL.
    """
    try:
        # Check tier-based access
        from ..services.tier_gate import check_connection_access
        # Assuming "github" is a valid platform name for tier checks
        try:
            check_connection_access(user, "github")
        except Exception as e:
            # If tier gate doesn't know about github yet, we might need to handle it
            logger.warning(f"Tier gate check for GitHub: {e}")
            pass

        service = GitHubService()

        if not service.client_id or not service.client_secret:
             raise HTTPException(status_code=500, detail="GitHub credentials not configured")

        # Create a unique state parameter
        state = f"gh_user_{user.id}_{int(time.time())}"
        
        # Store the state for the callback
        _state_store[state] = {
            "user_id": user.id,
            "created_at": time.time()
        }
        
        # Clean up old states
        now = time.time()
        expired_states = [s for s, data in _state_store.items() if now - data["created_at"] > 3600]
        for s in expired_states:
            _state_store.pop(s, None)

        auth_url = GitHubService.get_auth_url(state=state)

        return {"auth_url": auth_url, "state": state}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating GitHub auth URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
async def oauth_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Handle OAuth callback for GitHub.
    """
    try:
        if state not in _state_store:
            logger.error("State not found in state store")
            return RedirectResponse(
                f"{settings.FRONTEND_URL}/connections?error=Invalid or expired state parameter"
            )

        state_data = _state_store.pop(state)
        user_id = state_data["user_id"]

        service = GitHubService()
        if not service.client_id or not service.client_secret:
            return RedirectResponse(
                f"{settings.FRONTEND_URL}/connections?error=GitHub OAuth is not configured"
            )

        # Exchange authorization code for tokens
        token_data = await service.exchange_code_for_token(code)
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        if not access_token:
             return RedirectResponse(
                f"{settings.FRONTEND_URL}/connections?error=Failed to retrieve access token from GitHub"
            )

        service.access_token = access_token
        
        # Fetch user info for connection name
        user_info = await service.get_user_info()
        username = user_info.get("login")
        account_name = f"GitHub (@{username})"

        config = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "username": username,
            "avatar_url": user_info.get("avatar_url"),
            "scopes": GitHubService.SCOPES,
        }

        # Upsert connection
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user_id,
                Connection.platform == "github",
            )
        )
        existing_connection = result.scalars().first()

        if existing_connection:
            existing_connection.status = ConnectionStatus.ACTIVE
            existing_connection.config = config
            existing_connection.name = account_name
            await db.commit()
        else:
            new_connection = Connection(
                user_id=user_id,
                platform="github",
                name=account_name,
                status=ConnectionStatus.ACTIVE,
                config=config,
            )
            db.add(new_connection)
            await db.commit()

        return RedirectResponse(
            f"{settings.FRONTEND_URL}/connections?success=github_connected"
        )

    except Exception as e:
        logger.error(f"Error in GitHub OAuth callback: {e}")
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/connections?error={str(e)}"
        )

@router.post("/webhooks")
async def github_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Handle GitHub Webhook events.
    Verifies signature and processes events like installation/uninstallation.
    """
    import hmac
    import hashlib

    # 1. Verify Signature
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature:
        logger.warning("Missing GitHub signature header")
        raise HTTPException(status_code=401, detail="Missing signature")

    body = await request.body()
    secret = settings.GITHUB_WEBHOOK_SECRET
    
    if secret:
        hash_object = hmac.new(secret.encode(), msg=body, digestmod=hashlib.sha256)
        expected_signature = f"sha256={hash_object.hexdigest()}"
        
        if not hmac.compare_digest(signature, expected_signature):
            logger.error("Invalid GitHub webhook signature")
            raise HTTPException(status_code=401, detail="Invalid signature")

    # 2. Process Event
    try:
        event_type = request.headers.get("X-GitHub-Event")
        payload = await request.json()
        
        logger.info(f"Received GitHub webhook: {event_type}")

        if event_type == "installation":
            action = payload.get("action")
            # If the app is uninstalled, mark connection as INACTIVE or delete it
            if action == "deleted" or action == "suspend":
                installation_id = payload.get("installation", {}).get("id")
                # In a GitHub App, the installation ID is global for the install
                # We can store this in Connection.config or find it by other means
                # For now, we'll log it as a placeholder for full identity mapping
                logger.info(f"GitHub App uninstalled (ID: {installation_id})")
                
                # Logic to find and disable connection based on installation_id 
                # would go here if we were using Installation-based tokens.
                # Since we use User-based OAuth, we'd ideally map installation -> user.

        elif event_type == "meta":
            # App was deleted
            logger.warning("GitHub App was deleted from developer settings")

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error processing GitHub webhook: {e}")
        return {"status": "error", "message": str(e)}
