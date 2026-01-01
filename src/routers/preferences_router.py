"""
User preferences router for Mini-Hub.
Manages user notification and app preferences.
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, UserPreferences
from ..routers.auth_router import get_current_user


class ApiResponse(BaseModel):
    """Standard API response format."""
    success: bool
    data: Optional[Any] = None
    message: Optional[str] = None
    error: Optional[str] = None

logger = logging.getLogger(__name__)

router = APIRouter()


class UpdatePreferencesRequest(BaseModel):
    # Email notification preferences
    email_on_download: Optional[bool] = None
    email_on_sale: Optional[bool] = None
    email_on_review: Optional[bool] = None
    email_on_follower: Optional[bool] = None
    email_weekly_summary: Optional[bool] = None
    
    # In-app notification preferences
    notify_on_download: Optional[bool] = None
    notify_on_sale: Optional[bool] = None
    notify_on_review: Optional[bool] = None
    notify_on_follower: Optional[bool] = None
    
    # App preferences
    theme: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None
    default_visibility: Optional[str] = None


@router.get("/", response_model=ApiResponse)
async def get_preferences(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get user's preferences."""
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user.id)
    )
    preferences = result.scalar_one_or_none()
    
    if not preferences:
        # Create default preferences
        preferences = UserPreferences(user_id=user.id)
        db.add(preferences)
        await db.commit()
        await db.refresh(preferences)
    
    return ApiResponse(
        success=True,
        data={
            "email_on_download": preferences.email_on_download,
            "email_on_sale": preferences.email_on_sale,
            "email_on_review": preferences.email_on_review,
            "email_on_follower": preferences.email_on_follower,
            "email_weekly_summary": preferences.email_weekly_summary,
            "notify_on_download": preferences.notify_on_download,
            "notify_on_sale": preferences.notify_on_sale,
            "notify_on_review": preferences.notify_on_review,
            "notify_on_follower": preferences.notify_on_follower,
            "theme": preferences.theme,
            "language": preferences.language,
            "timezone": preferences.timezone,
            "default_visibility": preferences.default_visibility,
        }
    )


@router.put("/", response_model=ApiResponse)
async def update_preferences(
    request: UpdatePreferencesRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update user's preferences."""
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user.id)
    )
    preferences = result.scalar_one_or_none()
    
    if not preferences:
        preferences = UserPreferences(user_id=user.id)
        db.add(preferences)
    
    # Update only provided fields
    update_data = request.dict(exclude_unset=True, exclude_none=True)
    for field, value in update_data.items():
        setattr(preferences, field, value)
    
    await db.commit()
    await db.refresh(preferences)
    
    return ApiResponse(
        success=True,
        message="Preferences updated successfully",
        data={
            "email_on_download": preferences.email_on_download,
            "email_on_sale": preferences.email_on_sale,
            "email_on_review": preferences.email_on_review,
            "email_on_follower": preferences.email_on_follower,
            "email_weekly_summary": preferences.email_weekly_summary,
            "notify_on_download": preferences.notify_on_download,
            "notify_on_sale": preferences.notify_on_sale,
            "notify_on_review": preferences.notify_on_review,
            "notify_on_follower": preferences.notify_on_follower,
            "theme": preferences.theme,
            "language": preferences.language,
            "timezone": preferences.timezone,
            "default_visibility": preferences.default_visibility,
        }
    )


@router.put("/notifications/email", response_model=ApiResponse)
async def update_email_notifications(
    email_on_download: Optional[bool] = None,
    email_on_sale: Optional[bool] = None,
    email_on_review: Optional[bool] = None,
    email_on_follower: Optional[bool] = None,
    email_weekly_summary: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update email notification preferences."""
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user.id)
    )
    preferences = result.scalar_one_or_none()
    
    if not preferences:
        preferences = UserPreferences(user_id=user.id)
        db.add(preferences)
    
    if email_on_download is not None:
        preferences.email_on_download = email_on_download
    if email_on_sale is not None:
        preferences.email_on_sale = email_on_sale
    if email_on_review is not None:
        preferences.email_on_review = email_on_review
    if email_on_follower is not None:
        preferences.email_on_follower = email_on_follower
    if email_weekly_summary is not None:
        preferences.email_weekly_summary = email_weekly_summary
    
    await db.commit()
    
    return ApiResponse(success=True, message="Email preferences updated")


@router.put("/notifications/in-app", response_model=ApiResponse)
async def update_inapp_notifications(
    notify_on_download: Optional[bool] = None,
    notify_on_sale: Optional[bool] = None,
    notify_on_review: Optional[bool] = None,
    notify_on_follower: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update in-app notification preferences."""
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user.id)
    )
    preferences = result.scalar_one_or_none()
    
    if not preferences:
        preferences = UserPreferences(user_id=user.id)
        db.add(preferences)
    
    if notify_on_download is not None:
        preferences.notify_on_download = notify_on_download
    if notify_on_sale is not None:
        preferences.notify_on_sale = notify_on_sale
    if notify_on_review is not None:
        preferences.notify_on_review = notify_on_review
    if notify_on_follower is not None:
        preferences.notify_on_follower = notify_on_follower
    
    await db.commit()
    
    return ApiResponse(success=True, message="In-app notification preferences updated")


@router.put("/theme", response_model=ApiResponse)
async def update_theme(
    theme: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update theme preference."""
    if theme not in ["light", "dark", "system"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid theme. Must be 'light', 'dark', or 'system'"
        )
    
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user.id)
    )
    preferences = result.scalar_one_or_none()
    
    if not preferences:
        preferences = UserPreferences(user_id=user.id)
        db.add(preferences)
    
    preferences.theme = theme
    await db.commit()
    
    return ApiResponse(success=True, message=f"Theme set to {theme}")

