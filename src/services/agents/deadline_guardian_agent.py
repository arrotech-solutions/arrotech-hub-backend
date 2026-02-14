"""
Deadline Guardian Agent - Monitors task deadlines and proactively alerts users.

This agent watches connected task management systems (Jira, Trello, Asana)
and ensures users never miss important deadlines.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from .base_agent import BaseAgent
from ...models import User

logger = logging.getLogger(__name__)


class DeadlineGuardianAgent(BaseAgent):
    """
    Agent that monitors task deadlines and sends proactive alerts.
    
    Triggers:
        - Daily morning scan
        - Real-time when task deadline approaches
    
    Actions:
        - Fetch tasks from Jira, Trello, Asana
        - Check for tasks due within 24/48/72 hours
        - Generate urgency notifications
        - Suggest time blocks to complete urgent tasks
    """
    
    AGENT_ID = "deadline_guardian"
    AGENT_NAME = "Deadline Guardian"
    AGENT_DESCRIPTION = "Watches your tasks and warns you before deadlines slip"
    AGENT_ICON = "⏰"
    
    DEFAULT_CONFIG = {
        "warning_thresholds": [24, 48, 72],  # Hours before deadline to warn
        "scan_jira": True,
        "scan_trello": True,
        "scan_asana": True,
        "include_time_suggestions": True,
        "notification_channel": "both",  # email and slack
    }
    
    # Urgency levels based on hours remaining
    URGENCY_LEVELS = {
        6: {"level": "critical", "emoji": "🚨", "color": "red"},
        24: {"level": "high", "emoji": "⚠️", "color": "orange"},
        48: {"level": "medium", "emoji": "📅", "color": "yellow"},
        72: {"level": "low", "emoji": "📌", "color": "blue"},
    }
    
    def __init__(self, user: User, db: AsyncSession, config: Optional[Dict] = None):
        super().__init__(user, db)
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
    
    async def process_message(
        self,
        message: str,
        channel: str,
        slack_user_id: str
    ) -> Dict[str, Any]:
        """Process a request about deadlines."""
        try:
            intent = await self.classify_intent(message)
            
            if intent.get("intent") == "check_deadlines":
                deadlines = await self.check_upcoming_deadlines()
                return {
                    "success": True,
                    "response": self._format_deadline_report(deadlines),
                    "data": {"deadlines": deadlines}
                }
            elif intent.get("intent") == "suggest_time":
                suggestions = await self.suggest_time_blocks(
                    intent.get("parameters", {}).get("task_id")
                )
                return {
                    "success": True,
                    "response": self._format_time_suggestions(suggestions),
                    "data": {"suggestions": suggestions}
                }
            else:
                return {
                    "success": True,
                    "response": "I monitor your deadlines and alert you before they slip. Say 'check deadlines' to see what's coming up."
                }
        except Exception as e:
            logger.error(f"Deadline guardian error: {e}")
            return {
                "success": False,
                "error": str(e),
                "response": "I encountered an error checking your deadlines."
            }
    
    async def classify_intent(self, message: str) -> Dict[str, Any]:
        """Classify the user's intent."""
        message_lower = message.lower()
        
        if "deadline" in message_lower or "due" in message_lower:
            return {"intent": "check_deadlines"}
        elif "time" in message_lower and "suggest" in message_lower:
            return {"intent": "suggest_time", "parameters": {}}
        else:
            return {"intent": "unknown"}
    
    async def check_upcoming_deadlines(
        self,
        hours_ahead: int = 72
    ) -> List[Dict[str, Any]]:
        """
        Check for upcoming deadlines across all connected platforms.
        
        Args:
            hours_ahead: How many hours ahead to look
        
        Returns:
            List of upcoming deadlines with urgency levels
        """
        deadlines = []
        now = datetime.utcnow()
        
        # Fetch from Jira
        if self.config.get("scan_jira"):
            jira_tasks = await self._fetch_jira_deadlines(hours_ahead)
            deadlines.extend(jira_tasks)
        
        # Fetch from Trello
        if self.config.get("scan_trello"):
            trello_tasks = await self._fetch_trello_deadlines(hours_ahead)
            deadlines.extend(trello_tasks)
        
        # Fetch from Asana
        if self.config.get("scan_asana"):
            asana_tasks = await self._fetch_asana_deadlines(hours_ahead)
            deadlines.extend(asana_tasks)
        
        # Add urgency levels
        for deadline in deadlines:
            due_date = deadline.get("due_date")
            if isinstance(due_date, str):
                due_date = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
            
            hours_left = (due_date - now).total_seconds() / 3600
            deadline["hours_remaining"] = max(0, hours_left)
            deadline["urgency"] = self._get_urgency(hours_left)
        
        # Sort by urgency (most urgent first)
        deadlines.sort(key=lambda x: x.get("hours_remaining", 999))
        
        return deadlines
    
    async def _fetch_jira_deadlines(self, hours_ahead: int) -> List[Dict]:
        """Fetch deadlines from Jira."""
        # In production, this would use the JiraService via MCP
        # For demo, return mock data
        return [
            {
                "id": "PROJ-123",
                "title": "Complete API documentation",
                "source": "jira",
                "due_date": (datetime.utcnow() + timedelta(hours=12)).isoformat(),
                "project": "Backend",
                "priority": "High"
            },
            {
                "id": "PROJ-456",
                "title": "Review PR for auth module",
                "source": "jira",
                "due_date": (datetime.utcnow() + timedelta(hours=36)).isoformat(),
                "project": "Backend",
                "priority": "Medium"
            }
        ]
    
    async def _fetch_trello_deadlines(self, hours_ahead: int) -> List[Dict]:
        """Fetch deadlines from Trello."""
        return [
            {
                "id": "trello-001",
                "title": "Update marketing slides",
                "source": "trello",
                "due_date": (datetime.utcnow() + timedelta(hours=48)).isoformat(),
                "board": "Marketing",
                "priority": "Medium"
            }
        ]
    
    async def _fetch_asana_deadlines(self, hours_ahead: int) -> List[Dict]:
        """Fetch deadlines from Asana."""
        return []  # No mock data for Asana
    
    def _get_urgency(self, hours_remaining: float) -> Dict[str, Any]:
        """Determine urgency level based on hours remaining."""
        for threshold, urgency in sorted(self.URGENCY_LEVELS.items()):
            if hours_remaining <= threshold:
                return {
                    **urgency,
                    "hours_remaining": round(hours_remaining, 1)
                }
        
        return {
            "level": "future",
            "emoji": "📆",
            "color": "gray",
            "hours_remaining": round(hours_remaining, 1)
        }
    
    async def suggest_time_blocks(
        self,
        task_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Suggest time blocks to complete urgent tasks.
        
        Args:
            task_id: Optional specific task to suggest time for
        
        Returns:
            List of suggested time blocks
        """
        # In production, this would check the user's calendar for free slots
        now = datetime.utcnow()
        
        suggestions = [
            {
                "start": (now + timedelta(hours=2)).isoformat(),
                "end": (now + timedelta(hours=4)).isoformat(),
                "label": "This afternoon",
                "available": True
            },
            {
                "start": (now + timedelta(days=1, hours=9)).isoformat(),
                "end": (now + timedelta(days=1, hours=11)).isoformat(),
                "label": "Tomorrow morning",
                "available": True
            },
            {
                "start": (now + timedelta(days=1, hours=14)).isoformat(),
                "end": (now + timedelta(days=1, hours=16)).isoformat(),
                "label": "Tomorrow afternoon",
                "available": True
            }
        ]
        
        return suggestions
    
    def _format_deadline_report(self, deadlines: List[Dict]) -> str:
        """Format the deadline report for display."""
        if not deadlines:
            return "✨ No upcoming deadlines! Enjoy your free time."
        
        lines = [f"⏰ **Deadline Report** ({len(deadlines)} items)", ""]
        
        # Group by urgency
        for deadline in deadlines[:10]:
            urgency = deadline.get("urgency", {})
            emoji = urgency.get("emoji", "📅")
            level = urgency.get("level", "unknown")
            hours = deadline.get("hours_remaining", 0)
            
            if hours < 24:
                time_str = f"{int(hours)}h remaining"
            else:
                time_str = f"{int(hours / 24)}d remaining"
            
            lines.append(
                f"{emoji} **{deadline.get('title')}** [{level.upper()}]"
            )
            lines.append(
                f"   {deadline.get('source').capitalize()} | {time_str}"
            )
            lines.append("")
        
        if len(deadlines) > 10:
            lines.append(f"...and {len(deadlines) - 10} more tasks")
        
        return "\n".join(lines)
    
    def _format_time_suggestions(self, suggestions: List[Dict]) -> str:
        """Format time suggestions for display."""
        if not suggestions:
            return "No available time slots found. Consider rescheduling some meetings."
        
        lines = ["📅 **Available Time Blocks:**", ""]
        
        for i, slot in enumerate(suggestions, 1):
            lines.append(f"{i}. {slot.get('label')}")
        
        lines.append("")
        lines.append("Reply with a number to create a focus block.")
        
        return "\n".join(lines)
    
    async def run_scheduled(self) -> Dict[str, Any]:
        """
        Run scheduled deadline check and send alerts.
        
        Returns:
            Summary of alerts sent
        """
        results = {
            "critical_alerts": 0,
            "high_alerts": 0,
            "medium_alerts": 0,
            "total_tasks": 0
        }
        
        deadlines = await self.check_upcoming_deadlines()
        results["total_tasks"] = len(deadlines)
        
        for deadline in deadlines:
            urgency = deadline.get("urgency", {})
            level = urgency.get("level")
            
            if level == "critical":
                results["critical_alerts"] += 1
                # Send immediate alert
                await self._send_alert(deadline, "critical")
            elif level == "high":
                results["high_alerts"] += 1
                await self._send_alert(deadline, "high")
            elif level == "medium":
                results["medium_alerts"] += 1
        
        return results
    
    async def _send_alert(
        self,
        deadline: Dict[str, Any],
        urgency: str
    ) -> None:
        """Send a deadline alert to the user."""
        # In production, this would send via email/Slack
        logger.info(
            f"Sending {urgency} alert for: {deadline.get('title')}"
        )
