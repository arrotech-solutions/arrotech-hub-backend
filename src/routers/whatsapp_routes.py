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

@router.get("/callback")
async def oauth_callback(
    code: str, 
    state: str, 
    error: Optional[str] = None,
    error_reason: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Handle WhatsApp OAuth callback."""
    if error:
        logger.error(f"WhatsApp OAuth error: {error} - {error_reason}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/connections?error={error}&reason={error_reason}"
        )

    try:
        user_id = int(state)
        redirect_uri = f"{settings.API_BASE_URL}/api/whatsapp/callback"
        
        # 1. Exchange code for short-lived token
        async with httpx.AsyncClient() as client:
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
            
            # 2. Exchange for long-lived token (60 days)
            exchange_url = f"{FACEBOOK_GRAPH_URL}/oauth/access_token"
            exchange_params = {
                "grant_type": "fb_exchange_token",
                "client_id": settings.WHATSAPP_APP_ID,
                "client_secret": settings.WHATSAPP_APP_SECRET,
                "fb_exchange_token": short_lived_token
            }
            
            exchange_resp = await client.get(exchange_url, params=exchange_params)
            exchange_data = exchange_resp.json()
            
            if exchange_resp.status_code != 200:
                logger.warning(f"Failed to exchange for long-lived token: {exchange_data}")
                # Fallback to short-lived token if exchange fails
                access_token = short_lived_token
            else:
                access_token = exchange_data.get("access_token")

            # 3. Get WhatsApp Business Accounts (WABA)
            # We need to find the WABA ID and Phone Number ID that the user granted access to
            # This is a bit complex as the user might have multiple. We'll pick the first one or ask (simplified for now)
            
            me_resp = await client.get(
                f"{FACEBOOK_GRAPH_URL}/me", 
                params={"access_token": access_token}
            )
            # me_data = me_resp.json()
            
            # Fetch WABAs
            waba_resp = await client.get(
                f"{FACEBOOK_GRAPH_URL}/me/accounts",
                params={"access_token": access_token}
            )
            # For now, we iterate businesses to find client_whatsapp_business_accounts
            # A more direct way often used in onboarding is checking the `granular_scopes` if returned
            
            # NOTE: For standard WhatsApp Embedded Signup, getting the WABA and Phone ID usually requires 
            # parsing the `setup` object if passed, or querying the user's businesses.
            # We will query for businesses and then look for phone numbers.
            
            # Simplified approach: Query for shared WABA info
            # See Meta docs on "Get Shared WABA ID"
            
            # Attempt to find a phone number directly if possible, or defaulting to user input later.
            # Storing the token is the most critical part. We can fetch details later or have the user select.
            
            # Update or Create Connection
            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user_id,
                    Connection.platform == "whatsapp"
                )
            )
            connection = result.scalar_one_or_none()
            
            # Try to fetch WABA and Phone Number ID from Meta API
            phone_number_id = None
            business_account_id = None
            setup_needed = True
            
            try:
                # Get the user's shared WhatsApp Business Accounts
                debug_resp = await client.get(
                    f"{FACEBOOK_GRAPH_URL}/debug_token",
                    params={
                        "input_token": access_token,
                        "access_token": f"{settings.WHATSAPP_APP_ID}|{settings.WHATSAPP_APP_SECRET}"
                    }
                )
                debug_data = debug_resp.json()
                logger.info(f"WhatsApp debug token response: {debug_data}")
                
                # Check granular scopes for WABA IDs
                if debug_data.get("data", {}).get("granular_scopes"):
                    for scope in debug_data["data"]["granular_scopes"]:
                        if scope.get("scope") == "whatsapp_business_messaging":
                            target_ids = scope.get("target_ids", [])
                            if target_ids:
                                business_account_id = target_ids[0]  # First WABA
                                logger.info(f"Found WABA ID from scopes: {business_account_id}")
                                break
                
                # If we found a WABA, get its phone numbers
                if business_account_id:
                    phones_resp = await client.get(
                        f"{FACEBOOK_GRAPH_URL}/{business_account_id}/phone_numbers",
                        params={"access_token": access_token}
                    )
                    phones_data = phones_resp.json()
                    logger.info(f"WhatsApp phone numbers response: {phones_data}")
                    
                    if phones_data.get("data"):
                        # Take the first phone number
                        phone_number_id = phones_data["data"][0].get("id")
                        logger.info(f"Found Phone Number ID: {phone_number_id}")
                        setup_needed = False
                        
            except Exception as fetch_error:
                logger.warning(f"Could not auto-fetch WABA/Phone ID: {fetch_error}")
            
            # If still no phone_number_id, try from env as fallback
            if not phone_number_id and settings.WHATSAPP_PHONE_NUMBER_ID:
                phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
                business_account_id = settings.WHATSAPP_BUSINESS_ACCOUNT_ID
                setup_needed = False
                logger.info(f"Using phone_number_id from env: {phone_number_id}")
            
            config_data = {
                "access_token": access_token,
                "auth_type": "oauth",
                "phone_number_id": phone_number_id,
                "business_account_id": business_account_id,
                "setup_needed": setup_needed
            }

            if connection:
                connection.status = ConnectionStatus.ACTIVE
                connection.config = {**connection.config, **config_data}
            else:
                connection = Connection(
                    user_id=user_id,
                    platform="whatsapp",
                    name="WhatsApp Business",
                    status=ConnectionStatus.ACTIVE,
                    config=config_data
                )
                db.add(connection)
            
            await db.commit()
            
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/connections?success=whatsapp_connected")

    except Exception as e:
        logger.error(f"Error in WhatsApp callback: {e}")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/connections?error=internal_error"
        )
