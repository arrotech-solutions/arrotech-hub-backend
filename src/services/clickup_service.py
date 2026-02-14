
import logging
import os
from typing import Dict, Any, Optional, List
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

    async def get_team_tasks(self, access_token: str, team_id: str, assignee_id: str = None, include_closed: bool = False) -> Dict[str, Any]:
        """Get tasks for a team (workspace), optionally filtered by assignee."""
        # Note: ClickUp API v2 doesn't have a direct "get all team tasks" endpoint that is simple. 
        # Usually one queries by list or uses filtered team view. 
        # But for now, we'll try to use the filtering endpoint if available or fallback to space->list iteration.
        # Actually, https://api.clickup.com/api/v2/team/{team_id}/task exists but it's legacy or specific filter.
        # Let's verify documentation. 'GET /team/{team_id}/task' DOES exist for filtered tasks.
        
        url = f"{self.BASE_URL}/team/{team_id}/task"
        headers = {"Authorization": access_token}
        params = {"include_closed": str(include_closed).lower()}
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

    async def get_list_members(self, access_token: str, list_id: str) -> Dict[str, Any]:
        """Get members who can be assigned to tasks in a list."""
        # ClickUp doesn't have a direct "list members" endpoint, but we can get list details or use the space members
        # Often getting the list returns members if expanded.
        # Alternatively, we can get Task members. 
        # Best bet: GET /list/{list_id} returns "members"? No.
        # GET /list/{list_id}/member - Only available for Spaces?
        # Let's fallback to getting team members? No, that's too broad.
        # But commonly we assume team members can be assigned. 
        # Let's try getting the list content via GET /list/{list_id} which might contain members info or access
        # If not, we resort to Team members which we already have potentially?
        
        # New strategy: ClickUp assigns from workspace (team) members usually.
        # So providing get_team_members is usually sufficient. But list_id allows us to find the team_id if needed.
        # For simplicity, we will expose get_team_members if we have team_id.
        pass

    async def get_team_members(self, access_token: str, team_id: str) -> Dict[str, Any]:
        """Get members of a team (workspace)."""
        # GET /team is actually what we use for 'get_teams' which includes members usually?
        # Let's check get_teams response. It returns 'teams' array which contains 'members'.
        # So we can reuse get_teams but filter for specific team_id if provided.
        
        url = f"{self.BASE_URL}/team"
        headers = {"Authorization": access_token}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            teams = data.get("teams", [])
            target_team = None
            if team_id:
                for t in teams:
                    if t.get("id") == team_id:
                        target_team = t
                        break
            else:
                target_team = teams[0] if teams else None
                
            if not target_team:
                return {"success": False, "error": "Team not found"}
                
            members = []
            for m in target_team.get("members", []):
                # Handle inconsistent ClickUp API structure: sometimes user data is wrapped in "user", sometimes it's at the root
                if "user" in m:
                    user = m.get("user", {})
                else:
                    user = m

                members.append({
                    "id": user.get("id"),
                    "username": user.get("username"),
                    "email": user.get("email"),
                    "profilePicture": user.get("profilePicture"),
                    "initials": user.get("initials")
                })
                
            return {"success": True, "members": members}

    async def create_task(self, access_token: str, list_id: str, name: str, description: str = None, assignees: List[int] = None, priority: int = None, due_date: int = None, start_date: int = None) -> Dict[str, Any]:
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
        
        if assignees:
            payload["assignees"] = assignees
        if priority:
            payload["priority"] = priority
        if due_date:
            payload["due_date"] = due_date
        if start_date:
            payload["start_date"] = start_date
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def update_task(self, access_token: str, task_id: str, status: str = None, name: str = None, description: str = None, due_date: int = None, start_date: int = None, assignees: Dict[str, List[int]] = None, priority: int = None) -> Dict[str, Any]:
        """Update a task (status, name, description, dates, assignees, priority)."""
        url = f"{self.BASE_URL}/task/{task_id}"
        headers = {
            "Authorization": access_token,
            "Content-Type": "application/json"
        }
        payload = {}
        if status:
            payload["status"] = status
        if name:
            payload["name"] = name
        if description:
            payload["description"] = description
        if due_date is not None:
            payload["due_date"] = due_date
        if start_date is not None:
            payload["start_date"] = start_date
        if priority is not None:
            payload["priority"] = priority
        if assignees:
            # ClickUp update assignees structure is tricky, often it wants { "add": [...], "rem": [...] }
            # For simplicity let's assume valid payload passed from executor
            payload["assignees"] = assignees
            
        if not payload:
             return {"success": False, "error": "No update parameters provided"}

        async with httpx.AsyncClient() as client:
            response = await client.put(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
