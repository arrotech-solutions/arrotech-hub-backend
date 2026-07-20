"""
Productivity Router - API endpoints for productivity metrics and analytics.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from .auth_router import get_current_user
from ..models import User
from ..services.productivity_service import (
    productivity_service, 
    ActivityType,
    DailyScore,
    StreakData,
    ActivityStats
)
from dataclasses import asdict

router = APIRouter(prefix="/productivity", tags=["productivity"])


class LogActivityRequest(BaseModel):
    """Request model for logging an activity."""
    activity_type: str
    metadata: Optional[dict] = None
    timestamp: Optional[str] = None


class LogActivityResponse(BaseModel):
    """Response model for logged activity."""
    success: bool
    activity: dict


@router.get("/score/daily")
async def get_daily_score(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    current_user: User = Depends(get_current_user)
):
    """
    Get productivity score for a specific day.
    
    Args:
        date: Optional date string (defaults to today)
    
    Returns:
        Daily productivity score and breakdown
    """
    try:
        if date:
            target_date = datetime.strptime(date, "%Y-%m-%d")
        else:
            target_date = datetime.utcnow()
        
        score = await productivity_service.calculate_daily_score(
            user_id=current_user.id,
            date=target_date
        )
        
        return {
            "success": True,
            **asdict(score)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/score/weekly")
async def get_weekly_score(
    week_start: Optional[str] = Query(None, description="Week start date in YYYY-MM-DD format"),
    current_user: User = Depends(get_current_user)
):
    """
    Get productivity score for a week.
    
    Args:
        week_start: Optional week start date (defaults to current week)
    
    Returns:
        Weekly productivity score with daily breakdown
    """
    try:
        if week_start:
            start_date = datetime.strptime(week_start, "%Y-%m-%d")
        else:
            start_date = None
        
        result = await productivity_service.calculate_weekly_score(
            user_id=current_user.id,
            week_start=start_date
        )
        
        return {
            "success": True,
            **result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/streak")
async def get_streak(
    current_user: User = Depends(get_current_user)
):
    """
    Get user's current productivity streak.
    
    Returns:
        Streak data including current streak, longest streak, and multiplier
    """
    try:
        streak = await productivity_service.get_current_streak(current_user.id)
        
        return {
            "success": True,
            **asdict(streak)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/breakdown/{period}")
async def get_activity_breakdown(
    period: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get activity breakdown for a period.
    
    Args:
        period: "day", "week", or "month"
    
    Returns:
        Activity statistics with breakdown by type
    """
    if period not in ["day", "week", "month"]:
        raise HTTPException(
            status_code=400, 
            detail="Period must be 'day', 'week', or 'month'"
        )
    
    try:
        stats = await productivity_service.get_activity_breakdown(
            user_id=current_user.id,
            period=period
        )
        
        return {
            "success": True,
            **asdict(stats)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trends")
async def get_productivity_trends(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    current_user: User = Depends(get_current_user)
):
    """
    Get productivity trend over specified days.
    
    Args:
        days: Number of days to look back (1-365)
    
    Returns:
        List of daily scores showing trend
    """
    try:
        trends = await productivity_service.get_productivity_trend(
            user_id=current_user.id,
            days=days
        )
        
        return {
            "success": True,
            "days": days,
            "scores": [asdict(score) for score in trends]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/achievements")
async def get_achievements(
    current_user: User = Depends(get_current_user)
):
    """
    Get user's productivity achievements.
    
    Returns:
        List of earned achievements and badges
    """
    try:
        achievements = await productivity_service.get_achievements(current_user.id)
        
        return {
            "success": True,
            "achievements": achievements
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/comparison")
async def get_weekly_comparison(
    current_user: User = Depends(get_current_user)
):
    """
    Compare this week's productivity to last week.
    
    Returns:
        Comparison data with change percentage
    """
    try:
        comparison = await productivity_service.get_weekly_comparison(current_user.id)
        
        return {
            "success": True,
            **comparison
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/log-activity")
async def log_activity(
    request: LogActivityRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Log a user activity for productivity tracking.
    
    Args:
        request: Activity logging request with type and metadata
    
    Returns:
        Logged activity confirmation
    """
    try:
        # Validate activity type
        try:
            activity_type = ActivityType(request.activity_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid activity type. Valid types: {[t.value for t in ActivityType]}"
            )
        
        # Parse timestamp if provided
        timestamp = None
        if request.timestamp:
            timestamp = datetime.fromisoformat(request.timestamp)
        
        result = await productivity_service.log_activity(
            user_id=current_user.id,
            activity_type=activity_type,
            metadata=request.metadata,
            timestamp=timestamp
        )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_productivity_summary(
    current_user: User = Depends(get_current_user)
):
    """
    Get a comprehensive productivity summary.
    
    Returns:
        Summary with score, streak, achievements, and comparison
    """
    try:
        daily_score = await productivity_service.calculate_daily_score(current_user.id)
        streak = await productivity_service.get_current_streak(current_user.id)
        achievements = await productivity_service.get_achievements(current_user.id)
        breakdown = await productivity_service.get_activity_breakdown(current_user.id, "week")
        comparison = await productivity_service.get_weekly_comparison(current_user.id)
        
        return {
            "success": True,
            "today_score": asdict(daily_score),
            "streak": asdict(streak),
            "achievements_count": len(achievements),
            "recent_achievements": achievements[:3],
            "weekly_breakdown": asdict(breakdown),
            "week_comparison": comparison
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Smart Scheduler (Business+ Feature)
# =============================================================================

from ..services.scheduling_service import scheduling_service
from ..services.feature_flags import FeatureGate
from ..services.tool_executor import tool_executor
from typing import List, Dict, Any
import logging


class SmartScheduleRequest(BaseModel):
    """Request model for smart scheduling."""
    duration_minutes: int = 30
    date_range_days: int = 7
    prefer_morning: bool = False
    prefer_afternoon: bool = False
    avoid_back_to_back: bool = True


class SmartScheduleResponse(BaseModel):
    """Response model for smart scheduling."""
    success: bool
    optimal_slots: List[Dict[str, Any]] = []
    message: str = ""
    error: Optional[str] = None


@router.post("/smart-schedule")
async def smart_schedule(
    request: SmartScheduleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Find optimal meeting times using AI-powered scheduling (Business+ feature).
    
    Uses the existing SchedulingService to analyze calendar and find best slots.
    """
    # Check feature access (Business+ only)
    if not FeatureGate.has_feature(current_user, "calendar_smart_scheduler"):
        return SmartScheduleResponse(
            success=False,
            message="",
            error="Upgrade to Business or higher for Smart Scheduling"
        )
    
    try:
        # Get user's calendar events
        calendar_events = []
        try:
            result = await tool_executor.execute_tool(
                tool_name="google_workspace_calendar",
                parameters={"operation": "list_events", "max_results": 100},
                user=current_user,
                db=db
            )
            if result.get("success") and result.get("result", {}).get("events"):
                calendar_events = result["result"]["events"]
        except Exception as e:
            logging.warning(f"Failed to fetch calendar: {e}")
        
        # Build preferences dict
        preferences = {
            "prefer_morning": request.prefer_morning,
            "prefer_afternoon": request.prefer_afternoon,
            "avoid_back_to_back": request.avoid_back_to_back
        }
        
        # Use existing scheduling service
        slots = await scheduling_service.find_optimal_slots(
            user_id=current_user.id,
            duration_minutes=request.duration_minutes,
            date_range_days=request.date_range_days,
            preferences=preferences,
            calendar_events=calendar_events
        )
        
        # Convert TimeSlot dataclass to dict
        slots_dict = []
        for slot in slots[:10]:  # Return top 10 slots
            slots_dict.append({
                "start": slot.start.isoformat(),
                "end": slot.end.isoformat(),
                "score": slot.score,
                "reason": slot.reason
            })
        
        return SmartScheduleResponse(
            success=True,
            optimal_slots=slots_dict,
            message=f"Found {len(slots_dict)} optimal slots for a {request.duration_minutes}-minute meeting"
        )
        
    except Exception as e:
        logging.error(f"Smart scheduling failed: {e}")
        return SmartScheduleResponse(
            success=False,
            message="",
            error=f"Smart scheduling failed: {str(e)}"
        )

