"""
Advanced API management service for Mini-Hub MCP Server.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class APIManagementService:
    """Advanced API management and developer portal service."""

    def __init__(self):
        self.api_keys = {}  # In-memory storage for API keys
        self.rate_limits = {}  # In-memory storage for rate limits
        self.api_versions = {}  # In-memory storage for API versions
        self.monitoring_data = {}  # In-memory storage for monitoring data
        self.developer_portal = {}  # In-memory storage for developer portal

    async def create_api_key(
        self,
        user_id: str,
        name: str,
        permissions: List[str],
        rate_limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """Create a new API key for a user."""
        try:
            api_key_id = str(uuid4())
            api_key = f"mh_{api_key_id[:8]}_{api_key_id[8:16]}"

            key_data = {
                "id": api_key_id,
                "api_key": api_key,
                "user_id": user_id,
                "name": name,
                "permissions": permissions,
                "rate_limit": rate_limit or 1000,
                "status": "active",
                "created_at": datetime.now().isoformat(),
                "last_used": None,
                "usage_count": 0
            }

            self.api_keys[api_key_id] = key_data

            logger.info(f"Created API key {api_key_id} for user {user_id}")

            return {
                "success": True,
                "api_key_id": api_key_id,
                "api_key": api_key,
                "key_data": key_data
            }

        except Exception as e:
            logger.error(f"Error creating API key: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def validate_api_key(self, api_key: str) -> Dict[str, Any]:
        """Validate an API key and return user permissions."""
        try:
            # Find API key
            key_data = None
            for key_id, data in self.api_keys.items():
                if data["api_key"] == api_key and data["status"] == "active":
                    key_data = data
                    break

            if not key_data:
                return {
                    "success": False,
                    "error": "Invalid or inactive API key"
                }

            # Update usage statistics
            key_data["last_used"] = datetime.now().isoformat()
            key_data["usage_count"] += 1

            return {
                "success": True,
                "user_id": key_data["user_id"],
                "permissions": key_data["permissions"],
                "rate_limit": key_data["rate_limit"]
            }

        except Exception as e:
            logger.error(f"Error validating API key: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def create_api_version(
        self,
        version: str,
        description: str,
        changelog: List[Dict[str, Any]],
        deprecated: bool = False
    ) -> Dict[str, Any]:
        """Create a new API version."""
        try:
            version_id = str(uuid4())

            version_data = {
                "id": version_id,
                "version": version,
                "description": description,
                "changelog": changelog,
                "deprecated": deprecated,
                "created_at": datetime.now().isoformat(),
                "end_of_life": None
            }

            self.api_versions[version_id] = version_data

            logger.info(f"Created API version {version}")

            return {
                "success": True,
                "version_id": version_id,
                "version_data": version_data
            }

        except Exception as e:
            logger.error(f"Error creating API version: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def set_rate_limit(
        self,
        user_id: str,
        endpoint: str,
        requests_per_minute: int,
        requests_per_hour: int,
        requests_per_day: int
    ) -> Dict[str, Any]:
        """Set rate limits for a user and endpoint."""
        try:
            rate_limit_id = str(uuid4())

            rate_limit = {
                "id": rate_limit_id,
                "user_id": user_id,
                "endpoint": endpoint,
                "requests_per_minute": requests_per_minute,
                "requests_per_hour": requests_per_hour,
                "requests_per_day": requests_per_day,
                "created_at": datetime.now().isoformat(),
                "usage": {
                    "minute": 0,
                    "hour": 0,
                    "day": 0,
                    "last_reset": datetime.now().isoformat()
                }
            }

            self.rate_limits[rate_limit_id] = rate_limit

            return {
                "success": True,
                "rate_limit_id": rate_limit_id,
                "rate_limit": rate_limit
            }

        except Exception as e:
            logger.error(f"Error setting rate limit: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def check_rate_limit(
        self,
        user_id: str,
        endpoint: str
    ) -> Dict[str, Any]:
        """Check if a user has exceeded their rate limit."""
        try:
            # Find rate limit for user and endpoint
            rate_limit = None
            for rl_id, rl_data in self.rate_limits.items():
                if rl_data["user_id"] == user_id and rl_data["endpoint"] == endpoint:
                    rate_limit = rl_data
                    break

            if not rate_limit:
                # No rate limit set, allow request
                return {
                    "success": True,
                    "allowed": True,
                    "remaining": 1000  # Default limit
                }

            # Check if limits are exceeded
            now = datetime.now()
            last_reset = datetime.fromisoformat(
                rate_limit["usage"]["last_reset"])

            # Reset counters if needed
            if (now - last_reset).total_seconds() > 60:
                rate_limit["usage"]["minute"] = 0
            if (now - last_reset).total_seconds() > 3600:
                rate_limit["usage"]["hour"] = 0
            if (now - last_reset).total_seconds() > 86400:
                rate_limit["usage"]["day"] = 0

            # Check limits
            minute_exceeded = rate_limit["usage"]["minute"] >= rate_limit["requests_per_minute"]
            hour_exceeded = rate_limit["usage"]["hour"] >= rate_limit["requests_per_hour"]
            day_exceeded = rate_limit["usage"]["day"] >= rate_limit["requests_per_day"]

            if minute_exceeded or hour_exceeded or day_exceeded:
                return {
                    "success": True,
                    "allowed": False,
                    "reason": "Rate limit exceeded",
                    "limits": {
                        "minute": rate_limit["requests_per_minute"],
                        "hour": rate_limit["requests_per_hour"],
                        "day": rate_limit["requests_per_day"]
                    },
                    "usage": rate_limit["usage"]
                }

            # Increment usage counters
            rate_limit["usage"]["minute"] += 1
            rate_limit["usage"]["hour"] += 1
            rate_limit["usage"]["day"] += 1

            return {
                "success": True,
                "allowed": True,
                "remaining": {
                    "minute": rate_limit["requests_per_minute"] - rate_limit["usage"]["minute"],
                    "hour": rate_limit["requests_per_hour"] - rate_limit["usage"]["hour"],
                    "day": rate_limit["requests_per_day"] - rate_limit["usage"]["day"]
                }
            }

        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def record_api_call(
        self,
        user_id: str,
        endpoint: str,
        method: str,
        response_time: float,
        status_code: int,
        request_size: int,
        response_size: int
    ) -> Dict[str, Any]:
        """Record an API call for monitoring."""
        try:
            call_id = str(uuid4())
            timestamp = datetime.now().isoformat()

            call_data = {
                "id": call_id,
                "user_id": user_id,
                "endpoint": endpoint,
                "method": method,
                "response_time": response_time,
                "status_code": status_code,
                "request_size": request_size,
                "response_size": response_size,
                "timestamp": timestamp
            }

            # Store in monitoring data
            if user_id not in self.monitoring_data:
                self.monitoring_data[user_id] = []

            self.monitoring_data[user_id].append(call_data)

            # Keep only last 1000 calls per user
            if len(self.monitoring_data[user_id]) > 1000:
                self.monitoring_data[user_id] = self.monitoring_data[user_id][-1000:]

            return {
                "success": True,
                "call_id": call_id
            }

        except Exception as e:
            logger.error(f"Error recording API call: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_api_analytics(
        self,
        user_id: Optional[str] = None,
        date_range: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get API usage analytics."""
        try:
            # Filter data by user and date range
            end_date = datetime.now()
            if date_range == "last_7_days":
                start_date = end_date - timedelta(days=7)
            elif date_range == "last_30_days":
                start_date = end_date - timedelta(days=30)
            else:
                start_date = end_date - timedelta(days=30)

            filtered_calls = []
            for uid, calls in self.monitoring_data.items():
                if user_id and uid != user_id:
                    continue

                for call in calls:
                    call_time = datetime.fromisoformat(call["timestamp"])
                    if start_date <= call_time <= end_date:
                        filtered_calls.append(call)

            # Calculate analytics
            total_calls = len(filtered_calls)
            successful_calls = len(
                [c for c in filtered_calls if 200 <= c["status_code"] < 300])
            error_calls = len(
                [c for c in filtered_calls if c["status_code"] >= 400])

            avg_response_time = sum(
                c["response_time"] for c in filtered_calls) / total_calls if total_calls > 0 else 0

            # Group by endpoint
            endpoint_stats = {}
            for call in filtered_calls:
                endpoint = call["endpoint"]
                if endpoint not in endpoint_stats:
                    endpoint_stats[endpoint] = {
                        "calls": 0,
                        "avg_response_time": 0,
                        "errors": 0
                    }

                endpoint_stats[endpoint]["calls"] += 1
                endpoint_stats[endpoint]["avg_response_time"] += call["response_time"]
                if call["status_code"] >= 400:
                    endpoint_stats[endpoint]["errors"] += 1

            # Calculate averages
            for endpoint in endpoint_stats:
                calls = endpoint_stats[endpoint]["calls"]
                if calls > 0:
                    endpoint_stats[endpoint]["avg_response_time"] /= calls

            analytics = {
                "total_calls": total_calls,
                "successful_calls": successful_calls,
                "error_calls": error_calls,
                "success_rate": (successful_calls / total_calls * 100) if total_calls > 0 else 0,
                "avg_response_time": round(avg_response_time, 2),
                "endpoint_stats": endpoint_stats,
                "date_range": {
                    "start": start_date.strftime("%Y-%m-%d"),
                    "end": end_date.strftime("%Y-%m-%d")
                }
            }

            return {
                "success": True,
                "analytics": analytics
            }

        except Exception as e:
            logger.error(f"Error getting API analytics: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def create_developer_portal(
        self,
        user_id: str,
        portal_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a developer portal for API documentation."""
        try:
            portal_id = str(uuid4())

            portal = {
                "id": portal_id,
                "user_id": user_id,
                "config": {
                    "title": portal_config.get("title", "API Documentation"),
                    "description": portal_config.get("description", ""),
                    "theme": portal_config.get("theme", "default"),
                    "custom_css": portal_config.get("custom_css", ""),
                    "logo_url": portal_config.get("logo_url"),
                    "contact_email": portal_config.get("contact_email"),
                    "support_url": portal_config.get("support_url")
                },
                "endpoints": portal_config.get("endpoints", []),
                "examples": portal_config.get("examples", []),
                "status": "active",
                "created_at": datetime.now().isoformat()
            }

            self.developer_portal[portal_id] = portal

            return {
                "success": True,
                "portal_id": portal_id,
                "portal": portal
            }

        except Exception as e:
            logger.error(f"Error creating developer portal: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def generate_api_documentation(
        self,
        portal_id: str,
        include_examples: bool = True
    ) -> Dict[str, Any]:
        """Generate API documentation for developer portal."""
        try:
            if portal_id not in self.developer_portal:
                return {
                    "success": False,
                    "error": f"Portal {portal_id} not found"
                }

            portal = self.developer_portal[portal_id]

            # Generate documentation
            documentation = {
                "title": portal["config"]["title"],
                "description": portal["config"]["description"],
                "version": "1.0.0",
                "base_url": "https://api.mini-hub.com/v1",
                "endpoints": []
            }

            for endpoint in portal["endpoints"]:
                doc_endpoint = {
                    "path": endpoint.get("path"),
                    "method": endpoint.get("method"),
                    "description": endpoint.get("description"),
                    "parameters": endpoint.get("parameters", []),
                    "responses": endpoint.get("responses", {}),
                    "examples": endpoint.get("examples", []) if include_examples else []
                }
                documentation["endpoints"].append(doc_endpoint)

            return {
                "success": True,
                "documentation": documentation
            }

        except Exception as e:
            logger.error(f"Error generating API documentation: {e}")
            return {
                "success": False,
                "error": str(e)
            }
