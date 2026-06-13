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
    waba_id: Optional[str] = None
    phone_number_id: Optional[str] = None

class WhatsAppRegisterRequest(BaseModel):
    phone_number_id: str
    pin: str

router = APIRouter(
    prefix="/api/whatsapp",
    tags=["whatsapp"]
)

logger = logging.getLogger(__name__)

import json

# Constants
FACEBOOK_GRAPH_URL = "https://graph.facebook.com/v22.0"
WHATSAPP_SCOPES = "whatsapp_business_management,whatsapp_business_messaging,business_management"

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
        "state": state,
        "display": "page"
    }
    
    auth_url = f"https://www.facebook.com/v22.0/dialog/oauth?{urllib.parse.urlencode(params)}"
    return {"url": auth_url}

@router.get("/callback")
async def oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_reason: Optional[str] = None,
    error_description: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Exchange authorization code and set up WhatsApp Business API connection via redirect (fallback path)."""
    
    print(f"[WHATSAPP CALLBACK] Hit! code={'YES' if code else 'NO'}, state={state}, error={error}, error_reason={error_reason}")
    logger.info(f"[WHATSAPP CALLBACK] code={'present' if code else 'missing'}, state={state}, error={error}")
    
    # Handle Facebook error redirects (denied permissions, cancelled, etc.)
    if error:
        detail = error_description or error_reason or error
        print(f"[WHATSAPP CALLBACK] Facebook returned error: {detail}")
        encoded_error = urllib.parse.quote(f"Facebook authorization failed: {detail}")
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/connections?error=whatsapp_auth_failed&detail={encoded_error}")
    
    if not code or not state:
        print(f"[WHATSAPP CALLBACK] Missing code or state!")
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/connections?error=whatsapp_setup_failed&detail=Missing+authorization+code+or+state")
    
    # State string contains the user id passed during the get_auth_url phase
    try:
        import uuid
        user_id = uuid.UUID(state)
    except ValueError:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/connections?error=invalid_state")
    
    try:
        redirect_uri = f"{settings.API_BASE_URL.rstrip('/')}/api/whatsapp/callback"
        
        access_token, waba_id, phone_number_id, display_phone_number, business_id = await _exchange_code_and_discover(
            code=code,
            redirect_uri=redirect_uri
        )
        
        # Subscribe to webhook events
        async with httpx.AsyncClient(timeout=30.0) as client:
            sub_resp = await client.post(
                f"{FACEBOOK_GRAPH_URL}/{waba_id}/subscribed_apps",
                params={"access_token": access_token}
            )
            if sub_resp.status_code != 200:
                logger.warning(f"Failed to subscribe to webhooks: {sub_resp.json()}")
        
        # Finalize Connection
        await _upsert_whatsapp_connection(
            db=db,
            user_id=user_id,
            access_token=access_token,
            business_id=business_id,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            display_phone_number=display_phone_number,
            auth_type="oauth_redirect"
        )
        
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/connections?success=whatsapp_connected")

    except HTTPException as he:
        detail_msg = he.detail if isinstance(he.detail, str) else str(he.detail)
        logger.error(f"WhatsApp callback HTTPException: {detail_msg}")
        encoded_error = urllib.parse.quote(detail_msg)
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/connections?error=whatsapp_setup_failed&detail={encoded_error}")
    except Exception as e:
        logger.error(f"Error in WhatsApp callback: {e}", exc_info=True)
        encoded_error = urllib.parse.quote(str(e))
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/connections?error=internal_error&detail={encoded_error}")

@router.post("/embedded-callback")
async def embedded_oauth_callback(
    request_data: WhatsAppOauthRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Exchange authorization code from embedded signup for long-lived access token.
    
    The Embedded Signup popup may return waba_id and phone_number_id directly
    when using a config_id. If provided, we skip the discovery step and use them.
    """
    code = request_data.code
    user_id = user.id
    
    logger.info(f"Embedded callback: code={'present' if code else 'missing'}, waba_id={request_data.waba_id}, phone_number_id={request_data.phone_number_id}")
    
    try:
        access_token, waba_id, phone_number_id, display_phone_number, business_id, phone_status = await _exchange_code_and_discover(
            code=code,
            redirect_uri="",  # Empty string — will be omitted from the token exchange request
            hint_waba_id=request_data.waba_id,
            hint_phone_number_id=request_data.phone_number_id
        )
        
        # Subscribe to webhook events
        async with httpx.AsyncClient(timeout=30.0) as client:
            sub_resp = await client.post(
                f"{FACEBOOK_GRAPH_URL}/{waba_id}/subscribed_apps",
                params={"access_token": access_token}
            )
            if sub_resp.status_code != 200:
                logger.warning(f"Failed to subscribe to webhooks: {sub_resp.json()}")
        
        # Finalize Connection
        await _upsert_whatsapp_connection(
            db=db,
            user_id=user_id,
            access_token=access_token,
            business_id=business_id,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            display_phone_number=display_phone_number,
            auth_type="embedded_signup"
        )
        
        return {"success": True, "message": "WhatsApp Business connected successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in WhatsApp embedded callback: {e}")
        raise HTTPException(status_code=500, detail="Internal server error linking WhatsApp")


# ── Shared helpers ────────────────────────────────────────────────────────────

async def _exchange_code_and_discover(
    code: str,
    redirect_uri: str,
    hint_waba_id: Optional[str] = None,
    hint_phone_number_id: Optional[str] = None
) -> tuple:
    """Exchange an auth code for a long-lived token and discover WABA/phone data.
    
    If hint_waba_id and hint_phone_number_id are provided (from Embedded Signup
    with config_id), they are used directly instead of blindly taking [0].
    
    Returns: (access_token, waba_id, phone_number_id, display_phone_number, business_id, phone_status)
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Exchange code for short-lived access token
        token_url = f"{FACEBOOK_GRAPH_URL}/oauth/access_token"
        params = {
            "client_id": settings.WHATSAPP_APP_ID,
            "client_secret": settings.WHATSAPP_APP_SECRET,
            "code": code
        }
        # Only include redirect_uri when it's a real URL (i.e. redirect OAuth).
        # The JS SDK embedded-signup flow issues codes without a redirect_uri,
        # so sending an empty string causes Meta to reject the request.
        if redirect_uri:
            params["redirect_uri"] = redirect_uri
        
        logger.info(f"Exchanging code with params (excluding secrets): client_id={settings.WHATSAPP_APP_ID}, redirect_uri={'<set>' if redirect_uri else '<omitted>'}")
        response = await client.get(token_url, params=params)
        data = response.json()
        
        if response.status_code != 200:
            logger.error(f"Failed to exchange code: status={response.status_code}, response={data}")
            error_msg = data.get('error', {}).get('message', '') if isinstance(data.get('error'), dict) else str(data)
            raise HTTPException(status_code=400, detail=f"Failed to exchange authorization code: {error_msg}")
        
        short_lived_token = data.get("access_token")
        
        # 2. Exchange for long-lived token (lasts ~60 days)
        exchange_params = {
            "grant_type": "fb_exchange_token",
            "client_id": settings.WHATSAPP_APP_ID,
            "client_secret": settings.WHATSAPP_APP_SECRET,
            "fb_exchange_token": short_lived_token
        }
        
        exchange_resp = await client.get(f"{FACEBOOK_GRAPH_URL}/oauth/access_token", params=exchange_params)
        exchange_data = exchange_resp.json()
        
        access_token = exchange_data.get("access_token", short_lived_token)
        token_expires_in = exchange_data.get("expires_in")  # seconds until expiry
        
        # 3. Discover WhatsApp Business data
        # If we already have hints from Embedded Signup, use them directly
        if hint_waba_id and hint_phone_number_id:
            waba_id = hint_waba_id
            phone_number_id = hint_phone_number_id
            business_id = ""  # We can leave this empty or fetch it later if needed
            
            # Fetch the display phone number for the hinted phone_number_id
            phone_resp = await client.get(
                f"{FACEBOOK_GRAPH_URL}/{phone_number_id}",
                params={
                    "access_token": access_token,
                    "fields": "id,display_phone_number,quality_rating,name_status,status"
                }
            )
            phone_data = phone_resp.json()
            display_phone_number = phone_data.get("display_phone_number", "Unknown")
            phone_status = phone_data.get("status", "PENDING")
            
        else:
            # Fallback 1: Use debug_token to discover WABA ID from granular scopes
            debug_token_url = f"{FACEBOOK_GRAPH_URL}/debug_token"
            app_access_token = f"{settings.WHATSAPP_APP_ID}|{settings.WHATSAPP_APP_SECRET}"
            debug_resp = await client.get(
                debug_token_url,
                params={
                    "input_token": access_token,
                    "access_token": app_access_token
                }
            )
            debug_data = debug_resp.json()
            
            waba_id = None
            granular_scopes = debug_data.get("data", {}).get("granular_scopes", [])
            for scope in granular_scopes:
                if scope.get("scope") == "whatsapp_business_management":
                    target_ids = scope.get("target_ids", [])
                    if target_ids:
                        waba_id = target_ids[0]
                        break
            
            business_id = ""
            
            if waba_id:
                # We found the WABA ID via debug_token! Now fetch its phone numbers
                phones_resp = await client.get(
                    f"{FACEBOOK_GRAPH_URL}/{waba_id}/phone_numbers",
                    params={
                        "access_token": access_token,
                        "fields": "id,display_phone_number,quality_rating,name_status,status"
                    }
                )
                phones_data = phones_resp.json()
                phones = phones_data.get("data", [])
                if not phones:
                    raise HTTPException(
                        status_code=400,
                        detail="No phone numbers found in your WhatsApp Business Account. Please add one in Meta Business Suite."
                    )
                phone_number_id = phones[0].get("id")
                display_phone_number = phones[0].get("display_phone_number")
                
            else:
                # Fallback 2: Fetch the user's Meta Business Account to discover WABAs
                me_resp = await client.get(
                    f"{FACEBOOK_GRAPH_URL}/me",
                    params={"fields": "businesses", "access_token": access_token}
                )
                me_data = me_resp.json()
                
                businesses = me_data.get("businesses", {}).get("data", [])
                if not businesses:
                    raise HTTPException(
                        status_code=400,
                        detail="No Meta Business Account found. Please ensure your Facebook account is linked to a Business account."
                    )
                
                business_id = businesses[0].get("id")
                
                # discover WABAs and phone numbers across ALL user businesses
                wabas = []
                
                for b in businesses:
                    b_id = b.get("id")
                    # Try owned WABAs
                    waba_resp = await client.get(
                        f"{FACEBOOK_GRAPH_URL}/{b_id}/owned_whatsapp_business_accounts",
                        params={"access_token": access_token}
                    )
                    wabas = waba_resp.json().get("data", [])
                    if wabas:
                        break
                        
                    # Try client WABAs
                    client_waba_resp = await client.get(
                        f"{FACEBOOK_GRAPH_URL}/{b_id}/client_whatsapp_business_accounts",
                        params={"access_token": access_token}
                    )
                    wabas = client_waba_resp.json().get("data", [])
                    if wabas:
                        break
                
                if not wabas:
                    # Log the final attempt's responses to help debug
                    logger.error(f"Failed to find WABAs in any business. Last owned resp: {waba_resp.json() if 'waba_resp' in locals() else 'None'}, Last client resp: {client_waba_resp.json() if 'client_waba_resp' in locals() else 'None'}")
                    raise HTTPException(
                        status_code=400,
                        detail="No WhatsApp Business Account found. Please create one in your Meta Business Suite first."
                    )
                
                waba_id = wabas[0].get("id")
                
                phones_resp = await client.get(
                    f"{FACEBOOK_GRAPH_URL}/{waba_id}/phone_numbers",
                    params={
                        "access_token": access_token,
                        "fields": "id,display_phone_number,quality_rating,name_status,status"
                    }
                )
                phones_data = phones_resp.json()
                
                phones = phones_data.get("data", [])
                if not phones:
                    raise HTTPException(
                        status_code=400,
                        detail="No phone numbers found in your WhatsApp Business Account. Please add one in Meta Business Suite."
                    )
                
                phone = phones[0]
                phone_number_id = phone.get("id")
                display_phone_number = phone.get("display_phone_number")
                phone_status = phone.get("status", "PENDING")
        
        logger.info(f"WhatsApp OAuth complete: waba={waba_id}, phone={phone_number_id}, display={display_phone_number}, status={phone_status}")
        
        return access_token, waba_id, phone_number_id, display_phone_number, business_id, phone_status


async def _upsert_whatsapp_connection(
    db: AsyncSession,
    user_id,
    access_token: str,
    business_id: str,
    waba_id: str,
    phone_number_id: str,
    display_phone_number: str,
    phone_status: str = "PENDING",
    auth_type: str = "embedded_signup"
):
    """Create or update the WhatsApp connection for a user."""
    from datetime import datetime, timedelta
    
    result = await db.execute(
        select(Connection).filter(
            Connection.user_id == user_id,
            Connection.platform == "whatsapp"
        )
    )
    connection = result.scalar_one_or_none()
    
    config_data = {
        "access_token": access_token,
        "auth_type": auth_type,
        "business_id": business_id,
        "waba_id": waba_id,
        "phone_number_id": phone_number_id,
        "display_phone_number": display_phone_number,
        "phone_status": phone_status,
        "base_url": FACEBOOK_GRAPH_URL,
        "token_refreshed_at": datetime.utcnow().isoformat(),
        "token_expires_at": (datetime.utcnow() + timedelta(days=60)).isoformat(),
        "setup_needed": False
    }
    
    if connection:
        connection.status = ConnectionStatus.ACTIVE
        connection.config = {**connection.config, **config_data}
        connection.error_message = None
    else:
        connection = Connection(
            user_id=user_id,
            platform="whatsapp",
            name=f"WhatsApp ({display_phone_number})",
            status=ConnectionStatus.ACTIVE,
            config=config_data
        )
        db.add(connection)
    
    await db.commit()

@router.get("/phone-numbers")
async def get_whatsapp_phone_numbers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Fetch phone numbers registered to the user's WABA ID."""
    result = await db.execute(
        select(Connection).filter(
            Connection.user_id == user.id,
            Connection.platform == "whatsapp",
            Connection.status == ConnectionStatus.ACTIVE
        )
    )
    connection = result.scalar_one_or_none()
    
    if not connection or not connection.config.get("waba_id") or not connection.config.get("access_token"):
        return {"success": False, "data": []}
        
    waba_id = connection.config["waba_id"]
    access_token = connection.config["access_token"]
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{FACEBOOK_GRAPH_URL}/{waba_id}/phone_numbers",
                params={
                    "access_token": access_token,
                    "fields": "id,display_phone_number,quality_rating,name_status,status"
                }
            )
            data = resp.json()
            if resp.status_code == 200:
                return {"success": True, "data": data.get("data", [])}
            else:
                logger.error(f"Failed to fetch phone numbers: {data}")
                return {"success": False, "data": []}
    except Exception as e:
        logger.error(f"Exception fetching phone numbers: {e}")
        return {"success": False, "data": []}

@router.post("/phone-numbers/sync")
async def sync_whatsapp_phone_numbers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Force re-fetch of phone numbers for the WA connection."""
    result = await get_whatsapp_phone_numbers(user, db)
    return result


class ManualConnectRequest(BaseModel):
    access_token: str
    waba_id: str
    phone_number_id: str
    display_phone_number: str = "Unknown"
    business_id: str = ""


@router.post("/manual-connect")
async def manual_connect(
    request_data: ManualConnectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Manually connect a WhatsApp Business Account (admin/testing endpoint).
    
    Use this when OAuth flow is unavailable. Provide the access token,
    WABA ID, and phone number ID from the Meta App Dashboard.
    """
    try:
        # Verify the token works by calling the Graph API
        async with httpx.AsyncClient(timeout=30.0) as client:
            verify_resp = await client.get(
                f"{FACEBOOK_GRAPH_URL}/{request_data.phone_number_id}",
                params={
                    "access_token": request_data.access_token,
                    "fields": "id,display_phone_number"
                }
            )
            if verify_resp.status_code == 200:
                verify_data = verify_resp.json()
                display_phone = verify_data.get("display_phone_number", request_data.display_phone_number)
            else:
                logger.warning(f"Token verification returned {verify_resp.status_code}: {verify_resp.text}")
                display_phone = request_data.display_phone_number
            
            # Subscribe to webhooks
            sub_resp = await client.post(
                f"{FACEBOOK_GRAPH_URL}/{request_data.waba_id}/subscribed_apps",
                params={"access_token": request_data.access_token}
            )
            if sub_resp.status_code != 200:
                logger.warning(f"Webhook subscription warning: {sub_resp.json()}")
        
        await _upsert_whatsapp_connection(
            db=db,
            user_id=user.id,
            access_token=request_data.access_token,
            business_id=request_data.business_id,
            waba_id=request_data.waba_id,
            phone_number_id=request_data.phone_number_id,
            display_phone_number=display_phone,
            auth_type="manual"
        )
        
        return {"success": True, "message": "WhatsApp Business connected successfully"}
    except Exception as e:
        logger.error(f"Manual connect error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/register-phone")
async def register_whatsapp_phone(
    request: WhatsAppRegisterRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Register the phone number with Meta Cloud API using the provided PIN."""
    result = await db.execute(
        select(Connection).filter(
            Connection.user_id == user.id,
            Connection.platform == "whatsapp"
        )
    )
    connection = result.scalar_one_or_none()
    
    if not connection or not connection.config.get("access_token"):
        raise HTTPException(status_code=400, detail="WhatsApp connection not found or incomplete.")
        
    access_token = connection.config.get("access_token")
    
    # Send registration request to Meta
    async with httpx.AsyncClient(timeout=30.0) as client:
        register_url = f"{FACEBOOK_GRAPH_URL}/{request.phone_number_id}/register"
        response = await client.post(
            register_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            },
            json={
                "messaging_product": "whatsapp",
                "pin": request.pin
            }
        )
        
        data = response.json()
        
        if response.status_code != 200:
            logger.error(f"Failed to register WhatsApp phone: {data}")
            error_msg = data.get('error', {}).get('message', '') if isinstance(data.get('error'), dict) else str(data)
            raise HTTPException(status_code=400, detail=f"Failed to register phone number: {error_msg}")
            
        # Update connection config to mark phone as connected
        config_data = connection.config.copy()
        config_data["phone_status"] = "CONNECTED"
        connection.config = config_data
        await db.commit()
        
        return {"success": True, "message": "Phone number successfully registered"}
