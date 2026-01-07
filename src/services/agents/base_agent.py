"""
Base Agent Class
All Slack-based AI agents inherit from this base class
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ..llm_service import LLMService

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base class for all AI agents that handle Slack messages."""

    def __init__(self, user: User, db: AsyncSession):
        self.user = user
        self.db = db
        self.llm_service = LLMService()

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
        Get response from LLM.

        Args:
            messages: List of message dicts with 'role' and 'content'
            provider: LLM provider to use
            temperature: Temperature for generation

        Returns:
            Response text from LLM
        """
        response = await self.llm_service.chat_completion(
            messages=messages,
            provider=provider,
            temperature=temperature
        )

        if response.error:
            logger.error(f"LLM error: {response.error}")
            return f"I encountered an error: {response.error}"

        return response.content or "I'm sorry, I couldn't generate a response."

