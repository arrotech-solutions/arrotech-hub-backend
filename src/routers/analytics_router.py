"""
Analytics Router

API endpoints for workflow analytics and metrics.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from .auth_router import get_current_user
from ..models import User, Workflow, WorkflowAnalytics, WorkflowVisibility

router = APIRouter(prefix="/analytics", tags=["analytics"])


# Request/Response Models
class TrackEventRequest(BaseModel):
    """Request to track an analytics event."""
    workflow_id: int
    event_type: str = Field(..., pattern="^(impression|detail_view|import_click|import_success|review_click|share_click|search_appear|search_click)$")


class AnalyticsSummary(BaseModel):
    """Summary of workflow analytics."""
    workflow_id: int
    workflow_name: str
    total_impressions: int
    total_detail_views: int
    total_imports: int
    conversion_rate: float
    avg_daily_views: float


class DailyMetrics(BaseModel):
    """Daily analytics metrics."""
    date: str
    impressions: int
    detail_views: int
    imports: int
    search_clicks: int


class ApiResponse(BaseModel):
    """Standard API response."""
    success: bool
    data: Optional[Any] = None
    message: Optional[str] = None


@router.post("/track", response_model=ApiResponse)
async def track_event(
    request: TrackEventRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Track an analytics event for a workflow."""
    try:
        # Get or create today's analytics record
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        result = await db.execute(
            select(WorkflowAnalytics).where(
                WorkflowAnalytics.workflow_id == request.workflow_id,
                WorkflowAnalytics.date == today
            )
        )
        analytics = result.scalar_one_or_none()
        
        if not analytics:
            analytics = WorkflowAnalytics(
                workflow_id=request.workflow_id,
                date=today
            )
            db.add(analytics)
        
        # Increment the appropriate counter
        event_map = {
            "impression": "impressions",
            "detail_view": "detail_views",
            "import_click": "import_clicks",
            "import_success": "successful_imports",
            "review_click": "review_clicks",
            "share_click": "share_clicks",
            "search_appear": "search_appearances",
            "search_click": "search_clicks",
        }
        
        field = event_map.get(request.event_type)
        if field:
            current_value = getattr(analytics, field, 0) or 0
            setattr(analytics, field, current_value + 1)
        
        await db.commit()
        
        return ApiResponse(success=True, message="Event tracked")
    except Exception as e:
        return ApiResponse(success=False, message=str(e))


@router.get("/workflow/{workflow_id}", response_model=ApiResponse)
async def get_workflow_analytics(
    workflow_id: int,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get analytics for a specific workflow (owner only)."""
    try:
        # Verify ownership
        result = await db.execute(
            select(Workflow).where(
                Workflow.id == workflow_id,
                Workflow.user_id == user.id
            )
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found or not authorized"
            )
        
        # Get analytics for the date range
        start_date = datetime.utcnow() - timedelta(days=days)
        
        result = await db.execute(
            select(WorkflowAnalytics)
            .where(
                WorkflowAnalytics.workflow_id == workflow_id,
                WorkflowAnalytics.date >= start_date
            )
            .order_by(WorkflowAnalytics.date)
        )
        records = result.scalars().all()
        
        # Calculate totals
        total_impressions = sum(r.impressions or 0 for r in records)
        total_detail_views = sum(r.detail_views or 0 for r in records)
        total_imports = sum(r.successful_imports or 0 for r in records)
        total_search_clicks = sum(r.search_clicks or 0 for r in records)
        
        # Calculate conversion rate
        conversion_rate = 0
        if total_detail_views > 0:
            conversion_rate = round((total_imports / total_detail_views) * 100, 2)
        
        # Prepare daily data
        daily_data = [
            {
                "date": r.date.strftime("%Y-%m-%d"),
                "impressions": r.impressions or 0,
                "detail_views": r.detail_views or 0,
                "imports": r.successful_imports or 0,
                "search_clicks": r.search_clicks or 0,
            }
            for r in records
        ]
        
        return ApiResponse(
            success=True,
            data={
                "workflow_id": workflow_id,
                "workflow_name": workflow.name,
                "period_days": days,
                "summary": {
                    "total_impressions": total_impressions,
                    "total_detail_views": total_detail_views,
                    "total_imports": total_imports,
                    "total_search_clicks": total_search_clicks,
                    "conversion_rate": conversion_rate,
                    "avg_daily_views": round(total_detail_views / max(len(records), 1), 2),
                },
                "daily": daily_data,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get analytics: {str(e)}"
        )


@router.get("/my-workflows", response_model=ApiResponse)
async def get_my_workflows_analytics(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get aggregated analytics for all user's workflows."""
    try:
        start_date = datetime.utcnow() - timedelta(days=days)
        
        # Get all user's workflows with their analytics
        result = await db.execute(
            select(
                Workflow.id,
                Workflow.name,
                func.coalesce(func.sum(WorkflowAnalytics.impressions), 0).label('impressions'),
                func.coalesce(func.sum(WorkflowAnalytics.detail_views), 0).label('detail_views'),
                func.coalesce(func.sum(WorkflowAnalytics.successful_imports), 0).label('imports'),
            )
            .outerjoin(
                WorkflowAnalytics,
                and_(
                    WorkflowAnalytics.workflow_id == Workflow.id,
                    WorkflowAnalytics.date >= start_date
                )
            )
            .where(
                Workflow.user_id == user.id,
                Workflow.visibility.in_([
                    WorkflowVisibility.PUBLIC,
                    WorkflowVisibility.MARKETPLACE
                ])
            )
            .group_by(Workflow.id, Workflow.name)
            .order_by(func.sum(WorkflowAnalytics.detail_views).desc().nulls_last())
        )
        rows = result.all()
        
        workflows_data = []
        total_impressions = 0
        total_views = 0
        total_imports = 0
        
        for row in rows:
            impressions = int(row.impressions or 0)
            views = int(row.detail_views or 0)
            imports = int(row.imports or 0)
            
            total_impressions += impressions
            total_views += views
            total_imports += imports
            
            conversion = round((imports / views) * 100, 2) if views > 0 else 0
            
            workflows_data.append({
                "workflow_id": row.id,
                "workflow_name": row.name,
                "impressions": impressions,
                "detail_views": views,
                "imports": imports,
                "conversion_rate": conversion,
            })
        
        overall_conversion = round((total_imports / total_views) * 100, 2) if total_views > 0 else 0
        
        return ApiResponse(
            success=True,
            data={
                "period_days": days,
                "summary": {
                    "total_workflows": len(workflows_data),
                    "total_impressions": total_impressions,
                    "total_views": total_views,
                    "total_imports": total_imports,
                    "overall_conversion_rate": overall_conversion,
                },
                "workflows": workflows_data,
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get analytics: {str(e)}"
        )


@router.get("/trending", response_model=ApiResponse)
async def get_trending_workflows(
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Get trending workflows based on recent activity."""
    try:
        start_date = datetime.utcnow() - timedelta(days=days)
        
        # Get workflows with highest engagement score in the period
        # Score = impressions * 1 + views * 3 + imports * 10
        result = await db.execute(
            select(
                Workflow.id,
                Workflow.name,
                Workflow.description,
                Workflow.category,
                Workflow.author_name,
                Workflow.downloads_count,
                Workflow.rating_sum,
                Workflow.rating_count,
                (
                    func.coalesce(func.sum(WorkflowAnalytics.impressions), 0) +
                    func.coalesce(func.sum(WorkflowAnalytics.detail_views), 0) * 3 +
                    func.coalesce(func.sum(WorkflowAnalytics.successful_imports), 0) * 10
                ).label('engagement_score')
            )
            .outerjoin(
                WorkflowAnalytics,
                and_(
                    WorkflowAnalytics.workflow_id == Workflow.id,
                    WorkflowAnalytics.date >= start_date
                )
            )
            .where(
                Workflow.visibility.in_([
                    WorkflowVisibility.PUBLIC,
                    WorkflowVisibility.MARKETPLACE
                ])
            )
            .group_by(Workflow.id)
            .order_by(func.coalesce(func.sum(WorkflowAnalytics.successful_imports), 0).desc())
            .limit(limit)
        )
        rows = result.all()
        
        trending = []
        for row in rows:
            rating = round(row.rating_sum / row.rating_count, 1) if row.rating_count > 0 else None
            trending.append({
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "category": row.category,
                "author_name": row.author_name,
                "downloads_count": row.downloads_count,
                "rating": rating,
                "rating_count": row.rating_count,
                "engagement_score": int(row.engagement_score or 0),
            })
        
        return ApiResponse(success=True, data=trending)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get trending: {str(e)}"
        )

