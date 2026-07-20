"""
Agent Context — Living documentation injected into every agent session.

Implements the AGENTS.md pattern from OpenAI's Harness Engineering:
machine-readable context that helps agents understand their environment,
capabilities, constraints, and lessons learned from past executions.

The context is dynamically assembled per session and includes:
- Platform capabilities and tool inventory summary
- User's subscription tier and feature access
- Known tool quirks and workarounds
- Recent error patterns and mitigations
- Behavioral guidelines and constraints

Stored in Redis with a 24-hour TTL, rebuilt on cache miss.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default context sections that apply to all agents
BASE_CONTEXT = """
## Platform Rules
- Always use the tool API to perform actions. Never fabricate or simulate results.
- If a tool fails, explain the error to the user and suggest alternatives.
- For write operations (send, create, update, delete), confirm the action with the user before executing unless they explicitly asked for it.
- Respect subscription tier limits. If a feature is blocked, explain why and suggest upgrading.
- Never expose API keys, tokens, or credentials in responses.
- Use Code Mode (execute_python_code) for multi-step operations that combine 3+ tools.

## Response Quality
- Be concise but complete. Don't pad responses with unnecessary caveats.
- When presenting data from tools, format it clearly (tables, bullet points).
- Include specific numbers and details from tool results, not vague summaries.
- If you used tools, briefly mention what you did (e.g., "I checked your Slack channels and found...").

## Error Handling
- If a tool returns an error, try to fix the arguments and retry (up to 3 times).
- If a connection/auth error occurs, tell the user to reconnect via the Connections page.
- For rate limit errors, wait and retry or inform the user.
- Never silently ignore errors — always communicate issues to the user.
"""

# Known tool-specific quirks and workarounds
TOOL_QUIRKS = {
    "hubspot_search": "Requires at least 3 characters for search queries. Empty/short queries will fail.",
    "slack_send_message": "Channel must be specified as channel name (e.g., '#general') or channel ID.",
    "gmail_send": "Recipients must be valid email addresses. CC and BCC are optional.",
    "calendar_create": "Time must be in ISO 8601 format. Always include timezone.",
    "maps.geocode": "Provide as specific an address as possible for accurate results.",
    "web_search": "Results are from DuckDuckGo. For recent events, add the year to the query.",
    "knowledge_base_query": "The knowledge_base_id parameter is required. Check user's KBs first.",
}

# Subscription tier descriptions
TIER_DESCRIPTIONS = {
    "free": "Free tier: 50 AI messages/day, 3 connections, read-only operations (no sending/creating).",
    "pro": "Pro tier: 1,000 AI messages/day, 15 connections, full read/write, Code Mode enabled.",
    "enterprise": "Enterprise tier: Unlimited AI messages, unlimited connections, full access, white-label.",
}


class AgentContext:
    """
    Manages the AGENTS.md equivalent — living documentation for agents.
    
    Assembles a context document that is injected into the system prompt
    for every agent session. The document adapts to:
    - The user's subscription tier and connections
    - Recent error patterns
    - Tool-specific quirks relevant to the user's integrations
    """
    
    def __init__(self):
        self._lessons_cache: Dict[str, List[Dict[str, Any]]] = {}
    
    async def get_context(
        self,
        user: Any,
        conversation_type: str = "chat",
        connected_platforms: Optional[List[str]] = None,
        recent_errors: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Build the agent context document for this session.
        
        Args:
            user: User object with subscription_tier, id, etc.
            conversation_type: "chat", "whatsapp_agent", "telegram_agent", "workflow"
            connected_platforms: List of platform names the user has connected
            recent_errors: Recent error patterns from FeedbackLoop
            
        Returns:
            A string to inject into the system prompt
        """
        sections = []
        
        # 1. Session info
        tier = getattr(user, 'subscription_tier', 'free')
        tier_desc = TIER_DESCRIPTIONS.get(tier, TIER_DESCRIPTIONS["free"])
        sections.append(f"## Session\n- User tier: {tier}\n- {tier_desc}")
        
        # 2. Base rules
        sections.append(BASE_CONTEXT.strip())
        
        # 3. Connected platforms and relevant quirks
        if connected_platforms:
            platform_list = ", ".join(connected_platforms)
            sections.append(f"## Connected Integrations\n{platform_list}")
            
            # Add relevant quirks
            relevant_quirks = []
            for platform in connected_platforms:
                for tool_name, quirk in TOOL_QUIRKS.items():
                    if platform in tool_name or tool_name.startswith(platform):
                        relevant_quirks.append(f"- **{tool_name}**: {quirk}")
            
            if relevant_quirks:
                sections.append("## Tool Notes\n" + "\n".join(relevant_quirks))
        
        # 4. Recent error patterns (from feedback loops)
        if recent_errors:
            error_notes = []
            for error in recent_errors[:5]:  # Top 5 patterns
                tool = error.get("tool_name", "unknown")
                category = error.get("category", "unknown")
                count = error.get("count", 1)
                if count >= 3:
                    error_notes.append(
                        f"- ⚠️ {tool}: Recurring {category} errors ({count} times recently). "
                        "Consider alternative approaches."
                    )
            
            if error_notes:
                sections.append("## Known Issues\n" + "\n".join(error_notes))
        
        # 5. Conversation type-specific context
        if conversation_type == "whatsapp_agent":
            sections.append(
                "## WhatsApp Agent Mode\n"
                "- You are operating as a WhatsApp business agent.\n"
                "- Keep responses short and mobile-friendly.\n"
                "- Use product cards for product displays.\n"
                "- Support M-Pesa payments for East African customers."
            )
        elif conversation_type == "telegram_agent":
            sections.append(
                "## Telegram Agent Mode\n"
                "- You are operating as a Telegram bot.\n"
                "- Keep responses concise.\n"
                "- Use inline keyboards for interactive choices."
            )
        elif conversation_type == "conversational_agent":
            sections.append(
                "## Conversational Agent Mode\n"
                "- You are operating as a business ordering agent on a messaging platform.\n"
                "- Keep responses short and mobile-friendly (under 200 words).\n"
                "- Use display_product_cards for product displays — never plain text lists.\n"
                "- Always search the knowledge base before answering product questions.\n"
                "- Collect customer details (name, phone) before creating orders.\n"
                "- Offer M-Pesa payment after order creation for East African customers.\n"
                "- If a tool fails, explain the issue simply and suggest alternatives.\n"
                "- Never expose internal system errors to the customer."
            )
        elif conversation_type == "autonomous_agent":
            sections.append(
                "## Autonomous Agent Mode\n"
                "- You are running as a scheduled autonomous agent.\n"
                "- Produce structured, actionable output.\n"
                "- Be thorough — there is no user to ask for clarification.\n"
                "- If a data source is unavailable, report what you could not access."
            )
        elif conversation_type == "workflow":
            sections.append(
                "## Workflow Execution Mode\n"
                "- You are executing a step within an automated workflow.\n"
                "- Follow the workflow step instructions precisely.\n"
                "- Return structured data that downstream steps can consume."
            )
        
        # 6. Code Mode instructions (if applicable)
        if tier in ("pro", "enterprise"):
            sections.append(
                "## Code Mode Available\n"
                "For complex multi-step tasks, you can use execute_python_code to write "
                "and run Python code that orchestrates multiple tools in a single step. "
                "The sandbox provides typed API classes for each connected platform."
            )
        
        # 7. Learned lessons
        user_id = str(getattr(user, 'id', 'unknown'))
        lessons = self._lessons_cache.get(user_id, [])
        if lessons:
            lesson_notes = [f"- {l['content']}" for l in lessons[-5:]]
            sections.append("## Learned Preferences\n" + "\n".join(lesson_notes))
        
        return "\n\n".join(sections)
    
    async def record_lesson(
        self,
        user_id: str,
        lesson_type: str,
        lesson_content: str,
        tool_name: Optional[str] = None,
    ):
        """
        Record a lesson learned from agent execution.
        
        These lessons accumulate over time and are injected into future sessions,
        creating a continuously improving agent experience.
        
        Args:
            user_id: User identifier
            lesson_type: Type of lesson ("preference", "quirk", "workaround")
            lesson_content: The lesson text
            tool_name: Optional associated tool
        """
        if user_id not in self._lessons_cache:
            self._lessons_cache[user_id] = []
        
        self._lessons_cache[user_id].append({
            "type": lesson_type,
            "content": lesson_content,
            "tool_name": tool_name,
            "timestamp": time.time(),
        })
        
        # Keep only last 50 lessons per user
        if len(self._lessons_cache[user_id]) > 50:
            self._lessons_cache[user_id] = self._lessons_cache[user_id][-50:]
        
        logger.info(f"Recorded lesson for user {user_id}: {lesson_content[:100]}")
    
    async def get_connected_platforms(self, user: Any, db: Any) -> List[str]:
        """Fetch user's connected platform names from the database."""
        try:
            from sqlalchemy import select
            from ...models import Connection, ConnectionStatus
            
            stmt = select(Connection.platform).where(
                Connection.user_id == user.id,
                Connection.status == ConnectionStatus.CONNECTED
            )
            result = await db.execute(stmt)
            return [row[0] for row in result.fetchall()]
        except Exception as e:
            logger.warning(f"Failed to fetch connected platforms: {e}")
            return []


# Module-level singleton
agent_context = AgentContext()
