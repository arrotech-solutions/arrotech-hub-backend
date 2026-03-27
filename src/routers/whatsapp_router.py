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
from ..services import WhatsAppService
from pydantic import BaseModel

class WhatsAppOauthRequest(BaseModel):
    code: str

router = APIRouter(
    prefix="/api/whatsapp",
    tags=["whatsapp"]
)

logger = logging.getLogger(__name__)

# Constants
FACEBOOK_GRAPH_URL = "https://graph.facebook.com/v22.0"
WHATSAPP_SCOPES = "whatsapp_business_management,whatsapp_business_messaging"

from ..routers.auth_router import get_current_user

@router.get("/auth-url")
async def get_auth_url(user: User = Depends(get_current_user)):
    """Generate WhatsApp (Meta) OAuth URL."""
    # Check tier-based access BEFORE allowing OAuth flow
    from ..services.tier_gate import check_connection_access
    check_connection_access(user, "whatsapp_business")
    
    if not settings.WHATSAPP_APP_ID or not settings.WHATSAPP_APP_SECRET:
        raise HTTPException(
            status_code=500, 
            detail="WhatsApp App ID or Secret not configured"
        )

    redirect_uri = f"{settings.API_BASE_URL}/api/whatsapp/callback"
    
    # State includes user_id to link connection back to user
    state = str(user.id)
    
    params = {
        "client_id": settings.WHATSAPP_APP_ID,
        "redirect_uri": redirect_uri,
        "scope": WHATSAPP_SCOPES,
        "response_type": "code",
        "state": state
    }
    
    auth_url = f"https://www.facebook.com/v22.0/dialog/oauth?{urllib.parse.urlencode(params)}"
    return {"url": auth_url}

@router.post("/oauth/callback")
async def oauth_callback(
    payload: WhatsAppOauthRequest, 
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Exchange authorization code and set up WhatsApp Business API connection."""
    code = payload.code
    
    try:
        redirect_uri = f"{settings.API_BASE_URL}/api/whatsapp/callback" # Must match redirect_uri used to get code if using standard flow, or omit/pass required for JS SDK
        
        async with httpx.AsyncClient() as client:
            # 1. Exchange code for access token using Meta OAuth endpoint
            token_url = f"{FACEBOOK_GRAPH_URL}/oauth/access_token"
            params = {
                "client_id": settings.WHATSAPP_APP_ID,
                "client_secret": settings.WHATSAPP_APP_SECRET,
                "redirect_uri": redirect_uri,
                "code": code
            }
            
            response = await client.get(token_url, params=params)
            data = response.json()
            
            if response.status_code != 200:
                logger.error(f"Failed to exchange code: {data}")
                raise HTTPException(status_code=400, detail="Failed to exchange authorization code")
                
            short_lived_token = data.get("access_token")
            
            # Exchange for long-lived token
            exchange_url = f"{FACEBOOK_GRAPH_URL}/oauth/access_token"
            exchange_params = {
                "grant_type": "fb_exchange_token",
                "client_id": settings.WHATSAPP_APP_ID,
                "client_secret": settings.WHATSAPP_APP_SECRET,
                "fb_exchange_token": short_lived_token
            }
            
            exchange_resp = await client.get(exchange_url, params=exchange_params)
            exchange_data = exchange_resp.json()
            
            access_token = exchange_data.get("access_token", short_lived_token)
            
            # 2. Fetch WhatsApp Business Data
            
            # GET /me?fields=businesses
            me_resp = await client.get(
                f"{FACEBOOK_GRAPH_URL}/me", 
                params={"fields": "businesses", "access_token": access_token}
            )
            me_data = me_resp.json()
            
            businesses = me_data.get("businesses", {}).get("data", [])
            if not businesses:
                raise HTTPException(status_code=400, detail="No Meta Business Account found for this user.")
            
            business_id = businesses[0].get("id")
            
            # GET /{business_id}/owned_whatsapp_business_accounts
            waba_resp = await client.get(
                f"{FACEBOOK_GRAPH_URL}/{business_id}/owned_whatsapp_business_accounts",
                params={"access_token": access_token}
            )
            waba_data = waba_resp.json()
            
            wabas = waba_data.get("data", [])
            if not wabas:
                raise HTTPException(status_code=400, detail="No WhatsApp Business Account found.")
                
            waba_id = wabas[0].get("id")
            
            # GET /{waba_id}/phone_numbers
            phones_resp = await client.get(
                f"{FACEBOOK_GRAPH_URL}/{waba_id}/phone_numbers",
                params={"access_token": access_token}
            )
            phones_data = phones_resp.json()
            
            phones = phones_data.get("data", [])
            if not phones:
                raise HTTPException(status_code=400, detail="No Phone Numbers found in this WhatsApp Business Account.")
            
            phone = phones[0]
            phone_number_id = phone.get("id")
            display_phone_number = phone.get("display_phone_number")
            
            # 3. Subscribe to webhook events
            sub_resp = await client.post(
                f"{FACEBOOK_GRAPH_URL}/{waba_id}/subscribed_apps",
                params={"access_token": access_token}
            )
            if sub_resp.status_code != 200:
                logger.warning(f"Failed to subscribe to webhooks: {sub_resp.json()}")
            
            # 4. Finalize Connection
            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user.id,
                    Connection.platform == "whatsapp"
                )
            )
            connection = result.scalar_one_or_none()
            
            config_data = {
                "access_token": access_token,
                "auth_type": "embedded_signup",
                "business_id": business_id,
                "waba_id": waba_id,
                "phone_number_id": phone_number_id,
                "display_phone_number": display_phone_number,
                "setup_needed": False
            }

            if connection:
                connection.status = ConnectionStatus.ACTIVE
                connection.config = {**connection.config, **config_data}
            else:
                connection = Connection(
                    user_id=user.id,
                    platform="whatsapp",
                    name="WhatsApp Business API",
                    status=ConnectionStatus.ACTIVE,
                    config=config_data
                )
                db.add(connection)
            
            await db.commit()
            
            return {"success": True, "message": "WhatsApp connected successfully ready for automation."}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in WhatsApp callback: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during connection.")
