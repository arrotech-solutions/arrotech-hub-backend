"""
Notification Router

API endpoints for in-app notifications.
"""

from datetime import datetime
from typing import Any, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from .auth_router import get_current_user
from ..models import User, Notification
from ..services.notification_service import NotificationService, serialize_notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


class ApiResponse(BaseModel):
    """Standard API response."""
    success: bool
    data: Optional[Any] = None
    message: Optional[str] = None
    count: Optional[int] = None


@router.get("", response_model=ApiResponse)
async def get_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get user's notifications."""
    try:
        query = (
            select(Notification)
            .options(selectinload(Notification.workflow))
            .options(selectinload(Notification.actor))
            .where(Notification.user_id == user.id)
        )

        if unread_only:
            query = query.where(Notification.is_read == False)  # noqa: E712

        query = query.order_by(Notification.created_at.desc()).limit(limit).offset(offset)

        result = await db.execute(query)
        notifications = result.scalars().all()

        data = []
        for n in notifications:
            item = serialize_notification(n)
            item["workflow_name"] = n.workflow.name if n.workflow else None
            item["actor_name"] = n.actor.name if n.actor else None
            # Back-compat alias for older clients
            item["metadata"] = n.extra_data or {}
            data.append(item)

        return ApiResponse(success=True, data=data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get notifications: {str(e)}"
        )


@router.get("/unread-count", response_model=ApiResponse)
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get count of unread notifications."""
    try:
        result = await db.execute(
            select(func.count(Notification.id))
            .where(
                Notification.user_id == user.id,
                Notification.is_read == False,  # noqa: E712
            )
        )
        count = result.scalar() or 0

        return ApiResponse(success=True, data={"unread_count": count}, count=count)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get unread count: {str(e)}"
        )


@router.put("/{notification_id}/read", response_model=ApiResponse)
async def mark_as_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark a notification as read."""
    try:
        result = await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user.id
            )
        )
        notification = result.scalar_one_or_none()

        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found"
            )

        notification.is_read = True
        notification.read_at = datetime.utcnow()

        await db.commit()

        return ApiResponse(success=True, message="Marked as read")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark as read: {str(e)}"
        )


@router.put("/read-all", response_model=ApiResponse)
async def mark_all_as_read(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark all notifications as read."""
    try:
        await db.execute(
            update(Notification)
            .where(
                Notification.user_id == user.id,
                Notification.is_read == False,  # noqa: E712
            )
            .values(is_read=True, read_at=datetime.utcnow())
        )

        await db.commit()

        return ApiResponse(success=True, message="All notifications marked as read")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark all as read: {str(e)}"
        )


@router.delete("/{notification_id}", response_model=ApiResponse)
async def delete_notification(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a notification."""
    try:
        result = await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user.id
            )
        )
        notification = result.scalar_one_or_none()

        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found"
            )

        await db.delete(notification)
        await db.commit()

        return ApiResponse(success=True, message="Notification deleted")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete notification: {str(e)}"
        )


async def create_notification(
    db: AsyncSession,
    user_id: uuid.UUID,
    notification_type: str,
    title: str,
    message: str,
    workflow_id: Optional[uuid.UUID] = None,
    actor_id: Optional[uuid.UUID] = None,
    action_url: Optional[str] = None,
    metadata: Optional[dict] = None,
    extra_data: Optional[dict] = None,
):
    """
    Back-compat helper — prefer NotificationService.notify directly.
    Maps legacy notification_type to event_key.
    """
    return await NotificationService.notify(
        db,
        user_id,
        notification_type,
        title,
        message,
        action_url=action_url,
        data=extra_data or metadata,
        actor_id=actor_id,
        workflow_id=workflow_id,
        commit=False,
        enqueue_delivery=True,
    )
