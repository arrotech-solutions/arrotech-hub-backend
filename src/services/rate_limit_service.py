"""
Rate limiting service for Mini-Hub MCP Server.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import redis

from ..config import settings

logger = logging.getLogger(__name__)


class RateLimitService:
    """Rate limiting service using Redis."""

    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None

    async def initialize(self):
        """Initialize Redis client."""
        try:
            self.redis_client = redis.from_url(settings.REDIS_URL)
            # Test connection
            self.redis_client.ping()
            logger.info("Redis client initialized")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
            self.redis_client = None

    async def check_limit(self, user_id: str, tier: str = "free") -> bool:
        """Check if user has remaining requests for the day."""
        if not self.redis_client:
            # If Redis is not available, allow requests (fallback)
            return True

        try:
            # Get daily limit based on tier
            daily_limit = self._get_daily_limit(tier)

            # Create key for today's usage
            today = datetime.now().strftime("%Y-%m-%d")
            key = f"rate_limit:{user_id}:{today}"

            # Get current usage
            current_usage = self.redis_client.get(key)
            if current_usage is None:
                current_usage = 0
            else:
                current_usage = int(current_usage)

            # Check if limit exceeded
            if current_usage >= daily_limit:
                return False

            # Increment usage
            self.redis_client.incr(key)
            # Set expiry to end of day
            self.redis_client.expire(key, 86400)  # 24 hours

            return True

        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            # On error, allow the request
            return True

    async def get_usage(self, user_id: str) -> Dict[str, Any]:
        """Get current usage for user."""
        if not self.redis_client:
            return {
                "current_usage": 0,
                "daily_limit": 100,
                "remaining": 100
            }

        try:
            today = datetime.now().strftime("%Y-%m-%d")
            key = f"rate_limit:{user_id}:{today}"

            current_usage = self.redis_client.get(key)
            if current_usage is None:
                current_usage = 0
            else:
                current_usage = int(current_usage)

            # Get user tier (in production, this would come from database)
            tier = "free"  # Default tier
            daily_limit = self._get_daily_limit(tier)

            return {
                "current_usage": current_usage,
                "daily_limit": daily_limit,
                "remaining": max(0, daily_limit - current_usage),
                "tier": tier
            }

        except Exception as e:
            logger.error(f"Error getting usage: {e}")
            return {
                "current_usage": 0,
                "daily_limit": 100,
                "remaining": 100,
                "error": str(e)
            }

    async def reset_usage(self, user_id: str) -> Dict[str, Any]:
        """Reset usage for user (admin function)."""
        if not self.redis_client:
            return {"success": False, "error": "Redis not available"}

        try:
            today = datetime.now().strftime("%Y-%m-%d")
            key = f"rate_limit:{user_id}:{today}"

            self.redis_client.delete(key)

            return {
                "success": True,
                "message": f"Usage reset for user {user_id}"
            }

        except Exception as e:
            logger.error(f"Error resetting usage: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _get_daily_limit(self, tier: str) -> int:
        """Get daily request limit for tier."""
        limits = {
            "free": settings.FREE_TIER_LIMIT,
            "pro": settings.PRO_TIER_LIMIT,
            "enterprise": 100000  # 100k requests per day
        }

        return limits.get(tier, settings.FREE_TIER_LIMIT)
