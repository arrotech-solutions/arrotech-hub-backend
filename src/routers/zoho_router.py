"""
Zoho OAuth Routes
Handles OAuth 2.0 authorization flow for Zoho integrations.
"""
import logging
import os
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from ..routers.auth_router import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/zoho", tags=["zoho-oauth"])

# Zoho OAuth configuration
ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")

# Redirect URI = the BACKEND callback endpoint
ZOHO_REDIRECT_URI = os.getenv(
    "ZOHO_REDIRECT_URI", 
    "http://localhost:8000/api/zoho/callback" if os.getenv("ENVIRONMENT") == "development" else "https://prod.api.arrotechsolutions.com/api/zoho/callback"
)

# Frontend URL = where the user ends up after the backend processes the callback
FRONTEND_URL = os.getenv("ZOHO_FRONTEND_URL", f"{os.getenv('FRONTEND_URL', 'https://hub.arrotechsolutions.com').rstrip('/')}/connections")

# OAuth scopes for Zoho CRM, Books, Desk, Mail
# Note: Desk service prefix is "Desk", NOT "ZohoDesk"
SCOPES = [
    "ZohoCRM.modules.ALL",
    "ZohoCRM.settings.ALL",
    "ZohoCRM.users.ALL",
    "ZohoBooks.contacts.ALL",
    "ZohoBooks.invoices.ALL",
    "ZohoBooks.expenses.ALL",
    "ZohoBooks.settings.ALL",
    "Desk.tickets.ALL",
    "Desk.articles.ALL",
    "Desk.search.READ",
    "Desk.settings.ALL",
    "ZohoMail.messages.ALL",
    "aaaserver.profile.read"
]

# Base auth URL (default .com, can be customized)
ZOHO_ACCOUNTS_URL = "https://accounts.zoho.com"

@router.get("/auth-url")
async def get_auth_url(
    user: User = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Generate Zoho OAuth authorization URL
    """
    try:
        if not ZOHO_CLIENT_ID:
            raise HTTPException(
                status_code=500,
                detail="Zoho OAuth is not configured. Please set ZOHO_CLIENT_ID."
            )

        from urllib.parse import urlencode

        params = {
            "client_id": ZOHO_CLIENT_ID,
            "response_type": "code",
            "scope": ",".join(SCOPES),
            "redirect_uri": ZOHO_REDIRECT_URI,
            "access_type": "offline",
            "prompt": "consent",
            "state": f"user_{user.id}",
        }

        auth_url = f"{ZOHO_ACCOUNTS_URL}/oauth/v2/auth?{urlencode(params)}"

        return {
            "auth_url": auth_url,
            "state": params["state"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating Zoho auth URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
async def oauth_callback(
    code: str,
    state: str = None,
    location: str = "us",
    db: AsyncSession = Depends(get_db)
):
    """
    Handle OAuth callback from Zoho.
    """
    try:
        if not ZOHO_CLIENT_ID or not ZOHO_CLIENT_SECRET:
            return RedirectResponse(
                url=f"{FRONTEND_URL}?error=Zoho+OAuth+is+not+configured",
                status_code=302
            )

        # Extract user ID from state
        if not state or not state.startswith("user_"):
            return RedirectResponse(
                url=f"{FRONTEND_URL}?error=Invalid+state+parameter",
                status_code=302
            )

        try:
            user_id = int(state.replace("user_", ""))
        except ValueError:
            return RedirectResponse(
                url=f"{FRONTEND_URL}?error=Invalid+state+format",
                status_code=302
            )

        # Exchange authorization code for tokens
        import requests

        token_url = f"{ZOHO_ACCOUNTS_URL}/oauth/v2/token"
        token_data = {
            "grant_type": "authorization_code",
            "client_id": ZOHO_CLIENT_ID,
            "client_secret": ZOHO_CLIENT_SECRET,
            "redirect_uri": ZOHO_REDIRECT_URI,
            "code": code,
        }

        token_response = requests.post(token_url, data=token_data)

        if token_response.status_code != 200:
            logger.error(f"Zoho token exchange failed: {token_response.text}")
            return RedirectResponse(
                url=f"{FRONTEND_URL}?error=Token+exchange+failed",
                status_code=302
            )

        data = token_response.json()

        if "error" in data:
            logger.error(f"Zoho token error: {data}")
            return RedirectResponse(
                url=f"{FRONTEND_URL}?error=Zoho+returned+error",
                status_code=302
            )

        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in")
        api_domain = data.get("api_domain", "https://www.zohoapis.com")

        if not access_token:
            return RedirectResponse(
                url=f"{FRONTEND_URL}?error=No+access+token+received",
                status_code=302
            )

        # Check if user already has a Zoho connection
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user_id,
                Connection.platform == "zoho"
            )
        )
        existing_connection = result.scalars().first()

        config = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
            "api_domain": api_domain,
            "scopes": SCOPES,
            "auth_method": "oauth2"
        }

        connection_name = "Zoho Workspace"

        if existing_connection:
            existing_connection.status = ConnectionStatus.ACTIVE
            
            # Preserve existing refresh token if Zoho didn't send a new one
            if not refresh_token and existing_connection.config and "refresh_token" in existing_connection.config:
                config["refresh_token"] = existing_connection.config["refresh_token"]

            existing_connection.config = config
            existing_connection.name = connection_name
            existing_connection.error_message = None
            await db.commit()
        else:
            new_connection = Connection(
                user_id=user_id,
                platform="zoho",
                name=connection_name,
                status=ConnectionStatus.ACTIVE,
                config=config
            )
            db.add(new_connection)
            await db.commit()

        logger.info(f"Zoho OAuth connection created for user {user_id}")

        # Redirect user to frontend with success
        return RedirectResponse(
            url=f"{FRONTEND_URL}?success=zoho_connected",
            status_code=302
        )

    except Exception as e:
        logger.error(f"Error in Zoho OAuth callback: {e}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}?error=zoho_connection_failed",
            status_code=302
        )
