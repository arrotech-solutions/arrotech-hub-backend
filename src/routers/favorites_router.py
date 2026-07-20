"""
Favorites router for Mini-Hub.
Allows users to bookmark/favorite workflows.
"""

import logging
from typing import Any, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import User, Workflow, WorkflowFavorite
from ..routers.auth_router import get_current_user


class ApiResponse(BaseModel):
    """Standard API response format."""
    success: bool
    data: Optional[Any] = None
    message: Optional[str] = None
    error: Optional[str] = None

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=ApiResponse)
async def get_my_favorites(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get list of user's favorite workflows."""
    result = await db.execute(
        select(WorkflowFavorite)
        .options(selectinload(WorkflowFavorite.workflow))
        .where(WorkflowFavorite.user_id == user.id)
        .order_by(WorkflowFavorite.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    favorites = result.scalars().all()
    
    data = [
        {
            "id": fav.id,
            "workflow_id": fav.workflow_id,
            "workflow": {
                "id": fav.workflow.id,
                "name": fav.workflow.name,
                "description": fav.workflow.description,
                "category": fav.workflow.category,
                "tags": fav.workflow.tags,
                "visibility": fav.workflow.visibility,
                "downloads_count": fav.workflow.downloads_count,
                "rating_count": fav.workflow.rating_count,
                "author_name": fav.workflow.author_name,
            } if fav.workflow else None,
            "created_at": fav.created_at.isoformat() if fav.created_at else None,
        }
        for fav in favorites
    ]
    
    # Get total count
    result = await db.execute(
        select(func.count(WorkflowFavorite.id))
        .where(WorkflowFavorite.user_id == user.id)
    )
    total = result.scalar() or 0
    
    return ApiResponse(success=True, data={"favorites": data, "total": total})


@router.post("/{workflow_id}", response_model=ApiResponse)
async def add_to_favorites(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Add a workflow to favorites."""
    # Check if workflow exists
    result = await db.execute(
        select(Workflow).where(Workflow.id == workflow_id)
    )
    workflow = result.scalar_one_or_none()
    
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found"
        )
    
    # Check if already favorited
    result = await db.execute(
        select(WorkflowFavorite).where(
            WorkflowFavorite.user_id == user.id,
            WorkflowFavorite.workflow_id == workflow_id
        )
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        return ApiResponse(success=True, message="Already in favorites")
    
    # Add to favorites
    favorite = WorkflowFavorite(
        user_id=user.id,
        workflow_id=workflow_id
    )
    db.add(favorite)
    await db.commit()
    
    return ApiResponse(success=True, message="Added to favorites")


@router.delete("/{workflow_id}", response_model=ApiResponse)
async def remove_from_favorites(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Remove a workflow from favorites."""
    result = await db.execute(
        select(WorkflowFavorite).where(
            WorkflowFavorite.user_id == user.id,
            WorkflowFavorite.workflow_id == workflow_id
        )
    )
    favorite = result.scalar_one_or_none()
    
    if favorite:
        await db.delete(favorite)
        await db.commit()
    
    return ApiResponse(success=True, message="Removed from favorites")


@router.get("/{workflow_id}/check", response_model=ApiResponse)
async def check_favorite(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Check if a workflow is in favorites."""
    result = await db.execute(
        select(WorkflowFavorite).where(
            WorkflowFavorite.user_id == user.id,
            WorkflowFavorite.workflow_id == workflow_id
        )
    )
    favorite = result.scalar_one_or_none()
    
    return ApiResponse(
        success=True,
        data={"is_favorite": favorite is not None}
    )

