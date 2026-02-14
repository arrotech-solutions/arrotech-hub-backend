"""
Follow-Up Agent - Tracks action items and sends reminders for missed follow-ups.

This agent monitors communications for commitments and ensures users
follow through on their promises and action items.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from .base_agent import BaseAgent
from ...models import User

logger = logging.getLogger(__name__)


class FollowUpAgent(BaseAgent):
    """
    Agent that tracks action items and sends follow-up reminders.
    
    Triggers:
        - Daily scan at 9 AM
        - After each meeting ends
    
    Actions:
        - Scan meeting notes for action items
        - Track open commitments
        - Send reminders after 24-48 hours of inactivity
        - Mark as complete when action is detected
    """
    
    AGENT_ID = "follow_up"
    AGENT_NAME = "Follow-Up Agent"
    AGENT_DESCRIPTION = "Tracks your commitments and reminds you to follow up"
    AGENT_ICON = "🔔"
    
    DEFAULT_CONFIG = {
        "reminder_delay_hours": 24,  # Hours before first reminder
        "max_reminders": 3,
        "scan_emails": True,
        "scan_slack": True,
        "scan_meetings": True,
        "notification_channel": "email",
    }
    
    # Patterns that indicate commitments
    COMMITMENT_PATTERNS = [
        r"I'll send you",
        r"I will send",
        r"Let me get back to you",
        r"I'll follow up",
        r"I will follow up",
        r"Let's schedule",
        r"I'll schedule",
        r"I will share",
        r"I'll share",
        r"I'll connect you",
        r"I will connect",
        r"I'll loop in",
        r"Let me check",
        r"I'll look into",
        r"action item",
        r"TODO",
        r"to-do",
    ]
    
    def __init__(self, user: User, db: AsyncSession, config: Optional[Dict] = None):
        super().__init__(user, db)
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
        self._pending_followups: List[Dict] = []  # In-memory storage for demo
    
    async def process_message(
        self,
        message: str,
        channel: str,
        slack_user_id: str
    ) -> Dict[str, Any]:
        """Process a request related to follow-ups."""
        try:
            intent = await self.classify_intent(message)
            
            if intent.get("intent") == "list_followups":
                followups = await self.get_pending_followups()
                return {
                    "success": True,
                    "response": self._format_followups_list(followups),
                    "data": {"followups": followups}
                }
            elif intent.get("intent") == "complete_followup":
                result = await self.mark_complete(intent.get("parameters", {}).get("id"))
                return {
                    "success": True,
                    "response": "Marked as complete! ✅",
                    "data": result
                }
            elif intent.get("intent") == "scan_content":
                found = await self.scan_for_commitments(message)
                return {
                    "success": True,
                    "response": f"Found {len(found)} potential commitments.",
                    "data": {"commitments": found}
                }
            else:
                return {
                    "success": True,
                    "response": "I track your commitments and remind you to follow up. Say 'list followups' to see pending items."
                }
        except Exception as e:
            logger.error(f"Follow-up error: {e}")
            return {
                "success": False,
                "error": str(e),
                "response": "I encountered an error processing your request."
            }
    
    async def classify_intent(self, message: str) -> Dict[str, Any]:
        """Classify the user's intent."""
        message_lower = message.lower()
        
        if "list" in message_lower and "followup" in message_lower:
            return {"intent": "list_followups"}
        elif "complete" in message_lower or "done" in message_lower:
            return {"intent": "complete_followup", "parameters": {"id": None}}
        elif "scan" in message_lower:
            return {"intent": "scan_content"}
        else:
            return {"intent": "unknown"}
    
    async def scan_for_commitments(
        self,
        content: str,
        source: str = "unknown",
        context: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        """
        Scan content for commitments and action items.
        
        Args:
            content: Text content to scan
            source: Where the content came from (email, slack, meeting)
            context: Additional context (sender, date, etc.)
        
        Returns:
            List of detected commitments
        """
        commitments = []
        
        for pattern in self.COMMITMENT_PATTERNS:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                # Extract surrounding context
                start = max(0, match.start() - 50)
                end = min(len(content), match.end() + 100)
                snippet = content[start:end].strip()
                
                commitment = {
                    "id": f"fu_{datetime.utcnow().timestamp()}_{len(commitments)}",
                    "pattern_matched": pattern,
                    "snippet": snippet,
                    "source": source,
                    "context": context or {},
                    "detected_at": datetime.utcnow().isoformat(),
                    "status": "pending",
                    "reminder_count": 0,
                    "due_date": (datetime.utcnow() + timedelta(
                        hours=self.config.get("reminder_delay_hours", 24)
                    )).isoformat()
                }
                commitments.append(commitment)
                self._pending_followups.append(commitment)
        
        return commitments
    
    async def get_pending_followups(self) -> List[Dict[str, Any]]:
        """
        Get all pending follow-ups.
        
        Returns:
            List of pending follow-up items
        """
        return [f for f in self._pending_followups if f.get("status") == "pending"]
    
    async def get_overdue_followups(self) -> List[Dict[str, Any]]:
        """
        Get follow-ups that are overdue for reminders.
        
        Returns:
            List of overdue follow-up items
        """
        now = datetime.utcnow()
        overdue = []
        
        for followup in self._pending_followups:
            if followup.get("status") != "pending":
                continue
            
            due_date = datetime.fromisoformat(followup.get("due_date", now.isoformat()))
            if now >= due_date:
                max_reminders = self.config.get("max_reminders", 3)
                if followup.get("reminder_count", 0) < max_reminders:
                    overdue.append(followup)
        
        return overdue
    
    async def mark_complete(
        self,
        followup_id: str
    ) -> Dict[str, Any]:
        """
        Mark a follow-up as complete.
        
        Args:
            followup_id: ID of the follow-up to mark complete
        
        Returns:
            Updated follow-up data
        """
        for followup in self._pending_followups:
            if followup.get("id") == followup_id:
                followup["status"] = "completed"
                followup["completed_at"] = datetime.utcnow().isoformat()
                return followup
        
        return {"error": "Follow-up not found"}
    
    async def send_reminder(
        self,
        followup: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send a reminder for a follow-up item.
        
        Args:
            followup: The follow-up item to remind about
        
        Returns:
            Reminder result
        """
        # Increment reminder count
        followup["reminder_count"] = followup.get("reminder_count", 0) + 1
        followup["last_reminder"] = datetime.utcnow().isoformat()
        
        # Set next due date
        followup["due_date"] = (datetime.utcnow() + timedelta(
            hours=self.config.get("reminder_delay_hours", 24)
        )).isoformat()
        
        # Format reminder message
        message = self._format_reminder(followup)
        
        # In production, this would send via email/Slack
        logger.info(f"Sending reminder: {message}")
        
        return {
            "success": True,
            "message": message,
            "followup_id": followup.get("id"),
            "reminder_number": followup.get("reminder_count")
        }
    
    def _format_reminder(self, followup: Dict[str, Any]) -> str:
        """Format a reminder message."""
        snippet = followup.get("snippet", "")[:100]
        source = followup.get("source", "unknown")
        days_ago = (datetime.utcnow() - datetime.fromisoformat(
            followup.get("detected_at", datetime.utcnow().isoformat())
        )).days
        
        return f"""🔔 **Follow-Up Reminder**

You made a commitment {days_ago} day(s) ago:
> "{snippet}..."

Source: {source}
Reminder #{followup.get('reminder_count', 1)}

Reply with "done" to mark as complete, or take action now!"""
    
    def _format_followups_list(self, followups: List[Dict]) -> str:
        """Format the follow-ups list for display."""
        if not followups:
            return "✨ No pending follow-ups! You're all caught up."
        
        lines = [f"📋 **Pending Follow-Ups** ({len(followups)}):", ""]
        
        for i, fu in enumerate(followups[:10], 1):
            snippet = fu.get("snippet", "")[:60]
            source = fu.get("source", "unknown")
            lines.append(f"{i}. {snippet}... ({source})")
        
        if len(followups) > 10:
            lines.append(f"\n...and {len(followups) - 10} more")
        
        return "\n".join(lines)
    
    async def run_scheduled(self) -> Dict[str, Any]:
        """
        Run scheduled follow-up checks and reminders.
        
        Returns:
            Summary of actions taken
        """
        results = {
            "reminders_sent": 0,
            "new_commitments": 0,
            "completed": 0
        }
        
        # Check for overdue follow-ups
        overdue = await self.get_overdue_followups()
        
        for followup in overdue:
            reminder_result = await self.send_reminder(followup)
            if reminder_result.get("success"):
                results["reminders_sent"] += 1
        
        # In production, also scan recent emails/Slack for new commitments
        
        return results
