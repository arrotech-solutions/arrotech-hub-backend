# Scheduling Service for Phase 4: Intelligent Scheduling Engine
# Provides AI-powered scheduling with optimal slot finding, focus time protection,
# buffer time automation, and conflict detection.

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TimeSlot:
    """Represents an available time slot."""
    start: datetime
    end: datetime
    score: float  # 0-100, higher = better fit
    reason: str  # Why this slot was suggested


@dataclass
class Conflict:
    """Represents a scheduling conflict."""
    event_id: str
    event_title: str
    start: datetime
    end: datetime
    overlap_minutes: int


class SchedulingService:
    """
    AI-powered scheduling service for intelligent calendar management.
    Inspired by Motion AI and Reclaim AI.
    """
    
    def __init__(self, calendar_service=None):
        self.calendar_service = calendar_service
    
    async def find_optimal_slots(
        self,
        user_id: int,
        duration_minutes: int,
        date_range_days: int = 7,
        preferences: Optional[Dict[str, Any]] = None,
        calendar_events: Optional[List[Dict]] = None
    ) -> List[TimeSlot]:
        """
        Find optimal time slots for a meeting/event.
        
        Args:
            user_id: User ID
            duration_minutes: Required duration in minutes
            date_range_days: How many days ahead to search
            preferences: Optional preferences like:
                - prefer_morning: bool
                - prefer_afternoon: bool
                - avoid_back_to_back: bool
                - min_gap_minutes: int
            calendar_events: Existing calendar events (if already fetched)
        
        Returns:
            List of TimeSlot suggestions, sorted by score (best first)
        """
        preferences = preferences or {}
        prefer_morning = preferences.get('prefer_morning', False)
        prefer_afternoon = preferences.get('prefer_afternoon', False)
        avoid_back_to_back = preferences.get('avoid_back_to_back', True)
        min_gap = preferences.get('min_gap_minutes', 15)
        
        now = datetime.now()
        search_start = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now.hour >= 8:
            search_start = now + timedelta(hours=1)  # Start from next hour
        
        search_end = (now + timedelta(days=date_range_days)).replace(hour=18, minute=0)
        
        # Get busy times from calendar events
        busy_times = []
        if calendar_events:
            for event in calendar_events:
                try:
                    start_str = event.get('start', {}).get('dateTime') or event.get('start', {}).get('date')
                    end_str = event.get('end', {}).get('dateTime') or event.get('end', {}).get('date')
                    if start_str and end_str:
                        start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                        end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                        busy_times.append((start, end))
                except Exception as e:
                    logger.warning(f"Failed to parse event time: {e}")
        
        # Find available slots
        available_slots: List[TimeSlot] = []
        current_date = search_start.date()
        end_date = search_end.date()
        
        while current_date <= end_date:
            # Skip weekends
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue
            
            # Work hours: 8 AM - 6 PM
            day_start = datetime.combine(current_date, datetime.min.time().replace(hour=8))
            day_end = datetime.combine(current_date, datetime.min.time().replace(hour=18))
            
            # Skip if before now
            if day_start < now:
                day_start = now + timedelta(hours=1)
                day_start = day_start.replace(minute=0, second=0, microsecond=0)
            
            if day_start >= day_end:
                current_date += timedelta(days=1)
                continue
            
            # Find gaps in the day
            current_time = day_start
            while current_time + timedelta(minutes=duration_minutes) <= day_end:
                slot_end = current_time + timedelta(minutes=duration_minutes)
                
                # Check for conflicts
                is_available = True
                for busy_start, busy_end in busy_times:
                    # Make timezone-naive for comparison
                    if busy_start.tzinfo:
                        busy_start = busy_start.replace(tzinfo=None)
                    if busy_end.tzinfo:
                        busy_end = busy_end.replace(tzinfo=None)
                    
                    # Add gap buffer if avoiding back-to-back
                    buffer_start = busy_start - timedelta(minutes=min_gap) if avoid_back_to_back else busy_start
                    buffer_end = busy_end + timedelta(minutes=min_gap) if avoid_back_to_back else busy_end
                    
                    # Check overlap
                    if not (slot_end <= buffer_start or current_time >= buffer_end):
                        is_available = False
                        break
                
                if is_available:
                    # Calculate score based on preferences
                    score = 50.0  # Base score
                    reason_parts = []
                    
                    hour = current_time.hour
                    if prefer_morning and 8 <= hour < 12:
                        score += 20
                        reason_parts.append("Morning slot (preferred)")
                    elif prefer_afternoon and 13 <= hour < 17:
                        score += 20
                        reason_parts.append("Afternoon slot (preferred)")
                    elif 10 <= hour <= 14:
                        score += 10
                        reason_parts.append("Prime working hours")
                    
                    # Prefer slots not at day boundaries
                    if 9 <= hour <= 16:
                        score += 10
                        reason_parts.append("Good energy time")
                    
                    # Prefer tomorrow over today (more flexibility)
                    days_ahead = (current_date - now.date()).days
                    if days_ahead == 1:
                        score += 5
                        reason_parts.append("Tomorrow (good lead time)")
                    
                    available_slots.append(TimeSlot(
                        start=current_time,
                        end=slot_end,
                        score=min(100, score),
                        reason="; ".join(reason_parts) if reason_parts else "Available slot"
                    ))
                
                # Move to next 30-min slot
                current_time += timedelta(minutes=30)
            
            current_date += timedelta(days=1)
        
        # Sort by score descending and limit results
        available_slots.sort(key=lambda s: s.score, reverse=True)
        return available_slots[:10]  # Top 10 suggestions
    
    async def protect_focus_time(
        self,
        user_id: int,
        hours_per_week: int = 10,
        calendar_events: Optional[List[Dict]] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate focus time blocks to protect deep work.
        
        Args:
            user_id: User ID
            hours_per_week: Target focus hours per week
            calendar_events: Existing calendar events
        
        Returns:
            List of suggested focus blocks to create
        """
        focus_blocks = []
        now = datetime.now()
        
        # Preferred focus times: morning (9-11 AM) and afternoon (2-4 PM)
        preferred_times = [
            (9, 11, "Morning Focus Block"),
            (14, 16, "Afternoon Focus Block")
        ]
        
        # Try to schedule focus blocks for the next week
        hours_scheduled = 0
        target_hours = hours_per_week
        current_date = now.date()
        
        for day_offset in range(7):
            if hours_scheduled >= target_hours:
                break
            
            check_date = current_date + timedelta(days=day_offset)
            
            # Skip weekends
            if check_date.weekday() >= 5:
                continue
            
            for start_hour, end_hour, title in preferred_times:
                if hours_scheduled >= target_hours:
                    break
                
                block_start = datetime.combine(check_date, datetime.min.time().replace(hour=start_hour))
                block_end = datetime.combine(check_date, datetime.min.time().replace(hour=end_hour))
                
                # Skip if in the past
                if block_end < now:
                    continue
                
                # Check for conflicts with existing events
                is_available = True
                if calendar_events:
                    for event in calendar_events:
                        try:
                            event_start_str = event.get('start', {}).get('dateTime')
                            event_end_str = event.get('end', {}).get('dateTime')
                            if event_start_str and event_end_str:
                                event_start = datetime.fromisoformat(event_start_str.replace('Z', '+00:00')).replace(tzinfo=None)
                                event_end = datetime.fromisoformat(event_end_str.replace('Z', '+00:00')).replace(tzinfo=None)
                                if not (block_end <= event_start or block_start >= event_end):
                                    is_available = False
                                    break
                        except:
                            pass
                
                if is_available:
                    focus_blocks.append({
                        "title": f"🧠 {title}",
                        "start": block_start.isoformat(),
                        "end": block_end.isoformat(),
                        "duration_hours": (block_end - block_start).seconds / 3600,
                        "description": "Protected focus time - minimize interruptions"
                    })
                    hours_scheduled += (block_end - block_start).seconds / 3600
        
        return focus_blocks
    
    async def add_buffer_time(
        self,
        user_id: int,
        buffer_minutes: int = 15,
        calendar_events: Optional[List[Dict]] = None
    ) -> List[Dict[str, Any]]:
        """
        Identify where buffer time should be added between back-to-back meetings.
        
        Args:
            user_id: User ID
            buffer_minutes: Minutes of buffer to suggest
            calendar_events: Existing calendar events
        
        Returns:
            List of suggested buffer blocks
        """
        if not calendar_events:
            return []
        
        # Sort events by start time
        events_with_times = []
        for event in calendar_events:
            try:
                start_str = event.get('start', {}).get('dateTime')
                end_str = event.get('end', {}).get('dateTime')
                if start_str and end_str:
                    start = datetime.fromisoformat(start_str.replace('Z', '+00:00')).replace(tzinfo=None)
                    end = datetime.fromisoformat(end_str.replace('Z', '+00:00')).replace(tzinfo=None)
                    events_with_times.append({
                        "event": event,
                        "start": start,
                        "end": end
                    })
            except:
                pass
        
        events_with_times.sort(key=lambda x: x["start"])
        
        # Find back-to-back meetings (less than 5 min gap)
        buffer_suggestions = []
        now = datetime.now()
        
        for i in range(len(events_with_times) - 1):
            current = events_with_times[i]
            next_event = events_with_times[i + 1]
            
            # Skip past events
            if current["end"] < now:
                continue
            
            gap = (next_event["start"] - current["end"]).total_seconds() / 60
            
            if gap < 5:  # Back-to-back (less than 5 min gap)
                buffer_suggestions.append({
                    "after_event": current["event"].get("summary", "Unknown"),
                    "before_event": next_event["event"].get("summary", "Unknown"),
                    "suggested_buffer_start": current["end"].isoformat(),
                    "suggested_buffer_end": (current["end"] + timedelta(minutes=buffer_minutes)).isoformat(),
                    "buffer_minutes": buffer_minutes,
                    "reason": "Back-to-back meetings detected"
                })
        
        return buffer_suggestions
    
    async def detect_conflicts(
        self,
        user_id: int,
        proposed_start: datetime,
        proposed_end: datetime,
        calendar_events: Optional[List[Dict]] = None
    ) -> List[Conflict]:
        """
        Detect conflicts with a proposed time slot.
        
        Args:
            user_id: User ID
            proposed_start: Proposed event start
            proposed_end: Proposed event end
            calendar_events: Existing calendar events
        
        Returns:
            List of conflicting events
        """
        conflicts = []
        
        if not calendar_events:
            return conflicts
        
        for event in calendar_events:
            try:
                start_str = event.get('start', {}).get('dateTime')
                end_str = event.get('end', {}).get('dateTime')
                if start_str and end_str:
                    event_start = datetime.fromisoformat(start_str.replace('Z', '+00:00')).replace(tzinfo=None)
                    event_end = datetime.fromisoformat(end_str.replace('Z', '+00:00')).replace(tzinfo=None)
                    
                    # Check overlap
                    if not (proposed_end <= event_start or proposed_start >= event_end):
                        # Calculate overlap duration
                        overlap_start = max(proposed_start, event_start)
                        overlap_end = min(proposed_end, event_end)
                        overlap_minutes = int((overlap_end - overlap_start).total_seconds() / 60)
                        
                        conflicts.append(Conflict(
                            event_id=event.get("id", "unknown"),
                            event_title=event.get("summary", "Unknown Event"),
                            start=event_start,
                            end=event_end,
                            overlap_minutes=overlap_minutes
                        ))
            except Exception as e:
                logger.warning(f"Failed to check conflict: {e}")
        
        return conflicts


# Singleton instance
scheduling_service = SchedulingService()
