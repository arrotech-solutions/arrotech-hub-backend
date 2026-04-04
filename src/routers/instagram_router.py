from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, Response, Query
from fastapi.responses import RedirectResponse
import httpx
import logging
import urllib.parse
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from ..config import settings
from ..routers.auth_router import get_current_user

router = APIRouter(
    prefix="/api/instagram",
    tags=["instagram"]
)

logger = logging.getLogger(__name__)

# Constants
FACEBOOK_GRAPH_URL = "https://graph.facebook.com/v22.0"
# Scopes for Instagram Business
# Note: Instagram Business API works via Facebook Login
INSTAGRAM_SCOPES = "pages_show_list,pages_read_engagement,pages_manage_metadata,instagram_basic,instagram_manage_messages"

@router.get("/auth-url")
async def get_auth_url(user: User = Depends(get_current_user)):
    """Generate Instagram (via Facebook) OAuth URL."""
    # Check tier-based access BEFORE allowing OAuth flow
    from ..services.tier_gate import check_connection_access
    check_connection_access(user, "instagram")
    
    # Re-use Facebook App credentials as Instagram works via FB Graph API
    if not settings.FACEBOOK_APP_ID or not settings.FACEBOOK_APP_SECRET:
        raise HTTPException(
            status_code=500, 
            detail="Facebook App ID or Secret not configured (required for Instagram)"
        )

    redirect_uri = f"{settings.API_BASE_URL}/api/instagram/callback"
    
    # State includes user_id to link connection back to user
    state = str(user.id)
    
    params = {
        "client_id": settings.FACEBOOK_APP_ID,
        "redirect_uri": redirect_uri,
        "scope": INSTAGRAM_SCOPES,
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
    """Handle Instagram OAuth callback."""
    if error:
        logger.error(f"Instagram OAuth error: {error} - {error_reason}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/connections?error={error}&reason={error_reason}"
        )

    try:
        import uuid
        user_id = uuid.UUID(state)
        redirect_uri = f"{settings.API_BASE_URL}/api/instagram/callback"
        
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
                    Connection.platform == "instagram"
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
                    platform="instagram",
                    name="Instagram Business",
                    status=ConnectionStatus.ACTIVE,
                    config=config_data
                )
                db.add(connection)
            
            await db.commit()
            
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/connections?success=instagram_connected")

    except Exception as e:
        logger.error(f"Error in Instagram callback: {e}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/connections?error=internal_error"
        )

@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge")
):
    """
    Verify the webhook with Meta.
    Meta sends a GET request to this endpoint with hub.mode, hub.challenge, and hub.verify_token.
    """
    logger.info(f"[INSTAGRAM WEBHOOK] Verification request received")
    logger.info(f"[INSTAGRAM WEBHOOK] Mode: {hub_mode}, Token: {hub_verify_token}")
    
    # Check verification token
    verify_token = getattr(settings, "INSTAGRAM_WEBHOOK_VERIFY_TOKEN", None) or "Arrotech_Secr3t_Token_2026"
    
    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        logger.info("[INSTAGRAM WEBHOOK] Verification successful!")
        return Response(content=hub_challenge, media_type="text/plain")
    else:
        logger.warning(f"[INSTAGRAM WEBHOOK] Verification failed! Expected: {verify_token}, Got: {hub_verify_token}")
        raise HTTPException(status_code=403, detail="Verification token mismatch")

@router.post("/webhook")
async def webhook_event(request: Request, background_tasks: BackgroundTasks):
    """
    Receive webhook events from Meta (Instagram).
    """
    try:
        body = await request.body()
        data = json.loads(body)
        
        if data.get("object") == "instagram":
            for entry in data.get("entry", []):
                for messaging_event in entry.get("messaging", []):
                    # We only care about message receives, not deliveries/reads
                    if "message" in messaging_event:
                        sender_id = messaging_event["sender"]["id"]
                        recipient_id = messaging_event["recipient"]["id"]
                        message_text = messaging_event["message"].get("text", "")
                        
                        if message_text:
                            logger.info(f"[IG_WEBHOOK] Received message from {sender_id}: {message_text[:50]}")
                            # Delegate to Trigger Engine asynchronously
                            from ..services.instagram_workflow_trigger import InstagramWorkflowTrigger
                            background_tasks.add_task(
                                InstagramWorkflowTrigger.on_message_received,
                                sender_id=sender_id,
                                recipient_id=recipient_id,
                                message=message_text
                            )
                        
            return Response(content="EVENT_RECEIVED", status_code=200, media_type="text/plain")
        else:
            return Response(content="NOT_INSTAGRAM_EVENT", status_code=404, media_type="text/plain")
            
    except Exception as e:
        logger.error(f"Error handling Instagram webhook: {str(e)}", exc_info=True)
        return Response(content="SERVER_ERROR", status_code=500, media_type="text/plain")
