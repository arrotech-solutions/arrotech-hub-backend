"""
Chat Router for handling conversation and messaging.
"""

import asyncio
import base64
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiohttp
from fastapi import (APIRouter, Depends, HTTPException, Request, Response,
                     status)
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import Conversation, Message, MessageRole, MessageStatus, User
from ..routers.auth_router import get_current_user
from ..routers.settings_router import get_or_create_user_settings
from ..services.dynamic_tool_registry import dynamic_tool_registry
from ..services.execution_orchestrator import ExecutionOrchestrator
from ..services.intent_processor import IntentProcessor
from ..services.tool_executor import tool_executor
from ..services.tool_selector import ToolRouter
from ..config import settings

router = APIRouter()


class MessageCreate(BaseModel):
    content: str = Field(
        ..., 
        description="The text content of the message. Supports markdown. This is the primary input for the AI agent.",
        example="Create a summary of my last 5 HubSpot deals."
    )
    provider: Optional[str] = Field(
        None, 
        description="Optional LLM provider override (e.g., 'openai', 'anthropic', 'ollama'). If not provided, the user's default provider is used.",
        example="openai"
    )
    use_reasoning: Optional[bool] = Field(
        False,
        description="If True, the orchestrator will forcibly route the request to a deep-thinking model like o3-mini or deepseek-r1 to perform advanced CoT."
    )
    use_search: Optional[bool] = Field(
        False,
        description="If True, the orchestrator will inject a web_search tool and require the LLM to research the query before answering."
    )


class ConversationCreate(BaseModel):
    title: Optional[str] = Field(
        None, 
        description="An optional title for the conversation. If omitted, the system will generate a title based on the first message.",
        example="HubSpot Integration Project"
    )


class ConversationUpdate(BaseModel):
    title: str = Field(
        ..., 
        description="The new title for the conversation.",
        example="Marketing Automation Campaign v2"
    )


class MessageRead(BaseModel):
    id: int = Field(..., description="Unique identifier for the message.")
    conversation_id: int = Field(..., description="The ID of the conversation this message belongs to.")
    role: str = Field(..., description="The role of the message sender (e.g., 'user', 'assistant', 'system', 'tool').")
    content: str = Field(..., description="The textual content of the message.")
    status: str = Field(..., description="The current delivery or processing status of the message.")
    tokens_used: Optional[int] = Field(None, description="The total number of tokens consumed by this message exchange.")
    tools_called: Optional[List[Dict[str, Any]]] = Field(None, description="Metadata about any tools executed during this message processing.")
    tool_call_id: Optional[str] = Field(None, description="The unique ID of the tool call, if this message is a tool response.")
    error_message: Optional[str] = Field(None, description="Detailed error message if the message processing failed.")
    created_at: Optional[str] = Field(None, description="The ISO 8601 timestamp of when the message was created.")

    class Config:
        from_attributes = True
    
    @classmethod
    def from_orm(cls, obj):
        """Custom from_orm method to handle datetime conversion."""
        data = {
            "id": obj.id,
            "conversation_id": obj.conversation_id,
            "role": obj.role,
            "content": obj.content,
            "status": obj.status,
            "tokens_used": obj.tokens_used,
            "tools_called": obj.tools_called,
            "tool_call_id": obj.tool_call_id,
            "error_message": obj.error_message,
            "created_at": obj.created_at.isoformat() if obj.created_at else None
        }
        return cls(**data)


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    data: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    ### Create a New Conversation
    
    Initiates a fresh conversation thread for the authenticated user. Conversations act as containers for messages and maintain the state for AI interactions.
    
    **Key features of conversations:**
    - **Persistence**: Messages are stored and can be retrieved later for context.
    - **Context Awareness**: The AI uses the message history within a conversation to provide relevant responses.
    - **Platform Bridging**: A single conversation can involve multiple tools and platforms (e.g., fetching a lead from HubSpot and sending a Slack alert).
    
    ---
    **Returns:** A success object containing the newly created conversation's unique ID and metadata.
    """
    try:
        conversation = Conversation(
            user_id=user.id,
            title=data.title or "New Conversation"
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)

        return {
            "success": True,
            "data": {
                "id": conversation.id,
                "title": conversation.title,
                "is_active": conversation.is_active,
                "created_at": conversation.created_at.isoformat() if conversation.created_at else "",
                "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else ""
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create conversation: {str(e)}"
        )


@router.get("/conversations")
async def get_conversations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    ### List User Conversations
    
    Retrieves a paginated list of all conversation threads belonging to the authenticated user. Conversations are returned in descending order of their last update (most recent first).
    
    This is useful for building a "Recent Chats" or "History" sidebar in your application.
    
    **Note:** This endpoint only returns metadata (IDs, titles). To get the actual messages, use the `GET /conversations/{conversation_id}` endpoint.
    """
    try:
        result = await db.execute(
            select(Conversation)
            .filter(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc())
        )
        conversations = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "id": conv.id,
                    "title": conv.title,
                    "is_active": conv.is_active,
                    "created_at": conv.created_at.isoformat() if conv.created_at else "",
                    "updated_at": conv.updated_at.isoformat() if conv.updated_at else ""
                }
                for conv in conversations
            ]
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get conversations: {str(e)}"
        )


@router.get("/conversations/{conversation_id}", response_model=Dict[str, Any])
async def get_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    ### Get Conversation Details
    
    Fetches the full metadata and a snapshot of messages for a specific conversation.
    
    This endpoint is the standard way to resume a chat session in a UI. It returns the conversation's state, its title, and its message history.
    
    **Security:**
    - Only the conversation owner can access this data.
    - All timestamps are returned in ISO 8601 UTC format.
    
    **Optimization Tip:**
    For very long conversations, consider using the `/messages` endpoint with pagination (if available) to avoid loading massive JSON payloads at once.
    """
    result = await db.execute(
        select(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
        .options(selectinload(Conversation.messages))
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return {
        "id": conversation.id,
        "title": conversation.title,
        "is_active": conversation.is_active,
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "status": msg.status,
                "tokens_used": msg.tokens_used,
                "tools_called": msg.tools_called,
                "error_message": msg.error_message,
                "created_at": msg.created_at
            }
            for msg in conversation.messages
        ],
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at
    }


async def build_system_prompt(tools: List[Dict[str, Any]] = None, user_context: Dict[str, Any] = None, user_query: str = "") -> str:
    """
    Build an enhanced system prompt for high-accuracy tool calling.
    
    Args:
        tools: List of available tools in OpenAI format
        user_context: Optional dict with user's connections, tier, etc.
        user_query: The user's current message for semantic relevance
    """
    system_prompt = """You are Mini-Hub, an AI-powered business automation assistant with access to 50+ integrations.

## YOUR IDENTITY:
- You are a professional, efficient assistant specialized in business automation
- You help users manage their connected platforms: Slack, Gmail, Calendar, M-Pesa, WhatsApp, and more
- You are precise with tool calls and never hallucinate tool names or parameters

## CORE RULES:
1. **Action requests → Use tools**: When user asks to DO something (send, create, get, list, show), use the appropriate tool
2. **Questions about capabilities → Respond directly**: Explain what you can do without calling tools
3. **Casual chat → Respond naturally**: Greetings, thanks, etc. don't need tools
4. **Unclear requests → Ask ONE clarifying question**: Don't guess, ask for specifics

## TOOL CALLING PRECISION:
- Use EXACT tool names from the available tools list
- Provide ALL required parameters with correct types
- For optional parameters, only include if user specified them
- Never invent tool names or operations that don't exist

## FEW-SHOT EXAMPLES:
"""

    # Dynamically inject examples from the tools themselves using Semantic Selection
    examples_text = ""
    if tools:
        examples_text = dynamic_tool_registry.get_relevant_examples(user_query, tools)

    # Fallback to hardcoded examples only if no dynamic examples found
    if not examples_text:
        examples_text = """
### Example 1: Slack Message
User: "Send a message to #general on Slack saying 'Hello team, standup in 5 minutes'"
Thought: The user wants to send a Slack message. I should look for a slack tool. The 'slack_team_communication' tool seems appropriate. I need the channel and content.
Tool Call: slack_team_communication with {"action": "send_message", "channel": "#general", "message": "Hello team, standup in 5 minutes"}
Response: "✅ Message sent to #general: 'Hello team, standup in 5 minutes'"

### Example 2: Market Analysis
User: "Analyze market trends for laptop sales"
Thought: This sounds like a marketing analysis request. The 'marketing_campaign_automation' tool has an 'analyze_trends' operation.
Tool Call: marketing_campaign_automation with {"operation": "analyze_trends", "topic": "laptop sales"}
Response: "📊 Analysis complete. Trends indicate a 15% rise in demand..."

### Example 3: Email
User: "Send an email to john@example.com about the meeting tomorrow"
Thought: I need to send an email. The 'google_workspace_gmail' tool is perfect for this. I have the recipient and the subject.
Tool Call: google_workspace_gmail with {"action": "send_email", "to": "john@example.com", "subject": "Meeting Tomorrow", "body": "Hi John, I wanted to confirm our meeting tomorrow..."}
Response: "✅ Email sent to john@example.com with subject 'Meeting Tomorrow'"
"""

    system_prompt += examples_text
    
    system_prompt += """
## RESPONSE FORMAT:
- **For successful actions**: Start with ✅ and briefly confirm what was done
- **For data queries**: Present in clear tables or bullet lists
- **For errors**: Start with ⚠️ and explain what went wrong + suggest fixes
- **Keep responses concise**: 2-4 sentences for confirmations, expand for data

## ERROR HANDLING:
- If a tool call fails, explain the error in simple terms
- Suggest what the user can do to fix it
- Don't expose technical error messages directly
"""

    # Add user context if provided
    if user_context:
        active_connections = user_context.get('connections', [])
        user_tier = user_context.get('tier', 'Free')
        
        if active_connections:
            system_prompt += f"\n## USER'S ACTIVE INTEGRATIONS:\n"
            system_prompt += ", ".join(active_connections) + "\n"
            system_prompt += "Prioritize these platforms when the user's intent is ambiguous.\n"

    # Add available tools
    if tools:
        system_prompt += "\n## AVAILABLE TOOLS:\n"
        system_prompt += "Use ONLY these tools. Do not invent tool names.\n\n"
        for tool in tools:
            # Handle both OpenAI format (nested in 'function') and flat format
            func = tool.get('function', tool)
            name = func.get('name', '')
            description = func.get('description', '')
            
            # Get parameters info for better guidance
            params = func.get('parameters', {})
            required_params = params.get('required', [])
            
            system_prompt += f"### {name}\n"
            system_prompt += f"{description}\n"
            if required_params:
                system_prompt += f"Required params: {', '.join(required_params)}\n"
            system_prompt += "\n"

    system_prompt += """
## FINAL REMINDERS:
- Be helpful and professional
- Confirm actions before major operations (delete, bulk send)
- When presenting data, use markdown tables for clarity
- Keep responses focused and actionable
"""

    return system_prompt


async def select_tools_semantically(
    user_message: str,
    available_tools: List[Dict[str, Any]],
    llm_service: Any = None
) -> List[Dict[str, Any]]:
    """
    Select relevant tools using semantic analysis via LLM.
    This replaces the brittle keyword matching.
    """
    # Optimization: If few tools, just return all
    if len(available_tools) <= 5:
        return available_tools

    # We use a robust keyword + semantic heuristic for now to avoid circular dependencies
    relevant = []
    user_msg_lower = user_message.lower()
    
    # Critical Keywords for various platforms
    intent_map = {
        "mpesa": ["mpesa", "m-pesa", "reconcile", "transaction", "pay", "money", "shilling", "kes", "invoice"],
        "slack": ["slack", "channel", "message team", "chat"],
        "hubspot": ["hubspot", "crm", "contact", "deal"],
        "salesforce": ["salesforce", "lead", "opportunity"],
        "ga4": ["ga4", "analytics", "traffic", "conversion"],
        "google_workspace": ["gmail", "email", "calendar", "drive", "sheet", "doc"],
        "gmail": ["gmail", "email"],
        "calendar": ["calendar", "event", "meeting"],
        "whatsapp": ["whatsapp", "message"],
        "jira": ["jira", "issue", "ticket"],
        "trello": ["trello", "board", "card"],
        "notion": ["notion", "page", "database"],
        "powerbi": ["powerbi", "power bi", "dashboard", "report"],
        "xero": ["xero", "accounting", "invoice", "receipt", "contact", "finance"],
        "zoho": ["zoho", "crm", "desk", "mail", "finance"]
    }

    for tool in available_tools:
        tool_name = tool['name'].lower()
        tool_desc = tool.get('description', '').lower()
        
        # 1. Direct name match
        if tool_name.replace('_', ' ') in user_msg_lower:
            relevant.append(tool)
            continue
            
        # 2. Intent Map Match
        matched_intent = False
        for platform, keywords in intent_map.items():
            if platform in tool_name and any(kw in user_msg_lower for kw in keywords):
                relevant.append(tool)
                matched_intent = True
                break
        if matched_intent:
            continue
            
        # 3. Description Keyword Match (Legacy fallback)
        import re
        desc_words = set(re.sub(r'[^\w\s]', '', tool_desc).split())
        keywords = {w for w in desc_words if len(w) > 4}
        if any(kw in user_msg_lower for kw in keywords):
            relevant.append(tool)
            continue
            
    # Fallback: if 'help' or general query, return all
    if not relevant or any(x in user_msg_lower for x in ['help', 'capabilities', 'what can']):
        return available_tools[:20]  # Return significant subset
            
    return relevant if relevant else available_tools[:5]

def relevant_tools(available_tools: List[Dict[str, Any]],
                   data: MessageCreate) -> List[Dict[str, Any]]:
    """Legacy wrapper for backward compatibility."""
    # This synchronous wrapper is deprecated but kept for safety.
    # The async select_tools_semantically should be used instead.
    return available_tools


async def create_conversation_summary(messages: List[Message]) -> str:
    """
    Create a summary of old conversation context using LLM.
    Falls back to rule-based if LLM fails.
    """
    if not messages:
        return ""

    try:
        # Prepare content for summarization
        conversation_text = ""
        for msg in messages:
            role = msg.role
            content = msg.content
            # Skip very long content in summary input to save tokens
            if len(content) > 500:
                content = content[:500] + "..."
            conversation_text += f"{role}: {content}\n"
            
        # Prompt for summarization
        prompt = f"""Summarize this conversation context in 2-3 sentences. 
Focus on user intent, key entities (names, dates, amounts), and pending actions.
Keep it concise.

Conversation:
{conversation_text}

Summary:"""

        # Use the legacy call which is simple for text generation
        # We need to construct messages format for it
        summary_messages = [{"role": "user", "content": prompt}]
        
        # We default to a standard model if not specified, or just "llama3" or "mistral"
        # Since we don't have model arg here, user env defaults will apply in call_ollama_legacy
        # or we defaults to "llama3"
        import os
        model = os.getenv("DEFAULT_LLM_MODEL", "llama3") 
        
        response = await call_ollama_legacy(model, summary_messages, tools=None)
        
        if response and response.get('response'):
            return f"Context Summary: {response['response']}"
            
    except Exception as e:
        print(f"⚠️ Summarization failed: {e}. Using fallback.")

    # FALLBACK: Extract key information from messages (Rule-based)
    summary_parts = []
    user_messages = [msg for msg in messages if msg.role == "user"]
    assistant_messages = [msg for msg in messages if msg.role == "assistant"]

    # Summarize user intent and topics
    if user_messages:
        topics = []
        for msg in user_messages[-5:]:  # Last 5 user messages
            content = msg.content.lower()
            if "slack" in content:
                topics.append("Slack communication")
            if "whatsapp" in content:
                topics.append("WhatsApp messaging")
            if "hubspot" in content or "crm" in content:
                topics.append("CRM management")
            if "analytics" in content or "ga4" in content:
                topics.append("Analytics reporting")
            if "marketing" in content:
                topics.append("Marketing campaigns")

        if topics:
            unique_topics = list(set(topics))
            summary_parts.append(
                f"Previous topics: {', '.join(unique_topics)}")

    # Create final summary
    if summary_parts:
        return "Conversation Summary (Fallback): " + ". ".join(summary_parts)
    else:
        return "Conversation Summary: General discussion about business automation."


async def analyze_conversation_complexity(messages: List[Message], user_message: str) -> Dict[str, Any]:
    """
    Analyze conversation complexity and user intent to determine optimal chunking strategy.
    """
    complexity_score = 0
    intent_type = "general"
    recommended_context_size = 8

    # Analyze message count
    if len(messages) > 30:
        complexity_score += 3
    elif len(messages) > 20:
        complexity_score += 2
    elif len(messages) > 10:
        complexity_score += 1

    # Analyze user intent
    user_message_lower = user_message.lower()

    # Tool-specific intents (need more context)
    if any(word in user_message_lower for word in ["slack", "whatsapp", "hubspot", "crm", "analytics", "ga4"]):
        intent_type = "tool_operation"
        complexity_score += 2
        recommended_context_size = 10  # Need more context for tool operations

    # Complex queries (need more context)
    if any(word in user_message_lower for word in ["report", "summary", "analysis", "compare", "trend"]):
        intent_type = "complex_query"
        complexity_score += 2
        recommended_context_size = 12

    # Simple queries (need less context)
    if any(word in user_message_lower for word in ["hello", "hi", "thanks", "thank you", "ok", "yes", "no"]):
        intent_type = "simple_interaction"
        complexity_score -= 1
        recommended_context_size = 4

    # Check for follow-up questions
    if any(word in user_message_lower for word in ["what about", "how about", "also", "and", "but", "however"]):
        intent_type = "follow_up"
        complexity_score += 1
        recommended_context_size = 8

    # Analyze recent conversation patterns
    recent_messages = messages[-5:] if len(messages) >= 5 else messages
    tool_calls_count = sum(1 for msg in recent_messages if msg.tools_called)

    if tool_calls_count > 0:
        intent_type = "tool_continuation"
        complexity_score += 1
        recommended_context_size = 10

    return {
        "complexity_score": complexity_score,
        "intent_type": intent_type,
        "recommended_context_size": recommended_context_size,
        "message_count": len(messages),
        "recent_tool_calls": tool_calls_count
    }


async def get_dynamic_context(conversation_id: int, db: AsyncSession, user_message: str) -> List[Message]:
    """
    Get dynamically optimized context based on conversation analysis.
    """
    # Get all messages for analysis
    result = await db.execute(
        select(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
    )
    all_messages = result.scalars().all()
    all_messages.reverse()  # Put in chronological order

    # Analyze conversation complexity
    analysis = await analyze_conversation_complexity(all_messages, user_message)

    # Determine optimal strategy based on analysis
    if analysis["message_count"] <= 5:
        # Very short conversation - use all messages
        return all_messages

    elif analysis["message_count"] <= 15 and analysis["complexity_score"] <= 1:
        # Short, simple conversation - use recent messages
        recent_messages = all_messages[-analysis["recommended_context_size"]:]
        return recent_messages

    elif analysis["message_count"] > 25 and analysis["complexity_score"] >= 3:
        # Long, complex conversation - use summarization
        old_messages = all_messages[:-analysis["recommended_context_size"]]
        recent_messages = all_messages[-analysis["recommended_context_size"]:]

        # Create summary of old messages
        summary = await create_conversation_summary(old_messages)

        # Create a summary message
        summary_message = type('obj', (object,), {
            'role': 'system',
            'content': summary,
            'created_at': recent_messages[0].created_at if recent_messages else None
        })()

        return [summary_message] + recent_messages

    else:
        # Medium complexity - use smart chunking
        recent_messages = all_messages[-analysis["recommended_context_size"]:]
        return recent_messages


async def get_optimized_context(conversation_id: int, db: AsyncSession, max_messages: int = 4, user_message: str = "") -> List[Message]:
    """
    Get optimized conversation context for LLM.
    Uses dynamic chunking based on conversation analysis.
    """
    # Use dynamic context selection if user message is provided
    if user_message:
        return await get_dynamic_context(conversation_id, db, user_message)

    # Fallback to original logic for backward compatibility
    # Get recent messages with a reasonable limit, including tool messages
    result = await db.execute(
        select(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(max_messages * 2)  # Get more to account for tool messages
    )
    messages = result.scalars().all()
    messages.reverse()  # Put back in chronological order
    
    # Filter to include tool messages and their related assistant messages
    optimized_messages = []
    for msg in messages:
        if msg.role in [MessageRole.USER, MessageRole.ASSISTANT, MessageRole.TOOL]:
            optimized_messages.append(msg)
    
    # Limit to max_messages while preserving tool message relationships
    if len(optimized_messages) > max_messages:
        optimized_messages = optimized_messages[-max_messages:]
    
    messages = optimized_messages

    # If we have very few messages, return all of them
    if len(messages) <= 4:
        return messages

    # For longer conversations, check if we need summarization
    total_messages_result = await db.execute(
        select(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
    )
    all_messages = total_messages_result.scalars().all()

    # If conversation is very long (>20 messages), use summarization
    if len(all_messages) > 20:
        # Get old messages for summarization (everything except recent ones)
        old_messages = all_messages[max_messages:]
        old_messages.reverse()  # Put in chronological order

        # Create summary of old messages
        summary = await create_conversation_summary(old_messages)

        # Create a summary message
        from ..models import MessageRole
        summary_message = type('obj', (object,), {
            'role': 'system',
            'content': summary,
            'created_at': messages[0].created_at if messages else None
        })()

        # Return summary + recent messages
        return [summary_message] + messages

    # For medium-length conversations, just use recent messages
    return messages


async def build_context_prompt(messages: List[Message], system_prompt: str, user_message: str) -> str:
    """
    Build an optimized prompt for high-throughput interactions.
    """
    prompt = system_prompt + "\n\nRecent:\n"

    # Add only essential context with shorter truncation
    for msg in messages[-3:]:  # Only last 3 messages for speed
        content = msg.content
        if len(content) > 100:  # Shorter truncation
            content = content[:100] + "..."

        prompt += f"{msg.role}: {content}\n"

    prompt += f"\nUser: {user_message}\nAssistant:"

    return prompt


def clean_streaming_chunk(chunk: str) -> str:
    """Clean streaming chunks to remove obvious repetition and artifacts."""
    if not chunk:
        return ""

    # Remove obvious repetition patterns
    import re

    # Remove repeated characters (more than 2 in a row)
    chunk = re.sub(r'(.)\1{2,}', r'\1\1', chunk)

    # Remove repeated words (more than 1 in a row)
    chunk = re.sub(r'\b(\w+)(\s+\1)+\b', r'\1', chunk)

    # Remove repeated phrases (more than 1 in a row)
    chunk = re.sub(r'(\b\w+\s+\w+\b)(\s+\1)+', r'\1', chunk)

    # Remove repeated sentences
    chunk = re.sub(r'([^.!?]+[.!?])\s*\1+', r'\1', chunk)

    # Remove backticks that might be artifacts
    chunk = chunk.replace('``', '`')

    # Remove excessive spaces
    chunk = re.sub(r'\s{3,}', ' ', chunk)

    # Remove common streaming artifacts
    chunk = re.sub(r'[^\w\s\.,!?;:()\[\]{}"\'-]', '', chunk)

    # Remove partial words that might be artifacts
    chunk = re.sub(r'\b\w{1,2}\s+', '', chunk)

    return chunk.strip()


def extract_tool_call(response: str) -> dict:
    """Extract tool call from response text."""
    import json
    import re

    # Look for TOOL_CALL pattern with better handling
    tool_call_match = re.search(r'TOOL_CALL:\s*(\{.*?\})', response, re.DOTALL)
    if tool_call_match:
        try:
            tool_call_text = tool_call_match.group(1).strip()
            print(f"🔍 Extracted tool call text: '{tool_call_text}'")

            # Handle common JSON formatting issues
            if tool_call_text.startswith("```") and tool_call_text.endswith("```"):
                tool_call_text = tool_call_text[3:-3].strip()

            # Remove any markdown formatting
            if tool_call_text.startswith("json"):
                tool_call_text = tool_call_text[4:].strip()

            # Remove any trailing commas
            tool_call_text = tool_call_text.rstrip(',')

            result = json.loads(tool_call_text)
            print(f"✅ Successfully parsed tool call: {result}")
            return result
        except json.JSONDecodeError as e:
            print(f"❌ JSON parsing error: {e}")
            print(f"❌ Problematic text: '{tool_call_text}'")
            return None
    return None


async def execute_tool_call(tool_call: dict, user: User, db: AsyncSession, tools_called: List[Dict[str, Any]] = None) -> str:
    """Execute a tool call and return the result."""
    from ..services.tool_executor import tool_executor

    try:
        result = await tool_executor.execute_tool(
            tool_name=tool_call["tool"],
            arguments=tool_call["arguments"],
            user=user,
            db=db,
            tools_called=tools_called
        )
        return str(result)
    except Exception as e:
        return f"Error executing tool: {str(e)}"


async def test_ollama_connection() -> Dict[str, Any]:
    """Test Ollama connection and return status."""
    try:
        import os

        import aiohttp

        ollama_base_url = os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434")
        ollama_url = f"{ollama_base_url}/api/tags"

        async with aiohttp.ClientSession() as session:
            async with session.get(ollama_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    models = await response.json()
                    return {
                        "success": True,
                        "message": "Ollama is running",
                        "models": [model.get("name", "") for model in models.get("models", [])],
                        "url": ollama_url
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Ollama returned status {response.status}",
                        "url": ollama_url
                    }
    except Exception as e:
        return {
            "success": False,
            "message": f"Cannot connect to Ollama: {str(e)}",
            "url": ollama_base_url
        }


async def execute_function_calling_loop(
    provider: str,
    model: str,
    conversation: Conversation,
    user_message: str,
    user: User,
    db: AsyncSession,
    tools_called: List[Dict[str, Any]],
    max_iterations: int = 5
) -> tuple[str, List[Dict[str, Any]]]:
    """
    Execute function calling loop with structured tool execution.
    
    This function implements a multi-step tool calling process where:
    1. LLM decides whether to call tools or respond directly
    2. Tool calls are executed and results are stored
    3. Process continues until no more tool calls are needed
    4. All intermediate messages are stored in the database
    """
    print(f"🔄 Starting function calling loop for {provider}")
    
    # Get available tools in OpenAI format
    available_tools = await dynamic_tool_registry.get_tools_for_llm(user.id, db)
    
    # 1. Semantic Tool Selection
    print(f"🧠 Selecting tools semantically for: '{user_message}'")
    available_tools = await select_tools_semantically(user_message, available_tools)
    print(f"🔧 Selected {len(available_tools)} relevant tools")
    
    openai_tools = dynamic_tool_registry.convert_tools_to_openai_format(available_tools)
    
    # 2. Build Dynamic System Prompt
    system_prompt = await build_system_prompt(available_tools, user_context={
        "tier": user.subscription_tier,
        # Fetch actual connections if possible, or leave empty for now
        "connections": [] 
    }, user_query=user_message)
    
    # Get conversation context
    context_messages = await get_optimized_context(conversation.id, db, user_message=user_message)
    
    # Prepare initial messages for LLM
    messages = []
    
    # Always add system prompt
    messages.append({"role": "system", "content": system_prompt})
    
    for msg in context_messages:
        if msg.role == MessageRole.USER:
            messages.append({"role": "user", "content": msg.content})
        elif msg.role == MessageRole.ASSISTANT:
            messages.append({"role": "assistant", "content": msg.content})
        elif msg.role == MessageRole.TOOL:
            messages.append({"role": "tool", "content": msg.content, "tool_call_id": msg.tool_call_id})
    
    # Add the new user message
    messages.append({"role": "user", "content": user_message})
    
    print(f"📝 Initial messages prepared: {len(messages)} messages")
    print(f"🔧 Available tools: {len(openai_tools)} tools")
    
    # Execute the function calling loop
    for iteration in range(max_iterations):
        print(f"🔄 Iteration {iteration + 1}/{max_iterations}")
        
        try:
            # Call LLM with function calling support
            if provider == "ollama":
                response = await call_ollama_with_functions(model, messages, openai_tools)
            else:
                response = await call_llm_fallback(provider, model, messages, openai_tools)
            
            if not response:
                print(f"❌ No response from LLM in iteration {iteration + 1}")
                break
            
            # Extract assistant message
            assistant_message = response.get('choices', [{}])[0].get('message', {})
            assistant_content = assistant_message.get('content', '')
            tool_calls = assistant_message.get('tool_calls', [])
            
            print(f"📤 Assistant response: {len(assistant_content)} chars, {len(tool_calls)} tool calls")
            
            # Save assistant message to database
            assistant_msg = Message(
                conversation_id=conversation.id,
                role=MessageRole.ASSISTANT,
                content=assistant_content,
                status=MessageStatus.COMPLETED,
                tools_called=tool_calls if tool_calls else None
            )
            db.add(assistant_msg)
            await db.commit()
            await db.refresh(assistant_msg)
            
            # Add assistant message to conversation
            messages.append({
                "role": "assistant",
                "content": assistant_content,
                "tool_calls": tool_calls
            })
            
            # If no tool calls, we're done
            if not tool_calls:
                print(f"✅ No tool calls, returning final response")
                return assistant_content, tools_called
            
            # Execute tool calls
            for tool_call in tool_calls:
                function_name = tool_call.get('function', {}).get('name', '')
                arguments_str = tool_call.get('function', {}).get('arguments', '{}')
                tool_call_id = tool_call.get('id', '')
                
                try:
                    arguments = json.loads(arguments_str)
                except json.JSONDecodeError as e:
                    print(f"❌ JSON decode error for tool call: {e}")
                    # Feed error back to LLM for self-correction
                    messages.append({
                        "role": "tool",
                        "content": json.dumps({"error": f"Invalid JSON arguments: {str(e)}. Please correct the arguments."}),
                        "tool_call_id": tool_call_id
                    })
                    continue
                
                print(f"🔧 Executing tool: {function_name} with args: {arguments}")
                
                # Execute the tool
                tool_result = await tool_executor.execute_tool(
                    function_name, arguments, user, db, tools_called
                )
                
                # Store tool call info
                tools_called.append({
                    "name": function_name,
                    "arguments": arguments,
                    "result": tool_result,
                    "tool_call_id": tool_call_id
                })
                
                # Save tool result as tool message
                tool_msg = Message(
                    conversation_id=conversation.id,
                    role=MessageRole.TOOL,
                    content=json.dumps(tool_result) if isinstance(tool_result, dict) else str(tool_result),
                    status=MessageStatus.COMPLETED,
                    tool_call_id=tool_call_id
                )
                db.add(tool_msg)
                await db.commit()
                await db.refresh(tool_msg)
                
                # Add tool message to conversation
                messages.append({
                    "role": "tool",
                    "content": json.dumps(tool_result) if isinstance(tool_result, dict) else str(tool_result),
                    "tool_call_id": tool_call_id
                })
                
                print(f"✅ Tool executed: {function_name}")
        
        except Exception as e:
            print(f"❌ Error in iteration {iteration + 1}: {e}")
            import traceback
            print(f"❌ Traceback: {traceback.format_exc()}")
            
            # Self-Correction: Feed exception back to LLM
            messages.append({
                "role": "user", # Using user role for system errors to force attention
                "content": f"⚠️ System Error: {str(e)}. Please try a different approach or simplified tool call."
            })
            # Continue to next iteration giving LLM a chance to fix
            continue
    
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


async def call_ollama_with_functions(model: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Call Ollama with function calling support."""
    import os

    import aiohttp
    
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    
    # Try the new OpenAI-compatible endpoint first
    ollama_url = f"{ollama_base_url}/v1/chat/completions"
    
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto"
    }
    
    print(f"🌐 Calling Ollama at: {ollama_url}")
    print(f"📦 Payload: {json.dumps(payload, indent=2)}")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ollama_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=300)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"✅ Ollama response: {json.dumps(result, indent=2)}")
                    return result
                else:
                    error_text = await response.text()
                    print(f"❌ Ollama error {response.status}: {error_text}")
                    
                    # Fallback to old API if new endpoint doesn't work
                    if response.status == 404:
                        print("🔄 Falling back to old Ollama API")
                        return await call_ollama_legacy(model, messages, tools)
                    
                    return None
    except Exception as e:
        print(f"❌ Error calling Ollama: {e}")
        return None


async def call_ollama_legacy(model: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Call Ollama using the legacy API with structured prompts."""
    import os

    import aiohttp
    
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_url = f"{ollama_base_url}/api/generate"
    
    # Convert messages to a single prompt
    prompt = ""
    for msg in messages:
        if msg["role"] == "system":
            prompt += f"System: {msg['content']}\n\n"
        elif msg["role"] == "user":
            prompt += f"User: {msg['content']}\n"
        elif msg["role"] == "assistant":
            prompt += f"Assistant: {msg['content']}\n"
        elif msg["role"] == "tool":
            prompt += f"Tool Result: {msg['content']}\n"
    
    # Add tool information to the prompt
    if tools:
        prompt += "\nAvailable tools:\n"
        for tool in tools:
            function = tool.get("function", {})
            prompt += f"- {function.get('name')}: {function.get('description')}\n"
            if function.get('parameters'):
                prompt += f"  Parameters: {json.dumps(function.get('parameters'), indent=2)}\n"
        
        prompt += "\nPlease respond with either:\n"
        prompt += "1. A direct response to the user, OR\n"
        prompt += "2. A JSON array of tool calls in this format:\n"
        prompt += '[{"tool": "tool_name", "arguments": {"param1": "value1"}}]\n\n'
    
    prompt += "Assistant:"
    
    print(f"📝 Legacy prompt length: {len(prompt)} chars")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ollama_url,
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "enable_thinking": False
                    }
                },
                timeout=aiohttp.ClientTimeout(total=300)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    response_text = result.get("response", "")
                    
                    # Try to parse tool calls from the response
                    tool_calls = []
                    if "[" in response_text and "]" in response_text:
                        try:
                            # Extract JSON array from response
                            start = response_text.find("[")
                            end = response_text.rfind("]") + 1
                            json_str = response_text[start:end]
                            parsed_tools = json.loads(json_str)
                            
                            # Convert to OpenAI format
                            for i, tool_call in enumerate(parsed_tools):
                                tool_calls.append({
                                    "id": f"call_{i}",
                                    "type": "function",
                                    "function": {
                                        "name": tool_call.get("tool"),
                                        "arguments": json.dumps(tool_call.get("arguments", {}))
                                    }
                                })
                        except (json.JSONDecodeError, KeyError) as e:
                            print(f"❌ Failed to parse tool calls: {e}")
                    
                    return {
                        "choices": [{
                            "message": {
                                "role": "assistant",
                                "content": response_text,
                                "tool_calls": tool_calls
                            }
                        }]
                    }
                else:
                    error_text = await response.text()
                    print(f"❌ Legacy Ollama error {response.status}: {error_text}")
                    return None
    except Exception as e:
        print(f"❌ Error calling legacy Ollama: {e}")
        return None


async def call_llm_fallback(provider: str, model: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Fallback for non-Ollama providers - routes to appropriate provider API."""
    from ..services.execution_orchestrator import ExecutionOrchestrator
    
    print(f"🔄 call_llm_fallback routing to provider: {provider}")
    
    # We need db and user context to use BYOK keys
    # This function is called from execute_function_calling_loop which has these in scope
    # For now, try to use the orchestrator's provider-specific methods
    try:
        # Import provider-specific call functions
        if provider == "openai":
            from ..config import settings
            if not settings.OPENAI_API_KEY:
                print(f"⚠️ No OpenAI API key configured for function calling fallback")
                return None
            
            import openai
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            
            request_params = {
                "model": model,
                "messages": messages,
            }
            
            is_o_series = model.startswith(('o1', 'o3'))
            
            if not is_o_series:
                request_params["temperature"] = getattr(settings, 'LLM_TEMPERATURE', 0.7)
                
            max_tokens_val = getattr(settings, 'LLM_MAX_TOKENS', 1024)
            if max_tokens_val:
                if is_o_series:
                    request_params["max_completion_tokens"] = max_tokens_val
                else:
                    request_params["max_tokens"] = max_tokens_val
            if tools:
                request_params["tools"] = tools
                request_params["tool_choice"] = "auto"
            
            response = await client.chat.completions.create(**request_params)
            return response.model_dump()
            
        elif provider == "anthropic":
            from ..config import settings
            import aiohttp
            
            api_key = settings.ANTHROPIC_API_KEY
            if not api_key:
                print(f"⚠️ No Anthropic API key configured for function calling fallback")
                return None
            
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
                "max_tokens": getattr(settings, 'LLM_MAX_TOKENS', 1024) or 1024,
                "temperature": getattr(settings, 'LLM_TEMPERATURE', 0.7) or 0.7,
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
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        content = result.get("content", [{}])[0].get("text", "")
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
                        print(f"❌ Anthropic error in fallback: {response.status}: {error_text}")
                        return None
        else:
            print(f"⚠️ No function calling support for provider: {provider}")
            return None
    except Exception as e:
        print(f"❌ Error in call_llm_fallback for {provider}: {e}")
        import traceback
        print(f"❌ Traceback: {traceback.format_exc()}")
        return None


async def process_ollama(provider: str, data: MessageCreate, user: User, db: AsyncSession, conversation: Conversation, tools_called: List[Dict[str, Any]]) -> tuple[str, List[Dict[str, Any]], Conversation]:
    """Process message using the new function calling approach."""
    if provider == "ollama":
        try:
            print(f"🚀 Starting improved Ollama processing for user {user.id}")

            # Test Ollama connection first
            connection_test = await test_ollama_connection()
            if not connection_test["success"]:
                error_msg = f"❌ **Connection Error**: {connection_test['message']}. Please check if Ollama is running and accessible at {connection_test['url']}"
                return error_msg, tools_called, conversation

            print(f"✅ Ollama connection test passed: {connection_test['message']}")
            print(f"📋 Available models: {connection_test.get('models', [])}")

            # Check if current model is available
            current_model = "mistral:latest"
            if current_model not in connection_test.get("models", []):
                error_msg = f"🤖 **Model Error**: The model '{current_model}' is not available. Available models: {', '.join(connection_test.get('models', []))}"
                return error_msg, tools_called, conversation

            # Use the new function calling loop
            final_response, updated_tools_called = await execute_function_calling_loop(
                provider=provider,
                model=current_model,
                conversation=conversation,
                user_message=data.content,
                user=user,
                db=db,
                tools_called=tools_called,
                max_iterations=5
            )

            return final_response, updated_tools_called, conversation

        except Exception as e:
            import traceback
            error_msg = str(e)
            print(f"🔴 ERROR in process_ollama: {error_msg}")
            print(f"🔴 Error traceback: {traceback.format_exc()}")

            # Provide specific error messages based on the error type
            if "Connection refused" in error_msg or "Cannot connect" in error_msg:
                assistant_content = "❌ **Connection Error**: I cannot connect to the AI service. Please check if Ollama is running on your system."
            elif "timeout" in error_msg.lower():
                assistant_content = "⏰ **Timeout Error**: The request took too long. This might be due to a complex request or high system load. Please try again or break your request into smaller parts."
            elif "model" in error_msg.lower() and "not found" in error_msg.lower():
                assistant_content = f"🤖 **Model Error**: The AI model '{data.provider or 'mistral:latest'}' is not available. Please check your Ollama installation."
            elif "permission" in error_msg.lower():
                assistant_content = "🔒 **Permission Error**: I don't have permission to access the required resources."
            elif "rate limit" in error_msg.lower():
                assistant_content = "🚫 **Rate Limit**: Too many requests. Please wait a moment and try again."
            else:
                assistant_content = f"⚠️ **Technical Issue**: {error_msg}\n\n🔍 **Debug Info**: Please check the application logs for more details."
            
            return assistant_content, tools_called, conversation
    else:
        # Placeholder for other providers
        assistant_content = f"This is a placeholder response for {provider}. Integration coming soon."
        return assistant_content, tools_called, conversation

# REMOVED: execute_task_sequence and prepare_task_arguments methods - they cause hallucinations

@router.post("/conversations/{conversation_id}/messages", response_model=MessageRead)
async def send_message(
    conversation_id: int,
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    ### Send a Message & Direct AI Execution
    
    This is the core "command center" endpoint of Arrotech Hub. When you send a message here, the Hub's **Execution Orchestrator** takes over to perform autonomous tasks.
    
    **The Orchestration Lifecycle:**
    1.  **Intent Analysis:** The AI determines if your request requires action (tool calling) or just a textual response.
    2.  **Semantic Tool Selection:** The system selects relevant tools from over 50+ integrations based on your query.
    3.  **Autonomous Execution:** The AI calls tools (e.g., Slack, M-Pesa, HubSpot) in a loop until your goal is reached.
    4.  **Context Management:** Every message is saved, ensuring the AI remembers previous steps in the chain.
    
    **Usage Examples:**
    - *Simple Chat:* "Explain how Arrotech MCP works."
    - *Automation:* "Find all 'In Progress' tickets in Jira and post a summary to Slack #prod-updates."
    - *Platform Query:* "Who are my top 5 customers in HubSpot by revenue?"
    
    ---
    **Note on Providers:** You can explicitly request a provider like `gpt-4o` or `claude-3-5-sonnet` using the `provider` field, or leave it null to use your default.
    """
    print(f"📨 Processing message in conversation {conversation_id}")
    
    # Validate conversation exists and user has access
    conversation = await get_conversation_or_404(conversation_id, user.id, db)
    
    # Create user message
    user_message = Message(
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content=data.content,
        status=MessageStatus.COMPLETED
    )
    db.add(user_message)
    await db.commit()
    await db.refresh(user_message)
    
    # Use ExecutionOrchestrator for masterclass-level processing
    orchestrator = ExecutionOrchestrator(db, user, conversation_id)
    
    try:
        # Process message with full orchestration
        final_content, tools_called, tokens_used = await orchestrator.process_message(data.content, data.provider)
        
        # Create final assistant message
        assistant_message = Message(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=final_content,
            status=MessageStatus.COMPLETED,
            tools_called=tools_called if tools_called else None,
            tokens_used=tokens_used
        )
        db.add(assistant_message)
        await db.commit()
        await db.refresh(assistant_message)
        
        print(f"✅ Message processed successfully")
        return MessageRead.from_orm(assistant_message)
        
    except Exception as e:
        print(f"❌ Error processing message: {e}")
        import traceback
        print(f"❌ Traceback: {traceback.format_exc()}")
        
        # Create error message
        error_message = Message(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content="I apologize, but I encountered an issue processing your request. Please try again.",
            status=MessageStatus.COMPLETED,
            error_message=str(e)
        )
        db.add(error_message)
        await db.commit()
        await db.refresh(error_message)
        
        return MessageRead.from_orm(error_message)


@router.post("/conversations/{conversation_id}/messages/stream")
async def send_message_stream(
    conversation_id: int,
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    ### Stream AI Response via Server-Sent Events (SSE)
    
    This endpoint streams the AI's response in real-time, providing visibility into:
    - **Thinking steps**: What the AI is analyzing
    - **Tool executions**: Which tools are being called and their results
    - **Content tokens**: The response text, streamed token by token
    
    **SSE Event Types:**
    - `thinking` — AI reasoning step (content field)
    - `tool_start` — Tool execution beginning (tool, args fields)
    - `tool_result` — Tool execution complete (tool, success, summary fields)
    - `content_delta` — Single token of response text (delta field)
    - `content` — Full response text when streaming isn't supported (content field)
    - `done` — Stream complete (message_id, tokens_used, tools_called fields)
    - `error` — Error occurred (error field)
    """
    # Validate conversation
    conversation = await get_conversation_or_404(conversation_id, user.id, db)
    
    # Save user message immediately
    user_message = Message(
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content=data.content,
        status=MessageStatus.COMPLETED
    )
    db.add(user_message)
    await db.commit()
    await db.refresh(user_message)

    async def event_generator():
        """Generate SSE events from the orchestrator stream."""
        orchestrator = ExecutionOrchestrator(db, user, conversation_id)
        accumulated_content = ""
        accumulated_reasoning = ""
        tools_called_final = []
        tokens_used_final = 0
        
        try:
            async for event in orchestrator.process_message_stream(
                data.content, 
                data.provider or "ollama",
                use_reasoning=data.use_reasoning,
                use_search=data.use_search
            ):
                event_type = event.get("type", "")
                
                # Accumulate content for final DB save
                if event_type == "content_delta":
                    accumulated_content += event.get("delta", "")
                elif event_type == "content":
                    accumulated_content = event.get("content", "")
                elif event_type == "reasoning_delta":
                    accumulated_reasoning += event.get("delta", "")
                elif event_type == "done":
                    tools_called_final = event.get("tools_called", [])
                    tokens_used_final = event.get("tokens_used", 0)
                
                # Yield SSE-formatted event
                yield f"data: {json.dumps(event)}\n\n"
            
            # Save final assistant message to DB
            content_to_save = accumulated_content
            if accumulated_reasoning:
                content_to_save = f"<think>\n{accumulated_reasoning}\n</think>\n\n{accumulated_content}"

            if content_to_save:
                assistant_message = Message(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=content_to_save,
                    status=MessageStatus.COMPLETED,
                    tools_called=tools_called_final if tools_called_final else None,
                    tokens_used=tokens_used_final
                )
                db.add(assistant_message)
                await db.commit()
                await db.refresh(assistant_message)
                
                # Send the message_id back to the client in a final event
                yield f"data: {json.dumps({'type': 'message_saved', 'message_id': assistant_message.id})}\n\n"
        
        except Exception as e:
            print(f"❌ SSE stream error: {e}")
            import traceback
            print(f"❌ Traceback: {traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
            
            # Save error message to DB
            error_msg = Message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content="I apologize, but I encountered an issue processing your request. Please try again.",
                status=MessageStatus.COMPLETED,
                error_message=str(e)
            )
            db.add(error_msg)
            await db.commit()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.put("/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: int,
    data: ConversationUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Update a conversation title."""
    # First check if conversation exists and belongs to user
    result = await db.execute(
        select(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Update the conversation title
    conversation.title = data.title
    await db.commit()
    await db.refresh(conversation)

    return {
        "success": True,
        "data": {
            "id": conversation.id,
            "title": conversation.title,
            "is_active": conversation.is_active,
            "created_at": conversation.created_at.isoformat() if conversation.created_at else "",
            "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else ""
        },
        "message": "Conversation updated successfully"
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Delete a conversation and all its messages."""
    # First check if conversation exists and belongs to user
    result = await db.execute(
        select(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Delete all messages in the conversation first
    await db.execute(
        delete(Message).where(Message.conversation_id == conversation_id)
    )

    # Delete the conversation
    await db.execute(
        delete(Conversation).where(Conversation.id == conversation_id)
    )

    await db.commit()

    return {
        "success": True,
        "message": "Conversation deleted successfully",
        "conversation_id": conversation_id
    }


@router.get("/ollama/status")
async def check_ollama_status():
    """Check Ollama service status."""
    import os

    import aiohttp
    
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ollama_base_url}/api/tags", timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 200:
                    data = await response.json()
                    models = [model["name"] for model in data.get("models", [])]
                    return {
                        "status": "running",
                        "models": models,
                        "total_models": len(models),
                        "base_url": ollama_base_url
                    }
                else:
                    return {
                        "status": "error",
                        "message": f"Ollama returned status {response.status}",
                        "models": [],
                        "base_url": ollama_base_url
                    }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Cannot connect to Ollama: {str(e)}",
            "models": [],
            "base_url": ollama_base_url
        }


@router.get("/ollama/diagnostic")
async def ollama_diagnostic():
    """Comprehensive Ollama diagnostic."""
    try:
        # Test connection
        connection_test = await test_ollama_connection()

        # Get system info
        import os
        import platform

        from ..config import settings
        
        system_info = {
            "platform": platform.system(),
            "python_version": platform.python_version(),
            "ollama_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            "configured_model": settings.OLLAMA_MODEL
        }

        # Test model availability
        current_model = settings.OLLAMA_MODEL
        model_test = {
            "current_model": current_model,
            "available": current_model in connection_test.get("models", [])
        }

        return {
            "success": True,
            "connection": connection_test,
            "system": system_info,
            "model": model_test,
            "recommendations": []
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "recommendations": [
                "Check if Ollama is installed and running",
                "Verify the model is available: ollama list",
                "Check network connectivity to localhost:11434",
                f"Try pulling the configured model: ollama pull {settings.OLLAMA_MODEL}"
            ]
        }


@router.post("/test/direct-response")
async def test_direct_response(
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Test direct response generation without tools."""
    try:
        from ..services.execution_orchestrator import ExecutionOrchestrator

        # Create a temporary conversation for testing
        conversation = Conversation(
            user_id=user.id,
            title="Test Conversation"
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
        
        # Test the orchestrator
        orchestrator = ExecutionOrchestrator(db, user, conversation.id)
        response, tools_called = await orchestrator.process_message(data.content, data.provider or "ollama")
        
        # Clean up test conversation
        await db.delete(conversation)
        await db.commit()
        
        return {
            "success": True,
            "response": response,
            "tools_called": tools_called,
            "conversation_id": conversation.id
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "response": "I apologize, but I encountered an issue processing your request. Please try again."
        }


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    ### Fetch Message History
    
    Retrieves the complete chronological list of messages in a conversation. This includes user prompts, assistant responses, and "tool" messages (the technical results of API calls made by the AI).
    
    **Understanding Roles:**
    - `user`: Your input.
    - `assistant`: The AI's response to you.
    - `tool`: Internal technical data from integrations (e.g., raw JSON from HubSpot). Usually hidden from end-users but vital for debugging.
    - `system`: Architectural instructions provided to the AI.
    """
    # First check if conversation exists and belongs to user
    result = await db.execute(
        select(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Get messages for this conversation
    result = await db.execute(
        select(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    return {
        "success": True,
        "data": [
            {
                "id": msg.id,
                "conversation_id": msg.conversation_id,
                "role": msg.role,
                "content": msg.content,
                "status": msg.status,
                "tokens_used": msg.tokens_used,
                "tools_called": msg.tools_called,
                "error_message": msg.error_message,
                "created_at": msg.created_at.isoformat() if msg.created_at else ""
            }
            for msg in messages
        ]
    }


@router.get("/providers")
async def get_available_providers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get available LLM providers."""
    from ..services.llm_service import llm_service

    # Get all configured providers
    # Get all configured system providers
    available_providers = llm_service.get_available_providers()
    
    # Check for User BYOK keys
    user_settings = await get_or_create_user_settings(db, current_user.id)
    
    if user_settings.openai_api_key:
        if "openai" not in available_providers:
            available_providers.append("openai")
            
    if user_settings.anthropic_api_key:
        if "anthropic" not in available_providers:
            available_providers.append("anthropic")
            
    if user_settings.gemini_api_key:
        if "gemini" not in available_providers:
            available_providers.append("gemini")
            
    if user_settings.huggingface_api_key:
        if "huggingface" not in available_providers:
            available_providers.append("huggingface")
            
    if user_settings.together_api_key:
        if "togetherai" not in available_providers:
            available_providers.append("togetherai")

    # Define all possible providers with their display names
    all_providers = {
        "openai": "OpenAI GPT",
        "gemini": "Google Gemini",
        "ollama": "Ollama (Local)",
        "huggingface": "Hugging Face",
        "togetherai": "Together AI",
        "anthropic": "Anthropic Claude"
    }

    # Return all providers with their availability status
    providers_list = []
    for provider_id, display_name in all_providers.items():
        providers_list.append({
            "id": provider_id,
            "name": display_name,
            "available": provider_id in available_providers
        })

    return {
        "success": True,
        "data": {
            "providers": [p["id"] for p in providers_list if p["available"]],
            "all_providers": providers_list,
            "default": settings.DEFAULT_LLM_PROVIDER
        }
    }


@router.get("/tools")
async def get_available_tools(
    include_all: bool = True,
    all: bool = True,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get available MCP tools."""
    try:
        # For chat tools, we default to ALL tools for discovery
        discovery_mode = include_all or all
        
        tools = await dynamic_tool_registry.get_user_tools(current_user.id, db, include_all=discovery_mode)

        return {
            "success": True,
            "data": {
                "tools": tools,
                "total": len(tools),
                "description": "Dynamic tools based on platform capabilities and user connections"
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get tools: {str(e)}"
        )


@router.get("/download/{conversation_id}/{message_id}/{filename}")
async def download_file(
    conversation_id: int,
    message_id: int,
    filename: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Download a file from a specific message."""
    try:
        # Verify conversation belongs to user
        result = await db.execute(
            select(Conversation)
            .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
        )
        conversation = result.scalar_one_or_none()

        if not conversation:
            raise HTTPException(
                status_code=404, detail="Conversation not found")

        # Get the specific message
        result = await db.execute(
            select(Message)
            .filter(Message.id == message_id, Message.conversation_id == conversation_id)
        )
        message = result.scalar_one_or_none()

        if not message:
            raise HTTPException(status_code=404, detail="Message not found")

        # Check if message has tools_called with file content
        if not message.tools_called:
            raise HTTPException(
                status_code=404, detail="No file content found in message")

        # Find the file_management tool result
        file_content = None
        for tool_call in message.tools_called:
            if tool_call.get("name") == "file_management" and tool_call.get("result", {}).get("success"):
                result_data = tool_call["result"]
                if "content" in result_data:
                    file_content = result_data["content"]
                    break

        if not file_content:
            raise HTTPException(
                status_code=404, detail="No file content found")

        # Decode base64 content
        try:
            file_bytes = base64.b64decode(file_content)
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid file content: {str(e)}")

        # Determine content type based on filename
        content_type = "application/octet-stream"
        if filename.endswith('.pdf'):
            content_type = "application/pdf"
        elif filename.endswith('.png'):
            content_type = "image/png"
        elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
            content_type = "image/jpeg"
        elif filename.endswith('.txt'):
            content_type = "text/plain"
        elif filename.endswith('.html'):
            content_type = "text/html"

        return Response(
            content=file_bytes,
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Length": str(len(file_bytes))
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download file: {str(e)}"
        )

# Add this endpoint to get file information


@router.get("/files/{conversation_id}/{message_id}")
async def get_file_info(
    conversation_id: int,
    message_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Get file information from a specific message."""
    try:
        # Verify conversation belongs to user
        result = await db.execute(
            select(Conversation)
            .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
        )
        conversation = result.scalar_one_or_none()

        if not conversation:
            raise HTTPException(
                status_code=404, detail="Conversation not found")

        # Get the specific message
        result = await db.execute(
            select(Message)
            .filter(Message.id == message_id, Message.conversation_id == conversation_id)
        )
        message = result.scalar_one_or_none()

        if not message:
            raise HTTPException(status_code=404, detail="Message not found")

        # Extract file information from tools_called
        files = []
        if message.tools_called:
            for tool_call in message.tools_called:
                if tool_call.get("name") == "file_management" and tool_call.get("result", {}).get("success"):
                    result_data = tool_call["result"]
                    if "filename" in result_data:
                        files.append({
                            "filename": result_data["filename"],
                            "size": result_data.get("size", 0),
                            "method": result_data.get("method", "unknown"),
                            "download_url": f"/api/chat/download/{conversation_id}/{message_id}/{result_data['filename']}"
                        })

        return {
            "success": True,
            "data": {
                "message_id": message_id,
                "conversation_id": conversation_id,
                "files": files
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get file info: {str(e)}"
        )


@router.post("/conversations/{conversation_id}/validate-tool")
async def validate_tool_call(
    conversation_id: int,
    tool_call: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Validate a tool call before execution."""
    try:
        # Validate conversation access
        conversation = await get_conversation_or_404(conversation_id, user.id, db)
        
        tool_name = tool_call.get("tool")
        arguments = tool_call.get("arguments", {})
        
        if not tool_name:
            raise HTTPException(status_code=400, detail="Missing tool name")
        
        # Use ToolRouter for validation
        tool_router = ToolRouter(user, db)
        tool = await tool_router.get_tool_by_name(tool_name)
        if not tool:
            raise HTTPException(status_code=404, detail=f"Tool {tool_name} not found")
        
        # Validate arguments
        validation_result = await tool_router.validate_tool_arguments(tool_name, arguments)
        
        return {
            "valid": validation_result["valid"],
            "errors": validation_result["errors"],
            "corrected_arguments": validation_result.get("corrected_arguments"),
            "tool_description": tool.get("description", ""),
            "tool_schema": tool.get("inputSchema", {})
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/conversations/{conversation_id}/explain-intent")
async def explain_intent(
    conversation_id: int,
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Explain the intent classification for a user message."""
    try:
        # Validate conversation access
        conversation = await get_conversation_or_404(conversation_id, user.id, db)
        
        # Use IntentProcessor for explanation
        intent_processor = IntentProcessor(user, db)
        explanation = await intent_processor.explain_intent(data.content)
        
        return explanation
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/conversations/{conversation_id}/explain-tools")
async def explain_relevant_tools(
    conversation_id: int,
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Explain which tools are relevant for a user message."""
    try:
        # Validate conversation access
        conversation = await get_conversation_or_404(conversation_id, user.id, db)
        
        # Use ToolRouter for tool explanation
        tool_router = ToolRouter(user, db)
        relevant_tools = await tool_router.get_relevant_tools(data.content)
        
        tool_explanations = []
        for tool in relevant_tools:
            tool_explanations.append({
                "name": tool.get("name"),
                "description": tool.get("description"),
                "relevance_score": tool.get("relevance_score", 0),
                "platform": tool.get("platform", "universal"),
                "schema": tool.get("inputSchema", {})
            })
        
        return {
            "user_input": data.content,
            "relevant_tools": tool_explanations,
            "total_tools_found": len(relevant_tools),
            "explanation": f"Found {len(relevant_tools)} relevant tools for your request."
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


async def get_conversation_or_404(conversation_id: int, user_id: int, db: AsyncSession) -> Conversation:
    """Get conversation or raise 404 if not found or user doesn't have access."""
    result = await db.execute(
        select(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation
