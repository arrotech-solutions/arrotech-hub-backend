"""
HubSpot OAuth Routes
Handles OAuth 2.0 authorization flow for HubSpot CRM integration.
"""
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from ..routers.auth_router import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hubspot", tags=["hubspot-oauth"])

# HubSpot OAuth configuration
HUBSPOT_CLIENT_ID = os.getenv("HUBSPOT_CLIENT_ID")
HUBSPOT_CLIENT_SECRET = os.getenv("HUBSPOT_CLIENT_SECRET")

# Redirect URI = the BACKEND callback endpoint (where HubSpot sends the auth code)
HUBSPOT_REDIRECT_URI = os.getenv("HUBSPOT_REDIRECT_URI", "https://mini-hub.fly.dev/api/hubspot/callback")

# Frontend URL = where the user ends up after the backend processes the callback
FRONTEND_URL = os.getenv("HUBSPOT_FRONTEND_URL", os.getenv("FRONTEND_URL", "https://hub.arrotechsolutions.com/connections"))

# OAuth scopes for HubSpot CRM
SCOPES = [
    "crm.objects.contacts.read",
    "crm.objects.contacts.write",
    "crm.objects.deals.read",
    "crm.objects.deals.write",
    "crm.objects.companies.read",
    "crm.objects.companies.write",
]


@router.get("/auth-url")
async def get_auth_url(
    user: User = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Generate HubSpot OAuth authorization URL
    """
    try:
        if not HUBSPOT_CLIENT_ID:
            raise HTTPException(
                status_code=500,
                detail="HubSpot OAuth is not configured. Please set HUBSPOT_CLIENT_ID."
            )

        from urllib.parse import urlencode

        params = {
            "client_id": HUBSPOT_CLIENT_ID,
            "scope": " ".join(SCOPES),
            "redirect_uri": HUBSPOT_REDIRECT_URI,
            "state": f"user_{user.id}",
        }

        auth_url = f"https://app.hubspot.com/oauth/authorize?{urlencode(params)}"

        return {
            "auth_url": auth_url,
            "state": params["state"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating HubSpot auth URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
async def oauth_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Handle OAuth callback from HubSpot.
    HubSpot sends the auth code here, we exchange it for tokens,
    create the connection, and redirect the user to the frontend.
    """
    try:
        if not HUBSPOT_CLIENT_ID or not HUBSPOT_CLIENT_SECRET:
            return RedirectResponse(
                url=f"{FRONTEND_URL}?error=HubSpot+OAuth+is+not+configured",
                status_code=302
            )

        # Extract user ID from state
        if not state.startswith("user_"):
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

        token_url = "https://api.hubapi.com/oauth/v1/token"
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": HUBSPOT_CLIENT_ID,
            "client_secret": HUBSPOT_CLIENT_SECRET,
            "redirect_uri": HUBSPOT_REDIRECT_URI,
        }

        token_response = requests.post(
            token_url,
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        if token_response.status_code != 200:
            logger.error(f"HubSpot token exchange failed: {token_response.text}")
            return RedirectResponse(
                url=f"{FRONTEND_URL}?error=Token+exchange+failed",
                status_code=302
            )

        data = token_response.json()

        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        expires_in = data.get("expires_in")

        if not access_token:
            return RedirectResponse(
                url=f"{FRONTEND_URL}?error=No+access+token+received",
                status_code=302
            )

        # Get account info to verify the connection
        account_info = {}
        try:
            info_response = requests.get(
                "https://api.hubapi.com/account-info/v3/details",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            if info_response.status_code == 200:
                account_info = info_response.json()
        except Exception as e:
            logger.warning(f"Could not fetch HubSpot account info: {e}")

        portal_id = account_info.get("portalId", "")

        # Check if user already has a HubSpot connection
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user_id,
                Connection.platform == "hubspot"
            )
        )
        existing_connection = result.scalars().first()

        # Prepare config — store api_key for backward compatibility with HubSpotService
        config = {
            "api_key": access_token,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
            "portal_id": str(portal_id),
            "scopes": SCOPES,
            "auth_method": "oauth2",
        }

        connection_name = f"HubSpot ({portal_id})" if portal_id else "HubSpot CRM"

        if existing_connection:
            existing_connection.status = ConnectionStatus.ACTIVE
            existing_connection.config = config
            existing_connection.name = connection_name
            existing_connection.error_message = None
            await db.commit()
        else:
            new_connection = Connection(
                user_id=user_id,
                platform="hubspot",
                name=connection_name,
                status=ConnectionStatus.ACTIVE,
                config=config
            )
            db.add(new_connection)
            await db.commit()

        logger.info(f"HubSpot OAuth connection created for user {user_id}, portal {portal_id}")

        # Redirect user to frontend with success
        return RedirectResponse(
            url=f"{FRONTEND_URL}?success=hubspot_connected",
            status_code=302
        )

    except Exception as e:
        logger.error(f"Error in HubSpot OAuth callback: {e}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}?error=hubspot_connection_failed",
            status_code=302
        )
