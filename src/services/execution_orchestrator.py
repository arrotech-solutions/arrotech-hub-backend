"""
Execution Orchestrator Service for coordinating intent processing, tool selection, and execution.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Conversation, Message, MessageRole, MessageStatus, User
from .dynamic_tool_registry import dynamic_tool_registry
from .intent_processor import IntentProcessor
from .tool_executor import tool_executor
from .tool_router import ToolRouter

logger = logging.getLogger(__name__)


class ExecutionOrchestrator:
    """Orchestrates the end-to-end execution of user requests with precision."""
    
    def __init__(self, db: AsyncSession, user: User, conversation_id: int):
        self.db = db
        self.user = user
        self.conversation_id = conversation_id
        self.tool_router = ToolRouter(user, db)
        self.intent_processor = IntentProcessor(user, db)
    
    async def process_message(self, content: str, provider: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Process a user message with full orchestration.
        
        Args:
            content: User's message content
            provider: LLM provider to use
            
        Returns:
            Tuple of (response_content, tools_called)
        """
        try:
            print(f"🎯 Orchestrating message processing for: '{content[:50]}...'")
            
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
            return await self._execute_with_function_calling(content, provider, relevant_tools)
            
        except Exception as e:
            print(f"❌ Error in process_message: {e}")
            import traceback
            print(f"❌ Traceback: {traceback.format_exc()}")
            
            # Return a helpful error message
            error_response = f"I apologize, but I encountered an issue processing your request: '{content[:100]}...'. Please try again or rephrase your question."
            return error_response, []
    
    async def _generate_direct_response(self, content: str, provider: str) -> Tuple[str, List[Dict[str, Any]]]:
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
        if provider == "ollama":
            response = await self._call_ollama_direct(messages)
        else:
            response = await self._call_llm_fallback(provider, messages)
        
        if response:
            assistant_message = response.get('choices', [{}])[0].get('message', {})
            content = assistant_message.get('content', '')
            if content:
                return content, []
        
        # Fallback response when LLM is not available
        print(f"⚠️ LLM not available, providing fallback response")
        fallback_response = f"I understand you're asking about: '{content[:100]}...'. I'm here to help with your questions and can assist with various tasks when you need them. How can I be of assistance?"
        return fallback_response, []
    
    async def _execute_with_function_calling(self, content: str, provider: str, relevant_tools: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        """Execute using function calling loop with relevant tools."""
        # Convert tools to OpenAI format
        openai_tools = dynamic_tool_registry.convert_tools_to_openai_format(relevant_tools)
        
        print(f"🔧 Converted {len(openai_tools)} tools to OpenAI format:")
        for tool in openai_tools:
            print(f"  - {tool['function']['name']}: {tool['function']['description']}")
        
        # Get conversation context
        from ..routers.chat_router import get_optimized_context
        context_messages = await get_optimized_context(self.conversation_id, self.db, user_message=content)
        
        # Prepare messages for LLM with system prompt
        messages = []
        
        # Add system prompt to guide tool selection
        system_prompt = f"""You are a helpful AI assistant with access to the following tools:

{chr(10).join([f"- {tool['function']['name']}: {tool['function']['description']}" for tool in openai_tools])}

When the user asks for something that requires using these tools, you MUST call the appropriate tool using the function calling format. Do not provide instructions or code examples - actually call the tools.

For example:
- If asked to "list slack channels", call the slack_list_channels tool
- If asked to "send a message", call the slack_send_message tool
- If asked to "get campaign performance", call the campaign_performance_tracking tool
- If asked to "create a slack channel", call the slack_create_channel tool with channel_name (without # prefix, e.g., "projects" not "#projects")
- If asked to "create an image", call the content_creation tool with operation="generate_image" and text="description of the image"
- If asked to "generate content", call the content_creation tool with the appropriate operation and required parameters
- If asked to "show today's payments", "get payment summary", or "show payments", call the mpesa_payment_reconciliation tool with operation="get_summary" and days=1
- If asked to "get unmatched payments" or "show unmatched", call the mpesa_payment_reconciliation tool with operation="get_unmatched"
- If asked about "M-Pesa payments", "payment summary", or "payment reconciliation", use the mpesa_payment_reconciliation tool

Always use the exact tool names provided above and include all required parameters."""
        
        messages.append({"role": "system", "content": system_prompt})
        
        for msg in context_messages:
            if msg.role == MessageRole.USER:
                messages.append({"role": "user", "content": msg.content})
            elif msg.role == MessageRole.ASSISTANT:
                messages.append({"role": "assistant", "content": msg.content})
            elif msg.role == MessageRole.TOOL:
                messages.append({"role": "tool", "content": msg.content, "tool_call_id": msg.tool_call_id})
        
        messages.append({"role": "user", "content": content})
        
        # Execute function calling loop
        return await self._execute_function_calling_loop(provider, messages, openai_tools)
    
    async def _execute_function_calling_loop(self, provider: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]], max_iterations: int = 5) -> Tuple[str, List[Dict[str, Any]]]:
        """Execute function calling loop with validation and error handling."""
        tools_called = []
        
        for iteration in range(max_iterations):
            print(f"🔄 Function calling iteration {iteration + 1}/{max_iterations}")
            
            try:
                # Call LLM with tools
                if provider == "ollama":
                    response = await self._call_ollama_with_functions(messages, tools)
                else:
                    response = await self._call_llm_fallback(provider, messages, tools)
                
                if not response:
                    print(f"❌ No response from LLM in iteration {iteration + 1}")
                    break
                
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
                
                # Add assistant message to conversation
                messages.append(assistant_message)
                
                # If no tool calls, we're done
                if not tool_calls:
                    print(f"✅ No tool calls - generating final user-facing response")
                    # Make a final LLM call with the updated messages (including tool result)
                    if provider == "ollama":
                        final_response = await self._call_ollama_with_functions(messages, tools)
                    else:
                        final_response = await self._call_llm_fallback(provider, messages, tools)
                    if final_response:
                        final_message = final_response.get('choices', [{}])[0].get('message', {})
                        final_content = final_message.get('content', '')
                        return final_content, tools_called
                    else:
                        return content, tools_called
                
                # Execute tool calls
                for tool_call in tool_calls:
                    tool_call_id = tool_call.get('id')
                    function_name = tool_call.get('function', {}).get('name', '')
                    arguments_str = tool_call.get('function', {}).get('arguments', '{}')
                    
                    print(f"🔧 Executing tool: {function_name} with args: {arguments_str}")
                    
                    try:
                        # Parse arguments
                        arguments = json.loads(arguments_str)
                        
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
                return last_assistant.get("content", ""), tools_called
        
        return "I apologize, but I encountered an issue processing your request. Please try again.", tools_called
    
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
    
    async def _call_ollama_with_functions(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Call Ollama with function calling support."""
        import os

        import aiohttp
        
        ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        ollama_url = f"{ollama_base_url}/v1/chat/completions"
        
        # Try different models in order of preference
        models_to_try = ["llama3.2:3b", "mistral:latest", "llama3.1:8b"]
        
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
    
    async def _call_llm_fallback(self, provider: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Call LLM for providers like OpenAI, Anthropic, etc."""
        from ..config import settings
        
        if provider == "openai":
            return await self._call_openai_with_functions(messages, tools)
        elif provider == "anthropic":
            return await self._call_anthropic(messages, tools)
        
        # For unknown providers, return None
        print(f"⚠️ Unknown provider: {provider}")
        return None
    
    async def _call_openai_with_functions(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Call OpenAI API with function calling support."""
        from ..config import settings
        
        if not settings.OPENAI_API_KEY:
            print("❌ OpenAI API key not configured")
            return None
        
        try:
            import openai
            from openai import AsyncOpenAI
            
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            
            # Build request parameters
            model = getattr(settings, 'OPENAI_MODEL', 'gpt-4o')
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
                }]
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
    
    async def _call_anthropic(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Call Anthropic Claude API."""
        from ..config import settings
        
        if not settings.ANTHROPIC_API_KEY:
            print("❌ Anthropic API key not configured")
            return None
        
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
                "model": "claude-3-sonnet-20240229",
                "messages": anthropic_messages,
                "max_tokens": settings.LLM_MAX_TOKENS or 1024,
                "temperature": settings.LLM_TEMPERATURE or 0.7,
            }
            
            if system_content:
                payload["system"] = system_content
            
            headers = {
                "x-api-key": settings.ANTHROPIC_API_KEY,
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
                        print(f"❌ Anthropic error {response.status}: {error_text}")
                        return None
                        
        except Exception as e:
            print(f"❌ Anthropic API error: {e}")
            import traceback
            print(f"❌ Traceback: {traceback.format_exc()}")
            return None 