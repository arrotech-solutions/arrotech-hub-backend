
import logging
import os
from typing import Dict, Any, Optional
import httpx
from ..config import settings

logger = logging.getLogger(__name__)

class ClickUpService:
    """Service for interacting with ClickUp API."""
    
    BASE_URL = "https://api.clickup.com/api/v2"
    AUTH_URL = "https://app.clickup.com/api"
    
    def __init__(self):
        self.client_id = os.getenv("CLICKUP_CLIENT_ID")
        self.client_secret = os.getenv("CLICKUP_CLIENT_SECRET")
        self.redirect_uri = f"{settings.API_BASE_URL}/api/clickup/callback"
        
    async def get_auth_url(self, state: str = None) -> str:
        """Get the ClickUp OAuth authorization URL."""
        if not self.client_id:
            raise ValueError("CLICKUP_CLIENT_ID not set")
            
        url = f"{self.AUTH_URL}?client_id={self.client_id}&redirect_uri={self.redirect_uri}"
        if state:
            url += f"&state={state}"
        return url
        
    async def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access token."""
        if not self.client_id or not self.client_secret:
            raise ValueError("ClickUp credentials not configured")
            
        url = f"{self.BASE_URL}/oauth/token"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, params={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code
            })
            
            if response.status_code != 200:
                logger.error(f"ClickUp token exchange failed: {response.text}")
                raise Exception(f"Failed to exchange code for token: {response.text}")
                
            return response.json()
            
    async def get_user(self, access_token: str) -> Dict[str, Any]:
        """Get authenticated user details."""
        url = f"{self.BASE_URL}/user"
        headers = {"Authorization": access_token}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
            
    async def get_teams(self, access_token: str) -> Dict[str, Any]:
        """Get authorized teams (workspaces)."""
        url = f"{self.BASE_URL}/team"
        headers = {"Authorization": access_token}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    async def get_team_tasks(self, access_token: str, team_id: str, assignee_id: str = None) -> Dict[str, Any]:
        """Get tasks for a team (workspace), optionally filtered by assignee."""
        url = f"{self.BASE_URL}/team/{team_id}/task"
        headers = {"Authorization": access_token}
        params = {}
        if assignee_id:
            params["assignees"] = [assignee_id]
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()

    async def get_spaces(self, access_token: str, team_id: str) -> Dict[str, Any]:
        """Get spaces for a team."""
        url = f"{self.BASE_URL}/team/{team_id}/space"
        headers = {"Authorization": access_token}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    async def get_folders(self, access_token: str, space_id: str) -> Dict[str, Any]:
        """Get folders in a space."""
        url = f"{self.BASE_URL}/space/{space_id}/folder"
        headers = {"Authorization": access_token}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    async def get_lists(self, access_token: str, folder_id: str) -> Dict[str, Any]:
        """Get lists in a folder."""
        url = f"{self.BASE_URL}/folder/{folder_id}/list"
        headers = {"Authorization": access_token}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    async def get_folderless_lists(self, access_token: str, space_id: str) -> Dict[str, Any]:
        """Get folderless lists in a space."""
        url = f"{self.BASE_URL}/space/{space_id}/list"
        headers = {"Authorization": access_token}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    async def get_tasks(self, access_token: str, list_id: str, include_closed: bool = False) -> Dict[str, Any]:
        """Get tasks from a list."""
        url = f"{self.BASE_URL}/list/{list_id}/task"
        headers = {"Authorization": access_token}
        params = {"include_closed": str(include_closed).lower()}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()

    async def create_task(self, access_token: str, list_id: str, name: str, description: str = None) -> Dict[str, Any]:
        """Create a new task in a list."""
        url = f"{self.BASE_URL}/list/{list_id}/task"
        headers = {
            "Authorization": access_token,
            "Content-Type": "application/json"
        }
        payload = {
            "name": name,
            "description": description
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
