"""
Asana Service for managing projects, tasks, and team collaboration.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiohttp

from ..config import settings

logger = logging.getLogger(__name__)


class AsanaService:
    """Service for managing Asana projects and tasks."""

    def __init__(self):
        self.access_token = None
        self.workspace_id = None
        self.base_url = "https://app.asana.com/api/1.0"
        self._initialized = False

    async def initialize(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the Asana service with configuration."""
        if self._initialized:
            return

        # Get configuration from settings or provided config
        if config:
            self.access_token = config.get("access_token")
            self.workspace_id = config.get("workspace_id")
        else:
            self.access_token = settings.ASANA_ACCESS_TOKEN
            self.workspace_id = settings.ASANA_WORKSPACE_ID

        if not self.access_token:
            logger.warning("Asana access token not configured")
            return

        self._initialized = True
        logger.info("Asana service initialized")

    def get_auth_url(self, user_id: str) -> str:
        """Get Asana OAuth authorization URL."""
        client_id = settings.ASANA_CLIENT_ID
        # Redirect to Frontend to handle the code exchange
        redirect_uri = f"{settings.FRONTEND_URL}/connections"
        # Embed user_id in state to link connection to correct user
        state = f"asana_connection::{user_id}"
        return (
            f"https://app.asana.com/-/oauth_authorize?"
            f"client_id={client_id}&"
            f"redirect_uri={redirect_uri}&"
            f"response_type=code&"
            f"state={state}&"
            f"scope=default&"
            f"display_ui=always" # Force login/consent screen (Asana specific)
        )

    async def get_token_from_code(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access token."""
        client_id = settings.ASANA_CLIENT_ID
        client_secret = settings.ASANA_CLIENT_SECRET
        # Must match the redirect_uri used in get_auth_url
        redirect_uri = f"{settings.FRONTEND_URL}/connections"
        
        url = "https://app.asana.com/-/oauth_token"
        data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": code
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to get Asana token: {error_text}")
                    return None

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh Asana access token using refresh token."""
        client_id = settings.ASANA_CLIENT_ID
        client_secret = settings.ASANA_CLIENT_SECRET
        # Must match the redirect_uri used in initial auth? (Usually not strictly required for refresh but good practice)
        redirect_uri = f"{settings.FRONTEND_URL}/connections"
        
        url = "https://app.asana.com/-/oauth_token"
        data = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "refresh_token": refresh_token
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to refresh Asana token: {error_text}")
                    return {"error": error_text, "success": False}

    async def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make authenticated request to Asana API."""
        if not self._initialized:
            return {"success": False, "error": "Asana service not initialized"}

        headers = {
            "Authorization": f"Bearer {self.access_token}",
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
            logger.error(f"Error making Asana API request: {e}")
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
                errors = response_data.get("errors", [])
                if isinstance(errors, list) and len(errors) > 0:
                    error_msg = errors[0].get("message", f"HTTP {response.status}")
                else:
                    error_msg = f"HTTP {response.status}: {response_data}"
                return {"success": False, "error": error_msg}

        except Exception as e:
            logger.error(f"Error handling response: {e}")
            return {"success": False, "error": f"Response parsing failed: {str(e)}"}

    async def test_connection(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Test Asana connection by getting user info."""
        await self.initialize(config)
        
        # Check if service was initialized properly
        if not self._initialized:
            return {
                "success": False,
                "error": "Asana service not initialized - check credentials"
            }
        
        result = await self._make_request("GET", "/users/me")
        
        if result.get("success"):
            user_data = result.get("data", {})
            return {
                "success": True,
                "message": "Asana connection successful",
                "method": "Bearer Token Authentication",
                "user": {
                    "id": user_data.get("gid"),
                    "name": user_data.get("name"),
                    "email": user_data.get("email"),
                    "workspaces": user_data.get("workspaces", [])
                }
            }
        else:
            error_msg = result.get("error", "Asana connection test failed")
            logger.error(f"Asana connection test failed: {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }

    # Workspace Management
    async def get_workspaces(self) -> Dict[str, Any]:
        """Get user's workspaces."""
        return await self._make_request("GET", "/workspaces")

    async def get_workspace(self, workspace_id: str) -> Dict[str, Any]:
        """Get workspace details."""
        return await self._make_request("GET", f"/workspaces/{workspace_id}")

    # Project Management
    async def create_project(
        self,
        name: str,
        workspace_id: Optional[str] = None,
        team_id: Optional[str] = None,
        notes: Optional[str] = None,
        color: Optional[str] = None,
        default_view: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new project."""
        data = {
            "name": name,
            "workspace": workspace_id or self.workspace_id
        }
        
        if team_id:
            data["team"] = team_id
        if notes:
            data["notes"] = notes
        if color:
            data["color"] = color
        if default_view:
            data["default_view"] = default_view

        return await self._make_request("POST", "/projects", data)

    async def get_project(self, project_id: str) -> Dict[str, Any]:
        """Get project details."""
        return await self._make_request("GET", f"/projects/{project_id}")

    async def update_project(
        self,
        project_id: str,
        name: Optional[str] = None,
        notes: Optional[str] = None,
        color: Optional[str] = None,
        default_view: Optional[str] = None,
        archived: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Update project details."""
        data = {}
        if name:
            data["name"] = name
        if notes is not None:
            data["notes"] = notes
        if color:
            data["color"] = color
        if default_view:
            data["default_view"] = default_view
        if archived is not None:
            data["archived"] = str(archived).lower()

        return await self._make_request("PUT", f"/projects/{project_id}", data)

    async def delete_project(self, project_id: str) -> Dict[str, Any]:
        """Delete a project."""
        return await self._make_request("DELETE", f"/projects/{project_id}")

    async def list_projects(
        self,
        workspace_id: Optional[str] = None,
        team_id: Optional[str] = None,
        archived: bool = False,
        opt_fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """List projects."""
        params = {"archived": str(archived).lower()}
        
        if workspace_id:
            params["workspace"] = workspace_id
        if team_id:
            params["team"] = team_id
        if opt_fields:
            params["opt_fields"] = ",".join(opt_fields)

        return await self._make_request("GET", "/projects", params=params)

    # Task Management
    async def create_task(
        self,
        name: str,
        workspace_id: Optional[str] = None,
        projects: Optional[List[str]] = None,
        parent: Optional[str] = None,
        notes: Optional[str] = None,
        assignee: Optional[str] = None,
        due_date: Optional[str] = None,
        due_on: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Create a new task."""
        data = {
            "name": name,
            "workspace": workspace_id or self.workspace_id
        }
        
        if projects:
            data["projects"] = projects
        if parent:
            data["parent"] = parent
        if notes:
            data["notes"] = notes
        if assignee:
            data["assignee"] = assignee
        if due_date:
            data["due_date"] = due_date
        if due_on:
            data["due_on"] = due_on
        if tags:
            data["tags"] = tags

        return await self._make_request("POST", "/tasks", data)

    async def get_task(self, task_id: str, opt_fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """Get task details."""
        params = {}
        if opt_fields:
            params["opt_fields"] = ",".join(opt_fields)
        
        return await self._make_request("GET", f"/tasks/{task_id}", params=params)

    async def update_task(
        self,
        task_id: str,
        name: Optional[str] = None,
        notes: Optional[str] = None,
        assignee: Optional[str] = None,
        due_date: Optional[str] = None,
        due_on: Optional[str] = None,
        completed: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Update task details."""
        data = {}
        if name:
            data["name"] = name
        if notes is not None:
            data["notes"] = notes
        if assignee:
            data["assignee"] = assignee
        if due_date:
            data["due_date"] = due_date
        if due_on:
            data["due_on"] = due_on
        if completed is not None:
            data["completed"] = str(completed).lower()

        return await self._make_request("PUT", f"/tasks/{task_id}", data)

    async def delete_task(self, task_id: str) -> Dict[str, Any]:
        """Delete a task."""
        return await self._make_request("DELETE", f"/tasks/{task_id}")

    async def list_tasks(
        self,
        assignee: Optional[str] = None,
        workspace_id: Optional[str] = None,
        project_id: Optional[str] = None,
        completed_since: Optional[str] = None,
        opt_fields: Optional[List[str]] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """List tasks."""
        params = {"limit": str(limit)}
        
        if assignee:
            params["assignee"] = assignee
        if workspace_id:
            params["workspace"] = workspace_id
        if project_id:
            params["project"] = project_id
        if completed_since:
            params["completed_since"] = completed_since
        if opt_fields:
            params["opt_fields"] = ",".join(opt_fields)

        return await self._make_request("GET", "/tasks", params=params)

    # Subtask Management
    async def create_subtask(
        self,
        parent_task_id: str,
        name: str,
        notes: Optional[str] = None,
        assignee: Optional[str] = None,
        due_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a subtask."""
        data = {
            "name": name,
            "parent": parent_task_id
        }
        
        if notes:
            data["notes"] = notes
        if assignee:
            data["assignee"] = assignee
        if due_date:
            data["due_date"] = due_date

        return await self._make_request("POST", "/tasks", data)

    async def get_subtasks(self, task_id: str) -> Dict[str, Any]:
        """Get subtasks of a task."""
        return await self._make_request("GET", f"/tasks/{task_id}/subtasks")

    # Section Management
    async def create_section(
        self,
        project_id: str,
        name: str
    ) -> Dict[str, Any]:
        """Create a section in a project."""
        data = {
            "name": name
        }
        return await self._make_request("POST", f"/projects/{project_id}/sections", data)

    async def get_sections(self, project_id: str) -> Dict[str, Any]:
        """Get sections in a project."""
        return await self._make_request("GET", f"/projects/{project_id}/sections")

    async def update_section(
        self,
        section_id: str,
        name: str
    ) -> Dict[str, Any]:
        """Update a section."""
        data = {"name": name}
        return await self._make_request("PUT", f"/sections/{section_id}", data)

    async def delete_section(self, section_id: str) -> Dict[str, Any]:
        """Delete a section."""
        return await self._make_request("DELETE", f"/sections/{section_id}")

    # Team Management
    async def get_teams(self, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        """Get teams."""
        params = {}
        if workspace_id:
            params["workspace"] = workspace_id
        
        return await self._make_request("GET", "/teams", params=params)

    async def get_team(self, team_id: str) -> Dict[str, Any]:
        """Get team details."""
        return await self._make_request("GET", f"/teams/{team_id}")

    async def get_team_members(self, team_id: str) -> Dict[str, Any]:
        """Get team members."""
        return await self._make_request("GET", f"/teams/{team_id}/users")

    # User Management
    async def get_users(
        self,
        workspace_id: Optional[str] = None,
        team_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get users."""
        params = {}
        if workspace_id:
            params["workspace"] = workspace_id
        if team_id:
            params["team"] = team_id
        
        return await self._make_request("GET", "/users", params=params)

    async def get_user(self, user_id: str) -> Dict[str, Any]:
        """Get user details."""
        return await self._make_request("GET", f"/users/{user_id}")

    # Tag Management
    async def create_tag(
        self,
        name: str,
        workspace_id: Optional[str] = None,
        color: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a tag."""
        data = {
            "name": name,
            "workspace": workspace_id or self.workspace_id
        }
        
        if color:
            data["color"] = color
        if notes:
            data["notes"] = notes

        return await self._make_request("POST", "/tags", data)

    async def get_tags(
        self,
        workspace_id: Optional[str] = None,
        opt_fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Get tags."""
        params = {}
        if workspace_id:
            params["workspace"] = workspace_id
        if opt_fields:
            params["opt_fields"] = ",".join(opt_fields)
        
        return await self._make_request("GET", "/tags", params=params)

    async def update_tag(
        self,
        tag_id: str,
        name: Optional[str] = None,
        color: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update a tag."""
        data = {}
        if name:
            data["name"] = name
        if color:
            data["color"] = color
        if notes is not None:
            data["notes"] = notes

        return await self._make_request("PUT", f"/tags/{tag_id}", data)

    # Comment Management
    async def add_comment(
        self,
        task_id: str,
        text: str
    ) -> Dict[str, Any]:
        """Add a comment to a task."""
        data = {"text": text}
        return await self._make_request("POST", f"/tasks/{task_id}/stories", data)

    async def get_comments(self, task_id: str) -> Dict[str, Any]:
        """Get comments for a task."""
        return await self._make_request("GET", f"/tasks/{task_id}/stories")

    # Search and Filtering
    async def search_tasks(
        self,
        query: str,
        workspace_id: Optional[str] = None,
        project_id: Optional[str] = None,
        assignee: Optional[str] = None,
        completed_since: Optional[str] = None
    ) -> Dict[str, Any]:
        """Search tasks."""
        params = {"query": query}
        
        if workspace_id:
            params["workspace"] = workspace_id
        if project_id:
            params["project"] = project_id
        if assignee:
            params["assignee"] = assignee
        if completed_since:
            params["completed_since"] = completed_since

        return await self._make_request("GET", "/tasks/search", params=params)

    # Project Templates
    async def get_project_templates(self, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        """Get project templates."""
        params = {}
        if workspace_id:
            params["workspace"] = workspace_id
        
        return await self._make_request("GET", "/project_templates", params=params)

    async def create_project_from_template(
        self,
        template_id: str,
        name: str,
        workspace_id: Optional[str] = None,
        team_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a project from a template."""
        data = {
            "name": name,
            "workspace": workspace_id or self.workspace_id
        }
        
        if team_id:
            data["team"] = team_id

        return await self._make_request("POST", f"/project_templates/{template_id}/instantiateProject", data)

    # Portfolio Management
    async def create_portfolio(
        self,
        name: str,
        workspace_id: Optional[str] = None,
        color: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a portfolio."""
        data = {
            "name": name,
            "workspace": workspace_id or self.workspace_id
        }
        
        if color:
            data["color"] = color
        if notes:
            data["notes"] = notes

        return await self._make_request("POST", "/portfolios", data)

    async def get_portfolios(self, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        """Get portfolios."""
        params = {}
        if workspace_id:
            params["workspace"] = workspace_id
        
        return await self._make_request("GET", "/portfolios", params=params)

    async def add_project_to_portfolio(
        self,
        portfolio_id: str,
        project_id: str
    ) -> Dict[str, Any]:
        """Add a project to a portfolio."""
        data = {"project": project_id}
        return await self._make_request("POST", f"/portfolios/{portfolio_id}/addItem", data)

    # Utility Methods
    async def get_task_dependencies(self, task_id: str) -> Dict[str, Any]:
        """Get task dependencies."""
        return await self._make_request("GET", f"/tasks/{task_id}/dependencies")

    async def add_task_dependency(
        self,
        task_id: str,
        dependent_task_id: str
    ) -> Dict[str, Any]:
        """Add a task dependency."""
        data = {"dependent_task": dependent_task_id}
        return await self._make_request("POST", f"/tasks/{task_id}/dependencies", data)

    async def get_task_followers(self, task_id: str) -> Dict[str, Any]:
        """Get task followers."""
        return await self._make_request("GET", f"/tasks/{task_id}/followers")

    async def add_task_follower(
        self,
        task_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Add a follower to a task."""
        data = {"follower": user_id}
        return await self._make_request("POST", f"/tasks/{task_id}/followers", data)

    async def get_project_statuses(self, project_id: str) -> Dict[str, Any]:
        """Get project status updates."""
        return await self._make_request("GET", f"/projects/{project_id}/project_statuses")

    async def create_project_status(
        self,
        project_id: str,
        text: str,
        color: str = "green"
    ) -> Dict[str, Any]:
        """Create a project status update."""
        data = {
            "text": text,
            "color": color
        }
        return await self._make_request("POST", f"/projects/{project_id}/project_statuses", data) 