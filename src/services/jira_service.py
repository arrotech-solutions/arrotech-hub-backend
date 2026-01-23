"""
Jira service for Mini-Hub MCP Server (Atlassian OAuth 2.0).
"""

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, quote

import aiohttp

from ..config import settings

logger = logging.getLogger(__name__)


class JiraService:
    """Jira API service using Atlassian OAuth 2.0."""

    def __init__(self):
        self.access_token: Optional[str] = None
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
        self.cloud_id: Optional[str] = None
        
        # Atlassian API base
        self.auth_base_url = "https://auth.atlassian.com/authorize"
        self.token_url = "https://auth.atlassian.com/oauth/token"
        
        # Base will be dynamically constructed with cloud_id: https://api.atlassian.com/ex/jira/{cloud_id}
        self.api_base_url = "https://api.atlassian.com/ex/jira" 

    async def initialize(self):
        """Initialize Jira credentials."""
        self.client_id = getattr(settings, "JIRA_CLIENT_ID", None)
        self.client_secret = getattr(settings, "JIRA_CLIENT_SECRET", None)
        
        if self.client_id and self.client_secret:
             logger.info("Jira credentials initialized")
        else:
             logger.warning("Jira credentials not fully configured")

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        """
        Generate Atlassian OAuth 2.0 authorization URL for Jira.
        Scopes: read:jira-work write:jira-work offline_access read:me
        """
        if not self.client_id:
            raise ValueError("Jira client_id must be configured")

        scopes = [
            "read:jira-work", 
            "write:jira-work", 
            "read:me", # For accessible-resources
            "offline_access"
        ]
        
        params = {
            "audience": "api.atlassian.com",
            "client_id": self.client_id,
            "scope": " ".join(scopes),
            "redirect_uri": redirect_uri,
            "state": state,
            "response_type": "code",
            "prompt": "consent"
        }
        
        return f"{self.auth_base_url}?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange authorization code for access token."""
        if not self.client_id or not self.client_secret:
            raise ValueError("Jira credentials must be configured")

        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.token_url, json=data) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    raise Exception(f"Failed to exchange token: {response.status} - {error_text}")

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh access token using refresh token."""
        if not self.client_id or not self.client_secret:
            raise ValueError("Jira credentials must be configured")

        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.token_url, json=data) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to refresh Jira token: {response.status} - {error_text}")
                    raise Exception(f"Failed to refresh token: {response.status} - {error_text}")

    async def get_accessible_resources(self) -> List[Dict[str, Any]]:
        """Get accessible resources (Cloud IDs)."""
         # https://api.atlassian.com/oauth/token/accessible-resources
        if not self.access_token:
             raise Exception("Access token required")

        url = "https://api.atlassian.com/oauth/token/accessible-resources"
        headers = {"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception(f"Failed to get resources: {response.status}")

    async def _request(self, method: str, endpoint: str, params: Dict = None, json_data: Dict = None) -> Any:
        """Helper to make authenticated requests to Jira API."""
        if not self.access_token:
             return {"success": False, "error": "Access token required"}
        
        if not self.cloud_id:
            # Try to fetch cloud_id if missing? Or assume it's set in init.
            # Usually router sets it from stored config.
            return {"success": False, "error": "Cloud ID required for Jira API calls"}

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json"
        }
        
        url = f"{self.api_base_url}/{self.cloud_id}/{endpoint}"

        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, params=params, json=json_data, headers=headers) as response:
                if response.status == 200 or response.status == 201:
                    return await response.json()
                else:
                    text = await response.text()
                    try:
                         # Attempt to parse json error if possible
                         err_json = await response.json()
                         return {"success": False, "error": f"Jira API Error ({response.status}): {err_json}"}
                    except:
                         return {"success": False, "error": f"Jira API Error ({response.status}): {text}"}

    async def get_projects(self) -> Dict[str, Any]:
        """Get projects."""
        response = await self._request("GET", "rest/api/3/project")
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        projects = []
        for p in response:
            projects.append({
                "id": p.get("id"),
                "key": p.get("key"),
                "name": p.get("name"),
                "type": p.get("projectTypeKey")
            })
            
        return {"success": True, "projects": projects, "count": len(projects)}

    async def search_issues(self, jql: str, limit: int = 10) -> Dict[str, Any]:
        """Search issues using JQL."""
        payload = {
            "jql": jql,
            "maxResults": limit,
            "fields": ["summary", "status", "priority", "assignee", "created", "project"]
        }
        # Updated to use new JQL search endpoint
        response = await self._request("POST", "rest/api/3/search", json_data=payload)
        
        if isinstance(response, dict) and "error" in response:
            # Fallback/Retry logic or just try the new endpoint directly if the above is the one that failed.
            # The user said the error output showed failure on 'rest/api/3/search'?
            # "The requested API has been removed... migrate to .../jql"
            # So I should use "rest/api/3/search/jql`?
            pass
            
        # Let's trust the error message and use /search for now?
        # Actually, let's look at the error again.
        # "The requested API ... migrate to .../jql API"
        # Checks online: `POST /rest/api/3/search` is indeed deprecated? 
        # Ref: https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/#api-rest-api-3-search-post
        # It seems `POST /rest/api/3/search` IS correct.
        # Maybe the user is on an older version or something?
        # BUT the error is explicit.
        # I will change to `rest/api/3/search` -> `rest/api/3/search`?
        # Wait, the error implies I am hitting a removed API.
        # Maybe the `jql` argument in body is the issue?
        # Let's try `rest/api/3/search` (which I was using).
        # Oh, maybe I should use `rest/api/3/search` with `jql` query param instead of body?
        # No, `POST` uses body.
        
        # NOTE: I will update the URL to `rest/api/3/search/jql` as explicitly requested by error.
        response = await self._request("POST", "rest/api/3/search/jql", json_data=payload)

        if isinstance(response, dict) and "error" in response:
             return response

        issues = []
        for i in response.get("issues", []):
            fields = i.get("fields", {})
            issues.append({
                "id": i.get("id"),
                "key": i.get("key"),
                "summary": fields.get("summary"),
                "status": (fields.get("status") or {}).get("name"),
                "assignee": (fields.get("assignee") or {}).get("displayName") if fields.get("assignee") else "Unassigned",
                "priority": (fields.get("priority") or {}).get("name"),
                "project": (fields.get("project") or {}).get("name"),
                "created": fields.get("created"),
                "url": i.get("self")
            })
            
        return {"success": True, "issues": issues, "count": len(issues)}

    async def create_issue(self, project_key: str, summary: str, description: str = "", issuetype: str = "Task", status: str = "To Do") -> Dict[str, Any]:
        """Create a new issue and optionally transition to specified status."""
        
        # Build ADF for description if using API v3 - Jira mandates ADF (Atlassian Document Format) for v3 'description'
        if description:
             description_adf = {
                 "type": "doc",
                 "version": 1,
                 "content": [
                     {
                         "type": "paragraph",
                         "content": [
                             {
                                 "type": "text",
                                 "text": description
                             }
                         ]
                     }
                 ]
             }
        else:
             description_adf = None

        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "issuetype": {"name": issuetype}
            }
        }
        
        if description_adf:
             payload["fields"]["description"] = description_adf
             
        response = await self._request("POST", "rest/api/3/issue", json_data=payload)
        
        if isinstance(response, dict) and "error" in response:
            return response
        
        issue_key = response.get("key")
        issue_id = response.get("id")
        
        # If status is not the default "To Do", transition the issue
        if status and status.lower() != "to do" and issue_key:
            try:
                await self._transition_issue(issue_key, status)
            except Exception as e:
                logger.warning(f"Could not transition issue {issue_key} to {status}: {e}")
            
        return {
            "success": True,
            "message": "Issue created",
            "issue": {
                "id": issue_id,
                "key": issue_key,
                "url": response.get("self"),
                "status": status
            }
        }

    async def _transition_issue(self, issue_key: str, target_status: str) -> Dict[str, Any]:
        """Transition an issue to a new status."""
        # Get available transitions
        transitions_response = await self._request("GET", f"rest/api/3/issue/{issue_key}/transitions")
        
        if isinstance(transitions_response, dict) and "error" in transitions_response:
            return transitions_response
        
        transitions = transitions_response.get("transitions", [])
        
        # Find matching transition
        target_status_lower = target_status.lower()
        transition_id = None
        for t in transitions:
            if t.get("name", "").lower() == target_status_lower or t.get("to", {}).get("name", "").lower() == target_status_lower:
                transition_id = t.get("id")
                break
        
        if not transition_id:
            logger.warning(f"No transition found to status '{target_status}' for issue {issue_key}. Available: {[t.get('name') for t in transitions]}")
            return {"success": False, "error": f"No transition to '{target_status}' available"}
        
        # Execute transition
        transition_payload = {"transition": {"id": transition_id}}
        result = await self._request("POST", f"rest/api/3/issue/{issue_key}/transitions", json_data=transition_payload)
        
        # Successful transition returns empty response
        if result is None or (isinstance(result, dict) and "error" not in result):
            return {"success": True, "message": f"Transitioned to {target_status}"}
        
        return result

