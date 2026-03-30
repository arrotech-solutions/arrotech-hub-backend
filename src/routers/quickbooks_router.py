"""
QuickBooks OAuth Routes.
Handles OAuth 2.0 authorization flow for QuickBooks Online integration.
"""
import logging
import os
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import RedirectResponse

from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from ..routers.auth_router import get_current_user
from ..services.quickbooks_service import QuickBooksService
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quickbooks", tags=["quickbooks-oauth"])

# QuickBooks (Intuit) configuration
QUICKBOOKS_CLIENT_ID = os.getenv("QUICKBOOKS_CLIENT_ID")
QUICKBOOKS_CLIENT_SECRET = os.getenv("QUICKBOOKS_CLIENT_SECRET")
QUICKBOOKS_REDIRECT_URI = os.getenv(
    "QUICKBOOKS_REDIRECT_URI", "http://localhost:8000/api/quickbooks/callback"
)


@router.get("/auth-url")
async def get_auth_url(
    user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """
    Generate QuickBooks OAuth authorization URL.
    """
    try:
        # Check tier-based access BEFORE allowing OAuth flow
        from ..services.tier_gate import check_connection_access
        check_connection_access(user, "quickbooks")

        service = QuickBooksService()
        await service.initialize()

        if QUICKBOOKS_CLIENT_ID:
            service.client_id = QUICKBOOKS_CLIENT_ID

        state = f"user_{user.id}"
        auth_url = service.get_auth_url(
            redirect_uri=QUICKBOOKS_REDIRECT_URI, state=state
        )

        return {"auth_url": auth_url, "state": state}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating QuickBooks auth URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
async def oauth_callback(
    code: str,
    state: str,
    realmId: str,  # QuickBooks sends realmId as a query param
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Handle OAuth callback for QuickBooks.
    Intuit redirects here with ?code=...&state=...&realmId=...
    """
    try:
        if not QUICKBOOKS_CLIENT_ID or not QUICKBOOKS_CLIENT_SECRET:
            error_msg = "QuickBooks OAuth is not configured"
            return RedirectResponse(
                f"{settings.FRONTEND_URL}/connections?error={error_msg}"
            )

        if not state.startswith("user_"):
            return RedirectResponse(
                f"{settings.FRONTEND_URL}/connections?error=Invalid state parameter"
            )

        try:
            import uuid
            user_id = uuid.UUID(state.replace("user_", ""))
        except ValueError:
            return RedirectResponse(
                f"{settings.FRONTEND_URL}/connections?error=Invalid state format"
            )

        service = QuickBooksService()
        await service.initialize()

        service.client_id = QUICKBOOKS_CLIENT_ID
        service.client_secret = QUICKBOOKS_CLIENT_SECRET

        # Exchange authorization code for tokens
        token_data = await service.exchange_code_for_token(
            code, QUICKBOOKS_REDIRECT_URI
        )

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        # Fetch company info to get a friendly name
        service.access_token = access_token
        service.refresh_token = refresh_token
        service.realm_id = realmId
        service.environment = getattr(settings, "QUICKBOOKS_ENVIRONMENT", "sandbox")

        company_name = "QuickBooks Company"
        try:
            info = await service.get_company_info()
            if info.get("success"):
                company_name = info["company"].get("name", company_name)
        except Exception as e:
            logger.warning(f"Could not fetch company name: {e}")

        config = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "realm_id": realmId,
            "company_name": company_name,
            "environment": getattr(settings, "QUICKBOOKS_ENVIRONMENT", "sandbox"),
            "scopes": "com.intuit.quickbooks.accounting",
        }

        # Upsert connection
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == user_id,
                Connection.platform == "quickbooks",
            )
        )
        existing_connection = result.scalars().first()

        if existing_connection:
            existing_connection.status = ConnectionStatus.ACTIVE
            existing_connection.config = config
            existing_connection.name = f"QuickBooks ({company_name})"
            await db.commit()
        else:
            new_connection = Connection(
                user_id=user_id,
                platform="quickbooks",
                name=f"QuickBooks ({company_name})",
                status=ConnectionStatus.ACTIVE,
                config=config,
            )
            db.add(new_connection)
            await db.commit()

        return RedirectResponse(
            f"{settings.FRONTEND_URL}/connections?success=quickbooks_connected"
        )

    except Exception as e:
        logger.error(f"Error in QuickBooks OAuth callback: {e}")
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/connections?error={str(e)}"
        )
