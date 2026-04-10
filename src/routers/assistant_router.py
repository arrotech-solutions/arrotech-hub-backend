"""
Assistant Router — Dedicated endpoints for the AI Assistant widget.

Supports both anonymous (KB-only) and authenticated (KB + tools) access
with tiered rate limiting for abuse protection and conversion incentive.
"""

import logging
import time
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, Connection, ConnectionStatus
from ..routers.auth_router import get_optional_current_user
from ..services.assistant_kb_service import assistant_kb_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant", tags=["assistant"])


# ─── Rate Limiting ────────────────────────────────────────────────────────────

class AssistantRateLimiter:
    """
    Tiered rate limiter for the assistant endpoint.
    
    Anonymous: 5 messages/session + 15 messages/IP/hour
    Authenticated Free: 30 messages/hour
    Authenticated Paid: 100 messages/hour
    """
    
    def __init__(self):
        self._ip_hits: Dict[str, List[float]] = defaultdict(list)
        self._user_hits: Dict[str, List[float]] = defaultdict(list)
        self._session_hits: Dict[str, int] = defaultdict(int)
    
    def _cleanup(self, hits: List[float], window: float) -> List[float]:
        now = time.time()
        return [t for t in hits if now - t < window]
    
    def check_anonymous(self, client_ip: str, session_id: str) -> tuple[bool, str]:
        """Check rate limit for anonymous users. Returns (allowed, reason)."""
        # Session limit: 5 messages per session
        if self._session_hits[session_id] >= 5:
            return False, "You've reached the message limit for this session. Create a free account for unlimited access! 🚀"
        
        # IP hourly limit: 15 messages/hour
        self._ip_hits[client_ip] = self._cleanup(self._ip_hits[client_ip], 3600)
        if len(self._ip_hits[client_ip]) >= 15:
            return False, "Too many requests. Please try again later or create an account for higher limits."
        
        self._session_hits[session_id] += 1
        self._ip_hits[client_ip].append(time.time())
        return True, ""
    
    def check_authenticated(self, user_id: str, tier: str = "free") -> tuple[bool, str]:
        """Check rate limit for authenticated users. Returns (allowed, reason)."""
        limit = 100 if tier in ("pro", "enterprise") else 30
        
        self._user_hits[user_id] = self._cleanup(self._user_hits[user_id], 3600)
        if len(self._user_hits[user_id]) >= limit:
            return False, f"You've reached the hourly limit ({limit} messages). Please wait before sending more."
        
        self._user_hits[user_id].append(time.time())
        return True, ""


rate_limiter = AssistantRateLimiter()


# ─── Request/Response Models ─────────────────────────────────────────────────

class AssistantChatRequest(BaseModel):
    """Request model for assistant chat endpoint."""
    message: str = Field(..., min_length=1, max_length=2000, description="User message")
    conversation_history: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Previous messages in format [{role: 'user'|'assistant', content: '...'}]"
    )
    page_context: str = Field(default="", description="Current page the user is viewing")
    session_id: str = Field(default="", description="Anonymous session ID for rate limiting")


class AssistantChatResponse(BaseModel):
    """Response model for assistant chat endpoint."""
    response: str
    sources: List[Dict[str, Any]] = []
    suggested_followups: List[str] = []
    tokens_used: int = 0
    is_authenticated: bool = False
    rate_limit_remaining: Optional[int] = None


class AssistantFeedbackRequest(BaseModel):
    """Request model for feedback on assistant responses."""
    message_content: str = Field(..., description="The assistant response being rated")
    helpful: bool = Field(..., description="Whether the response was helpful")
    user_query: str = Field(default="", description="The user's original query")


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=AssistantChatResponse)
async def assistant_chat(
    request: Request,
    data: AssistantChatRequest,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user)
):
    """
    ### AI Assistant Chat — RAG-powered responses
    
    Supports both anonymous and authenticated users:
    - **Anonymous**: KB-only responses + tool discovery. Rate limited to 5 messages/session.
    - **Authenticated**: KB + connected tool context + full intelligence. Rate limited by tier.
    
    The assistant queries the pre-ingested Arrotech Knowledge Base via Pinecone
    and generates grounded responses using the LLM.
    """
    client_ip = request.client.host if request.client else "unknown"
    
    # ── Rate Limiting ──
    if user:
        tier = getattr(user, "subscription_tier", "free")
        tier_str = tier.value if hasattr(tier, "value") else str(tier)
        allowed, reason = rate_limiter.check_authenticated(str(user.id), tier_str)
    else:
        session_id = data.session_id or f"anon_{client_ip}"
        allowed, reason = rate_limiter.check_anonymous(client_ip, session_id)
    
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    # ── Resolve user context ──
    user_name = ""
    connected_tools = []
    is_authenticated = False
    
    if user:
        is_authenticated = True
        user_name = getattr(user, "name", "") or ""
        
        # Fetch connected tools for authenticated users
        try:
            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user.id,
                    Connection.status == ConnectionStatus.ACTIVE
                )
            )
            connections = result.scalars().all()
            connected_tools = [conn.platform for conn in connections if conn.platform]
        except Exception as e:
            logger.warning(f"[ASSISTANT] Error fetching connections: {e}")

    # ── Generate RAG response ──
    try:
        result = await assistant_kb_service.generate_rag_response(
            user_message=data.message,
            conversation_history=data.conversation_history,
            page_context=data.page_context,
            user_name=user_name,
            is_authenticated=is_authenticated,
            connected_tools=connected_tools
        )
        
        return AssistantChatResponse(
            response=result.get("response", "I'm sorry, I couldn't generate a response."),
            sources=result.get("sources", []),
            suggested_followups=result.get("suggested_followups", []),
            tokens_used=result.get("tokens_used", 0),
            is_authenticated=is_authenticated
        )
    except Exception as e:
        logger.error(f"[ASSISTANT] Error generating response: {e}")
        import traceback
        logger.error(f"[ASSISTANT] Traceback: {traceback.format_exc()}")
        
        return AssistantChatResponse(
            response="I'm having trouble right now. Please try again in a moment, or contact support at info@arrotechsolutions.com.",
            sources=[],
            suggested_followups=["What is Arrotech Hub?", "What integrations do you offer?"],
            tokens_used=0,
            is_authenticated=is_authenticated
        )


@router.get("/capabilities")
async def get_assistant_capabilities(
    user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    ### Platform Capabilities — Tool Discovery
    
    Returns a structured list of all platform capabilities grouped by category.
    For authenticated users, shows which tools are connected vs available.
    """
    connected_tools = []
    
    if user:
        try:
            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user.id,
                    Connection.status == ConnectionStatus.ACTIVE
                )
            )
            connections = result.scalars().all()
            connected_tools = [conn.platform for conn in connections if conn.platform]
        except Exception as e:
            logger.warning(f"[ASSISTANT] Error fetching connections: {e}")
    
    capabilities = assistant_kb_service.get_capabilities_structured(connected_tools)
    
    return {
        "success": True,
        "data": {
            "categories": capabilities,
            "total_integrations": sum(len(cat["tools"]) for cat in capabilities),
            "connected_count": len(connected_tools),
            "is_authenticated": user is not None
        }
    }


@router.post("/feedback")
async def submit_assistant_feedback(
    data: AssistantFeedbackRequest,
    request: Request,
    user: Optional[User] = Depends(get_optional_current_user)
):
    """
    ### Submit Feedback on Assistant Response
    
    Captures thumbs up/down on responses for quality tracking.
    Works for both anonymous and authenticated users.
    """
    client_ip = request.client.host if request.client else "unknown"
    user_id = str(user.id) if user else f"anon_{client_ip}"
    
    # Log the feedback (in production, you'd store this in a database table)
    feedback_type = "positive" if data.helpful else "negative"
    logger.info(
        f"[ASSISTANT FEEDBACK] {feedback_type} | "
        f"User: {user_id} | "
        f"Query: {data.user_query[:100]} | "
        f"Response: {data.message_content[:100]}"
    )
    
    return {
        "success": True,
        "message": "Thank you for your feedback! It helps us improve."
    }
