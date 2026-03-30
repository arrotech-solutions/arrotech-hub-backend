"""
Productivity Service - Calculates productivity metrics and tracks user streaks.

This service powers the ProductivityStats analytics page and provides
scoring algorithms for measuring user productivity across the platform.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import uuid
from dataclasses import dataclass, asdict
from enum import Enum
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from ..models import User

logger = logging.getLogger(__name__)


class ActivityType(str, Enum):
    """Types of activities tracked for productivity scoring."""
    EMAIL_SENT = "email_sent"
    EMAIL_PROCESSED = "email_processed"
    TASK_COMPLETED = "task_completed"
    TASK_CREATED = "task_created"
    MEETING_ATTENDED = "meeting_attended"
    FOCUS_TIME = "focus_time"
    INBOX_ZERO = "inbox_zero"
    MESSAGE_SENT = "message_sent"
    DOCUMENT_CREATED = "document_created"


@dataclass
class DailyScore:
    """Daily productivity score data."""
    date: str
    score: int
    breakdown: Dict[str, int]
    activities_count: int


@dataclass
class StreakData:
    """User streak tracking data."""
    current_streak: int
    longest_streak: int
    last_active_date: str
    streak_type: str  # "daily", "weekly"
    multiplier: float


@dataclass
class ActivityStats:
    """Activity breakdown statistics."""
    period: str
    total_activities: int
    by_type: Dict[str, int]
    peak_hour: int
    peak_day: str
    trend: str  # "up", "down", "stable"


# In-memory storage for demo (in production, use database)
_user_activities: Dict[int, List[Dict]] = {}
_user_streaks: Dict[int, Dict] = {}


class ProductivityService:
    """
    Service for calculating productivity metrics and tracking streaks.
    
    Scoring Formula:
    - Emails processed: 0.5 points each (max 20)
    - Tasks completed: 2 points each (max 30)
    - Meetings attended: 1.5 points each (max 15)
    - Focus time blocks: 3 points per hour (max 20)
    - Inbox Zero bonus: +5
    - Streak multiplier: 1.0 + (streak_days * 0.02)
    """
    
    # Scoring weights
    WEIGHTS = {
        ActivityType.EMAIL_PROCESSED: 0.5,
        ActivityType.EMAIL_SENT: 0.3,
        ActivityType.TASK_COMPLETED: 2.0,
        ActivityType.TASK_CREATED: 0.5,
        ActivityType.MEETING_ATTENDED: 1.5,
        ActivityType.FOCUS_TIME: 3.0,
        ActivityType.INBOX_ZERO: 5.0,
        ActivityType.MESSAGE_SENT: 0.2,
        ActivityType.DOCUMENT_CREATED: 1.0,
    }
    
    # Maximum points per category
    MAX_POINTS = {
        ActivityType.EMAIL_PROCESSED: 20,
        ActivityType.EMAIL_SENT: 10,
        ActivityType.TASK_COMPLETED: 30,
        ActivityType.TASK_CREATED: 10,
        ActivityType.MEETING_ATTENDED: 15,
        ActivityType.FOCUS_TIME: 20,
        ActivityType.INBOX_ZERO: 5,
        ActivityType.MESSAGE_SENT: 5,
        ActivityType.DOCUMENT_CREATED: 10,
    }
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    async def log_activity(
        self,
        user_id: uuid.UUID,
        activity_type: ActivityType,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Log a user activity for productivity tracking.
        
        Args:
            user_id: The user's ID
            activity_type: Type of activity performed
            metadata: Additional activity data
            timestamp: When the activity occurred (defaults to now)
        
        Returns:
            Dict with activity logging result
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        activity = {
            "type": activity_type.value,
            "timestamp": timestamp.isoformat(),
            "metadata": metadata or {},
            "date": timestamp.strftime("%Y-%m-%d")
        }
        
        if user_id not in _user_activities:
            _user_activities[user_id] = []
        
        _user_activities[user_id].append(activity)
        
        # Update streak
        await self.update_streak(user_id, activity_type)
        
        self.logger.info(f"Logged activity {activity_type.value} for user {user_id}")
        
        return {"success": True, "activity": activity}
    
    async def calculate_daily_score(
        self,
        user_id: uuid.UUID,
        date: Optional[datetime] = None
    ) -> DailyScore:
        """
        Calculate productivity score for a specific day.
        
        Args:
            user_id: The user's ID
            date: Date to calculate for (defaults to today)
        
        Returns:
            DailyScore with score and breakdown
        """
        if date is None:
            date = datetime.utcnow()
        
        date_str = date.strftime("%Y-%m-%d")
        
        # Get activities for this day
        activities = _user_activities.get(user_id, [])
        day_activities = [a for a in activities if a.get("date") == date_str]
        
        # Count by type
        type_counts: Dict[str, int] = {}
        for activity in day_activities:
            act_type = activity.get("type", "unknown")
            type_counts[act_type] = type_counts.get(act_type, 0) + 1
        
        # Calculate points per category
        breakdown: Dict[str, int] = {}
        total_score = 0.0
        
        for act_type, count in type_counts.items():
            try:
                activity_enum = ActivityType(act_type)
                weight = self.WEIGHTS.get(activity_enum, 0)
                max_pts = self.MAX_POINTS.get(activity_enum, 100)
                
                raw_points = count * weight
                capped_points = min(raw_points, max_pts)
                
                breakdown[act_type] = int(capped_points)
                total_score += capped_points
            except ValueError:
                continue
        
        # Apply streak multiplier
        streak = await self.get_current_streak(user_id)
        multiplier = streak.multiplier
        total_score = total_score * multiplier
        
        # Cap at 100
        final_score = min(int(total_score), 100)
        
        return DailyScore(
            date=date_str,
            score=final_score,
            breakdown=breakdown,
            activities_count=len(day_activities)
        )
    
    async def calculate_weekly_score(
        self,
        user_id: uuid.UUID,
        week_start: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Calculate productivity score for a week.
        
        Args:
            user_id: The user's ID
            week_start: Start of week (defaults to current week's Monday)
        
        Returns:
            Dict with weekly score and daily breakdown
        """
        if week_start is None:
            today = datetime.utcnow()
            week_start = today - timedelta(days=today.weekday())
        
        daily_scores = []
        total_score = 0
        
        for i in range(7):
            day = week_start + timedelta(days=i)
            daily = await self.calculate_daily_score(user_id, day)
            daily_scores.append(asdict(daily))
            total_score += daily.score
        
        avg_score = total_score // 7 if daily_scores else 0
        
        return {
            "week_start": week_start.strftime("%Y-%m-%d"),
            "average_score": avg_score,
            "total_score": total_score,
            "daily_scores": daily_scores,
            "best_day": max(daily_scores, key=lambda x: x["score"]) if daily_scores else None
        }
    
    async def get_productivity_trend(
        self,
        user_id: uuid.UUID,
        days: int = 30
    ) -> List[DailyScore]:
        """
        Get productivity trend over specified days.
        
        Args:
            user_id: The user's ID
            days: Number of days to look back
        
        Returns:
            List of DailyScore objects
        """
        today = datetime.utcnow()
        scores = []
        
        for i in range(days):
            day = today - timedelta(days=days - 1 - i)
            score = await self.calculate_daily_score(user_id, day)
            scores.append(score)
        
        return scores
    
    async def get_current_streak(self, user_id: uuid.UUID) -> StreakData:
        """
        Get user's current productivity streak.
        
        Args:
            user_id: The user's ID
        
        Returns:
            StreakData with current and longest streak
        """
        streak_data = _user_streaks.get(user_id, {
            "current_streak": 0,
            "longest_streak": 0,
            "last_active_date": None,
            "streak_type": "daily"
        })
        
        current = streak_data.get("current_streak", 0)
        multiplier = 1.0 + (current * 0.02)  # 2% bonus per streak day
        multiplier = min(multiplier, 2.0)  # Cap at 2x
        
        return StreakData(
            current_streak=current,
            longest_streak=streak_data.get("longest_streak", 0),
            last_active_date=streak_data.get("last_active_date", ""),
            streak_type=streak_data.get("streak_type", "daily"),
            multiplier=round(multiplier, 2)
        )
    
    async def update_streak(
        self,
        user_id: uuid.UUID,
        activity_type: ActivityType
    ) -> StreakData:
        """
        Update user's streak based on activity.
        
        Args:
            user_id: The user's ID
            activity_type: Type of activity performed
        
        Returns:
            Updated StreakData
        """
        today = datetime.utcnow().strftime("%Y-%m-%d")
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        if user_id not in _user_streaks:
            _user_streaks[user_id] = {
                "current_streak": 0,
                "longest_streak": 0,
                "last_active_date": None,
                "streak_type": "daily"
            }
        
        streak = _user_streaks[user_id]
        last_active = streak.get("last_active_date")
        
        if last_active == today:
            # Already active today, no change
            pass
        elif last_active == yesterday:
            # Continuing streak
            streak["current_streak"] += 1
            streak["last_active_date"] = today
            if streak["current_streak"] > streak["longest_streak"]:
                streak["longest_streak"] = streak["current_streak"]
        else:
            # Streak broken or first activity
            streak["current_streak"] = 1
            streak["last_active_date"] = today
        
        _user_streaks[user_id] = streak
        
        return await self.get_current_streak(user_id)
    
    async def get_activity_breakdown(
        self,
        user_id: uuid.UUID,
        period: str = "week"
    ) -> ActivityStats:
        """
        Get activity breakdown for a period.
        
        Args:
            user_id: The user's ID
            period: "day", "week", or "month"
        
        Returns:
            ActivityStats with breakdown by type
        """
        today = datetime.utcnow()
        
        if period == "day":
            start_date = today
        elif period == "week":
            start_date = today - timedelta(days=7)
        elif period == "month":
            start_date = today - timedelta(days=30)
        else:
            start_date = today - timedelta(days=7)
        
        start_str = start_date.strftime("%Y-%m-%d")
        
        activities = _user_activities.get(user_id, [])
        period_activities = [
            a for a in activities 
            if a.get("date", "") >= start_str
        ]
        
        # Count by type
        by_type: Dict[str, int] = {}
        hour_counts: Dict[int, int] = {}
        day_counts: Dict[str, int] = {}
        
        for activity in period_activities:
            act_type = activity.get("type", "unknown")
            by_type[act_type] = by_type.get(act_type, 0) + 1
            
            # Parse timestamp for peak analysis
            try:
                ts = datetime.fromisoformat(activity.get("timestamp", ""))
                hour = ts.hour
                day = ts.strftime("%A")
                hour_counts[hour] = hour_counts.get(hour, 0) + 1
                day_counts[day] = day_counts.get(day, 0) + 1
            except:
                pass
        
        peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else 9
        peak_day = max(day_counts, key=day_counts.get) if day_counts else "Monday"
        
        # Calculate trend (compare first half vs second half)
        mid = len(period_activities) // 2
        first_half = len(period_activities[:mid]) if mid > 0 else 0
        second_half = len(period_activities[mid:]) if mid > 0 else 0
        
        if second_half > first_half * 1.1:
            trend = "up"
        elif second_half < first_half * 0.9:
            trend = "down"
        else:
            trend = "stable"
        
        return ActivityStats(
            period=period,
            total_activities=len(period_activities),
            by_type=by_type,
            peak_hour=peak_hour,
            peak_day=peak_day,
            trend=trend
        )
    
    async def get_achievements(self, user_id: uuid.UUID) -> List[Dict[str, Any]]:
        """
        Get user's productivity achievements and milestones.
        
        Args:
            user_id: The user's ID
        
        Returns:
            List of achievement dictionaries
        """
        streak = await self.get_current_streak(user_id)
        activities = _user_activities.get(user_id, [])
        
        achievements = []
        
        # Streak achievements
        if streak.current_streak >= 3:
            achievements.append({
                "id": "streak_3",
                "title": "On Fire! 🔥",
                "description": "3-day productivity streak",
                "earned": True,
                "icon": "🔥"
            })
        
        if streak.current_streak >= 7:
            achievements.append({
                "id": "streak_7",
                "title": "Week Warrior",
                "description": "7-day productivity streak",
                "earned": True,
                "icon": "⚔️"
            })
        
        if streak.longest_streak >= 30:
            achievements.append({
                "id": "streak_30",
                "title": "Monthly Master",
                "description": "30-day productivity streak",
                "earned": True,
                "icon": "👑"
            })
        
        # Activity achievements
        task_completions = sum(
            1 for a in activities 
            if a.get("type") == ActivityType.TASK_COMPLETED.value
        )
        
        if task_completions >= 10:
            achievements.append({
                "id": "tasks_10",
                "title": "Task Crusher",
                "description": "Completed 10 tasks",
                "earned": True,
                "icon": "✅"
            })
        
        if task_completions >= 100:
            achievements.append({
                "id": "tasks_100",
                "title": "Centurion",
                "description": "Completed 100 tasks",
                "earned": True,
                "icon": "💯"
            })
        
        # Inbox Zero
        inbox_zeros = sum(
            1 for a in activities 
            if a.get("type") == ActivityType.INBOX_ZERO.value
        )
        
        if inbox_zeros >= 1:
            achievements.append({
                "id": "inbox_zero_1",
                "title": "Inbox Zero Hero",
                "description": "Achieved Inbox Zero",
                "earned": True,
                "icon": "📭"
            })
        
        return achievements
    
    async def get_weekly_comparison(self, user_id: uuid.UUID) -> Dict[str, Any]:
        """
        Compare this week's productivity to last week.
        
        Args:
            user_id: The user's ID
        
        Returns:
            Dict with comparison data
        """
        today = datetime.utcnow()
        this_week_start = today - timedelta(days=today.weekday())
        last_week_start = this_week_start - timedelta(days=7)
        
        this_week = await self.calculate_weekly_score(user_id, this_week_start)
        last_week = await self.calculate_weekly_score(user_id, last_week_start)
        
        this_avg = this_week.get("average_score", 0)
        last_avg = last_week.get("average_score", 0)
        
        if last_avg > 0:
            change_pct = ((this_avg - last_avg) / last_avg) * 100
        else:
            change_pct = 100 if this_avg > 0 else 0
        
        return {
            "this_week": this_week,
            "last_week": last_week,
            "change_percentage": round(change_pct, 1),
            "trend": "up" if change_pct > 0 else "down" if change_pct < 0 else "stable"
        }


# Singleton instance
productivity_service = ProductivityService()
