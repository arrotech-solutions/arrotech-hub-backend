"""
Airtable OAuth Routes.
Handles OAuth 2.0 authorization flow with PKCE for Airtable integration.
"""
import logging
import os
import time
import base64
import hashlib
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import RedirectResponse

from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from ..routers.auth_router import get_current_user
from ..services.airtable_service import AirtableService
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/airtable", tags=["airtable-oauth"])

# Airtable uses PKCE. We need to temporarily store the code verifier mapping to the state.
# For production at scale, this should be in Redis. For a single-instance backend, memory is fine.
_pkce_store: Dict[str, Dict[str, Any]] = {}

def get_code_verifier() -> str:
    """Generate a random strong code verifier."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode('utf-8').rstrip('=')

def get_code_challenge(verifier: str) -> str:
    """Hash the verifier to create the code challenge."""
    digest = hashlib.sha256(verifier.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest).decode('utf-8').rstrip('=')


@router.get("/auth-url")
async def get_auth_url(
    user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """
    Generate Airtable OAuth authorization URL.
    """
    try:
        # Check tier-based access BEFORE allowing OAuth flow
        from ..services.tier_gate import check_connection_access
        check_connection_access(user, "airtable")

        service = AirtableService()

        if not service.client_id or not service.client_secret:
             raise HTTPException(status_code=500, detail="Airtable credentials not configured")

        # Create a unique state parameter
        state = f"user_{user.id}_{int(time.time())}"
        
        # Generator PKCE parameters
        code_verifier = get_code_verifier()
        code_challenge = get_code_challenge(code_verifier)
        
        # Store the verifier for the callback
        _pkce_store[state] = {
            "verifier": code_verifier,
            "user_id": user.id,
            "created_at": time.time()
        }
        
        # Clean up old states to prevent memory leaks
        now = time.time()
        expired_states = [s for s, data in _pkce_store.items() if now - data["created_at"] > 3600]
        for s in expired_states:
            _pkce_store.pop(s, None)

        auth_url = service.get_auth_url(
            state=state,
            code_challenge=code_challenge
        )

        return {"auth_url": auth_url, "state": state}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating Airtable auth URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
async def oauth_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Handle OAuth callback for Airtable.
    """
    try:
        if state not in _pkce_store:
            logger.error("State not found in PKCE store")
            return RedirectResponse(
                f"{settings.FRONTEND_URL}/connections?error=Invalid or expired state parameter"
            )

        state_data = _pkce_store.pop(state)
        user_id = state_data["user_id"]
        code_verifier = state_data["verifier"]

        service = AirtableService()
        if not service.client_id or not service.client_secret:
            return RedirectResponse(
                f"{settings.FRONTEND_URL}/connections?error=Airtable OAuth is not configured"
            )

        # Exchange authorization code for tokens
        token_data = await service.exchange_code_for_token(code, code_verifier)

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        service.access_token = access_token
        service.refresh_token = refresh_token

        # Fetch Airtable User ID or base list to get a display name
        account_name = "Airtable Account"
        try:
            # Airtable doesn't explicitly have a "get user profile" endpoint via the standard API without specific scopes.
            # However, we can try to list bases to verify it works and use "Connected" as fallback.
            bases = await service.list_bases()
            bases_list = bases.get("bases", [])
            if bases_list:
                account_name = f"Airtable ({len(bases_list)} bases)"
        except Exception as e:
            logger.warning(f"Could not fetch Airtable bases during callback: {e}")

        config = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "account_name": account_name,
            "scopes": AirtableService.SCOPES,
        }

        # Upsert connection
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user_id,
                Connection.platform == "airtable",
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
                platform="airtable",
                name=account_name,
                status=ConnectionStatus.ACTIVE,
                config=config,
            )
            db.add(new_connection)
            await db.commit()

        return RedirectResponse(
            f"{settings.FRONTEND_URL}/connections?success=airtable_connected"
        )

    except Exception as e:
        logger.error(f"Error in Airtable OAuth callback: {e}")
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/connections?error={str(e)}"
        )
