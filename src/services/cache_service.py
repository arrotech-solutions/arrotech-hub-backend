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

    async def initialize(self):
        """Initialize Redis client."""
        try:
            self.redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
            self.redis_client.ping()
            logger.info("CacheService Redis client initialized")
        except Exception as e:
            logger.warning(f"CacheService Redis connection failed: {e}")
            self.redis_client = None

    def get(self, key: str) -> Optional[Any]:
        """Get a value from cache."""
        if not self.redis_client:
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
        if not self.redis_client:
            return False
        try:
            self.redis_client.setex(key, expire_seconds, json.dumps(value))
            return True
        except Exception as e:
            logger.error(f"Redis set error: {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        if not self.redis_client:
            return False
        try:
            self.redis_client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Redis delete error: {e}")
            return False

    def keys(self, pattern: str) -> list:
        """Get all keys matching pattern."""
        if not self.redis_client:
            return []
        try:
            return self.redis_client.keys(pattern)
        except Exception as e:
            logger.error(f"Redis keys error: {e}")
            return []

cache_service = CacheService()
