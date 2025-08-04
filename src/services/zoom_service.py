"""
Zoom Service for managing Zoom meetings, recordings, and analytics.
"""

import base64
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiohttp

from ..config import settings

logger = logging.getLogger(__name__)


class ZoomService:
    """Service for managing Zoom meetings and operations."""

    def __init__(self):
        self.client_id = None
        self.client_secret = None
        self.account_id = None
        self.base_url = "https://api.zoom.us/v2"
        self.token_url = "https://zoom.us/oauth/token"
        self._initialized = False
        self._access_token = None
        self._token_expires_at = None

    async def initialize(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the Zoom service with configuration."""
        if self._initialized:
            return

        # Get configuration from settings or provided config
        if config:
            self.client_id = config.get("client_id")
            self.client_secret = config.get("client_secret")
            self.account_id = config.get("account_id")
        else:
            self.client_id = settings.ZOOM_CLIENT_ID
            self.client_secret = settings.ZOOM_CLIENT_SECRET
            self.account_id = settings.ZOOM_ACCOUNT_ID

            if not self.client_id or not self.client_secret:
                logger.warning("Zoom OAuth credentials not configured")
                logger.warning(f"Client ID: {'Set' if self.client_id else 'Not set'}")
                logger.warning(f"Client Secret: {'Set' if self.client_secret else 'Not set'}")
                return

        self._initialized = True
        logger.info("Zoom service initialized")

    async def _get_access_token(self) -> Optional[str]:
        """Get Zoom access token using OAuth 2.0 client credentials flow."""
        try:
            # Check if we have a valid cached token
            if self._access_token and self._token_expires_at and datetime.utcnow() < self._token_expires_at:
                return self._access_token

            # Create basic auth header
            credentials = f"{self.client_id}:{self.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()

            headers = {
                "Authorization": f"Basic {encoded_credentials}",
                "Content-Type": "application/x-www-form-urlencoded"
            }

            data = {
                "grant_type": "client_credentials"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self.token_url, headers=headers, data=data) as response:
                    if response.status == 200:
                        token_data = await response.json()
                        self._access_token = token_data.get("access_token")
                        expires_in = token_data.get("expires_in", 3600)
                        self._token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in - 300)  # 5 min buffer
                        return self._access_token
                    else:
                        try:
                            error_data = await response.json()
                            logger.error(f"Failed to get Zoom access token: {error_data}")
                            # Log more details for debugging
                            logger.error(f"Response status: {response.status}")
                            logger.error(f"Response headers: {dict(response.headers)}")
                        except Exception as parse_error:
                            error_text = await response.text()
                            logger.error(f"Failed to get Zoom access token. Status: {response.status}, Response: {error_text}")
                        return None

        except Exception as e:
            logger.error(f"Error getting Zoom access token: {e}")
            return None

    async def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make authenticated request to Zoom API."""
        if not self._initialized:
            return {"success": False, "error": "Zoom service not initialized"}

        token = await self._get_access_token()
        if not token:
            return {"success": False, "error": "Failed to get access token"}

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        url = f"{self.base_url}{endpoint}"

        try:
            async with aiohttp.ClientSession() as session:
                if method.upper() == "GET":
                    async with session.get(url, headers=headers, params=params) as response:
                        return await self._handle_response(response)
                elif method.upper() == "POST":
                    async with session.post(url, headers=headers, json=data) as response:
                        return await self._handle_response(response)
                elif method.upper() == "PUT":
                    async with session.put(url, headers=headers, json=data) as response:
                        return await self._handle_response(response)
                elif method.upper() == "DELETE":
                    async with session.delete(url, headers=headers) as response:
                        return await self._handle_response(response)
                else:
                    return {"success": False, "error": f"Unsupported HTTP method: {method}"}

        except Exception as e:
            logger.error(f"Error making Zoom API request: {e}")
            return {"success": False, "error": f"Request failed: {str(e)}"}

    async def _handle_response(self, response: aiohttp.ClientResponse) -> Dict[str, Any]:
        """Handle API response and return standardized format."""
        try:
            if response.status == 204:  # No content
                return {"success": True, "message": "Operation completed successfully"}

            response_data = await response.json()
            
            if response.status < 400:
                return {"success": True, "data": response_data}
            else:
                error_msg = response_data.get("message", f"HTTP {response.status}")
                return {"success": False, "error": error_msg}

        except Exception as e:
            logger.error(f"Error handling response: {e}")
            return {"success": False, "error": f"Response parsing failed: {str(e)}"}

    async def test_connection(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Test Zoom connection by getting user info."""
        await self.initialize(config)
        
        # Check if service was initialized properly
        if not self._initialized:
            return {
                "success": False,
                "error": "Zoom service not initialized - check credentials"
            }
        
        result = await self._make_request("GET", "/users/me")
        
        if result.get("success"):
            user_data = result.get("data", {})
            return {
                "success": True,
                "message": "Zoom connection successful",
                "method": "OAuth Authentication",
                "user": {
                    "id": user_data.get("id"),
                    "email": user_data.get("email"),
                    "first_name": user_data.get("first_name"),
                    "last_name": user_data.get("last_name"),
                    "account_id": user_data.get("account_id")
                }
            }
        else:
            error_msg = result.get("error", "Zoom connection test failed")
            logger.error(f"Zoom connection test failed: {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }

    # Meeting Management
    async def create_meeting(
        self,
        topic: str,
        start_time: Optional[str] = None,
        duration: int = 60,
        password: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new Zoom meeting."""
        data = {
            "topic": topic,
            "type": 2,  # Scheduled meeting
            "start_time": start_time,
            "duration": duration,
            "password": password,
            "settings": settings or {
                "host_video": True,
                "participant_video": True,
                "join_before_host": True,
                "mute_upon_entry": False,
                "watermark": False,
                "use_pmi": False,
                "approval_type": 0,
                "audio": "both",
                "auto_recording": "none"
            }
        }

        return await self._make_request("POST", "/users/me/meetings", data)

    async def get_meeting(self, meeting_id: str) -> Dict[str, Any]:
        """Get meeting details."""
        return await self._make_request("GET", f"/meetings/{meeting_id}")

    async def update_meeting(
        self,
        meeting_id: str,
        topic: Optional[str] = None,
        start_time: Optional[str] = None,
        duration: Optional[int] = None,
        settings: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Update meeting details."""
        data = {}
        if topic:
            data["topic"] = topic
        if start_time:
            data["start_time"] = start_time
        if duration:
            data["duration"] = duration
        if settings:
            data["settings"] = settings

        return await self._make_request("PUT", f"/meetings/{meeting_id}", data)

    async def delete_meeting(self, meeting_id: str) -> Dict[str, Any]:
        """Delete a meeting."""
        return await self._make_request("DELETE", f"/meetings/{meeting_id}")

    async def list_meetings(
        self,
        user_id: str = "me",
        type: str = "scheduled",
        page_size: int = 30,
        page_number: int = 1
    ) -> Dict[str, Any]:
        """List user's meetings."""
        params = {
            "type": type,
            "page_size": page_size,
            "page_number": page_number
        }
        return await self._make_request("GET", f"/users/{user_id}/meetings", params=params)

    # Meeting Operations
    async def get_meeting_participants(
        self,
        meeting_id: str,
        page_size: int = 30,
        page_number: int = 1
    ) -> Dict[str, Any]:
        """Get meeting participants."""
        params = {
            "page_size": page_size,
            "page_number": page_number
        }
        return await self._make_request("GET", f"/meetings/{meeting_id}/participants", params=params)

    async def get_meeting_registrants(
        self,
        meeting_id: str,
        page_size: int = 30,
        page_number: int = 1
    ) -> Dict[str, Any]:
        """Get meeting registrants."""
        params = {
            "page_size": page_size,
            "page_number": page_number
        }
        return await self._make_request("GET", f"/meetings/{meeting_id}/registrants", params=params)

    # Recording Management
    async def get_meeting_recordings(
        self,
        meeting_id: str,
        page_size: int = 30,
        page_number: int = 1
    ) -> Dict[str, Any]:
        """Get meeting recordings."""
        params = {
            "page_size": page_size,
            "page_number": page_number
        }
        return await self._make_request("GET", f"/meetings/{meeting_id}/recordings", params=params)

    async def delete_recording(self, meeting_id: str, recording_id: str) -> Dict[str, Any]:
        """Delete a recording."""
        return await self._make_request("DELETE", f"/meetings/{meeting_id}/recordings/{recording_id}")

    # User Management
    async def get_user(self, user_id: str = "me") -> Dict[str, Any]:
        """Get user information."""
        return await self._make_request("GET", f"/users/{user_id}")

    async def list_users(
        self,
        status: str = "active",
        page_size: int = 30,
        page_number: int = 1
    ) -> Dict[str, Any]:
        """List users in account."""
        params = {
            "status": status,
            "page_size": page_size,
            "page_number": page_number
        }
        return await self._make_request("GET", "/users", params=params)

    # Webinar Management
    async def create_webinar(
        self,
        topic: str,
        start_time: Optional[str] = None,
        duration: int = 60,
        password: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new webinar."""
        data = {
            "topic": topic,
            "type": 5,  # Scheduled webinar
            "start_time": start_time,
            "duration": duration,
            "password": password,
            "settings": settings or {
                "host_video": True,
                "panelists_video": True,
                "practice_session": False,
                "hd_video": True,
                "audio": "both",
                "auto_recording": "none",
                "alternative_hosts": ""
            }
        }

        return await self._make_request("POST", "/users/me/webinars", data)

    async def get_webinar(self, webinar_id: str) -> Dict[str, Any]:
        """Get webinar details."""
        return await self._make_request("GET", f"/webinars/{webinar_id}")

    async def list_webinars(
        self,
        user_id: str = "me",
        page_size: int = 30,
        page_number: int = 1
    ) -> Dict[str, Any]:
        """List user's webinars."""
        params = {
            "page_size": page_size,
            "page_number": page_number
        }
        return await self._make_request("GET", f"/users/{user_id}/webinars", params=params)

    # Analytics and Reports
    async def get_meeting_reports(
        self,
        user_id: str = "me",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        page_size: int = 30,
        page_number: int = 1
    ) -> Dict[str, Any]:
        """Get meeting reports."""
        params = {
            "page_size": page_size,
            "page_number": page_number
        }
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        return await self._make_request("GET", f"/report/users/{user_id}/meetings", params=params)

    async def get_daily_reports(
        self,
        year: int,
        month: int,
        page_size: int = 30,
        page_number: int = 1
    ) -> Dict[str, Any]:
        """Get daily reports."""
        params = {
            "year": year,
            "month": month,
            "page_size": page_size,
            "page_number": page_number
        }
        return await self._make_request("GET", "/report/daily", params=params)

    # Utility Methods
    async def get_meeting_invitation(self, meeting_id: str) -> Dict[str, Any]:
        """Get meeting invitation details."""
        return await self._make_request("GET", f"/meetings/{meeting_id}/invitation")

    async def update_meeting_status(self, meeting_id: str, action: str) -> Dict[str, Any]:
        """Update meeting status (approve, deny, etc.)."""
        data = {"action": action}
        return await self._make_request("PUT", f"/meetings/{meeting_id}/status", data)

    async def get_meeting_polls(self, meeting_id: str) -> Dict[str, Any]:
        """Get meeting polls."""
        return await self._make_request("GET", f"/meetings/{meeting_id}/polls")

    async def create_meeting_poll(
        self,
        meeting_id: str,
        title: str,
        questions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Create a meeting poll."""
        data = {
            "title": title,
            "questions": questions
        }
        return await self._make_request("POST", f"/meetings/{meeting_id}/polls", data) 