import json
import logging
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .coding_agent_registry import CODING_AGENT_TOOLS
from .dynamic_tool_registry import dynamic_tool_registry

logger = logging.getLogger(__name__)

class CodingAgentLLM:
    """
    Lightweight, non-blocking LLM orchestrator for the Coding Agent.
    
    Unlike the main ExecutionOrchestrator which loops on the backend,
    this service performs a single interaction with the LLM and returns
    either a text response or a list of tool calls for the frontend to execute.
    This enables the real-time, interactive UI.
    """
    
    def __init__(self, db: AsyncSession, user):
        self.db = db
        self.user = user

    def _get_coding_tools_openai_format(self) -> List[Dict[str, Any]]:
        """Extract the 24 coding tools and convert them to OpenAI format."""
        tools_list = list(CODING_AGENT_TOOLS.values())
        return dynamic_tool_registry.convert_tools_to_openai_format(tools_list)

    async def generate_response(
        self, 
        messages: List[Dict[str, Any]], 
        model_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send the conversation history to the LLM with coding tools injected.
        Returns a dictionary with 'type' (message or tool_calls) and the content/calls.
        """
        from ..config import settings
        from ..models import UserSettings

        # 1. Resolve API Key (Support BYOK)
        api_key = settings.OPENAI_API_KEY
        try:
            stmt = select(UserSettings).where(UserSettings.user_id == self.user.id)
            result = await self.db.execute(stmt)
            user_settings = result.scalar_one_or_none()
            if user_settings and user_settings.openai_api_key:
                api_key = user_settings.openai_api_key
        except Exception as e:
            logger.warning(f"Failed to fetch BYOK settings: {e}")

        if not api_key:
            return {
                "type": "error",
                "content": "No OpenAI API key found. Please configure one in your settings."
            }

        # 2. Get tools
        tools = self._get_coding_tools_openai_format()

        # 3. Call OpenAI
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key)
            model = model_override or getattr(settings, 'OPENAI_MODEL', 'gpt-4o')

            kwargs = {
                "model": model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
            }
            
            is_o_series = model.startswith(('o1', 'o3'))
            if not is_o_series:
                kwargs["temperature"] = settings.LLM_TEMPERATURE or 0.2 # Lower temp for coding
            
            if settings.LLM_MAX_TOKENS:
                if is_o_series:
                    kwargs["max_completion_tokens"] = settings.LLM_MAX_TOKENS
                else:
                    kwargs["max_tokens"] = settings.LLM_MAX_TOKENS

            response = await client.chat.completions.create(**kwargs)
            message = response.choices[0].message
            
            # 4. Process Response
            if message.tool_calls:
                tool_calls_formatted = []
                for tool_call in message.tool_calls:
                    # Safely parse JSON arguments
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                        
                    tool_calls_formatted.append({
                        "id": tool_call.id,
                        "tool": tool_call.function.name,
                        "args": args
                    })
                    
                return {
                    "type": "tool_calls",
                    "calls": tool_calls_formatted
                }
            else:
                return {
                    "type": "message",
                    "content": message.content or ""
                }

        except Exception as e:
            logger.error(f"OpenAI error in Coding Agent: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "type": "error",
                "content": f"Failed to connect to the AI provider: {str(e)}"
            }

coding_agent_llm_factory = CodingAgentLLM
