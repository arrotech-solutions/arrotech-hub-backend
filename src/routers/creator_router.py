"""
Creator Profile Router

API endpoints for creator profiles in the marketplace.
"""

from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from .auth_router import get_current_user
from ..models import (
    User, Workflow, WorkflowVisibility, CreatorProfile,
    WorkflowDownload, WorkflowReview
)

router = APIRouter(prefix="/creators", tags=["creators"])


# Request/Response Models
class CreatorProfileCreate(BaseModel):
    """Request to create/update creator profile."""
    display_name: str = Field(..., min_length=2, max_length=50)
    bio: Optional[str] = Field(None, max_length=500)
    avatar_url: Optional[str] = None
    website: Optional[str] = None
    github_url: Optional[str] = None
    twitter_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    is_public: bool = True
    accept_donations: bool = False


class CreatorProfileResponse(BaseModel):
    """Response for creator profile."""
    id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    bio: Optional[str]
    avatar_url: Optional[str]
    website: Optional[str]
    github_url: Optional[str]
    twitter_url: Optional[str]
    linkedin_url: Optional[str]
    is_verified: bool
    badges: Optional[List[str]]
    total_workflows: int
    total_downloads: int
    total_reviews: int
    average_rating: float
    is_public: bool
    accept_donations: bool
    created_at: str


class CreatorWorkflowResponse(BaseModel):
    """Response for a creator's workflow."""
    id: uuid.UUID
    name: str
    description: Optional[str]
    category: Optional[str]
    tags: Optional[List[str]]
    downloads_count: int
    rating: Optional[float]
    rating_count: int
    visibility: str
    created_at: str


class ApiResponse(BaseModel):
    """Standard API response."""
    success: bool
    data: Optional[Any] = None
    message: Optional[str] = None


@router.get("/me", response_model=ApiResponse)
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get the current user's creator profile."""
    result = await db.execute(
        select(CreatorProfile).where(CreatorProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    
    if not profile:
        return ApiResponse(success=True, data=None, message="No creator profile found")
    
    return ApiResponse(
        success=True,
        data={
            "id": profile.id,
            "user_id": profile.user_id,
            "display_name": profile.display_name,
            "bio": profile.bio,
            "avatar_url": profile.avatar_url,
            "website": profile.website,
            "github_url": profile.github_url,
            "twitter_url": profile.twitter_url,
            "linkedin_url": profile.linkedin_url,
            "is_verified": profile.is_verified,
            "badges": profile.badges,
            "total_workflows": profile.total_workflows,
            "total_downloads": profile.total_downloads,
            "total_reviews": profile.total_reviews,
            "average_rating": float(profile.average_rating) if profile.average_rating else 0,
            "total_earnings": float(profile.total_earnings) if profile.total_earnings else 0,
            "is_public": profile.is_public,
            "accept_donations": profile.accept_donations,
            "created_at": profile.created_at.isoformat() if profile.created_at else None,
        }
    )


@router.post("/me", response_model=ApiResponse)
async def create_or_update_profile(
    data: CreatorProfileCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create or update the current user's creator profile."""
    result = await db.execute(
        select(CreatorProfile).where(CreatorProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    
    if profile:
        # Update existing profile
        profile.display_name = data.display_name
        profile.bio = data.bio
        profile.avatar_url = data.avatar_url
        profile.website = data.website
        profile.github_url = data.github_url
        profile.twitter_url = data.twitter_url
        profile.linkedin_url = data.linkedin_url
        profile.is_public = data.is_public
        profile.accept_donations = data.accept_donations
    else:
        # Create new profile
        profile = CreatorProfile(
            user_id=user.id,
            display_name=data.display_name,
            bio=data.bio,
            avatar_url=data.avatar_url,
            website=data.website,
            github_url=data.github_url,
            twitter_url=data.twitter_url,
            linkedin_url=data.linkedin_url,
            is_public=data.is_public,
            accept_donations=data.accept_donations,
        )
        db.add(profile)
    
    # Update stats
    await update_creator_stats(profile, user.id, db)
    
    await db.commit()
    await db.refresh(profile)
    
    return ApiResponse(
        success=True,
        data={
            "id": profile.id,
            "display_name": profile.display_name,
        },
        message="Profile updated successfully"
    )


@router.get("/{creator_id}", response_model=ApiResponse)
async def get_creator_profile(
    creator_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a creator's public profile."""
    result = await db.execute(
        select(CreatorProfile).where(
            CreatorProfile.id == creator_id,
            CreatorProfile.is_public == True
        )
    )
    profile = result.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator profile not found"
        )
    
    return ApiResponse(
        success=True,
        data={
            "id": profile.id,
            "display_name": profile.display_name,
            "bio": profile.bio,
            "avatar_url": profile.avatar_url,
            "website": profile.website,
            "github_url": profile.github_url,
            "twitter_url": profile.twitter_url,
            "linkedin_url": profile.linkedin_url,
            "is_verified": profile.is_verified,
            "badges": profile.badges,
            "total_workflows": profile.total_workflows,
            "total_downloads": profile.total_downloads,
            "total_reviews": profile.total_reviews,
            "average_rating": float(profile.average_rating) if profile.average_rating else 0,
            "accept_donations": profile.accept_donations,
            "created_at": profile.created_at.isoformat() if profile.created_at else None,
        }
    )


@router.get("/{creator_id}/workflows", response_model=ApiResponse)
async def get_creator_workflows(
    creator_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get a creator's public workflows."""
    # First get the profile to get user_id
    result = await db.execute(
        select(CreatorProfile).where(
            CreatorProfile.id == creator_id,
            CreatorProfile.is_public == True
        )
    )
    profile = result.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator profile not found"
        )
    
    # Get public workflows
    result = await db.execute(
        select(Workflow)
        .where(
            Workflow.user_id == profile.user_id,
            Workflow.visibility.in_([
                WorkflowVisibility.PUBLIC,
                WorkflowVisibility.MARKETPLACE
            ])
        )
        .order_by(Workflow.downloads_count.desc())
        .limit(limit)
        .offset(offset)
    )
    workflows = result.scalars().all()
    
    workflow_data = []
    for wf in workflows:
        rating = round(wf.rating_sum / wf.rating_count, 1) if wf.rating_count > 0 else None
        workflow_data.append({
            "id": wf.id,
            "name": wf.name,
            "description": wf.description,
            "category": wf.category,
            "tags": wf.tags,
            "downloads_count": wf.downloads_count,
            "rating": rating,
            "rating_count": wf.rating_count,
            "visibility": wf.visibility,
            "share_code": wf.share_code,
            "created_at": wf.created_at.isoformat() if wf.created_at else None,
        })
    
    return ApiResponse(success=True, data=workflow_data)


@router.get("/top", response_model=ApiResponse)
async def get_top_creators(
    limit: int = Query(10, ge=1, le=50),
    sort_by: str = Query("downloads", pattern="^(downloads|rating|workflows)$"),
    db: AsyncSession = Depends(get_db),
):
    """Get top creators by various metrics."""
    query = select(CreatorProfile).where(CreatorProfile.is_public == True)
    
    if sort_by == "downloads":
        query = query.order_by(CreatorProfile.total_downloads.desc())
    elif sort_by == "rating":
        query = query.order_by(CreatorProfile.average_rating.desc())
    elif sort_by == "workflows":
        query = query.order_by(CreatorProfile.total_workflows.desc())
    
    result = await db.execute(query.limit(limit))
    profiles = result.scalars().all()
    
    creators_data = []
    for profile in profiles:
        creators_data.append({
            "id": profile.id,
            "display_name": profile.display_name,
            "avatar_url": profile.avatar_url,
            "is_verified": profile.is_verified,
            "badges": profile.badges,
            "total_workflows": profile.total_workflows,
            "total_downloads": profile.total_downloads,
            "average_rating": float(profile.average_rating) if profile.average_rating else 0,
        })
    
    return ApiResponse(success=True, data=creators_data)


@router.post("/me/refresh-stats", response_model=ApiResponse)
async def refresh_my_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Refresh the current user's creator statistics."""
    result = await db.execute(
        select(CreatorProfile).where(CreatorProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No creator profile found"
        )
    
    await update_creator_stats(profile, user.id, db)
    await db.commit()
    await db.refresh(profile)
    
    return ApiResponse(
        success=True,
        data={
            "total_workflows": profile.total_workflows,
            "total_downloads": profile.total_downloads,
            "total_reviews": profile.total_reviews,
            "average_rating": float(profile.average_rating) if profile.average_rating else 0,
        },
        message="Stats refreshed successfully"
    )


async def update_creator_stats(profile: CreatorProfile, user_id: uuid.UUID, db: AsyncSession):
    """Update cached statistics for a creator profile."""
    # Count public workflows
    result = await db.execute(
        select(func.count(Workflow.id)).where(
            Workflow.user_id == user_id,
            Workflow.visibility.in_([
                WorkflowVisibility.PUBLIC,
                WorkflowVisibility.MARKETPLACE
            ])
        )
    )
    profile.total_workflows = result.scalar() or 0
    
    # Sum downloads
    result = await db.execute(
        select(func.sum(Workflow.downloads_count)).where(
            Workflow.user_id == user_id
        )
    )
    profile.total_downloads = result.scalar() or 0
    
    # Count reviews and average rating
    result = await db.execute(
        select(
            func.sum(Workflow.rating_count),
            func.sum(Workflow.rating_sum)
        ).where(Workflow.user_id == user_id)
    )
    row = result.one()
    total_reviews = row[0] or 0
    total_rating_sum = row[1] or 0
    
    profile.total_reviews = total_reviews
    if total_reviews > 0:
        profile.average_rating = round(total_rating_sum / total_reviews, 2)
    else:
        profile.average_rating = 0


# ================== Follower Endpoints ==================

@router.post("/{creator_id}/follow", response_model=ApiResponse)
async def follow_creator(
    creator_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Follow a creator."""
    from ..models import CreatorFollower
    
    # Get the creator profile to find user_id
    result = await db.execute(
        select(CreatorProfile).where(CreatorProfile.id == creator_id)
    )
    profile = result.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator not found"
        )
    
    if profile.user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot follow yourself"
        )
    
    # Check if already following
    result = await db.execute(
        select(CreatorFollower).where(
            CreatorFollower.follower_id == user.id,
            CreatorFollower.following_id == profile.user_id
        )
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        return ApiResponse(success=True, message="Already following this creator")
    
    # Create follow relationship
    follow = CreatorFollower(
        follower_id=user.id,
        following_id=profile.user_id
    )
    db.add(follow)
    
    # Create notification for the creator
    from ..models import Notification
    notification = Notification(
        user_id=profile.user_id,
        notification_type="new_follower",
        title="New Follower!",
        message=f"{user.name} is now following you",
        actor_id=user.id,
        action_url="/creator-profile",
    )
    db.add(notification)
    
    await db.commit()
    
    return ApiResponse(success=True, message="Now following this creator")


@router.delete("/{creator_id}/follow", response_model=ApiResponse)
async def unfollow_creator(
    creator_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Unfollow a creator."""
    from ..models import CreatorFollower
    
    # Get the creator profile to find user_id
    result = await db.execute(
        select(CreatorProfile).where(CreatorProfile.id == creator_id)
    )
    profile = result.scalar_one_or_none()
    
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Creator not found"
        )
    
    # Find and delete the follow relationship
    result = await db.execute(
        select(CreatorFollower).where(
            CreatorFollower.follower_id == user.id,
            CreatorFollower.following_id == profile.user_id
        )
    )
    follow = result.scalar_one_or_none()
    
    if follow:
        await db.delete(follow)
        await db.commit()
    
    return ApiResponse(success=True, message="Unfollowed this creator")


@router.get("/{creator_id}/is-following", response_model=ApiResponse)
async def check_following(
    creator_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Check if current user is following a creator."""
    from ..models import CreatorFollower
    
    result = await db.execute(
        select(CreatorProfile).where(CreatorProfile.id == creator_id)
    )
    profile = result.scalar_one_or_none()
    
    if not profile:
        return ApiResponse(success=True, data={"is_following": False})
    
    result = await db.execute(
        select(CreatorFollower).where(
            CreatorFollower.follower_id == user.id,
            CreatorFollower.following_id == profile.user_id
        )
    )
    follow = result.scalar_one_or_none()
    
    return ApiResponse(success=True, data={"is_following": follow is not None})


@router.get("/me/followers", response_model=ApiResponse)
async def get_my_followers(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get list of users following the current user."""
    from ..models import CreatorFollower
    from sqlalchemy.orm import selectinload
    
    result = await db.execute(
        select(CreatorFollower)
        .options(selectinload(CreatorFollower.follower))
        .where(CreatorFollower.following_id == user.id)
        .order_by(CreatorFollower.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    followers = result.scalars().all()
    
    data = [
        {
            "id": f.id,
            "user_id": f.follower_id,
            "user_name": f.follower.name if f.follower else None,
            "followed_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in followers
    ]
    
    # Get total count
    result = await db.execute(
        select(func.count(CreatorFollower.id))
        .where(CreatorFollower.following_id == user.id)
    )
    total = result.scalar() or 0
    
    return ApiResponse(success=True, data={"followers": data, "total": total})


@router.get("/me/following", response_model=ApiResponse)
async def get_my_following(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get list of creators the current user is following."""
    from ..models import CreatorFollower
    from sqlalchemy.orm import selectinload
    
    result = await db.execute(
        select(CreatorFollower)
        .options(selectinload(CreatorFollower.following))
        .where(CreatorFollower.follower_id == user.id)
        .order_by(CreatorFollower.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    following = result.scalars().all()
    
    # Get creator profiles for these users
    following_user_ids = [f.following_id for f in following]
    
    if following_user_ids:
        result = await db.execute(
            select(CreatorProfile).where(
                CreatorProfile.user_id.in_(following_user_ids)
            )
        )
        profiles = {p.user_id: p for p in result.scalars().all()}
    else:
        profiles = {}
    
    data = []
    for f in following:
        profile = profiles.get(f.following_id)
        data.append({
            "id": f.id,
            "user_id": f.following_id,
            "user_name": f.following.name if f.following else None,
            "creator_profile_id": profile.id if profile else None,
            "display_name": profile.display_name if profile else None,
            "avatar_url": profile.avatar_url if profile else None,
            "followed_at": f.created_at.isoformat() if f.created_at else None,
        })
    
    # Get total count
    result = await db.execute(
        select(func.count(CreatorFollower.id))
        .where(CreatorFollower.follower_id == user.id)
    )
    total = result.scalar() or 0
    
    return ApiResponse(success=True, data={"following": data, "total": total})


@router.get("/me/activity-feed", response_model=ApiResponse)
async def get_activity_feed(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get activity feed from followed creators."""
    from ..models import ActivityFeedItem
    from sqlalchemy.orm import selectinload
    
    result = await db.execute(
        select(ActivityFeedItem)
        .options(
            selectinload(ActivityFeedItem.actor),
            selectinload(ActivityFeedItem.workflow)
        )
        .where(ActivityFeedItem.user_id == user.id)
        .order_by(ActivityFeedItem.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = result.scalars().all()
    
    data = [
        {
            "id": item.id,
            "activity_type": item.activity_type,
            "title": item.title,
            "description": item.description,
            "actor_name": item.actor.name if item.actor else None,
            "workflow_id": item.workflow_id,
            "workflow_name": item.workflow.name if item.workflow else None,
            "metadata": item.metadata,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in items
    ]
    
    return ApiResponse(success=True, data=data)

