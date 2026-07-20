"""Resolve per-user WhatsApp Cloud API credentials from Connection records."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Connection, User


async def get_whatsapp_config(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    require_active: bool = True,
) -> Dict[str, Any]:
    """
    Load WhatsApp credentials for a user.

    Prefers the user's active Connection; falls back to platform env vars.
    """
    result = await db.execute(
        select(Connection).filter(
            Connection.user_id == user_id,
            Connection.platform == "whatsapp",
            Connection.status == "active",
        )
    )
    connection = result.scalars().first()
    conn_config = (connection.config or {}) if connection else {}

    phone_number_id = conn_config.get("phone_number_id") or settings.WHATSAPP_PHONE_NUMBER_ID
    access_token = conn_config.get("access_token") or settings.WHATSAPP_TOKEN
    business_account_id = (
        conn_config.get("business_account_id") or settings.WHATSAPP_BUSINESS_ACCOUNT_ID
    )
    base_url = conn_config.get("base_url") or settings.WHATSAPP_BASE_URL or "https://graph.facebook.com/v22.0"

    if require_active and (not phone_number_id or not access_token):
        raise HTTPException(
            status_code=400,
            detail="WhatsApp is not connected. Connect your WhatsApp Business account first.",
        )

    return {
        "phone_number_id": phone_number_id,
        "access_token": access_token,
        "business_account_id": business_account_id,
        "base_url": base_url.rstrip("/"),
        "connection_id": str(connection.id) if connection else None,
    }


async def get_whatsapp_config_for_user(
    db: AsyncSession,
    user: User,
    *,
    require_active: bool = True,
) -> Dict[str, Any]:
    return await get_whatsapp_config(db, user.id, require_active=require_active)
