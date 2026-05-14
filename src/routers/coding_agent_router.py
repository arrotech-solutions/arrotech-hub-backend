"""
Coding Agent Router — REST API for managing coding agent sessions.

Endpoints:
  POST   /coding-agent/sessions           — Create a new session
  GET    /coding-agent/sessions/{id}       — Get session status
  DELETE /coding-agent/sessions/{id}       — Destroy a session
  POST   /coding-agent/sessions/{id}/tools — Execute a tool within a session
"""
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, SubscriptionTier
from .auth_router import get_current_user

router = APIRouter(prefix="/coding-agent", tags=["coding-agent"])


# ── Request / Response Models ──────────────────────────────────────────

class SessionCreateRequest(BaseModel):
    repo_url: Optional[str] = Field(None, description="Git URL to clone into workspace")
    github_token: Optional[str] = Field(None, description="GitHub PAT for private repos")


class ToolExecuteRequest(BaseModel):
    tool_name: str = Field(..., description="Name of the coding tool (e.g. coding_file_read)")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    approved: bool = Field(False, description="Whether the user explicitly approved this execution")

class ChatExecuteRequest(BaseModel):
    messages: list = Field(..., description="List of message dicts (role, content, etc)")
    model_override: Optional[str] = Field(None, description="Optional model override")



# ── Dependencies ───────────────────────────────────────────────────────

def get_redis(request: Request):
    """Get the async Redis client from app.state (initialized per-worker in lifespan)."""
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis is not available. Cannot manage coding agent sessions.",
        )
    return redis


# ── Tier Guard ─────────────────────────────────────────────────────────

def _require_pro_tier(user: User):
    """Ensure user is on Pro or Enterprise tier."""
    allowed = {SubscriptionTier.PRO, SubscriptionTier.ENTERPRISE}
    if hasattr(SubscriptionTier, "BUSINESS"):
        allowed.add(SubscriptionTier.BUSINESS)
    if user.subscription_tier not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Coding Agent requires a Pro or Enterprise subscription. "
                   "Upgrade at Settings → Billing.",
        )


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("/sessions", response_model=Dict[str, Any])
async def create_session(
    data: SessionCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """Create a new coding agent session with optional repo clone."""
    _require_pro_tier(user)

    from ..services.coding_agent_sandbox import coding_agent_sandbox

    session_id = str(uuid.uuid4())
    try:
        session = await coding_agent_sandbox.create_session(
            redis,
            session_id=session_id,
            repo_url=data.repo_url,
            github_token=data.github_token,
            user_id=str(user.id),
        )
        return {
            "success": True,
            "session_id": session.session_id,
            "status": session.status,
            "workspace_path": session.workspace_path,
            "message": "Coding agent session created",
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create session: {str(e)}",
        )


@router.get("/sessions/{session_id}", response_model=Dict[str, Any])
async def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """Get the current status of a coding agent session."""
    from ..services.coding_agent_sandbox import coding_agent_sandbox

    session = await coding_agent_sandbox.get_session(redis, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.user_id != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your session")

    return {
        "session_id": session.session_id,
        "status": session.status,
        "repo_url": session.repo_url,
        "has_container": session.container_id is not None,
        "created_at": session.created_at,
        "last_activity_at": session.last_activity_at,
    }


@router.delete("/sessions/{session_id}", response_model=Dict[str, Any])
async def destroy_session(
    session_id: str,
    user: User = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """Destroy a coding agent session — stops container and deletes workspace."""
    from ..services.coding_agent_sandbox import coding_agent_sandbox

    session = await coding_agent_sandbox.get_session(redis, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.user_id != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your session")

    await coding_agent_sandbox.destroy_session(redis, session_id)
    return {"success": True, "session_id": session_id, "message": "Session destroyed"}


@router.post("/sessions/{session_id}/tools", response_model=Dict[str, Any])
async def execute_tool(
    session_id: str,
    data: ToolExecuteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """Execute a coding agent tool within an active session."""
    _require_pro_tier(user)

    from ..services.coding_agent_sandbox import coding_agent_sandbox

    session = await coding_agent_sandbox.get_session(redis, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.user_id != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your session")

    if not data.tool_name.startswith("coding_"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tool name must start with 'coding_'",
        )

    from ..services.coding_agent_executor import coding_agent_executor

    # Inject session_id into arguments
    arguments = {**data.arguments, "session_id": session_id}
    result = await coding_agent_executor.execute(
        data.tool_name, 
        arguments, 
        user, 
        db, 
        redis,
        approved=data.approved
    )
    return result

@router.post("/sessions/{session_id}/chat", response_model=Dict[str, Any])
async def execute_chat(
    session_id: str,
    data: ChatExecuteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """Execute a single LLM chat completion with Coding Agent tools injected."""
    _require_pro_tier(user)

    from ..services.coding_agent_sandbox import coding_agent_sandbox

    session = await coding_agent_sandbox.get_session(redis, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.user_id != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your session")

    from ..services.coding_agent_llm import coding_agent_llm_factory
    
    llm_service = coding_agent_llm_factory(db, user)
    result = await llm_service.generate_response(data.messages, model_override=data.model_override)
    
    return result
