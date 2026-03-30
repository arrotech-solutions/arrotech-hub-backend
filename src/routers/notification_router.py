"""
Notification Router

API endpoints for in-app notifications.
"""

from datetime import datetime
from typing import Any, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func, update, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from .auth_router import get_current_user
from ..models import User, Notification, Workflow

router = APIRouter(prefix="/notifications", tags=["notifications"])


# Response Models
class NotificationResponse(BaseModel):
    """Response for a single notification."""
    id: uuid.UUID
    notification_type: str
    title: str
    message: str
    is_read: bool
    action_url: Optional[str]
    workflow_id: Optional[uuid.UUID]
    workflow_name: Optional[str]
    actor_name: Optional[str]
    metadata: Optional[dict]
    created_at: str


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
            query = query.where(Notification.is_read == False)
        
        query = query.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
        
        result = await db.execute(query)
        notifications = result.scalars().all()
        
        data = []
        for n in notifications:
            data.append({
                "id": n.id,
                "notification_type": n.notification_type,
                "title": n.title,
                "message": n.message,
                "is_read": n.is_read,
                "action_url": n.action_url,
                "workflow_id": n.workflow_id,
                "workflow_name": n.workflow.name if n.workflow else None,
                "actor_name": n.actor.name if n.actor else None,
                "metadata": n.metadata,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            })
        
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
                Notification.is_read == False
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
                Notification.is_read == False
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


# Helper function to create notifications (to be used by other services)
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
):
    """Create a new notification for a user."""
    notification = Notification(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        message=message,
        workflow_id=workflow_id,
        actor_id=actor_id,
        action_url=action_url,
        metadata=metadata,
    )
    db.add(notification)
    await db.flush()  # Don't commit, let the caller commit
    return notification

