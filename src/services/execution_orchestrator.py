"""
Execution Orchestrator Service for coordinating intent processing, tool selection, and execution.
"""

import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Conversation, Message, MessageRole, MessageStatus, User
from .dynamic_tool_registry import dynamic_tool_registry
from .intent_processor import IntentProcessor
from .tool_executor import ToolExecutor, tool_executor
from .tool_validator import ToolArgumentValidator
from .tool_selector import ToolRouter
from .feature_flags import FeatureGate
# Note: get_or_create_usage_record imported lazily inside process_message() to avoid circular import
try:
    import tiktoken
except ImportError:
    tiktoken = None

logger = logging.getLogger(__name__)


class ExecutionOrchestrator:
    """Orchestrates the end-to-end execution of user requests with precision."""
    
    def __init__(self, db: AsyncSession, user: User, conversation_id: int):
        self.db = db
        self.user = user
        self.conversation_id = conversation_id
        self.tool_router = ToolRouter(user, db)
        self.intent_processor = IntentProcessor(user, db)

    @staticmethod
    async def get_daily_message_count(db: AsyncSession, user_id: int) -> int:
        """Get the number of AI messages sent by the user today."""
        from datetime import datetime, time
        from sqlalchemy import func, select
        
        today_start = datetime.combine(datetime.utcnow().date(), time.min)
        
        stmt = select(func.count(Message.id)).where(
            Message.conversation_id == Conversation.id,
            Conversation.user_id == user_id,
            Message.role == MessageRole.ASSISTANT,
            Message.created_at >= today_start
        )
        
        result = await db.execute(stmt)
        return result.scalar() or 0
    
    async def process_message(self, content: str, provider: str) -> Tuple[str, List[Dict[str, Any]], int]:
        """
        Process a user message with full orchestration.
        
        Args:
            content: User's message content
            provider: LLM provider to use
            
        Returns:
            Tuple of (response_content, tools_called, tokens_used)
        """
        try:
            print(f"🎯 Orchestrating message processing for: '{content[:50]}...'")
            
            # Step 0: Check AI message limits (skip for BYOK users)
            # If the user has their own API key for this provider, they shouldn't be rate-limited
            is_byok = False
            try:
                from sqlalchemy import select
                from ..models import UserSettings
                stmt = select(UserSettings).where(UserSettings.user_id == self.user.id)
                result = await self.db.execute(stmt)
                user_settings = result.scalar_one_or_none()
                if user_settings:
                    byok_keys = {
                        "openai": user_settings.openai_api_key,
                        "anthropic": user_settings.anthropic_api_key,
                        "gemini": getattr(user_settings, 'gemini_api_key', None),
                    }
                    is_byok = bool(byok_keys.get(provider))
                    if is_byok:
                        print(f"🔑 BYOK detected for provider '{provider}' - skipping rate limit")
            except Exception as e:
                logger.warning(f"Failed to check BYOK status: {e}")

            if not is_byok:
                daily_count = await self.get_daily_message_count(self.db, self.user.id)
                if not FeatureGate.can_use_ai_message(self.user, daily_count):
                    return f"Plan limit reached: Your {self.user.subscription_tier} plan allows {FeatureGate.get_limits(self.user.subscription_tier)['max_ai_messages_daily']} AI messages per day. Please upgrade to continue.", [], 0

            # Step 1: Classify intent
            intent_classifier = await self.intent_processor.classify_intent(content)
            print(f"🧠 Intent classified: {intent_classifier.intent_type} (confidence: {intent_classifier.confidence:.1%})")
            
            # Step 2: Determine if tools are needed
            if not intent_classifier.requires_tools:
                print(f"💬 No tools required - generating direct response")
                return await self._generate_direct_response(content, provider)
            
            # Step 3: Get relevant tools
            relevant_tools = await self.tool_router.get_relevant_tools(content)
            if not relevant_tools:
                print(f"⚠️ No relevant tools found - generating direct response")
                return await self._generate_direct_response(content, provider)
            
            print(f"🔧 Found {len(relevant_tools)} relevant tools")
            
            # Step 4: Execute with function calling loop
            # Convert tools to OpenAI format
            openai_tools = dynamic_tool_registry.convert_tools_to_openai_format(relevant_tools)
            
            print(f"🔧 Converted {len(openai_tools)} tools to OpenAI format:")
            for tool in openai_tools:
                print(f"  - {tool['function']['name']}: {tool['function']['description']}")

            # Get conversation context for the function calling loop
            from ..routers.chat_router import get_optimized_context
            context_messages = await get_optimized_context(self.conversation_id, self.db, user_message=content)
            
            # Prepare messages for LLM
            messages = []
            for msg in context_messages:
                if msg.role == MessageRole.USER:
                    messages.append({"role": "user", "content": msg.content})
                elif msg.role == MessageRole.ASSISTANT:
                    messages.append({"role": "assistant", "content": msg.content})
                elif msg.role == MessageRole.TOOL:
                    messages.append({"role": "tool", "content": msg.content, "tool_call_id": msg.tool_call_id})
            
            messages.append({"role": "user", "content": content})
            
              # Execute function calling loop
            response_content, tools_called, output_tokens = await self._execute_function_calling_loop(provider, messages, openai_tools)

            # ===== AI ACTION USAGE TRACKING =====
            # Increment AI action counter for this chat message
            try:
                # Lazy import to avoid circular dependency
                from ..routers.subscription_router import get_or_create_usage_record
                usage_record = await get_or_create_usage_record(self.db, self.user)
                # Check if at limit BEFORE incrementing (soft enforcement - user already got response)
                if usage_record.ai_actions_count >= usage_record.ai_actions_limit:
                    logger.warning(f"User {self.user.id} exceeded AI action limit: {usage_record.ai_actions_count}/{usage_record.ai_actions_limit}")
                # Increment counter
                usage_record.ai_actions_count += 1
                await self.db.commit()
                logger.info(f"AI action tracked: {usage_record.ai_actions_count}/{usage_record.ai_actions_limit}")
            except Exception as tracking_error:
                logger.error(f"Failed to track AI action: {tracking_error}")
            # ===== END USAGE TRACKING =====

            # Count input tokens
            from ..config import settings
            input_tokens = self._count_message_tokens(messages, getattr(settings, 'OPENAI_MODEL', 'gpt-4o'))
            
            # Return content, tools, and total tokens
            total_tokens = input_tokens + output_tokens
            return response_content, tools_called, total_tokens
            
        except Exception as e:
            print(f"❌ Error in process_message: {e}")
            import traceback
            print(f"❌ Traceback: {traceback.format_exc()}")
            
            # Return a helpful error message
            error_response = f"I apologize, but I encountered an issue processing your request: '{content[:100]}...'. Please try again or rephrase your question."
            return error_response, [], 0
    
    async def process_message_stream(
        self, 
        content: str, 
        provider: str,
        use_reasoning: bool = False,
        use_search: bool = False
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Process a user message and stream the response as SSE events.
        Includes support for extracting <think> tags for live reasoning streams.
        """
        import asyncio
        import re
        
        yield {"type": "thinking", "content": "Analyzing your request..."}
        
        try:
            # Step 1: Intent Classification
            intent_classifier = await self.intent_processor.classify_intent(content)
            
            # Step 2: Tool routing
            relevant_tools = []
            if intent_classifier.requires_tools:
                yield {"type": "thinking", "content": "Selecting tools..."}
                relevant_tools = await self.tool_router.get_relevant_tools(content)
                
            if use_search:
                yield {"type": "thinking", "content": "Injecting web search capabilities..."}
                search_tool = dynamic_tool_registry.base_tools.get("web_search")
                if search_tool and search_tool not in relevant_tools:
                    relevant_tools.append(search_tool)
                
            openai_tools = dynamic_tool_registry.convert_tools_to_openai_format(relevant_tools)
            
            # Model Routing for Reasoning
            model_override = None
            if use_reasoning:
                yield {"type": "thinking", "content": "Routing to reasoning model..."}
                if provider == "openai":
                    model_override = "o3-mini"
                elif provider == "anthropic":
                    model_override = "claude-3-7-sonnet"
                else:
                    model_override = "deepseek-r1" # Default local reasoning model
            
            from ..routers.chat_router import get_optimized_context
            context_messages = await get_optimized_context(self.conversation_id, self.db, user_message=content)
            
            messages = []
            for msg in context_messages:
                if msg.role == MessageRole.USER:
                    messages.append({"role": "user", "content": msg.content})
                elif msg.role == MessageRole.ASSISTANT:
                    messages.append({"role": "assistant", "content": msg.content})
                elif msg.role == MessageRole.TOOL:
                    messages.append({"role": "tool", "content": msg.content, "tool_call_id": msg.tool_call_id})
                    
            if use_search:
                messages.insert(0, {
                    "role": "system", 
                    "content": "IMPORTANT INSTRUCTION: The user has requested deep research. You MUST use the `web_search` tool to gather up-to-date and accurate information before answering. Formulate a search query, execute the tool, and base your entire response on the search results."
                })
                    
            messages.append({"role": "user", "content": content})
            
            yield {"type": "thinking", "content": "Generating response..."}
            
            # Run the existing synchronous function-calling loop
            final_content, tools_called, tokens_used = await self._execute_function_calling_loop(provider, messages, openai_tools, model_override=model_override)
            
            # Yield tools execution for the UI to display in real-time
            for i, tc in enumerate(tools_called):
                yield {
                    "type": "tool_start",
                    "tool": tc.get("name"),
                    "args": tc.get("arguments", {})
                }
                # Simulate a slight delay to trigger UI animations
                await asyncio.sleep(0.5)
                yield {
                    "type": "tool_result",
                    "tool": tc.get("name"),
                    "success": "error" not in tc.get("result", {}),
                    "summary": f"Executed {tc.get('name')}",
                    "args": tc.get("arguments", {})
                }
            
            # Simulate streaming the final response to decouple reasoning and content
            # Parse <think> tags if they exist (used by DeepSeek/o1 models)
            think_match = re.search(r'<think>(.*?)</think>', final_content, re.DOTALL)
            
            if think_match:
                think_content = think_match.group(1).strip()
                # Remove the think block from final content
                final_content = final_content.replace(think_match.group(0), "").strip()
                
                # Stream the reasoning chunk by chunk
                chunk_size = 20
                for i in range(0, len(think_content), chunk_size):
                    yield {"type": "reasoning_delta", "delta": think_content[i:i+chunk_size]}
                    await asyncio.sleep(0.01)
            
            # Stream the final text chunks
            chunk_size = 15
            for i in range(0, len(final_content), chunk_size):
                yield {"type": "content_delta", "delta": final_content[i:i+chunk_size]}
                await asyncio.sleep(0.01)
                
            yield {"type": "done", "tokens_used": tokens_used}
            
        except Exception as e:
            logger.error(f"Error in stream: {e}")
            yield {"type": "error", "error": str(e)}

    async def _generate_direct_response(self, content: str, provider: str) -> Tuple[str, List[Dict[str, Any]], int]:
        """Generate a direct response without tool usage."""
        # Get conversation context
        from ..routers.chat_router import get_optimized_context
        context_messages = await get_optimized_context(self.conversation_id, self.db, user_message=content)
        
        # Prepare messages for LLM
        messages = []
        for msg in context_messages:
            if msg.role == MessageRole.USER:
                messages.append({"role": "user", "content": msg.content})
            elif msg.role == MessageRole.ASSISTANT:
                messages.append({"role": "assistant", "content": msg.content})
            elif msg.role == MessageRole.TOOL:
                messages.append({"role": "tool", "content": msg.content, "tool_call_id": msg.tool_call_id})
        
        messages.append({"role": "user", "content": content})
        
        # Call LLM for direct response
        logger.error(f"BYOK_DEBUG: _generate_direct_response called with provider='{provider}', messages_count={len(messages)}")
        if provider == "ollama":
            response = await self._call_ollama_direct(messages)
        else:
            response = await self._call_llm_fallback(provider, messages)
        
        if response:
            # Check if the response is an error dict from the provider
            if isinstance(response, dict) and response.get('error'):
                error_msg = response.get('error_message', 'Unknown provider error')
                logger.error(f"BYOK_DEBUG: Provider returned error: {error_msg}")
                return f"⚠️ {error_msg}", [], 0
            
            assistant_message = response.get('choices', [{}])[0].get('message', {})
            resp_content = assistant_message.get('content', '')
            if resp_content:
                # Extract tokens
                usage = response.get('usage', {})
                total_tokens = usage.get('total_tokens', 0)
                return resp_content, [], total_tokens
        
        # BYOK Fallback: Try user's own API keys if primary provider failed
        logger.error(f"BYOK_DEBUG: Primary provider '{provider}' returned None, trying BYOK fallback...")
        last_error_msg = None
        try:
            from sqlalchemy import select
            from ..models import UserSettings
            stmt = select(UserSettings).where(UserSettings.user_id == self.user.id)
            result = await self.db.execute(stmt)
            user_settings = result.scalar_one_or_none()
            if user_settings:
                byok_providers = []
                if user_settings.anthropic_api_key:
                    byok_providers.append("anthropic")
                if user_settings.openai_api_key:
                    byok_providers.append("openai")
                if getattr(user_settings, 'gemini_api_key', None):
                    byok_providers.append("gemini")
                
                for byok_provider in byok_providers:
                    if byok_provider == provider:
                        continue  # Already tried this one
                    print(f"🔑 Trying BYOK fallback provider: {byok_provider}")
                    fallback_response = await self._call_llm_fallback(byok_provider, messages)
                    if fallback_response:
                        # Check for error dict
                        if isinstance(fallback_response, dict) and fallback_response.get('error'):
                            last_error_msg = fallback_response.get('error_message')
                            continue
                        assistant_message = fallback_response.get('choices', [{}])[0].get('message', {})
                        resp_content = assistant_message.get('content', '')
                        if resp_content:
                            usage = fallback_response.get('usage', {})
                            total_tokens = usage.get('total_tokens', 0)
                            print(f"✅ BYOK fallback succeeded with {byok_provider}")
                            return resp_content, [], total_tokens
        except Exception as byok_error:
            logger.warning(f"BYOK fallback failed: {byok_error}")
        
        # Final fallback response when no LLM is available
        print(f"⚠️ No LLM available (including BYOK), providing fallback response")
        if last_error_msg:
            return f"⚠️ {last_error_msg}", [], 0
        fallback_response = f"I'm unable to connect to any AI provider right now. Please check your API key settings or try selecting a different provider."
        return fallback_response, [], 0
    
    async def _execute_with_function_calling(self, content: str, provider: str, relevant_tools: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        """Execute using function calling loop with relevant tools."""
        # Convert tools to OpenAI format
        openai_tools = dynamic_tool_registry.convert_tools_to_openai_format(relevant_tools)
        
        print(f"🔧 Converted {len(openai_tools)} tools to OpenAI format:")
        for tool in openai_tools:
            print(f"  - {tool['function']['name']}: {tool['function']['description']}")
        
    async def _call_openai_with_functions(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] = None, model_override: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Call OpenAI API with function calling support."""
        from ..config import settings
        from sqlalchemy import select
        from ..models import UserSettings

        api_key = settings.OPENAI_API_KEY
        
        # BYOK: Check for user-provided API key
        try:
            stmt = select(UserSettings).where(UserSettings.user_id == self.user.id)
            result = await self.db.execute(stmt)
            user_settings = result.scalar_one_or_none()
            if user_settings and user_settings.openai_api_key:
                logger.info(f"Using BYOK for user {self.user.id}")
                api_key = user_settings.openai_api_key
        except Exception as e:
            logger.warning(f"Failed to fetch user settings: {e}")

        if not api_key:
            print("❌ OpenAI API key not configured")
            return None
        
        try:
            from openai import AsyncOpenAI
            
            client = AsyncOpenAI(api_key=api_key)
            
            # Build request parameters
            model = model_override or getattr(settings, 'OPENAI_MODEL', 'gpt-4o')
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": settings.LLM_TEMPERATURE or 0.7,
            }
            
            if settings.LLM_MAX_TOKENS:
                kwargs["max_tokens"] = settings.LLM_MAX_TOKENS
            
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            
            print(f"📤 Calling OpenAI with {len(messages)} messages and {len(tools) if tools else 0} tools")
            
            response = await client.chat.completions.create(**kwargs)
            
            # Convert response to dict format matching our expected structure
            message = response.choices[0].message
            
            # Capture usage if available
            usage = response.usage
            input_tokens = usage.prompt_tokens if usage else 0
            output_tokens = usage.completion_tokens if usage else 0
            logger.info(f"Token usage - Input: {input_tokens}, Output: {output_tokens}")
            
            result = {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": []
                    }
                }],
                "usage": {
                    "prompt_tokens": input_tokens,
                    "completion_tokens": output_tokens
                }
            }
            
            # Convert tool_calls to expected format
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    result["choices"][0]["message"]["tool_calls"].append({
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    })
            
            print(f"✅ OpenAI response received with {len(result['choices'][0]['message']['tool_calls'])} tool calls")
            return result
            
        except Exception as e:
            print(f"❌ OpenAI API error: {e}")
            import traceback
            print(f"❌ Traceback: {traceback.format_exc()}")
            return None

    def _count_message_tokens(self, messages: List[Dict[str, Any]], model: str = "gpt-4o") -> int:
        """Count tokens for a list of messages."""
        if not tiktoken:
            return 0
        
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
            
        num_tokens = 0
        for message in messages:
            num_tokens += 4  # every message follows <im_start>{role/name}\n{content}<im_end>\n
            for key, value in message.items():
                if key == "content" and value:
                    num_tokens += len(encoding.encode(value))
                if key == "name":
                    num_tokens += -1  # role is always required and always 1 token
        num_tokens += 2  # every reply is primed with <im_start>assistant
        return num_tokens
    
    async def _execute_function_calling_loop(self, provider: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]], max_iterations: int = 5, model_override: Optional[str] = None) -> Tuple[str, List[Dict[str, Any]], int]:
        """Execute function calling loop with validation and error handling."""
        tools_called = []
        total_output_tokens = 0
        
        for iteration in range(max_iterations):
            print(f"🔄 Function calling iteration {iteration + 1}/{max_iterations}")
            
            try:
                # Call LLM with tools
                if provider == "ollama":
                    response = await self._call_ollama_with_functions(messages, tools, model_override=model_override)
                else:
                    response = await self._call_llm_fallback(provider, messages, tools, model_override=model_override)
                
                if not response:
                    print(f"❌ No response from LLM in iteration {iteration + 1}")
                    break
                
                # Track tokens from response if available
                if "usage" in response:
                    total_output_tokens += response["usage"].get("completion_tokens", 0)

                print(f"📥 LLM Response: {json.dumps(response, indent=2)}")
                
                # Get assistant message
                assistant_message = response.get('choices', [{}])[0].get('message', {})
                content = assistant_message.get('content', '')
                tool_calls = assistant_message.get('tool_calls', [])
                
                print(f"💬 Assistant content: {content}")
                print(f"🔧 Tool calls: {len(tool_calls)}")
                
                # Fallback: If no tool_calls but content contains JSON, try to parse it
                if not tool_calls and content.strip().startswith('[') and content.strip().endswith(']'):
                    try:
                        print(f"🔄 Attempting to parse tool calls from content")
                        parsed_tool_calls = json.loads(content.strip())
                        if isinstance(parsed_tool_calls, list):
                            # Convert to proper tool_calls format
                            tool_calls = []
                            for i, tool_call in enumerate(parsed_tool_calls):
                                if isinstance(tool_call, dict) and 'name' in tool_call:
                                    tool_calls.append({
                                        'id': f'call_{i}',
                                        'type': 'function',
                                        'function': {
                                            'name': tool_call['name'],
                                            'arguments': json.dumps(tool_call.get('arguments', {}))
                                        }
                                    })
                            print(f"✅ Parsed {len(tool_calls)} tool calls from content")
                    except json.JSONDecodeError as e:
                        print(f"❌ Failed to parse tool calls from content: {e}")
                
                # Clean assistant message - remove empty tool_calls to avoid OpenAI API errors
                if 'tool_calls' in assistant_message and not assistant_message['tool_calls']:
                    del assistant_message['tool_calls']

                # Add assistant message to conversation
                messages.append(assistant_message)
                
                # If no tool calls, we're done
                if not tool_calls:
                    print(f"✅ No tool calls - final response generated")
                    return content, tools_called, total_output_tokens
                
                # Execute tool calls
                for tool_call in tool_calls:
                    tool_call_id = tool_call.get('id')
                    function_name = tool_call.get('function', {}).get('name', '')
                    arguments_str = tool_call.get('function', {}).get('arguments', '{}')
                    
                    print(f"🔧 Executing tool: {function_name} with args: {arguments_str}")
                    
                    try:
                        # Parse arguments
                        arguments = json.loads(arguments_str)
                        
                        # Validate arguments
                        is_valid, error_msg = ToolArgumentValidator.validate(function_name, arguments, tools)
                        
                        if not is_valid:
                            print(f"❌ Validation failed for {function_name}: {error_msg}")
                            # Self-Correction: Feed error back to LLM
                            messages.append({
                                "role": "tool",
                                "content": f"Error: Invalid arguments. {error_msg} Please fix the arguments and retry.",
                                "tool_call_id": tool_call_id
                            })
                            # Add to tools_called for tracking attempts
                            tools_called.append({
                                "name": function_name,
                                "arguments": arguments,
                                "result": {"error": error_msg}
                            })
                            continue

                        # Execute tool
                        tool_result = await tool_executor.execute_tool(
                            function_name, arguments, self.user, self.db, tools_called
                        )
                        
                        # Add to tools_called list
                        tools_called.append({
                            "name": function_name,
                            "arguments": arguments,
                            "result": tool_result
                        })
                        
                        # Add tool result to messages
                        messages.append({
                            "role": "tool",
                            "content": json.dumps(tool_result) if isinstance(tool_result, dict) else str(tool_result),
                            "tool_call_id": tool_call_id
                        })
                        
                        print(f"✅ Tool executed: {function_name}")
                    
                    except Exception as e:
                        print(f"❌ Error executing tool {function_name}: {e}")
                        # Add error to messages
                        messages.append({
                            "role": "tool",
                            "content": f"Error: {str(e)}",
                            "tool_call_id": tool_call_id
                        })
            
            except Exception as e:
                print(f"❌ Error in iteration {iteration + 1}: {e}")
                import traceback
                print(f"❌ Traceback: {traceback.format_exc()}")
                break
        
        # If we've exhausted iterations, return the last assistant message
        if messages:
            last_assistant = None
            for msg in reversed(messages):
                if msg.get("role") == "assistant":
                    last_assistant = msg
                    break
            
            if last_assistant:
                return last_assistant.get("content", ""), tools_called, total_output_tokens
        
        return "I apologize, but I encountered an issue processing your request. Please try again.", tools_called, total_output_tokens
    
    async def _call_ollama_direct(self, messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Call Ollama for direct response without function calling."""
        import os

        import aiohttp

        from ..config import settings
        
        ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        ollama_url = f"{ollama_base_url}/v1/chat/completions"
        
        # Check if Ollama is available
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{ollama_base_url}/api/tags", timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status != 200:
                        print(f"❌ Ollama not available (status {response.status})")
                        return None
        except Exception as e:
            print(f"❌ Ollama not available: {e}")
            return None
        
        # Try multiple models in order of preference
        models_to_try = [
            settings.OLLAMA_MODEL,  # Use configured model first
            "qwen3",  # Fallback to qwen3
            "mistral:latest",  # Fallback to mistral
            "llama3.1:8b"  # Final fallback
        ]
        
        for model in models_to_try:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": settings.LLM_TEMPERATURE,
                "max_tokens": settings.LLM_MAX_TOKENS or 1000,
                "stream": False
            }
            
            print(f"📤 Trying Ollama direct call with model '{model}'")
            
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        ollama_url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            print(f"✅ Ollama direct response received with model '{model}'")
                            return result
                        else:
                            error_text = await response.text()
                            print(f"❌ Ollama error {response.status} with model '{model}': {error_text}")
                            continue
            except Exception as e:
                print(f"❌ Error calling Ollama with model '{model}': {e}")
                continue
        
        print(f"❌ All models failed for direct response")
        return None
    
    async def _call_ollama_with_functions(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]], model_override: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Call Ollama with function calling support."""
        import os

        import aiohttp
        
        ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        ollama_url = f"{ollama_base_url}/v1/chat/completions"
        
        # Try different models in order of preference
        models_to_try = [model_override] if model_override else ["llama3.2:3b", "mistral:latest", "llama3.1:8b"]
        
        for model in models_to_try:
            payload = {
                "model": model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "temperature": 0.1,  # Lower temperature for more precise tool selection
                "max_tokens": 1000,
                "stream": False
            }
            
            print(f"📤 Trying model '{model}' with {len(tools)} tools:")
            for tool in tools:
                print(f"  - {tool['function']['name']}: {tool['function']['description']}")
            
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        ollama_url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            print(f"✅ Ollama response received with model '{model}'")
                            return result
                        else:
                            error_text = await response.text()
                            print(f"❌ Ollama error {response.status} with model '{model}': {error_text}")
                            continue
            except Exception as e:
                print(f"❌ Error calling Ollama with model '{model}': {e}")
                continue
        
        print(f"❌ All models failed for function calling")
        return None
    
    async def _call_llm_fallback(self, provider: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] = None, model_override: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Call LLM for providers like OpenAI, Anthropic, etc."""
        from ..config import settings
        
        if provider == "openai":
            return await self._call_openai_with_functions(messages, tools, model_override=model_override)
        elif provider == "anthropic":
            return await self._call_anthropic(messages, tools, model_override=model_override)
        elif provider == "gemini":
            return await self._call_gemini(messages, tools)
        elif provider == "huggingface":
            return await self._call_huggingface(messages, tools)
        elif provider == "together":
            return await self._call_together(messages, tools)
        
        # For unknown providers, return None
        print(f"⚠️ Unknown provider: {provider}")
        return None
    
    async def _call_openai_with_functions(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] = None, model_override: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Call OpenAI API with function calling support."""
        from ..config import settings
        from sqlalchemy import select
        from ..models import UserSettings

        api_key = settings.OPENAI_API_KEY
        
        # BYOK: Check for user-provided API key
        try:
            stmt = select(UserSettings).where(UserSettings.user_id == self.user.id)
            result = await self.db.execute(stmt)
            user_settings = result.scalar_one_or_none()
            if user_settings and user_settings.openai_api_key:
                logger.info(f"Using BYOK (OpenAI) for user {self.user.id}")
                api_key = user_settings.openai_api_key
        except Exception as e:
            logger.warning(f"Failed to fetch user settings for BYOK: {e}")

        if not api_key:
            print("❌ OpenAI API key not configured")
            return None
        
        try:
            import openai
            from openai import AsyncOpenAI
            
            client = AsyncOpenAI(api_key=api_key)
            
            # Build request parameters
            model = model_override or getattr(settings, 'OPENAI_MODEL', 'gpt-4o')
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": settings.LLM_TEMPERATURE or 0.7,
            }
            
            if settings.LLM_MAX_TOKENS:
                kwargs["max_tokens"] = settings.LLM_MAX_TOKENS
            
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            
            print(f"📤 Calling OpenAI with {len(messages)} messages and {len(tools) if tools else 0} tools")
            
            response = await client.chat.completions.create(**kwargs)
            
            # Convert response to dict format matching our expected structure
            message = response.choices[0].message
            
            result = {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": []
                    }
                }],
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }
            
            # Convert tool_calls to expected format
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    result["choices"][0]["message"]["tool_calls"].append({
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    })
            
            print(f"✅ OpenAI response received with {len(result['choices'][0]['message']['tool_calls'])} tool calls")
            return result
            
        except Exception as e:
            print(f"❌ OpenAI API error: {e}")
            import traceback
            print(f"❌ Traceback: {traceback.format_exc()}")
            return None
    
    async def _call_anthropic(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] = None, model_override: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Call Anthropic Claude API."""
        from ..config import settings
        from sqlalchemy import select
        from ..models import UserSettings

        logger.error(f"BYOK_DEBUG: _call_anthropic entered for user {self.user.id}")

        api_key = settings.ANTHROPIC_API_KEY
        user_settings = None
        
        # BYOK: Check for user-provided API key
        try:
            stmt = select(UserSettings).where(UserSettings.user_id == self.user.id)
            result = await self.db.execute(stmt)
            user_settings = result.scalar_one_or_none()
            logger.error(f"BYOK_DEBUG: UserSettings found: {user_settings is not None}, has anthropic key: {bool(user_settings and user_settings.anthropic_api_key) if user_settings else False}")
            if user_settings and user_settings.anthropic_api_key:
                logger.error(f"BYOK_DEBUG: Using BYOK (Anthropic) for user {self.user.id}")
                api_key = user_settings.anthropic_api_key
        except Exception as e:
            logger.error(f"BYOK_DEBUG: Failed to fetch user settings for BYOK: {e}")

        if not api_key:
            logger.error(f"BYOK_DEBUG: Anthropic - NO API key found (system key: {bool(settings.ANTHROPIC_API_KEY)}, user_settings found: {user_settings is not None}, user_settings has key: {bool(user_settings and user_settings.anthropic_api_key) if user_settings else 'N/A'})")
            return None
        
        logger.error(f"BYOK_DEBUG: Anthropic API key resolved (starts with: {api_key[:8]}..., length: {len(api_key)})")
        
        try:
            import aiohttp
            
            # Convert messages to Anthropic format
            anthropic_messages = []
            system_content = ""
            
            for msg in messages:
                if msg.get("role") == "system":
                    system_content = msg.get("content", "")
                elif msg.get("role") in ["user", "assistant"]:
                    anthropic_messages.append({
                        "role": msg["role"],
                        "content": msg.get("content", "")
                    })
            
            payload = {
                "model": "claude-sonnet-4-20250514",
                "messages": anthropic_messages,
                "max_tokens": settings.LLM_MAX_TOKENS or 1024,
                "temperature": settings.LLM_TEMPERATURE or 0.7,
            }
            
            if system_content:
                payload["system"] = system_content
            
            headers = {
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01"
            }
            
            print(f"📤 Calling Anthropic with {len(anthropic_messages)} messages")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.anthropic.com/v1/messages",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        content = result.get("content", [{}])[0].get("text", "")
                        
                        print(f"✅ Anthropic response received")
                        return {
                            "choices": [{
                                "message": {
                                    "role": "assistant",
                                    "content": content,
                                    "tool_calls": []
                                }
                            }]
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"BYOK_DEBUG: Anthropic API error response {response.status}: {error_text[:500]}")
                        # Parse the error message for user-friendly display
                        try:
                            import json as _json
                            error_data = _json.loads(error_text)
                            error_msg = error_data.get("error", {}).get("message", error_text)
                        except Exception:
                            error_msg = error_text
                        return {"error": True, "error_message": f"Anthropic API error: {error_msg}", "status": response.status}
                        
        except Exception as e:
            logger.error(f"BYOK_DEBUG: Anthropic API exception: {e}")
            import traceback
            logger.error(f"BYOK_DEBUG: Traceback: {traceback.format_exc()}")
            return {"error": True, "error_message": f"Failed to connect to Anthropic API: {str(e)}"}

    async def _call_gemini(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Call Google Gemini API."""
        from ..config import settings
        from sqlalchemy import select
        from ..models import UserSettings

        api_key = settings.GEMINI_API_KEY
        
        # BYOK: Check for user-provided API key
        try:
            stmt = select(UserSettings).where(UserSettings.user_id == self.user.id)
            result = await self.db.execute(stmt)
            user_settings = result.scalar_one_or_none()
            if user_settings and user_settings.gemini_api_key:
                logger.info(f"Using BYOK (Gemini) for user {self.user.id}")
                api_key = user_settings.gemini_api_key
        except Exception as e:
            logger.warning(f"Failed to fetch user settings for BYOK: {e}")

        if not api_key:
            print("❌ Gemini API key not configured")
            return None

        try:
            import aiohttp
            
            # Simple content generation for now
            last_message = messages[-1].get("content", "")
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            
            payload = {
                "contents": [{
                    "parts": [{"text": last_message}]
                }]
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        result = await response.json()
                        try:
                            content = result['candidates'][0]['content']['parts'][0]['text']
                            return {
                                "choices": [{
                                    "message": {
                                        "role": "assistant",
                                        "content": content,
                                        "tool_calls": []
                                    }
                                }]
                            }
                        except KeyError:
                            print(f"❌ Gemini response format error: {result}")
                            return None
                    else:
                        print(f"❌ Gemini error {response.status}: {await response.text()}")
                        return None
        except Exception as e:
            print(f"❌ Gemini API error: {e}")
            return None

    async def _call_huggingface(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Call Hugging Face Inference API."""
        from ..config import settings
        from sqlalchemy import select
        from ..models import UserSettings

        api_key = settings.HUGGINGFACE_API_KEY
        
        # BYOK: Check for user-provided API key
        try:
            stmt = select(UserSettings).where(UserSettings.user_id == self.user.id)
            result = await self.db.execute(stmt)
            user_settings = result.scalar_one_or_none()
            if user_settings and user_settings.huggingface_api_key:
                logger.info(f"Using BYOK (HuggingFace) for user {self.user.id}")
                api_key = user_settings.huggingface_api_key
        except Exception as e:
            logger.warning(f"Failed to fetch user settings for BYOK: {e}")

        if not api_key:
            print("❌ Hugging Face API key not configured")
            return None

        try:
            import aiohttp
            
            # Use a default model if not specified
            model = "mistralai/Mistral-7B-Instruct-v0.2"
            url = f"https://api-inference.huggingface.co/models/{model}"
            
            headers = {"Authorization": f"Bearer {api_key}"}
            last_message = messages[-1].get("content", "")
            
            # Simple text generation payload
            payload = {
                "inputs": last_message,
                "parameters": {"max_new_tokens": 512, "return_full_text": False}
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        result = await response.json()
                        # HF returns a list of objects with 'generated_text'
                        if isinstance(result, list) and len(result) > 0:
                            content = result[0].get('generated_text', '')
                            return {
                                "choices": [{
                                    "message": {
                                        "role": "assistant",
                                        "content": content,
                                        "tool_calls": []
                                    }
                                }]
                            }
                        return None
                    else:
                        print(f"❌ HuggingFace error {response.status}: {await response.text()}")
                        return None
        except Exception as e:
            print(f"❌ HuggingFace API error: {e}")
            return None

    async def _call_together(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Call Together AI API (OpenAI Compatible)."""
        from ..config import settings
        from sqlalchemy import select
        from ..models import UserSettings

        api_key = settings.TOGETHER_API_KEY
        
        # BYOK: Check for user-provided API key
        try:
            stmt = select(UserSettings).where(UserSettings.user_id == self.user.id)
            result = await self.db.execute(stmt)
            user_settings = result.scalar_one_or_none()
            if user_settings and user_settings.together_api_key:
                logger.info(f"Using BYOK (Together) for user {self.user.id}")
                api_key = user_settings.together_api_key
        except Exception as e:
            logger.warning(f"Failed to fetch user settings for BYOK: {e}")

        if not api_key:
            print("❌ Together API key not configured")
            return None

        try:
            # Together is OpenAI compatible
            from openai import AsyncOpenAI
            
            client = AsyncOpenAI(
                api_key=api_key,
                base_url="https://api.together.xyz/v1"
            )
            
            model = "meta-llama/Llama-3-8b-chat-hf"
            
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=1024,
                temperature=0.7
            )
            
            content = response.choices[0].message.content
            
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": content,
                        "tool_calls": []
                    }
                }]
            }
        except Exception as e:
            print(f"❌ Together API error: {e}")
            return None 

    # ==================== STREAMING METHODS ====================

    async def process_message_stream(
        self, 
        content: str, 
        provider: str,
        use_reasoning: bool = False,
        use_search: bool = False
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Process a user message and yield SSE events at each stage.
        
        Yields dicts like:
          {"type": "thinking", "content": "Analyzing your request..."}
          {"type": "tool_start", "tool": "slack_send_message", "args": {...}}
          {"type": "tool_result", "tool": "slack_send_message", "success": true, "summary": "..."}
          {"type": "content_delta", "delta": "Here's"}
          {"type": "done", "message_id": 42, "tokens_used": 350, "tools_called": [...]}
          {"type": "error", "error": "..."}
        """
        tools_called = []
        total_tokens = 0

        try:
            yield {"type": "thinking", "content": "Analyzing your request..."}

            # Step 0: Check AI limits (same as synchronous path)
            is_byok = False
            try:
                from sqlalchemy import select
                from ..models import UserSettings
                stmt = select(UserSettings).where(UserSettings.user_id == self.user.id)
                result = await self.db.execute(stmt)
                user_settings = result.scalar_one_or_none()
                if user_settings:
                    byok_keys = {
                        "openai": user_settings.openai_api_key,
                        "anthropic": user_settings.anthropic_api_key,
                        "gemini": getattr(user_settings, 'gemini_api_key', None),
                    }
                    is_byok = bool(byok_keys.get(provider))
            except Exception:
                pass

            if not is_byok:
                daily_count = await self.get_daily_message_count(self.db, self.user.id)
                if not FeatureGate.can_use_ai_message(self.user, daily_count):
                    limit = FeatureGate.get_limits(self.user.subscription_tier)['max_ai_messages_daily']
                    yield {"type": "error", "error": f"Plan limit reached: Your {self.user.subscription_tier} plan allows {limit} AI messages per day. Please upgrade to continue."}
                    return

            # Step 1: Classify intent
            yield {"type": "thinking", "content": "Understanding your intent..."}
            intent_classifier = await self.intent_processor.classify_intent(content)
            logger.info(f"Intent: {intent_classifier.intent_type} ({intent_classifier.confidence:.0%})")

            # Step 2: Check if tools are needed
            model_override = None
            if use_reasoning:
                yield {"type": "thinking", "content": "Routing to reasoning model..."}
                model_override = "o3-mini" if provider == "openai" else ("claude-3-7-sonnet" if provider == "anthropic" else "deepseek-r1")

            if not intent_classifier.requires_tools and not use_search:
                yield {"type": "thinking", "content": "Generating response..."}
                async for event in self._stream_direct_response(content, provider, model_override=model_override):
                    yield event
                return

            # Step 3: Get relevant tools
            yield {"type": "thinking", "content": "Selecting relevant tools..."}
            relevant_tools = await self.tool_router.get_relevant_tools(content)
            
            if use_search:
                yield {"type": "thinking", "content": "Injecting web search capabilities..."}
                search_tool = dynamic_tool_registry.base_tools.get("web_search")
                if search_tool and search_tool not in relevant_tools:
                    relevant_tools.append(search_tool)
                    
            if not relevant_tools:
                yield {"type": "thinking", "content": "No specific tools needed, generating response..."}
                async for event in self._stream_direct_response(content, provider, model_override=model_override):
                    yield event
                return

            tool_names = [t.get('name', '') for t in relevant_tools]
            yield {"type": "thinking", "content": f"Found {len(relevant_tools)} relevant tools: {', '.join(tool_names[:5])}"}

            # Step 4: Prepare for function calling loop
            openai_tools = dynamic_tool_registry.convert_tools_to_openai_format(relevant_tools)
            
            from ..routers.chat_router import get_optimized_context
            context_messages = await get_optimized_context(self.conversation_id, self.db, user_message=content)
            
            messages = []
            for msg in context_messages:
                if msg.role == MessageRole.USER:
                    messages.append({"role": "user", "content": msg.content})
                elif msg.role == MessageRole.ASSISTANT:
                    messages.append({"role": "assistant", "content": msg.content})
                elif msg.role == MessageRole.TOOL:
                    messages.append({"role": "tool", "content": msg.content, "tool_call_id": msg.tool_call_id})
            messages.append({"role": "user", "content": content})

            # Step 5: Function calling loop (up to 5 iterations)
            max_iterations = 5
            for iteration in range(max_iterations):
                logger.info(f"🔄 Stream iteration {iteration + 1}/{max_iterations}")

                try:
                    # Call LLM with tools (non-streaming for tool selection)
                    if provider == "ollama":
                        response = await self._call_ollama_with_functions(messages, openai_tools, model_override=model_override)
                    else:
                        response = await self._call_llm_fallback(provider, messages, openai_tools, model_override=model_override)

                    if not response:
                        yield {"type": "error", "error": "No response from AI provider. Please check your configuration."}
                        return

                    if "usage" in response:
                        total_tokens += response["usage"].get("total_tokens", 0)

                    assistant_message = response.get('choices', [{}])[0].get('message', {})
                    llm_content = assistant_message.get('content', '')
                    tool_calls = assistant_message.get('tool_calls', [])

                    # Parse tool calls from content if needed
                    if not tool_calls and llm_content.strip().startswith('[') and llm_content.strip().endswith(']'):
                        try:
                            parsed = json.loads(llm_content.strip())
                            if isinstance(parsed, list):
                                tool_calls = []
                                for i, tc in enumerate(parsed):
                                    if isinstance(tc, dict) and 'name' in tc:
                                        tool_calls.append({
                                            'id': f'call_{i}',
                                            'type': 'function',
                                            'function': {
                                                'name': tc['name'],
                                                'arguments': json.dumps(tc.get('arguments', {}))
                                            }
                                        })
                        except json.JSONDecodeError:
                            pass

                    # Clean assistant message
                    if 'tool_calls' in assistant_message and not assistant_message['tool_calls']:
                        del assistant_message['tool_calls']
                    messages.append(assistant_message)

                    # If no tool calls, stream the final response
                    if not tool_calls:
                        yield {"type": "thinking", "content": "Composing final response..."}
                        # Stream the final LLM response token by token
                        async for event in self._stream_final_response(provider, messages, openai_tools, model_override=model_override):
                            if event.get("type") == "content_delta":
                                yield event
                            elif event.get("type") == "content":
                                yield event
                            elif event.get("type") == "usage":
                                total_tokens += event.get("tokens", 0)

                        # Track usage
                        try:
                            from ..routers.subscription_router import get_or_create_usage_record
                            usage_record = await get_or_create_usage_record(self.db, self.user)
                            usage_record.ai_actions_count += 1
                            await self.db.commit()
                        except Exception:
                            pass

                        yield {"type": "done", "tokens_used": total_tokens, "tools_called": tools_called}
                        return

                    # Execute tool calls
                    for tc in tool_calls:
                        tool_call_id = tc.get('id', '')
                        function_name = tc.get('function', {}).get('name', '')
                        arguments_str = tc.get('function', {}).get('arguments', '{}')

                        try:
                            arguments = json.loads(arguments_str)
                        except json.JSONDecodeError:
                            arguments = {}

                        yield {"type": "tool_start", "tool": function_name, "args": arguments}

                        try:
                            # Validate
                            is_valid, error_msg = ToolArgumentValidator.validate(function_name, arguments, openai_tools)
                            if not is_valid:
                                yield {"type": "tool_result", "tool": function_name, "success": False, "summary": f"Validation error: {error_msg}"}
                                messages.append({"role": "tool", "content": f"Error: {error_msg}", "tool_call_id": tool_call_id})
                                tools_called.append({"name": function_name, "arguments": arguments, "result": {"error": error_msg}})
                                continue

                            # Execute tool
                            tool_result = await tool_executor.execute_tool(
                                function_name, arguments, self.user, self.db, tools_called
                            )

                            tools_called.append({"name": function_name, "arguments": arguments, "result": tool_result})

                            # Build a short summary
                            summary = ""
                            if isinstance(tool_result, dict):
                                if tool_result.get("success"):
                                    summary = tool_result.get("message", str(tool_result)[:200])
                                else:
                                    summary = tool_result.get("error", tool_result.get("message", str(tool_result)[:200]))
                            else:
                                summary = str(tool_result)[:200]

                            success = isinstance(tool_result, dict) and tool_result.get("success", True)
                            yield {"type": "tool_result", "tool": function_name, "success": success, "summary": summary}

                            messages.append({
                                "role": "tool",
                                "content": json.dumps(tool_result) if isinstance(tool_result, dict) else str(tool_result),
                                "tool_call_id": tool_call_id
                            })

                        except Exception as e:
                            yield {"type": "tool_result", "tool": function_name, "success": False, "summary": f"Execution error: {str(e)}"}
                            messages.append({"role": "tool", "content": f"Error: {str(e)}", "tool_call_id": tool_call_id})
                            tools_called.append({"name": function_name, "arguments": arguments, "result": {"error": str(e)}})

                except Exception as e:
                    logger.error(f"Error in stream iteration {iteration + 1}: {e}")
                    yield {"type": "error", "error": f"Processing error: {str(e)}"}
                    return

            # Exhausted iterations — stream whatever we have
            yield {"type": "content", "content": "I've completed the available actions. Let me know if you need anything else."}
            yield {"type": "done", "tokens_used": total_tokens, "tools_called": tools_called}

        except Exception as e:
            logger.error(f"Error in process_message_stream: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            yield {"type": "error", "error": f"An unexpected error occurred: {str(e)}"}

    async def _stream_direct_response(self, content: str, provider: str, model_override: Optional[str] = None) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream a direct response (no tools) token by token."""
        from ..routers.chat_router import get_optimized_context
        
        context_messages = await get_optimized_context(self.conversation_id, self.db, user_message=content)
        messages = []
        for msg in context_messages:
            if msg.role == MessageRole.USER:
                messages.append({"role": "user", "content": msg.content})
            elif msg.role == MessageRole.ASSISTANT:
                messages.append({"role": "assistant", "content": msg.content})
            elif msg.role == MessageRole.TOOL:
                messages.append({"role": "tool", "content": msg.content, "tool_call_id": msg.tool_call_id})
        messages.append({"role": "user", "content": content})

        streamed_any = False
        async for event in self._stream_final_response(provider, messages, tools=None, model_override=model_override):
            streamed_any = True
            yield event

        if not streamed_any:
            # Fallback: try non-streaming
            if provider == "ollama":
                response = await self._call_ollama_direct(messages)
            else:
                response = await self._call_llm_fallback(provider, messages)

            if response and not (isinstance(response, dict) and response.get('error')):
                resp_content = response.get('choices', [{}])[0].get('message', {}).get('content', '')
                if resp_content:
                    yield {"type": "content", "content": resp_content}
                else:
                    yield {"type": "content", "content": "I'm sorry, I couldn't generate a response. Please try again."}
            else:
                error_msg = response.get('error_message', 'Unable to connect to AI provider.') if isinstance(response, dict) else 'Unable to connect to AI provider.'
                yield {"type": "error", "error": error_msg}
                return

        # Track usage
        try:
            from ..routers.subscription_router import get_or_create_usage_record
            usage_record = await get_or_create_usage_record(self.db, self.user)
            usage_record.ai_actions_count += 1
            await self.db.commit()
        except Exception:
            pass

        yield {"type": "done", "tokens_used": 0, "tools_called": []}

    async def _stream_final_response(self, provider: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] = None, model_override: Optional[str] = None) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream the final LLM response token by token from the appropriate provider."""
        if provider == "openai":
            async for event in self._stream_openai_response(messages, tools, model_override=model_override):
                yield event
        elif provider == "anthropic":
            async for event in self._stream_anthropic_response(messages):
                yield event
        elif provider == "ollama":
            async for event in self._stream_ollama_response(messages, tools):
                yield event
        else:
            # For unsupported streaming providers, fall back to non-streaming
            if provider == "ollama":
                response = await self._call_ollama_direct(messages)
            else:
                response = await self._call_llm_fallback(provider, messages, tools)
            if response and not (isinstance(response, dict) and response.get('error')):
                content = response.get('choices', [{}])[0].get('message', {}).get('content', '')
                if content:
                    yield {"type": "content", "content": content}

    async def _stream_openai_response(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] = None, model_override: Optional[str] = None) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream from OpenAI API token by token."""
        from ..config import settings
        from sqlalchemy import select
        from ..models import UserSettings

        api_key = settings.OPENAI_API_KEY
        try:
            stmt = select(UserSettings).where(UserSettings.user_id == self.user.id)
            result = await self.db.execute(stmt)
            user_settings = result.scalar_one_or_none()
            if user_settings and user_settings.openai_api_key:
                api_key = user_settings.openai_api_key
        except Exception:
            pass

        if not api_key:
            return

        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key)
            model = model_override or getattr(settings, 'OPENAI_MODEL', 'gpt-4o')

            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": settings.LLM_TEMPERATURE or 0.7,
                "stream": True,
            }
            if settings.LLM_MAX_TOKENS:
                kwargs["max_tokens"] = settings.LLM_MAX_TOKENS
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            async for chunk in await client.chat.completions.create(**kwargs):
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield {"type": "content_delta", "delta": delta.content}

        except Exception as e:
            logger.error(f"OpenAI streaming error: {e}")

    async def _stream_anthropic_response(self, messages: List[Dict[str, Any]]) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream from Anthropic API token by token."""
        from ..config import settings
        from sqlalchemy import select
        from ..models import UserSettings
        import aiohttp

        api_key = settings.ANTHROPIC_API_KEY
        try:
            stmt = select(UserSettings).where(UserSettings.user_id == self.user.id)
            result = await self.db.execute(stmt)
            user_settings = result.scalar_one_or_none()
            if user_settings and user_settings.anthropic_api_key:
                api_key = user_settings.anthropic_api_key
        except Exception:
            pass

        if not api_key:
            return

        try:
            anthropic_messages = []
            system_content = ""
            for msg in messages:
                if msg.get("role") == "system":
                    system_content = msg.get("content", "")
                elif msg.get("role") in ["user", "assistant"]:
                    anthropic_messages.append({"role": msg["role"], "content": msg.get("content", "")})

            payload = {
                "model": "claude-sonnet-4-20250514",
                "messages": anthropic_messages,
                "max_tokens": settings.LLM_MAX_TOKENS or 1024,
                "temperature": settings.LLM_TEMPERATURE or 0.7,
                "stream": True,
            }
            if system_content:
                payload["system"] = system_content

            headers = {
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.anthropic.com/v1/messages",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Anthropic streaming error: {error_text}")
                        return

                    buffer = ""
                    async for raw_bytes in response.content:
                        buffer += raw_bytes.decode("utf-8", errors="replace")
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line or not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                return
                            try:
                                data = json.loads(data_str)
                                event_type = data.get("type", "")
                                if event_type == "content_block_delta":
                                    delta_text = data.get("delta", {}).get("text", "")
                                    if delta_text:
                                        yield {"type": "content_delta", "delta": delta_text}
                            except json.JSONDecodeError:
                                continue

        except Exception as e:
            logger.error(f"Anthropic streaming error: {e}")

    async def _stream_ollama_response(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] = None) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream from Ollama API token by token."""
        import os
        import aiohttp
        from ..config import settings

        ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        ollama_url = f"{ollama_base_url}/v1/chat/completions"

        models_to_try = [settings.OLLAMA_MODEL, "qwen3", "mistral:latest", "llama3.1:8b"]

        for model in models_to_try:
            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
            }
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        ollama_url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=120)
                    ) as response:
                        if response.status != 200:
                            continue

                        buffer = ""
                        async for raw_bytes in response.content:
                            buffer += raw_bytes.decode("utf-8", errors="replace")
                            while "\n" in buffer:
                                line, buffer = buffer.split("\n", 1)
                                line = line.strip()
                                if not line or not line.startswith("data: "):
                                    continue
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    return
                                try:
                                    data = json.loads(data_str)
                                    choices = data.get("choices", [])
                                    if choices:
                                        delta = choices[0].get("delta", {})
                                        content = delta.get("content", "")
                                        if content:
                                            yield {"type": "content_delta", "delta": content}
                                except json.JSONDecodeError:
                                    continue
                        return  # Success with this model
            except Exception as e:
                logger.error(f"Ollama streaming error with model {model}: {e}")
                continue

        logger.error("All Ollama models failed for streaming")