import json
import logging
import httpx
from typing import Dict, Any, Optional
from urllib.parse import urlencode

from ..config import get_settings

logger = logging.getLogger(__name__)

class GitHubService:
    AUTH_URL = "https://github.com/login/oauth/authorize"
    TOKEN_URL = "https://github.com/login/oauth/access_token"
    API_BASE_URL = "https://api.github.com"

    # Scopes needed for the Coding Agent
    SCOPES = "repo,user:email"

    def __init__(self, access_token: str = None):
        self.access_token = access_token
        settings = get_settings()
        self.client_id = settings.GITHUB_CLIENT_ID
        self.client_secret = settings.GITHUB_CLIENT_SECRET
        self.redirect_uri = settings.GITHUB_REDIRECT_URI

    @classmethod
    def get_auth_url(cls, state: str) -> str:
        settings = get_settings()
        params = {
            "client_id": settings.GITHUB_CLIENT_ID,
            "redirect_uri": settings.GITHUB_REDIRECT_URI,
            "scope": cls.SCOPES,
            "state": state,
        }
        return f"{cls.AUTH_URL}?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """Exchange the OAuth authorization code for an access token."""
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        headers = {"Accept": "application/json"}

        async with httpx.AsyncClient() as client:
            response = await client.post(self.TOKEN_URL, headers=headers, data=data)
            response_data = response.json()
            
            if not response.is_success or "error" in response_data:
                logger.error(f"GitHub token exchange failed: {response.status_code} {response_data}")
                raise Exception(f"Failed to exchange GitHub code: {response_data.get('error_description', 'Unknown error')}")

            self.access_token = response_data.get("access_token")
            return response_data

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Use a refresh token to get a new access token."""
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        headers = {"Accept": "application/json"}

        async with httpx.AsyncClient() as client:
            response = await client.post(self.TOKEN_URL, headers=headers, data=data)
            response_data = response.json()

            if not response.is_success or "error" in response_data:
                logger.error(f"GitHub token refresh failed: {response_data}")
                raise Exception("Failed to refresh GitHub token")

            self.access_token = response_data.get("access_token")
            return response_data

    async def get_user_info(self) -> Dict[str, Any]:
        """Fetch the authenticated user's profile information."""
        if not self.access_token:
            raise Exception("No access token available for GitHub")

        headers = {
            "Authorization": f"token {self.access_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.API_BASE_URL}/user", headers=headers)
            if not response.is_success:
                logger.error(f"GitHub API error ({response.status_code}): {response.text}")
                raise Exception(f"GitHub API Error: {response.text}")
            
            return response.json()

    async def test_connection(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Test the GitHub connection using a provided configuration."""
        try:
            token = config.get("access_token")
            if not token:
                return {"success": False, "error": "No access token provided"}
            
            self.access_token = token
            user_info = await self.get_user_info()
            
            return {
                "success": True,
                "message": f"Successfully connected to GitHub as @{user_info.get('login')}",
                "data": {
                    "username": user_info.get("login"),
                    "name": user_info.get("name"),
                    "avatar_url": user_info.get("avatar_url")
                }
            }
        except Exception as e:
            return {"success": False, "error": f"GitHub validation failed: {str(e)}"}
