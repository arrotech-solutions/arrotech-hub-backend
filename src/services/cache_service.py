import json
import logging
from typing import Any, Dict, Optional
import redis

from ..config import settings

logger = logging.getLogger(__name__)

class CacheService:
    """Generic Redis caching service."""

    def __init__(self):
        
        self.redis_client: Optional[redis.Redis] = None

    def _ensure_redis(self) -> bool:
        """Lazy-connect Redis (Celery workers do not run FastAPI startup hooks)."""
        if self.redis_client is not None:
            return True
        try:
            self.redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
            self.redis_client.ping()
            logger.info("CacheService Redis client initialized (lazy)")
            return True
        except Exception as e:
            logger.warning("CacheService Redis connection failed (lazy): %s", e)
            self.redis_client = None
            return False

    async def initialize(self):
        """Initialize Redis client."""
        self._ensure_redis()

    def get(self, key: str) -> Optional[Any]:
        """Get a value from cache."""
        if not self._ensure_redis():
            return None
        try:
            val = self.redis_client.get(key)
            if val:
                return json.loads(val)
            return None
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            return None

    def set(self, key: str, value: Any, expire_seconds: int = 3600) -> bool:
        """Set a value in cache."""
        if not self._ensure_redis():
            return False
        try:
            self.redis_client.setex(key, expire_seconds, json.dumps(value))
            return True
        except Exception as e:
            logger.error(f"Redis set error: {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        if not self._ensure_redis():
            return False
        try:
            self.redis_client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Redis delete error: {e}")
            return False

    def keys(self, pattern: str) -> list:
        """Get all keys matching pattern."""
        if not self._ensure_redis():
            return []
        try:
            return self.redis_client.keys(pattern)
        except Exception as e:
            logger.error(f"Redis keys error: {e}")
            return []

cache_service = CacheService()
