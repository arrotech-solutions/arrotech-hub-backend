"""
Coding Agent — Redis Session Store

Stores coding agent session metadata in Redis so that all Uvicorn workers
share a single source of truth.  Every worker reads/writes the same keys.

Key schema:
    agent:session:{session_id}      → JSON-serialized AgentSession
    agent:user_sessions:{user_id}   → Redis SET of session_ids belonging to this user
"""
import json
import logging
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Default TTL: 1 hour.  Extended on every tool call via touch_session().
DEFAULT_TTL = 3600


# ── Pydantic Model ─────────────────────────────────────────────────────

class AgentSession(BaseModel):
    """Serializable session record stored in Redis."""
    session_id: str
    workspace_path: str
    scratchpad_path: str
    container_id: Optional[str] = None
    repo_url: Optional[str] = None
    status: str = "creating"
    created_at: float = Field(default_factory=time.time)
    last_activity_at: float = Field(default_factory=time.time)
    user_id: Optional[str] = None


# ── Key Helpers ────────────────────────────────────────────────────────

def _session_key(session_id: str) -> str:
    return f"agent:session:{session_id}"


def _user_sessions_key(user_id: str) -> str:
    return f"agent:user_sessions:{user_id}"


# ── CRUD Functions ─────────────────────────────────────────────────────

async def save_session(redis, session: AgentSession, ttl: int = DEFAULT_TTL) -> None:
    """Serialize and store a session in Redis with a TTL."""
    key = _session_key(session.session_id)
    value = session.model_dump_json()
    await redis.set(key, value, ex=ttl)

    # Maintain the per-user reverse index
    if session.user_id:
        user_key = _user_sessions_key(session.user_id)
        await redis.sadd(user_key, session.session_id)
        await redis.expire(user_key, ttl * 2)  # generous TTL on the set

    logger.debug(f"Session saved to Redis: {session.session_id}")


async def get_session(redis, session_id: str) -> Optional[AgentSession]:
    """Retrieve a session from Redis.  Returns None if expired or missing."""
    key = _session_key(session_id)
    raw = await redis.get(key)
    if raw is None:
        return None
    return AgentSession.model_validate_json(raw)


async def touch_session(redis, session_id: str, ttl: int = DEFAULT_TTL) -> None:
    """Extend TTL and update last_activity_at.  Call on every tool execution."""
    session = await get_session(redis, session_id)
    if session is None:
        return
    session.last_activity_at = time.time()
    await save_session(redis, session, ttl)


async def delete_session(redis, session_id: str, user_id: Optional[str] = None) -> None:
    """Remove a session from Redis and the user's session set."""
    key = _session_key(session_id)
    await redis.delete(key)

    if user_id:
        user_key = _user_sessions_key(user_id)
        await redis.srem(user_key, session_id)

    logger.debug(f"Session deleted from Redis: {session_id}")


async def update_session(redis, session_id: str, **kwargs) -> Optional[AgentSession]:
    """Fetch, update fields, re-save.  Returns updated session or None."""
    session = await get_session(redis, session_id)
    if session is None:
        return None
    updated = session.model_copy(update=kwargs)
    updated.last_activity_at = time.time()
    await save_session(redis, updated)
    return updated


async def get_user_sessions(redis, user_id: str) -> List[AgentSession]:
    """Get all active sessions for a user (via the reverse-index set)."""
    user_key = _user_sessions_key(user_id)
    session_ids = await redis.smembers(user_key)

    sessions = []
    stale_ids = []

    for sid in session_ids:
        session = await get_session(redis, sid)
        if session and session.status == "active":
            sessions.append(session)
        elif session is None:
            # Session key expired but still in the set — mark for cleanup
            stale_ids.append(sid)

    # Clean up stale entries from the user set
    if stale_ids:
        await redis.srem(user_key, *stale_ids)

    return sessions
