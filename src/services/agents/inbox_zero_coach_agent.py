"""
Inbox Zero Coach Agent - Helps users achieve and maintain a clean inbox.

This agent provides coaching, suggestions, and celebration when users
work towards Inbox Zero across their email and messaging platforms.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from .base_agent import BaseAgent
from ...models import User

logger = logging.getLogger(__name__)


class InboxZeroCoachAgent(BaseAgent):
    """
    Agent that coaches users towards Inbox Zero.
    
    Triggers:
        - Hourly scan during work hours
        - Manual trigger from AgentHub
    
    Actions:
        - Identify emails older than 3 days without action
        - Suggest quick replies or archive actions
        - Track inbox count trends
        - Celebrate milestones
    """
    
    AGENT_ID = "inbox_zero_coach"
    AGENT_NAME = "Inbox Zero Coach"
    AGENT_DESCRIPTION = "Your personal coach for achieving and maintaining Inbox Zero"
    AGENT_ICON = "📭"
    
    DEFAULT_CONFIG = {
        "stale_email_days": 3,  # Days before email is considered stale
        "scan_interval_hours": 1,
        "work_hours_start": 9,
        "work_hours_end": 18,
        "celebrate_milestones": True,
        "quick_reply_suggestions": True,
        "notification_channel": "slack",
    }
    
    MILESTONES = [
        {"count": 0, "name": "Inbox Zero! 🎉", "message": "You did it! Inbox Zero achieved!"},
        {"count": 5, "name": "Almost There! ✨", "message": "Only 5 emails left! You're so close!"},
        {"count": 10, "name": "Getting Clean! 🧹", "message": "Down to 10! Keep going!"},
        {"count": 25, "name": "Making Progress! 📉", "message": "25 emails remaining. Great progress!"},
    ]
    
    def __init__(self, user: User, db: AsyncSession, config: Optional[Dict] = None):
        super().__init__(user, db)
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
        self._inbox_history: List[Dict] = []  # Track inbox counts over time
    
    async def process_message(
        self,
        message: str,
        channel: str,
        slack_user_id: str
    ) -> Dict[str, Any]:
        """Process a coaching-related request."""
        try:
            intent = await self.classify_intent(message)
            
            if intent.get("intent") == "inbox_status":
                status = await self.get_inbox_status()
                return {
                    "success": True,
                    "response": self._format_status_report(status),
                    "data": status
                }
            elif intent.get("intent") == "get_suggestions":
                suggestions = await self.get_action_suggestions()
                return {
                    "success": True,
                    "response": self._format_suggestions(suggestions),
                    "data": {"suggestions": suggestions}
                }
            elif intent.get("intent") == "quick_actions":
                stale = await self.get_stale_emails()
                return {
                    "success": True,
                    "response": self._format_stale_emails(stale),
                    "data": {"stale_emails": stale}
                }
            else:
                return {
                    "success": True,
                    "response": "I'm your Inbox Zero coach! Say 'inbox status' to check your progress or 'suggestions' for tips."
                }
        except Exception as e:
            logger.error(f"Inbox coach error: {e}")
            return {
                "success": False,
                "error": str(e),
                "response": "I encountered an error. Let's try again!"
            }
    
    async def classify_intent(self, message: str) -> Dict[str, Any]:
        """Classify the user's intent."""
        message_lower = message.lower()
        
        if "status" in message_lower or "count" in message_lower:
            return {"intent": "inbox_status"}
        elif "suggest" in message_lower or "tip" in message_lower:
            return {"intent": "get_suggestions"}
        elif "stale" in message_lower or "old" in message_lower:
            return {"intent": "quick_actions"}
        else:
            return {"intent": "unknown"}
    
    async def get_inbox_status(self) -> Dict[str, Any]:
        """
        Get current inbox status across all platforms.
        
        Returns:
            Dict with inbox counts and trends
        """
        # In production, this would query Gmail/Outlook via MCP
        # For demo, use mock data
        status = {
            "gmail": {
                "unread": 12,
                "total": 45,
                "starred": 5
            },
            "outlook": {
                "unread": 3,
                "total": 18,
                "flagged": 2
            },
            "slack": {
                "unread_channels": 3,
                "unread_dms": 2,
                "mentions": 4
            }
        }
        
        total_emails = status["gmail"]["total"] + status["outlook"]["total"]
        total_unread = status["gmail"]["unread"] + status["outlook"]["unread"]
        
        # Calculate trend
        trend = self._calculate_trend(total_emails)
        
        # Check for milestone
        milestone = self._check_milestone(total_emails)
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "platforms": status,
            "total_emails": total_emails,
            "total_unread": total_unread,
            "trend": trend,
            "milestone": milestone,
            "inbox_zero": total_emails == 0
        }
    
    async def get_stale_emails(self) -> List[Dict[str, Any]]:
        """
        Get emails that have been sitting without action.
        
        Returns:
            List of stale emails with suggested actions
        """
        stale_days = self.config.get("stale_email_days", 3)
        cutoff = datetime.utcnow() - timedelta(days=stale_days)
        
        # Mock stale emails - in production, query Gmail/Outlook
        stale_emails = [
            {
                "id": "email_001",
                "subject": "Weekly newsletter from TechCrunch",
                "from": "newsletter@techcrunch.com",
                "received": (datetime.utcnow() - timedelta(days=5)).isoformat(),
                "suggested_action": "archive",
                "reason": "Newsletter - likely doesn't need response"
            },
            {
                "id": "email_002",
                "subject": "Re: Quick question about the project",
                "from": "colleague@company.com",
                "received": (datetime.utcnow() - timedelta(days=4)).isoformat(),
                "suggested_action": "reply",
                "reason": "From colleague, might need quick response"
            },
            {
                "id": "email_003",
                "subject": "Your order has shipped!",
                "from": "orders@amazon.com",
                "received": (datetime.utcnow() - timedelta(days=7)).isoformat(),
                "suggested_action": "archive",
                "reason": "Order notification - likely no action needed"
            }
        ]
        
        return stale_emails
    
    async def get_action_suggestions(self) -> List[Dict[str, str]]:
        """
        Get coaching suggestions for reducing inbox.
        
        Returns:
            List of actionable suggestions
        """
        status = await self.get_inbox_status()
        total = status.get("total_emails", 0)
        
        suggestions = []
        
        if total > 50:
            suggestions.append({
                "tip": "Bulk archive old newsletters",
                "action": "Search for 'unsubscribe' and archive all",
                "impact": "Could clear 10-20 emails quickly"
            })
        
        if total > 20:
            suggestions.append({
                "tip": "Use the 2-minute rule",
                "action": "If it takes <2 min to respond, do it now",
                "impact": "Quick wins build momentum"
            })
        
        suggestions.append({
            "tip": "Process in batches",
            "action": "Set 3 specific times to check email daily",
            "impact": "Reduces context switching"
        })
        
        suggestions.append({
            "tip": "Unsubscribe ruthlessly",
            "action": "Unsubscribe from anything you haven't read in 2 weeks",
            "impact": "Reduces future inbox load"
        })
        
        return suggestions
    
    async def generate_quick_reply(
        self,
        email: Dict[str, Any]
    ) -> List[str]:
        """
        Generate quick reply suggestions for an email.
        
        Args:
            email: Email data including subject and content
        
        Returns:
            List of suggested quick replies
        """
        # In production, use LLM to generate context-aware replies
        return [
            "Thanks for the update! I'll review and get back to you.",
            "Got it, thanks!",
            "Let me check on this and follow up tomorrow.",
        ]
    
    def _calculate_trend(self, current_count: int) -> Dict[str, Any]:
        """Calculate inbox trend based on history."""
        self._inbox_history.append({
            "count": current_count,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Keep last 24 data points
        self._inbox_history = self._inbox_history[-24:]
        
        if len(self._inbox_history) < 2:
            return {"direction": "stable", "change": 0}
        
        previous = self._inbox_history[-2]["count"]
        change = current_count - previous
        
        if change < 0:
            direction = "down"
        elif change > 0:
            direction = "up"
        else:
            direction = "stable"
        
        return {
            "direction": direction,
            "change": change,
            "previous": previous,
            "current": current_count
        }
    
    def _check_milestone(self, count: int) -> Optional[Dict[str, str]]:
        """Check if user has reached a milestone."""
        for milestone in self.MILESTONES:
            if count <= milestone["count"]:
                return milestone
        return None
    
    def _format_status_report(self, status: Dict) -> str:
        """Format the inbox status report."""
        total = status.get("total_emails", 0)
        unread = status.get("total_unread", 0)
        trend = status.get("trend", {})
        milestone = status.get("milestone")
        
        lines = [
            "📬 **Inbox Status Report**",
            "",
            f"**Total Emails:** {total}",
            f"**Unread:** {unread}",
            ""
        ]
        
        # Trend indicator
        direction = trend.get("direction", "stable")
        change = trend.get("change", 0)
        if direction == "down":
            lines.append(f"📉 Great! Down {abs(change)} since last check!")
        elif direction == "up":
            lines.append(f"📈 Up {change} since last check - time to process!")
        else:
            lines.append("➡️ Holding steady")
        
        # Milestone celebration
        if milestone:
            lines.append("")
            lines.append(f"🏆 **{milestone['name']}**")
            lines.append(milestone['message'])
        
        return "\n".join(lines)
    
    def _format_suggestions(self, suggestions: List[Dict]) -> str:
        """Format coaching suggestions."""
        lines = ["💡 **Inbox Zero Tips:**", ""]
        
        for i, tip in enumerate(suggestions, 1):
            lines.append(f"**{i}. {tip['tip']}**")
            lines.append(f"   → {tip['action']}")
            lines.append(f"   _{tip['impact']}_")
            lines.append("")
        
        return "\n".join(lines)
    
    def _format_stale_emails(self, emails: List[Dict]) -> str:
        """Format stale emails report."""
        if not emails:
            return "✨ No stale emails! Your inbox is fresh."
        
        lines = [
            f"📧 **{len(emails)} Stale Emails** (>{self.config.get('stale_email_days', 3)} days old)",
            ""
        ]
        
        for email in emails[:5]:
            action = email.get("suggested_action", "review")
            emoji = "📥" if action == "archive" else "✉️"
            lines.append(f"{emoji} **{email['subject'][:40]}...**")
            lines.append(f"   From: {email['from']}")
            lines.append(f"   Suggestion: {action.capitalize()} - {email['reason']}")
            lines.append("")
        
        return "\n".join(lines)
    
    async def run_scheduled(self) -> Dict[str, Any]:
        """
        Run scheduled inbox coaching.
        
        Returns:
            Summary of coaching actions
        """
        now = datetime.utcnow()
        current_hour = now.hour
        
        # Only run during work hours
        if not (self.config["work_hours_start"] <= current_hour < self.config["work_hours_end"]):
            return {"skipped": True, "reason": "Outside work hours"}
        
        status = await self.get_inbox_status()
        results = {
            "total_emails": status.get("total_emails", 0),
            "milestone_reached": status.get("milestone") is not None,
            "inbox_zero": status.get("inbox_zero", False),
            "stale_emails_found": 0,
            "notifications_sent": 0
        }
        
        # Check for stale emails
        stale = await self.get_stale_emails()
        results["stale_emails_found"] = len(stale)
        
        # Send milestone notification if achieved
        if status.get("inbox_zero"):
            # Log to productivity service
            logger.info("User achieved Inbox Zero!")
            results["notifications_sent"] += 1
        elif len(stale) > 5:
            # Nudge user about stale emails
            logger.info(f"User has {len(stale)} stale emails")
            results["notifications_sent"] += 1
        
        return results
