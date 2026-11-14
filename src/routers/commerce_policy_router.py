"""Merchant commerce policy HTTP API."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User
from ..services.commerce_policy import (
    CommercePolicyValidationError,
    get_policy,
    upsert_policy,
)
from .auth_router import get_current_user

router = APIRouter(prefix="/api/commerce", tags=["commerce"])


class CommercePolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sell_modes: Optional[list[str]] = None
    delivery_methods: Optional[list[str]] = None
    reservations_enabled: Optional[bool] = None
    business_hours: Optional[Dict[str, Any]] = None
    away_message: Optional[str] = None
    return_window_days: Optional[int] = None
    return_reason_codes: Optional[list[str]] = None
    auto_approve_enabled: Optional[bool] = None
    auto_approve_max_amount_kes: Optional[float] = None
    cancel_until_status: Optional[str] = None
    human_handoff_ttl_hours: Optional[int] = None
    commerce_rails_enabled: Optional[bool] = None


@router.get("/policy")
async def read_commerce_policy(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the caller's effective commerce policy."""
    policy = await get_policy(db, user.id)
    return {"success": True, "data": policy}


@router.put("/policy")
async def update_commerce_policy(
    body: CommercePolicyBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update commerce policy fields for the caller."""
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        policy = await get_policy(db, user.id)
        return {"success": True, "data": policy}
    try:
        policy = await upsert_policy(db, user.id, patch)
    except CommercePolicyValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return {"success": True, "data": policy}