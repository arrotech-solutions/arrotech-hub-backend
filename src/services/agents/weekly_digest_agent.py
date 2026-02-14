"""
Weekly Digest Agent - Generates comprehensive weekly productivity summaries.

This agent compiles all user activity into a polished weekly digest
with insights, patterns, and AI-generated narrative summaries.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from .base_agent import BaseAgent
from ...models import User
from ..productivity_service import productivity_service, ActivityType

logger = logging.getLogger(__name__)


class WeeklyDigestAgent(BaseAgent):
    """
    Agent that generates weekly productivity digests.
    
    Triggers:
        - Every Friday at 5 PM (configurable)
        - Manual trigger from AgentHub
    
    Actions:
        - Aggregate stats: emails, meetings, tasks
        - Calculate productivity score
        - Identify patterns (most productive day, peak hours)
        - Generate AI narrative summary
        - Send digest email/Slack message
    """
    
    AGENT_ID = "weekly_digest"
    AGENT_NAME = "Weekly Digest"
    AGENT_DESCRIPTION = "Delivers a comprehensive weekly productivity summary every Friday"
    AGENT_ICON = "📊"
    
    DEFAULT_CONFIG = {
        "send_day": "friday",  # Day to send digest
        "send_hour": 17,  # Hour (24h format) to send
        "include_comparison": True,
        "include_patterns": True,
        "include_ai_insights": True,
        "notification_channel": "email",
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
        """Process a digest-related request."""
        try:
            intent = await self.classify_intent(message)
            
            if intent.get("intent") == "generate_digest":
                digest = await self.generate_weekly_digest()
                return {
                    "success": True,
                    "response": self._format_digest(digest),
                    "data": digest
                }
            elif intent.get("intent") == "preview_digest":
                preview = await self.preview_digest()
                return {
                    "success": True,
                    "response": preview,
                    "data": {}
                }
            else:
                return {
                    "success": True,
                    "response": "I create weekly productivity digests. Say 'generate digest' to create one now or 'preview' to see a sample."
                }
        except Exception as e:
            logger.error(f"Weekly digest error: {e}")
            return {
                "success": False,
                "error": str(e),
                "response": "I encountered an error generating your digest."
            }
    
    async def classify_intent(self, message: str) -> Dict[str, Any]:
        """Classify the user's intent."""
        message_lower = message.lower()
        
        if "generate" in message_lower or "create" in message_lower:
            return {"intent": "generate_digest"}
        elif "preview" in message_lower or "sample" in message_lower:
            return {"intent": "preview_digest"}
        else:
            return {"intent": "unknown"}
    
    async def generate_weekly_digest(
        self,
        week_start: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Generate a comprehensive weekly digest.
        
        Args:
            week_start: Start of the week to summarize (defaults to current week)
        
        Returns:
            Dict with complete digest data
        """
        if week_start is None:
            today = datetime.utcnow()
            week_start = today - timedelta(days=today.weekday())
        
        week_end = week_start + timedelta(days=6)
        
        # Gather all metrics
        digest = {
            "period": {
                "start": week_start.strftime("%Y-%m-%d"),
                "end": week_end.strftime("%Y-%m-%d"),
                "week_number": week_start.isocalendar()[1]
            },
            "generated_at": datetime.utcnow().isoformat(),
            "stats": await self._gather_weekly_stats(week_start),
            "productivity_score": await self._calculate_weekly_score(week_start),
            "patterns": await self._analyze_patterns(week_start),
            "comparison": await self._get_week_comparison(week_start),
            "highlights": [],
            "areas_for_improvement": [],
            "ai_summary": ""
        }
        
        # Generate highlights and improvements
        digest["highlights"] = self._identify_highlights(digest)
        digest["areas_for_improvement"] = self._identify_improvements(digest)
        
        # Generate AI narrative summary
        if self.config.get("include_ai_insights"):
            digest["ai_summary"] = await self._generate_ai_summary(digest)
        
        return digest
    
    async def _gather_weekly_stats(
        self,
        week_start: datetime
    ) -> Dict[str, Any]:
        """Gather all activity stats for the week."""
        # In production, this would aggregate from various sources
        return {
            "emails": {
                "sent": 45,
                "received": 127,
                "processed": 98,
                "response_time_avg_hours": 4.2
            },
            "meetings": {
                "attended": 12,
                "hours_total": 9.5,
                "organized": 3,
                "declined": 2
            },
            "tasks": {
                "completed": 23,
                "created": 18,
                "overdue": 2,
                "completion_rate": 0.85
            },
            "focus_time": {
                "hours": 8.5,
                "sessions": 6,
                "avg_session_length": 1.4
            },
            "messages": {
                "slack_sent": 67,
                "teams_sent": 12,
                "mentions_responded": 15
            }
        }
    
    async def _calculate_weekly_score(
        self,
        week_start: datetime
    ) -> Dict[str, Any]:
        """Calculate the weekly productivity score."""
        # Use productivity service
        weekly = await productivity_service.calculate_weekly_score(
            self.user.id,
            week_start
        )
        
        return {
            "score": weekly.get("average_score", 75),
            "trend": "up" if weekly.get("average_score", 0) > 70 else "stable",
            "best_day": weekly.get("best_day", {}).get("date", "Wednesday"),
            "daily_scores": [s.get("score", 0) for s in weekly.get("daily_scores", [])]
        }
    
    async def _analyze_patterns(
        self,
        week_start: datetime
    ) -> Dict[str, Any]:
        """Analyze productivity patterns for the week."""
        return {
            "most_productive_day": "Tuesday",
            "peak_hours": [9, 10, 14, 15],  # Most active hours
            "meeting_heavy_day": "Wednesday",
            "focus_day": "Friday",
            "email_peak_day": "Monday",
            "common_distractions": ["Slack notifications", "Unscheduled meetings"]
        }
    
    async def _get_week_comparison(
        self,
        week_start: datetime
    ) -> Dict[str, Any]:
        """Compare this week to previous week."""
        if not self.config.get("include_comparison"):
            return {}
        
        return {
            "emails_change": +12,
            "meetings_change": -2,
            "tasks_change": +5,
            "score_change": +8,
            "focus_time_change": +1.5,
            "overall_trend": "improving"
        }
    
    def _identify_highlights(self, digest: Dict) -> List[str]:
        """Identify positive highlights from the week."""
        highlights = []
        stats = digest.get("stats", {})
        
        # Check task completion
        tasks = stats.get("tasks", {})
        if tasks.get("completion_rate", 0) >= 0.8:
            highlights.append(f"💪 Completed {tasks.get('completed', 0)} tasks with {int(tasks.get('completion_rate', 0) * 100)}% completion rate!")
        
        # Check focus time
        focus = stats.get("focus_time", {})
        if focus.get("hours", 0) >= 6:
            highlights.append(f"🎯 Logged {focus.get('hours', 0)} hours of focused deep work")
        
        # Check email processing
        emails = stats.get("emails", {})
        if emails.get("processed", 0) > emails.get("received", 0) * 0.75:
            highlights.append("📧 Kept inbox under control - processed most incoming emails")
        
        # Check productivity score
        score = digest.get("productivity_score", {}).get("score", 0)
        if score >= 80:
            highlights.append(f"🌟 Achieved an excellent productivity score of {score}!")
        
        return highlights if highlights else ["Keep up the good work!"]
    
    def _identify_improvements(self, digest: Dict) -> List[str]:
        """Identify areas for improvement."""
        improvements = []
        stats = digest.get("stats", {})
        
        # Check overdue tasks
        tasks = stats.get("tasks", {})
        if tasks.get("overdue", 0) > 0:
            improvements.append(f"⏰ {tasks.get('overdue')} overdue task(s) need attention")
        
        # Check meeting load
        meetings = stats.get("meetings", {})
        if meetings.get("hours_total", 0) > 10:
            improvements.append("📅 Consider reducing meeting time - over 10 hours this week")
        
        # Check focus time
        focus = stats.get("focus_time", {})
        if focus.get("hours", 0) < 5:
            improvements.append("🎯 Try to schedule more focus time blocks")
        
        # Check email response time
        emails = stats.get("emails", {})
        if emails.get("response_time_avg_hours", 0) > 8:
            improvements.append("✉️ Email response time is high - consider processing more frequently")
        
        return improvements if improvements else ["You're doing great! No major areas to improve."]
    
    async def _generate_ai_summary(self, digest: Dict) -> str:
        """Generate an AI-powered narrative summary."""
        stats = digest.get("stats", {})
        score = digest.get("productivity_score", {}).get("score", 0)
        highlights = digest.get("highlights", [])
        
        # Build context for LLM
        context = f"""
Week: {digest['period']['start']} to {digest['period']['end']}
Productivity Score: {score}/100
Emails Processed: {stats.get('emails', {}).get('processed', 0)}
Tasks Completed: {stats.get('tasks', {}).get('completed', 0)}
Meetings: {stats.get('meetings', {}).get('attended', 0)}
Focus Time: {stats.get('focus_time', {}).get('hours', 0)} hours
Highlights: {', '.join(highlights)}
"""
        
        prompt = f"""Write a brief, encouraging 2-3 sentence summary of this person's week based on their productivity data:

{context}

Be specific but concise. Mention their strongest achievement and one area to focus on next week."""

        summary = await self.get_llm_response([
            {"role": "system", "content": "You are a supportive productivity coach writing weekly summaries. Be encouraging and specific."},
            {"role": "user", "content": prompt}
        ])
        
        return summary
    
    async def preview_digest(self) -> str:
        """Generate a preview/sample digest."""
        return """📊 **Weekly Productivity Digest Preview**

This is a sample of what your weekly digest will look like!

**Your Week at a Glance:**
• 📧 45 emails sent, 98 processed
• ✅ 23 tasks completed (85% rate)
• 📅 12 meetings attended
• 🎯 8.5 hours of focus time

**Productivity Score: 82/100** ⬆️ +8 from last week

**Highlights:**
• 💪 Completed 23 tasks with 85% completion rate!
• 🎯 Logged 8.5 hours of focused deep work

**AI Insight:**
You had a productive week! Your task completion rate was excellent, and you maintained good focus time. Consider blocking more time for deep work next week.

---
_Digests are sent every Friday at 5 PM_"""
    
    def _format_digest(self, digest: Dict) -> str:
        """Format the full digest for display."""
        period = digest.get("period", {})
        stats = digest.get("stats", {})
        score = digest.get("productivity_score", {})
        comparison = digest.get("comparison", {})
        
        lines = [
            f"📊 **Weekly Productivity Digest**",
            f"_Week of {period.get('start')} to {period.get('end')}_",
            "",
            "---",
            "",
            "**📈 Your Week at a Glance:**",
            f"• 📧 {stats.get('emails', {}).get('sent', 0)} emails sent, {stats.get('emails', {}).get('processed', 0)} processed",
            f"• ✅ {stats.get('tasks', {}).get('completed', 0)} tasks completed ({int(stats.get('tasks', {}).get('completion_rate', 0) * 100)}% rate)",
            f"• 📅 {stats.get('meetings', {}).get('attended', 0)} meetings attended ({stats.get('meetings', {}).get('hours_total', 0)}h)",
            f"• 🎯 {stats.get('focus_time', {}).get('hours', 0)}h of focus time",
            "",
        ]
        
        # Score section
        score_val = score.get("score", 0)
        change = comparison.get("score_change", 0)
        change_str = f"⬆️ +{change}" if change > 0 else f"⬇️ {change}" if change < 0 else "➡️"
        lines.append(f"**🏆 Productivity Score: {score_val}/100** {change_str}")
        lines.append("")
        
        # Highlights
        lines.append("**✨ Highlights:**")
        for highlight in digest.get("highlights", [])[:3]:
            lines.append(f"• {highlight}")
        lines.append("")
        
        # Areas for improvement
        improvements = digest.get("areas_for_improvement", [])
        if improvements:
            lines.append("**🔧 Areas to Improve:**")
            for imp in improvements[:2]:
                lines.append(f"• {imp}")
            lines.append("")
        
        # AI Summary
        if digest.get("ai_summary"):
            lines.append("**🤖 AI Insight:**")
            lines.append(digest["ai_summary"])
        
        return "\n".join(lines)
    
    async def run_scheduled(self) -> Dict[str, Any]:
        """
        Run scheduled digest generation.
        
        Returns:
            Summary of digest sent
        """
        now = datetime.utcnow()
        
        # Check if it's the right day and time
        day_name = now.strftime("%A").lower()
        if day_name != self.config.get("send_day", "friday"):
            return {"skipped": True, "reason": f"Not {self.config['send_day']}"}
        
        if now.hour != self.config.get("send_hour", 17):
            return {"skipped": True, "reason": f"Not {self.config['send_hour']}:00"}
        
        # Generate and send digest
        digest = await self.generate_weekly_digest()
        
        # In production, send via email/Slack
        logger.info(f"Sending weekly digest to user {self.user.id}")
        
        return {
            "success": True,
            "digest_generated": True,
            "score": digest.get("productivity_score", {}).get("score", 0),
            "sent_to": self.config.get("notification_channel", "email")
        }
