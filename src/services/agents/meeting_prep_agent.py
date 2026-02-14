"""
Meeting Prep Agent - Automatically prepares briefing materials before meetings.

This agent monitors the calendar and generates comprehensive meeting prep
documents including attendee context, recent interactions, and talking points.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from .base_agent import BaseAgent
from ...models import User
from ..llm_service import LLMService

logger = logging.getLogger(__name__)


class MeetingPrepAgent(BaseAgent):
    """
    Agent that automatically prepares meeting briefings.
    
    Triggers:
        - 30 minutes before any calendar event
        - On-demand via AgentHub
    
    Actions:
        - Fetch meeting attendees from calendar event
        - Search emails/Slack for recent conversations with attendees
        - Compile notes about the meeting topic
        - Generate AI summary and talking points
        - Send notification via email/Slack
    """
    
    AGENT_ID = "meeting_prep"
    AGENT_NAME = "Meeting Prep Agent"
    AGENT_DESCRIPTION = "Prepares comprehensive briefing materials before your meetings"
    AGENT_ICON = "📋"
    
    DEFAULT_CONFIG = {
        "prep_time_minutes": 30,  # How long before meeting to prepare
        "include_email_context": True,
        "include_slack_context": True,
        "include_linkedin_context": False,
        "max_context_items": 10,
        "notification_channel": "email",  # "email", "slack", or "both"
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
        """
        Process a request to prepare for a meeting.
        
        Args:
            message: The meeting details or request
            channel: Communication channel
            slack_user_id: User ID for notifications
        
        Returns:
            Dict with prep results
        """
        try:
            # Parse the meeting request
            intent = await self.classify_intent(message)
            
            if intent.get("intent") == "prepare_meeting":
                meeting_info = intent.get("parameters", {})
                prep = await self.prepare_for_meeting(meeting_info)
                return {
                    "success": True,
                    "response": self._format_prep_response(prep),
                    "data": prep
                }
            else:
                return {
                    "success": True,
                    "response": "I can help you prepare for meetings. Just tell me which meeting you'd like to prepare for."
                }
        except Exception as e:
            logger.error(f"Meeting prep error: {e}")
            return {
                "success": False,
                "error": str(e),
                "response": "I encountered an error while preparing your meeting brief."
            }
    
    async def classify_intent(self, message: str) -> Dict[str, Any]:
        """Classify the user's intent from message."""
        prompt = f"""Analyze this message and extract meeting preparation intent:
        
Message: {message}

Return JSON with:
- intent: "prepare_meeting" or "other"
- parameters: {{meeting_title, attendees, time, topic}}
"""
        
        response = await self.get_llm_response([
            {"role": "system", "content": "You are a meeting preparation assistant. Extract meeting details from user messages."},
            {"role": "user", "content": prompt}
        ])
        
        # Parse response (simplified for now)
        return {
            "intent": "prepare_meeting",
            "parameters": {"raw_message": message}
        }
    
    async def prepare_for_meeting(
        self,
        meeting_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Prepare comprehensive meeting brief.
        
        Args:
            meeting_info: Dict with meeting details (title, attendees, time, etc.)
        
        Returns:
            Dict with preparation materials
        """
        prep = {
            "meeting_title": meeting_info.get("title", "Upcoming Meeting"),
            "meeting_time": meeting_info.get("time", ""),
            "attendees": [],
            "context": [],
            "talking_points": [],
            "suggested_agenda": [],
            "action_items_from_previous": [],
            "prepared_at": datetime.utcnow().isoformat()
        }
        
        # Get attendee information
        attendees = meeting_info.get("attendees", [])
        for attendee in attendees:
            attendee_info = await self._get_attendee_context(attendee)
            prep["attendees"].append(attendee_info)
        
        # Get email context if enabled
        if self.config.get("include_email_context"):
            email_context = await self._get_email_context(meeting_info)
            prep["context"].extend(email_context)
        
        # Get Slack context if enabled
        if self.config.get("include_slack_context"):
            slack_context = await self._get_slack_context(meeting_info)
            prep["context"].extend(slack_context)
        
        # Generate talking points with AI
        talking_points = await self._generate_talking_points(prep)
        prep["talking_points"] = talking_points
        
        # Generate suggested agenda
        agenda = await self._generate_agenda(prep)
        prep["suggested_agenda"] = agenda
        
        return prep
    
    async def _get_attendee_context(self, attendee: str) -> Dict[str, Any]:
        """Get context about an attendee."""
        return {
            "name": attendee,
            "email": f"{attendee.lower().replace(' ', '.')}@company.com",
            "role": "Team Member",
            "last_interaction": "3 days ago",
            "recent_topics": ["Project update", "Timeline review"]
        }
    
    async def _get_email_context(
        self,
        meeting_info: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Get relevant email context for the meeting."""
        # In production, this would query Gmail/Outlook via MCP tools
        return [
            {
                "source": "email",
                "from": "attendee@company.com",
                "subject": f"Re: {meeting_info.get('title', 'Meeting')}",
                "snippet": "Looking forward to discussing the Q1 results...",
                "date": "2 days ago"
            }
        ]
    
    async def _get_slack_context(
        self,
        meeting_info: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Get relevant Slack context for the meeting."""
        # In production, this would query Slack via MCP tools
        return [
            {
                "source": "slack",
                "channel": "#project-updates",
                "snippet": "Quick update on the deliverables...",
                "date": "1 day ago"
            }
        ]
    
    async def _generate_talking_points(
        self,
        prep: Dict[str, Any]
    ) -> List[str]:
        """Generate AI-powered talking points."""
        context = prep.get("context", [])
        context_text = "\n".join([
            f"- {c.get('snippet', '')}" for c in context[:5]
        ])
        
        prompt = f"""Based on this meeting context, generate 3-5 key talking points:

Meeting: {prep.get('meeting_title')}
Attendees: {', '.join([a.get('name', '') for a in prep.get('attendees', [])])}

Recent Context:
{context_text}

Generate concise, actionable talking points."""

        response = await self.get_llm_response([
            {"role": "system", "content": "You are a meeting preparation expert. Generate clear, actionable talking points."},
            {"role": "user", "content": prompt}
        ])
        
        # Parse response into list
        points = response.strip().split("\n")
        return [p.strip("- •").strip() for p in points if p.strip()][:5]
    
    async def _generate_agenda(
        self,
        prep: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        """Generate a suggested meeting agenda."""
        return [
            {"time": "0-5 min", "item": "Welcome & quick updates"},
            {"time": "5-20 min", "item": "Main discussion points"},
            {"time": "20-25 min", "item": "Action items review"},
            {"time": "25-30 min", "item": "Next steps & wrap-up"}
        ]
    
    def _format_prep_response(self, prep: Dict[str, Any]) -> str:
        """Format the prep data into a readable message."""
        lines = [
            f"📋 **Meeting Prep: {prep.get('meeting_title')}**",
            "",
            "**Attendees:**"
        ]
        
        for attendee in prep.get("attendees", []):
            lines.append(f"• {attendee.get('name')} - {attendee.get('role')}")
        
        lines.append("")
        lines.append("**Key Talking Points:**")
        for point in prep.get("talking_points", []):
            lines.append(f"• {point}")
        
        lines.append("")
        lines.append("**Suggested Agenda:**")
        for item in prep.get("suggested_agenda", []):
            lines.append(f"• [{item.get('time')}] {item.get('item')}")
        
        return "\n".join(lines)
    
    async def run_scheduled(
        self,
        upcoming_meetings: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Run scheduled preparation for upcoming meetings.
        
        Args:
            upcoming_meetings: List of meetings happening soon
        
        Returns:
            List of preparation results
        """
        results = []
        prep_time = self.config.get("prep_time_minutes", 30)
        now = datetime.utcnow()
        
        for meeting in upcoming_meetings:
            meeting_time = meeting.get("start_time")
            if isinstance(meeting_time, str):
                meeting_time = datetime.fromisoformat(meeting_time)
            
            # Check if meeting is within prep window
            time_until = (meeting_time - now).total_seconds() / 60
            if 0 < time_until <= prep_time:
                prep = await self.prepare_for_meeting(meeting)
                results.append({
                    "meeting": meeting,
                    "prep": prep,
                    "sent_at": now.isoformat()
                })
        
        return results
