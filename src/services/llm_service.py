"""
LLM Service for handling chat completions and tool calling.
Supports multiple LLM providers with a unified interface.
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import aiohttp
import openai
from openai import AsyncOpenAI

# Try to import Google Generative AI
try:
    import google.generativeai as genai
    from google.generativeai import AsyncGenerativeModel
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    genai = None
    AsyncGenerativeModel = None

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from LLM service."""
    content: str
    tokens_used: Optional[int] = None
    tools_called: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> LLMResponse:
        """Generate chat completion."""
        pass


class OpenAIProvider(LLMProvider):
    """OpenAI GPT provider."""

    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> LLMResponse:
        try:
            model = getattr(settings, 'OPENAI_MODEL', 'gpt-4o')
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }

            if max_tokens:
                kwargs["max_tokens"] = max_tokens

            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = await self.client.chat.completions.create(**kwargs)

            content = response.choices[0].message.content or ""
            tools_called = []

            if response.choices[0].message.tool_calls:
                for tool_call in response.choices[0].message.tool_calls:
                    tools_called.append({
                        "name": tool_call.function.name,
                        "arguments": json.loads(tool_call.function.arguments)
                    })

            return LLMResponse(
                content=content,
                tokens_used=response.usage.total_tokens if response.usage else None,
                tools_called=tools_called
            )

        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return LLMResponse(content="", error=str(e))


class GeminiProvider(LLMProvider):
    """Google Gemini provider."""

    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.model = AsyncGenerativeModel('gemini-pro')

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> LLMResponse:
        try:
            # Convert messages to Gemini format
            gemini_messages = []
            for msg in messages:
                if msg["role"] == "user":
                    gemini_messages.append(
                        {"role": "user", "parts": [msg["content"]]})
                elif msg["role"] == "assistant":
                    gemini_messages.append(
                        {"role": "model", "parts": [msg["content"]]})

            generation_config = {
                "temperature": temperature,
            }

            if max_tokens:
                generation_config["max_output_tokens"] = max_tokens

            response = await self.model.generate_content_async(
                gemini_messages,
                generation_config=generation_config
            )

            return LLMResponse(
                content=response.text,
                # Gemini doesn't provide token usage in the same way
                tokens_used=None
            )

        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return LLMResponse(content="", error=str(e))


class OllamaProvider(LLMProvider):
    """Ollama local provider (free)."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen3"):
        self.base_url = base_url
        self.model = model

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> LLMResponse:
        try:
            # Convert messages to Ollama format
            ollama_messages = []
            for msg in messages:
                if msg["role"] in ["user", "assistant"]:
                    ollama_messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })

            payload = {
                "model": self.model,
                "messages": ollama_messages,
                "stream": False,
                "options": {
                    "temperature": temperature
                }
            }

            if max_tokens:
                payload["options"]["num_predict"] = max_tokens

            # Make async request using aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    response.raise_for_status()
                    result = await response.json()

                    return LLMResponse(
                        content=result.get("message", {}).get("content", ""),
                        tokens_used=result.get("eval_count"),
                        # Ollama doesn't support tool calling natively
                        tools_called=None
                    )

        except Exception as e:
            logger.error(f"Ollama API error: {e}")
            return LLMResponse(content="", error=str(e))


class HuggingFaceProvider(LLMProvider):
    """Hugging Face Inference API provider."""

    def __init__(self, api_key: str, model: str = "meta-llama/Llama-2-7b-chat-hf"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api-inference.huggingface.co/models"

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> LLMResponse:
        try:
            # Convert to chat format
            chat_text = ""
            for msg in messages:
                if msg["role"] == "user":
                    chat_text += f"User: {msg['content']}\n"
                elif msg["role"] == "assistant":
                    chat_text += f"Assistant: {msg['content']}\n"

            chat_text += "Assistant: "

            payload = {
                "inputs": chat_text,
                "parameters": {
                    "temperature": temperature,
                    "max_new_tokens": max_tokens or 512,
                    "return_full_text": False
                }
            }

            headers = {"Authorization": f"Bearer {self.api_key}"}

            # Make async request using aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/{self.model}",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    response.raise_for_status()
                    result = await response.json()

                    content = result[0].get("generated_text", "") if isinstance(
                        result, list) else ""

                    return LLMResponse(
                        content=content,
                        # Hugging Face doesn't provide token usage
                        tokens_used=None,
                        # No tool calling support
                        tools_called=None
                    )

        except Exception as e:
            logger.error(f"Hugging Face API error: {e}")
            return LLMResponse(content="", error=str(e))


class TogetherAIProvider(LLMProvider):
    """Together AI provider (affordable)."""

    def __init__(self, api_key: str, model: str = "togethercomputer/llama-2-7b-chat"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.together.xyz/v1"

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> LLMResponse:
        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens or 512
            }

            headers = {"Authorization": f"Bearer {self.api_key}"}

            # Make async request using aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    response.raise_for_status()
                    result = await response.json()

                    content = result["choices"][0]["message"]["content"]
                    usage = result.get("usage", {})

                    return LLMResponse(
                        content=content,
                        tokens_used=usage.get("total_tokens"),
                        # Together AI doesn't support tool calling in the same way
                        tools_called=None
                    )

        except Exception as e:
            logger.error(f"Together AI API error: {e}")
            return LLMResponse(content="", error=str(e))


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.anthropic.com/v1"

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> LLMResponse:
        try:
            model = getattr(settings, 'ANTHROPIC_MODEL', 'claude-3-5-sonnet-20240620')
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens or 1024
            }

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01"
            }

            # Make async request using aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/messages",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    response.raise_for_status()
                    result = await response.json()

                    content = result["content"][0]["text"]

                    return LLMResponse(
                        content=content,
                        # Anthropic doesn't provide token usage in the same way
                        tokens_used=None,
                        # Tool calling support can be added here
                        tools_called=None
                    )

        except Exception as e:
            logger.error(f"Anthropic API error: {e}")
            return LLMResponse(content="", error=str(e))


class LLMService:
    """Main LLM service that manages different providers."""

    def __init__(self):
        self.providers: Dict[str, LLMProvider] = {}
        self.default_provider = "ollama"
        self._initialize_providers()

    def _initialize_providers(self):
        """Initialize available LLM providers."""
        # OpenAI
        if hasattr(settings, 'OPENAI_API_KEY') and settings.OPENAI_API_KEY:
            self.providers["openai"] = OpenAIProvider(settings.OPENAI_API_KEY)

        # Gemini
        if (hasattr(settings, 'GEMINI_API_KEY') and settings.GEMINI_API_KEY and
                GEMINI_AVAILABLE):
            try:
                self.providers["gemini"] = GeminiProvider(
                    settings.GEMINI_API_KEY)
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini provider: {e}")

        # Ollama (local, free)
        if hasattr(settings, 'OLLAMA_BASE_URL'):
            ollama_model = getattr(settings, 'OLLAMA_MODEL', 'qwen3')
            self.providers["ollama"] = OllamaProvider(
                base_url=getattr(settings, 'OLLAMA_BASE_URL',
                                 'http://localhost:11434'),
                model=ollama_model
            )

        # Hugging Face
        if hasattr(settings, 'HUGGINGFACE_API_KEY') and settings.HUGGINGFACE_API_KEY:
            hf_model = getattr(settings, 'HUGGINGFACE_MODEL',
                               'meta-llama/Llama-2-7b-chat-hf')
            self.providers["huggingface"] = HuggingFaceProvider(
                api_key=settings.HUGGINGFACE_API_KEY,
                model=hf_model
            )

        # Together AI
        if hasattr(settings, 'TOGETHER_API_KEY') and settings.TOGETHER_API_KEY:
            together_model = getattr(
                settings, 'TOGETHER_MODEL', 'togethercomputer/llama-2-7b-chat')
            self.providers["togetherai"] = TogetherAIProvider(
                api_key=settings.TOGETHER_API_KEY,
                model=together_model
            )

        # Anthropic
        if hasattr(settings, 'ANTHROPIC_API_KEY') and settings.ANTHROPIC_API_KEY:
            self.providers["anthropic"] = AnthropicProvider(
                settings.ANTHROPIC_API_KEY)

        # Set default provider from config
        if hasattr(settings, 'DEFAULT_LLM_PROVIDER'):
            self.default_provider = settings.DEFAULT_LLM_PROVIDER
        elif "ollama" in self.providers:
            self.default_provider = "ollama"
        elif self.providers:
            self.default_provider = list(self.providers.keys())[0]
        else:
            logger.warning("No LLM providers configured!")

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        provider: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> LLMResponse:
        """Generate chat completion using specified or default provider."""
        provider_name = provider or self.default_provider

        if provider_name not in self.providers:
            return LLMResponse(
                content="",
                error=f"Provider '{provider_name}' not available. Available: {list(self.providers.keys())}"
            )

        # Use config defaults if not specified
        if temperature is None:
            temperature = getattr(settings, 'LLM_TEMPERATURE', 0.7)
        if max_tokens is None:
            max_tokens = getattr(settings, 'LLM_MAX_TOKENS', None)

        return await self.providers[provider_name].chat_completion(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens
        )

    def get_available_providers(self) -> List[str]:
        """Get list of available LLM providers."""
        return list(self.providers.keys())

    def is_provider_available(self, provider: str) -> bool:
        """Check if a provider is available."""
        return provider in self.providers


# Global LLM service instance
llm_service = LLMService()
