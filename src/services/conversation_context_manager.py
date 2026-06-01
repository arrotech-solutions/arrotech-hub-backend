"""
Conversation Context Manager (CCM) for Stateless Messaging Platforms.

Provides multi-turn conversation memory for WhatsApp & Telegram by persisting
chat history in a dual-layer store: Redis (hot, fast) → PostgreSQL (cold, durable).

Session keys follow the pattern:
    ccm:{platform}:{owner_user_id}:{sender_id}

This guarantees complete multi-tenant isolation — Business A's customers never
see Business B's data, even if they share the same sender phone number across
different WhatsApp Business accounts.

Usage::

    from .conversation_context_manager import context_manager

    session = await context_manager.get_or_create_session(
        platform="whatsapp",
        owner_user_id="uuid-of-business-owner",
        sender_id="+254700000000",
    )
    await context_manager.add_message(session, "user", "What are your prices?")
    messages = await context_manager.get_context_messages(session, system_prompt="You are ...")
    # → [{"role": "system", ...}, {"role": "user", "content": "What are your prices?"}]
    await context_manager.add_message(session, "assistant", "We offer Basic ($10)...")
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─── Default configuration (overridable via config.py settings) ───────────────

CCM_MAX_MESSAGES = 20           # Sliding window size
CCM_MAX_TOKENS = 2000           # Token budget for context
CCM_SESSION_TTL = 7200          # Redis TTL in seconds (2 hours)
CCM_ENABLE_SUMMARIZATION = False
CCM_SUMMARY_THRESHOLD = 30     # Summarize when history exceeds this count
CCM_RESET_KEYWORDS = [          # Keywords that clear the session
    "reset", "start over", "new conversation", "clear", "restart",
    "anza upya",  # Swahili: "start fresh"
]


@dataclass
class ConversationSession:
    """Represents an active conversation session."""
    session_key: str
    platform: str                           # "whatsapp" | "telegram"
    owner_user_id: str                      # Business owner UUID
    sender_id: str                          # End-user phone/chat_id
    messages: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""                       # Compressed summary of older messages
    message_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_activity_at: float = 0.0           # Unix timestamp
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for Redis storage."""
        return {
            "session_key": self.session_key,
            "platform": self.platform,
            "owner_user_id": self.owner_user_id,
            "sender_id": self.sender_id,
            "messages": self.messages,
            "summary": self.summary,
            "message_count": self.message_count,
            "metadata": self.metadata,
            "last_activity_at": self.last_activity_at,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationSession":
        """Deserialize from Redis storage."""
        return cls(
            session_key=data.get("session_key", ""),
            platform=data.get("platform", ""),
            owner_user_id=data.get("owner_user_id", ""),
            sender_id=data.get("sender_id", ""),
            messages=data.get("messages", []),
            summary=data.get("summary", ""),
            message_count=data.get("message_count", 0),
            metadata=data.get("metadata", {}),
            last_activity_at=data.get("last_activity_at", 0.0),
            created_at=data.get("created_at", 0.0),
        )


def _build_session_key(platform: str, owner_user_id: str, sender_id: str) -> str:
    """Build a deterministic session key."""
    # Normalise phone numbers: strip whitespace, ensure consistent format
    sender_clean = sender_id.strip().replace(" ", "")
    return f"ccm:{platform}:{owner_user_id}:{sender_clean}"


def _estimate_tokens(text: str) -> int:
    """Fast token estimation (~4 chars per token). Falls back from tiktoken."""
    try:
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


class ConversationContextManager:
    """
    Multi-tenant conversation context manager for stateless messaging platforms.

    Storage architecture:
        Redis  → fast read/write for active sessions (TTL-based expiry)
        PostgreSQL → durable persistence for analytics, audit, session recovery
    """

    def __init__(self):
        self._redis = None
        self._config_loaded = False

    # ─── Lazy Redis access ────────────────────────────────────────────────

    def _get_redis(self):
        """Get the Redis client from the existing cache service (synchronous)."""
        if self._redis is None:
            try:
                from .cache_service import cache_service
                self._redis = cache_service.redis_client
                if self._redis is None:
                    logger.debug("[CCM] Redis client not yet initialized in cache_service")
            except Exception as e:
                logger.warning(f"[CCM] Redis unavailable, operating in DB-only mode: {e}")
        return self._redis

    def _load_config(self):
        """Load configuration from settings (once)."""
        if self._config_loaded:
            return
        try:
            from ..config import settings
            global CCM_MAX_MESSAGES, CCM_MAX_TOKENS, CCM_SESSION_TTL
            global CCM_ENABLE_SUMMARIZATION, CCM_SUMMARY_THRESHOLD
            CCM_MAX_MESSAGES = getattr(settings, "CCM_MAX_MESSAGES", CCM_MAX_MESSAGES)
            CCM_MAX_TOKENS = getattr(settings, "CCM_MAX_TOKENS", CCM_MAX_TOKENS)
            CCM_SESSION_TTL = getattr(settings, "CCM_SESSION_TTL", CCM_SESSION_TTL)
            CCM_ENABLE_SUMMARIZATION = getattr(settings, "CCM_ENABLE_SUMMARIZATION", CCM_ENABLE_SUMMARIZATION)
            CCM_SUMMARY_THRESHOLD = getattr(settings, "CCM_SUMMARY_THRESHOLD", CCM_SUMMARY_THRESHOLD)
        except Exception:
            pass
        self._config_loaded = True

    # ─── Public API ───────────────────────────────────────────────────────

    async def get_or_create_session(
        self,
        platform: str,
        owner_user_id: str,
        sender_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConversationSession:
        """
        Get an existing session or create a new one.

        Args:
            platform: "whatsapp" or "telegram"
            owner_user_id: UUID of the business owner (multi-tenant key)
            sender_id: End-user identifier (phone number or chat_id)
            metadata: Optional metadata (contact name, profile, etc.)

        Returns:
            ConversationSession instance
        """
        self._load_config()
        session_key = _build_session_key(platform, owner_user_id, sender_id)

        # 1. Try Redis (hot cache)
        session = self._load_from_redis(session_key)
        if session:
            logger.debug(f"[CCM] Session loaded from Redis: {session_key}")
            # Merge any new metadata
            if metadata:
                session.metadata.update(metadata)
            return session

        # 2. Try PostgreSQL (cold storage)
        session = await self._load_from_db(session_key)
        if session:
            logger.debug(f"[CCM] Session loaded from PostgreSQL: {session_key}")
            # Re-warm Redis
            self._save_to_redis(session)
            if metadata:
                session.metadata.update(metadata)
            return session

        # 3. Create new session
        now = time.time()
        session = ConversationSession(
            session_key=session_key,
            platform=platform,
            owner_user_id=owner_user_id,
            sender_id=sender_id,
            messages=[],
            summary="",
            message_count=0,
            metadata=metadata or {},
            last_activity_at=now,
            created_at=now,
        )
        logger.info(f"[CCM] New session created: {session_key}")
        return session

    async def add_message(
        self,
        session: ConversationSession,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Append a message to the conversation session.

        Idempotent — if the last message in the session has the same role and
        content, the call is silently skipped. This prevents duplicates when
        both the auto-reply engine and the workflow trigger fire for the same
        incoming message.

        Args:
            session: The active session
            role: "user" or "assistant"
            content: Message text
            metadata: Optional per-message metadata
        """
        if not content or not content.strip():
            return

        clean_content = content.strip()

        # ── Deduplication: skip if last message is identical ──
        if session.messages:
            last = session.messages[-1]
            if last.get("role") == role and last.get("content") == clean_content:
                logger.debug(f"[CCM] Skipping duplicate {role} message for {session.session_key}")
                return

        msg = {
            "role": role,
            "content": clean_content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            msg["metadata"] = metadata

        session.messages.append(msg)
        session.message_count += 1
        session.last_activity_at = time.time()

        # Enforce sliding window
        if len(session.messages) > CCM_MAX_MESSAGES * 2:
            # Keep the most recent messages; optionally summarize dropped ones
            if CCM_ENABLE_SUMMARIZATION and len(session.messages) > CCM_SUMMARY_THRESHOLD:
                await self._summarize_old_messages(session)
            else:
                # Simple truncation — keep last N messages
                session.messages = session.messages[-CCM_MAX_MESSAGES:]

        # Persist to both stores
        self._save_to_redis(session)
        await self._save_to_db(session)

    async def get_context_messages(
        self,
        session: ConversationSession,
        max_messages: Optional[int] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """
        Build the optimized message list for LLM consumption.

        Returns messages in OpenAI chat format:
            [{"role": "system", "content": "..."}, {"role": "user", ...}, ...]

        The method applies both a message count limit and a token budget to
        ensure we stay within the LLM's context window.

        Args:
            session: The active session
            max_messages: Override for sliding window size
            max_tokens: Override for token budget
            system_prompt: System prompt to prepend

        Returns:
            List of message dicts ready for llm_service.chat_completion()
        """
        limit = max_messages or CCM_MAX_MESSAGES
        token_budget = max_tokens or CCM_MAX_TOKENS

        messages = []

        # 1. Start with system prompt
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
            token_budget -= _estimate_tokens(system_prompt)

        # 2. If we have a summary of older messages, inject it as a system context
        if session.summary:
            summary_msg = (
                f"Previous conversation summary:\n{session.summary}"
            )
            messages.append({"role": "system", "content": summary_msg})
            token_budget -= _estimate_tokens(summary_msg)

        # 3. Add recent messages within token budget (newest first, then reverse)
        recent = session.messages[-limit:] if len(session.messages) > limit else session.messages
        selected = []
        tokens_used = 0

        for msg in reversed(recent):
            msg_tokens = _estimate_tokens(msg.get("content", ""))
            if tokens_used + msg_tokens > token_budget:
                break
            selected.insert(0, {"role": msg["role"], "content": msg["content"]})
            tokens_used += msg_tokens

        messages.extend(selected)
        return messages

    async def clear_session(self, session: ConversationSession) -> None:
        """
        Clear all messages from a session (user requested reset).
        The session itself remains but history is wiped.
        """
        session.messages = []
        session.summary = ""
        session.message_count = 0
        session.last_activity_at = time.time()
        session.metadata.pop("cart", None)
        session.metadata.pop("pending_confirmation", None)
        session.metadata.pop("order_confirmed", None)
        session.metadata.pop("welcome_sent", None)

        self._save_to_redis(session)
        await self._save_to_db(session)
        logger.info(f"[CCM] Session cleared: {session.session_key}")

    def is_reset_command(self, message: str) -> bool:
        """Check if the message is a session reset command."""
        if not message:
            return False
        normalized = message.strip().lower()
        return normalized in CCM_RESET_KEYWORDS

    async def get_session_by_key(self, session_key: str) -> Optional[ConversationSession]:
        """
        Load a session by its key. Used by downstream services that
        receive the session_key via workflow input_data.
        """
        self._load_config()

        # Try Redis first
        session = self._load_from_redis(session_key)
        if session:
            return session

        # Fallback to DB
        session = await self._load_from_db(session_key)
        if session:
            self._save_to_redis(session)
        return session

    async def save_session(self, session: ConversationSession) -> None:
        """Persist session metadata/messages to Redis and PostgreSQL."""
        session.last_activity_at = time.time()
        self._save_to_redis(session)
        await self._save_to_db(session)

    def get_cart(self, session: ConversationSession) -> List[Dict[str, Any]]:
        cart = session.metadata.get("cart", [])
        return cart if isinstance(cart, list) else []

    async def add_cart_item(
        self,
        session_key: str,
        item: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Add or increment an item in the session cart."""
        session = await self.get_session_by_key(session_key)
        if not session:
            return []

        cart = self.get_cart(session)
        product_id = str(item.get("id") or item.get("product_id") or "")
        name = (item.get("name") or "Item").strip()
        unit_price = float(item.get("unit_price", item.get("price", 0)) or 0)
        quantity = float(item.get("quantity", 1) or 1)

        merged = False
        for entry in cart:
            same_id = product_id and str(entry.get("id")) == product_id
            same_name = not product_id and entry.get("name", "").lower() == name.lower()
            if same_id or same_name:
                entry["quantity"] = float(entry.get("quantity", 1)) + quantity
                merged = True
                break

        if not merged:
            cart.append({
                "id": product_id or name[:50],
                "name": name,
                "quantity": quantity,
                "unit_price": unit_price,
                "unit": item.get("unit", "pcs"),
            })

        session.metadata["cart"] = cart
        await self.save_session(session)
        return cart

    async def clear_cart(self, session_key: str) -> None:
        session = await self.get_session_by_key(session_key)
        if not session:
            return
        session.metadata["cart"] = []
        session.metadata.pop("pending_confirmation", None)
        await self.save_session(session)

    async def set_pending_confirmation(
        self,
        session_key: str,
        items: List[Dict[str, Any]],
        total_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        session = await self.get_session_by_key(session_key)
        if not session:
            return
        session.metadata["pending_confirmation"] = {
            "items": items,
            "total_data": total_data or {},
            "at": time.time(),
        }
        session.metadata.pop("order_confirmed", None)
        await self.save_session(session)

    async def mark_order_confirmed(self, session_key: str) -> None:
        session = await self.get_session_by_key(session_key)
        if not session:
            return
        session.metadata["order_confirmed"] = True
        await self.save_session(session)

    async def clear_pending_confirmation(self, session_key: str) -> None:
        session = await self.get_session_by_key(session_key)
        if not session:
            return
        session.metadata.pop("pending_confirmation", None)
        session.metadata.pop("order_confirmed", None)
        await self.save_session(session)

    # ─── Redis Storage (synchronous — matches cache_service pattern) ──────

    def _load_from_redis(self, session_key: str) -> Optional[ConversationSession]:
        """Load session from Redis cache."""
        try:
            redis_client = self._get_redis()
            if not redis_client:
                return None
            raw = redis_client.get(session_key)
            if raw:
                data = json.loads(raw)
                return ConversationSession.from_dict(data)
        except Exception as e:
            logger.warning(f"[CCM] Redis read error for {session_key}: {e}")
        return None

    def _save_to_redis(self, session: ConversationSession) -> None:
        """Save session to Redis with TTL."""
        try:
            redis_client = self._get_redis()
            if not redis_client:
                return
            payload = json.dumps(session.to_dict(), default=str)
            redis_client.setex(session.session_key, CCM_SESSION_TTL, payload)
        except Exception as e:
            logger.warning(f"[CCM] Redis write error for {session.session_key}: {e}")

    # ─── PostgreSQL Storage ───────────────────────────────────────────────

    async def _load_from_db(self, session_key: str) -> Optional[ConversationSession]:
        """Load session from PostgreSQL."""
        try:
            from ..database import get_session_maker
            from ..models import MessagingConversation

            session_maker = get_session_maker()
            async with session_maker() as db:
                from sqlalchemy import select
                stmt = select(MessagingConversation).where(
                    MessagingConversation.session_key == session_key,
                    MessagingConversation.is_active == True,
                )
                result = await db.execute(stmt)
                row = result.scalar_one_or_none()

                if not row:
                    return None

                return ConversationSession(
                    session_key=row.session_key,
                    platform=row.platform,
                    owner_user_id=str(row.owner_user_id),
                    sender_id=row.sender_id,
                    messages=row.messages or [],
                    summary=row.summary or "",
                    message_count=row.message_count or 0,
                    metadata=row.metadata_ or {},
                    last_activity_at=row.last_activity_at.timestamp() if row.last_activity_at else 0.0,
                    created_at=row.created_at.timestamp() if row.created_at else 0.0,
                )
        except Exception as e:
            logger.warning(f"[CCM] DB read error for {session_key}: {e}")
        return None

    async def _save_to_db(self, session: ConversationSession) -> None:
        """Persist session to PostgreSQL (upsert)."""
        try:
            from ..database import get_session_maker
            from ..models import MessagingConversation

            session_maker = get_session_maker()
            async with session_maker() as db:
                from sqlalchemy import select
                stmt = select(MessagingConversation).where(
                    MessagingConversation.session_key == session.session_key
                )
                result = await db.execute(stmt)
                row = result.scalar_one_or_none()

                now = datetime.now(timezone.utc)

                if row:
                    # Update existing record
                    row.messages = session.messages
                    row.summary = session.summary
                    row.message_count = session.message_count
                    row.metadata_ = session.metadata
                    row.last_activity_at = now
                    row.is_active = True
                else:
                    # Insert new record
                    import uuid as _uuid
                    owner_uuid = _uuid.UUID(session.owner_user_id) if isinstance(session.owner_user_id, str) else session.owner_user_id

                    new_row = MessagingConversation(
                        owner_user_id=owner_uuid,
                        platform=session.platform,
                        sender_id=session.sender_id,
                        session_key=session.session_key,
                        messages=session.messages,
                        summary=session.summary,
                        message_count=session.message_count,
                        metadata_=session.metadata,
                        last_activity_at=now,
                        is_active=True,
                    )
                    db.add(new_row)

                await db.commit()
        except Exception as e:
            # DB persistence failures should not break the webhook response flow
            logger.error(f"[CCM] DB write error for {session.session_key}: {e}")

    # ─── Summarization ────────────────────────────────────────────────────

    async def _summarize_old_messages(self, session: ConversationSession) -> None:
        """
        Compress older messages into a summary using a background LLM call.
        Keeps the most recent `CCM_MAX_MESSAGES` messages intact.
        """
        try:
            from .llm_service import llm_service

            # Split: old messages (to summarize) vs recent (to keep)
            old_msgs = session.messages[:-CCM_MAX_MESSAGES]
            recent_msgs = session.messages[-CCM_MAX_MESSAGES:]

            if not old_msgs:
                return

            # Build conversation text for summarization
            conv_text = "\n".join(
                f"{m['role'].upper()}: {m['content']}" for m in old_msgs
            )

            # Combine with existing summary if any
            existing_summary = f"Previous summary: {session.summary}\n\n" if session.summary else ""

            summary_prompt = (
                f"{existing_summary}"
                f"Summarize the following conversation concisely, preserving key facts, "
                f"preferences, and context that would be needed to continue the conversation:\n\n"
                f"{conv_text}\n\n"
                f"Summary:"
            )

            response = await llm_service.chat_completion(
                messages=[
                    {"role": "system", "content": "You are a conversation summarizer. Create brief, factual summaries."},
                    {"role": "user", "content": summary_prompt},
                ],
                temperature=0.1,
                max_tokens=300,
                use_background_model=True,
            )

            if response and not response.error:
                session.summary = response.content.strip()
                session.messages = recent_msgs
                logger.info(
                    f"[CCM] Summarized {len(old_msgs)} messages for {session.session_key}"
                )
            else:
                # Summarization failed — fall back to simple truncation
                session.messages = recent_msgs

        except Exception as e:
            logger.warning(f"[CCM] Summarization failed for {session.session_key}: {e}")
            # Fallback: just truncate
            session.messages = session.messages[-CCM_MAX_MESSAGES:]


# ─── Module-level singleton ──────────────────────────────────────────────────

context_manager = ConversationContextManager()
