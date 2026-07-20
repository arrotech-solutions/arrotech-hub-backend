"""
Base Agent Class — Foundation for all autonomous AI agents.

All autonomous agents (InboxZeroCoach, MeetingPrep, DeadlineGuardian, etc.)
inherit from this base class.

Integrates Harness Engineering via HarnessedExecutionMixin for:
- Agent context injection into system prompts
- Quality scoring on agent outputs
- Error feedback loops for self-correction
- Observability logging for all harness events

Future agents that extend BaseAgent get harness coverage automatically.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ..llm_service import LLMService

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Base class for all AI agents.

    Provides:
    - LLM access via self.llm_service
    - Harness Engineering via self._harness_* methods
    - Standard process_message / classify_intent interface
    """

    def __init__(self, user: User, db: AsyncSession):
        self.user = user
        self.db = db
        self.llm_service = LLMService()
        # Initialize harness
        self._init_harness_components()

    def _init_harness_components(self):
        """Initialize harness engineering components for this agent."""
        try:
            from ..harness.mixin import HarnessedExecutionMixin
            mixin = HarnessedExecutionMixin()
            mixin._init_harness("autonomous_agent")
            # Copy state
            self._harness_guardrails = mixin._harness_guardrails
            self._harness_feedback = mixin._harness_feedback
            self._harness_quality = mixin._harness_quality
            self._harness_context = mixin._harness_context
            self._harness_agent_type = mixin._harness_agent_type
            self._harness_turn_start = 0.0
            self._harness_tools_used = []
            # Bind methods
            self._harness_evaluate_response = mixin._harness_evaluate_response.__func__.__get__(self)
            self._harness_build_context = mixin._harness_build_context.__func__.__get__(self)
            self._harness_handle_tool_error = mixin._harness_handle_tool_error.__func__.__get__(self)
            self._harness_track_tool_call = mixin._harness_track_tool_call.__func__.__get__(self)
            self._harness_reset_turn = mixin._harness_reset_turn.__func__.__get__(self)
            self._harness_log_event = mixin._harness_log_event.__func__.__get__(self)
            self._harness_enabled = True
        except Exception as e:
            logger.warning(f"Harness init failed for agent (running without): {e}")
            self._harness_enabled = False

    @abstractmethod
    async def process_message(
        self,
        message: str,
        channel: str,
        slack_user_id: str
    ) -> Dict[str, Any]:
        """
        Process incoming message and return response.

        Args:
            message: The message text from Slack
            channel: The Slack channel ID
            slack_user_id: The Slack user ID who sent the message

        Returns:
            Dict with keys:
            - success: bool
            - response: str (message to send back)
            - data: Optional[Dict] (additional data)
            - error: Optional[str] (error message if failed)
        """
        pass

    @abstractmethod
    async def classify_intent(self, message: str) -> Dict[str, Any]:
        """
        Classify user intent from message.

        Args:
            message: The user's message

        Returns:
            Dict with intent classification results:
            - intent: str (intent type)
            - confidence: float (0.0-1.0)
            - parameters: Optional[Dict] (extracted parameters)
        """
        pass

    async def get_llm_response(
        self,
        messages: list,
        provider: str = "openai",
        temperature: float = 0.7
    ) -> str:
        """
        Get response from LLM with optional harness context injection.

        If harness is enabled, injects agent context into the system prompt
        and evaluates the response quality.
        """
        # Harness: inject context into system prompt
        if self._harness_enabled and messages:
            try:
                self._harness_reset_turn()
                context = await self._harness_build_context(
                    self.user, "autonomous_agent", self.db
                )
                if context and messages[0].get("role") == "system":
                    messages[0]["content"] += f"\n\n# Agent Context\n{context}"
            except Exception as e:
                logger.warning(f"Harness context injection failed: {e}")

        response = await self.llm_service.chat_completion(
            messages=messages,
            provider=provider,
            temperature=temperature
        )

        if response.error:
            logger.error(f"LLM error: {response.error}")
            # Harness: log LLM error
            if self._harness_enabled:
                self._harness_log_event("AGENT_LLM_ERROR", {
                    "error": str(response.error),
                    "agent_type": self._harness_agent_type,
                })
            return f"I encountered an error: {response.error}"

        result = response.content or "I'm sorry, I couldn't generate a response."

        # Harness: evaluate response quality
        if self._harness_enabled:
            try:
                quality = await self._harness_evaluate_response(
                    result, messages[-1].get("content", ""), iterations=1
                )
                if quality.warnings:
                    logger.info(
                        f"Agent quality score: {quality.overall_score:.2f} "
                        f"warnings: {quality.warnings}"
                    )
            except Exception as e:
                logger.warning(f"Quality gate failed: {e}")

        return result
