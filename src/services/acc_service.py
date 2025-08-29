"""
ACC (Autodesk Construction Cloud) Service

Service for integrating with ACC through the ACC-MCP server.
Provides tools for managing hubs, projects, and issues.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from ..models import Connection, User
from ..services.mcp_client_service import mcp_client_service

logger = logging.getLogger(__name__)


class ACCService:
    """Service for ACC (Autodesk Construction Cloud) operations."""
    
    def __init__(self):
        self.platform = "acc"
        
    async def test_connection(self, connection: Connection) -> Dict[str, Any]:
        """Test ACC connection by attempting to get hubs."""
        try:
            logger.info("[DEBUG] ===== ACC Service Test Connection =====")
            logger.info(f"[DEBUG] Connection ID: {connection.id}")
            logger.info(f"[DEBUG] Connection platform: {connection.platform}")
            logger.info(f"[DEBUG] Connection config keys: {list(connection.config.keys()) if connection.config else 'None'}")
            
            logger.info("[DEBUG] First testing connection by listing available tools...")
            
            # First, let's try to get the list of available tools to test the connection
            result = await mcp_client_service.test_connection(connection.config)
            
            logger.info(f"[DEBUG] MCP test connection result: {result}")
            
            if result.get("success"):
                logger.info("[DEBUG] MCP test connection succeeded!")
                tools_found = result.get("tools_found", 0)
                logger.info(f"[DEBUG] Found {tools_found} available tools")
                return {
                    "success": True,
                    "message": f"Successfully connected to ACC-MCP server. Found {tools_found} available tools.",
                    "tools_count": tools_found
                }
            else:
                logger.error(f"[DEBUG] MCP test connection failed: {result.get('error', 'Unknown error')}")
                return {
                    "success": False,
                    "error": f"ACC connection failed: {result.get('error', 'Unknown error')}"
                }
                
        except Exception as e:
            logger.error(f"[DEBUG] ACC connection test failed with exception: {type(e).__name__}: {e}")
            logger.error(f"[DEBUG] Exception details: {str(e)}")
            return {
                "success": False,
                "error": f"Connection test failed: {str(e)}"
            }
    
    async def get_hubs(self, connection) -> Dict[str, Any]:
        """Get ACC hubs."""
        try:
            logger.info("[DEBUG] ===== Getting ACC Hubs =====")
            logger.info(f"[DEBUG] Connection ID: {connection.id}")
            
            # Prepare environment with access token
            env = connection.config.get("env", {}).copy()
            access_token = connection.config.get("access_token")
            
            if access_token:
                env["APS_ACCESS_TOKEN"] = access_token
                logger.info(f"[DEBUG] Added access token to environment (length: {len(access_token)})")
            else:
                logger.warning("[DEBUG] No access token found in connection config")
            
            # First, let's check what tools are available
            logger.info("[DEBUG] Listing available tools...")
            tools_result = await mcp_client_service._stdio_jsonrpc_request(
                connection.config.get("command"),
                connection.config.get("cwd"), 
                env,  # Use updated environment with token
                "tools/list",
                {},
                connection.config.get("timeoutMs", 30000)
            )
            logger.info(f"[DEBUG] Available tools: {tools_result}")
            
            # Call the GetHubsAsync tool through MCP tools/call
            logger.info("[DEBUG] Calling GetHubsAsync tool...")
            result = await mcp_client_service._stdio_jsonrpc_request(
                connection.config.get("command"),
                connection.config.get("cwd"), 
                env,  # Use updated environment with token
                "tools/call",
                {
                    "name": "GetHubsAsync",
                    "arguments": {}
                },
                connection.config.get("timeoutMs", 30000)
            )
            
            logger.info(f"[DEBUG] Get hubs result: {result}")
            return result
            
        except Exception as e:
            logger.error(f"[DEBUG] Error getting ACC hubs: {e}")
            return {"success": False, "error": f"Failed to get hubs: {str(e)}"}
            
    async def get_oauth_url(self, connection) -> Dict[str, Any]:
        """Get OAuth URL for manual authentication."""
        try:
            # Extract OAuth parameters from connection config
            env = connection.config.get("env", {})
            client_id = env.get("APS_CLIENT_ID")
            redirect_uri = env.get("APS_REDIRECT_URI", "http://localhost:5001/api/aps/callback/oauth")
            
            if not client_id:
                return {"success": False, "error": "APS_CLIENT_ID not configured"}
            
            # Generate OAuth URL manually
            scopes = "account:read data:create data:write data:read bucket:read"
            oauth_url = (
                f"https://developer.api.autodesk.com/authentication/v2/authorize"
                f"?response_type=code"
                f"&client_id={client_id}"
                f"&redirect_uri={redirect_uri}"
                f"&scope={scopes.replace(' ', '%20')}"
            )
            
            return {
                "success": True,
                "oauth_url": oauth_url,
                "redirect_uri": redirect_uri,
                "instructions": [
                    "1. Open the OAuth URL in your browser",
                    "2. Login to your Autodesk account",
                    "3. Grant permissions to the application", 
                    "4. You'll be redirected to the callback URL",
                    "5. The ACC-MCP server will automatically receive the authorization code"
                ]
            }
            
        except Exception as e:
            logger.error(f"Error generating OAuth URL: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_projects(self, connection, hub_id: str) -> Dict[str, Any]:
        """Get ACC projects for a hub."""
        try:
            logger.info("[DEBUG] ===== Getting ACC Projects =====")
            logger.info(f"[DEBUG] Connection ID: {connection.id}")
            logger.info(f"[DEBUG] Hub ID: {hub_id}")
            
            # Prepare environment with access token
            env = connection.config.get("env", {}).copy()
            access_token = connection.config.get("access_token")
            
            if access_token:
                env["APS_ACCESS_TOKEN"] = access_token
                logger.info(f"[DEBUG] Added access token to environment (length: {len(access_token)})")
            else:
                logger.warning("[DEBUG] No access token found in connection config")
            
            # Call the GetProjectsAsync tool through MCP tools/call
            logger.info("[DEBUG] Calling GetProjectsAsync tool...")
            result = await mcp_client_service._stdio_jsonrpc_request(
                connection.config.get("command"),
                connection.config.get("cwd"), 
                env,  # Use updated environment with token
                "tools/call",
                {
                    "name": "GetProjectsAsync",
                    "arguments": {
                        "hubId": hub_id  # ACC-MCP expects camelCase hubId
                    }
                },
                connection.config.get("timeoutMs", 30000)
            )
            
            logger.info(f"[DEBUG] Get projects result: {result}")
            return result
            
        except Exception as e:
            logger.error(f"[DEBUG] Error getting ACC projects: {e}")
            return {"success": False, "error": f"Failed to get projects: {str(e)}"}
    
    async def get_issues(self, connection, project_id: str, issue_type_id: str = None, created_at_start: str = None, auto_limit: bool = True) -> Dict[str, Any]:
        """Get ACC issues for a project with automatic buffer overflow protection."""
        try:
            logger.info("[DEBUG] ===== Getting ACC Issues with Auto Buffer Protection =====")
            logger.info(f"[DEBUG] Connection ID: {connection.id}")
            logger.info(f"[DEBUG] Original Project ID: {project_id}")
            logger.info(f"[DEBUG] Auto limit enabled: {auto_limit}")
            
            # CRITICAL: Clean project_id for Issues API - remove "b." prefix
            clean_project_id = project_id.replace('b.', '') if project_id and project_id.startswith('b.') else project_id
            logger.info(f"[DEBUG] Cleaned Project ID: {clean_project_id}")
            
            # Smart filtering to prevent buffer overflow
            if auto_limit and not created_at_start:
                # Automatically apply recent filter to prevent buffer overflow
                from datetime import datetime, timedelta
                recent_date = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
                created_at_start = recent_date
                logger.info(f"[DEBUG] Auto-applied recent filter: last 30 days since {recent_date}")
            
            # Prepare environment with access token
            env = connection.config.get("env", {}).copy()
            access_token = connection.config.get("access_token")
            
            if access_token:
                env["APS_ACCESS_TOKEN"] = access_token
                logger.info(f"[DEBUG] Added access token to environment (length: {len(access_token)})")
            else:
                logger.warning("[DEBUG] No access token found in connection config")
            
            # Prepare arguments for GetIssuesAsync - use cleaned project ID
            mcp_arguments = {
                "projectId": clean_project_id  # ACC-MCP expects camelCase projectId with pure GUID
            }
            
            # Add optional parameters if provided
            if issue_type_id:
                mcp_arguments["issueTypeId"] = issue_type_id
            if created_at_start:
                mcp_arguments["createdAtStart"] = created_at_start
            
            logger.info(f"[DEBUG] MCP arguments: {mcp_arguments}")
            
            # Try with current filters first
            try:
                logger.info("[DEBUG] Calling GetIssuesAsync tool...")
                result = await mcp_client_service._stdio_jsonrpc_request(
                    connection.config.get("command"),
                    connection.config.get("cwd"), 
                    env,  # Use updated environment with token
                    "tools/call",
                    {
                        "name": "GetIssuesAsync",
                        "arguments": mcp_arguments
                    },
                    connection.config.get("timeoutMs", 30000)
                )
                
                logger.info(f"[DEBUG] Get issues result: {result}")
                return result
                
            except Exception as buffer_error:
                # If we hit buffer limit, try progressively shorter filters
                if "chunk exceed the limit" in str(buffer_error) or "Separator is not found" in str(buffer_error):
                    if auto_limit:
                        logger.warning(f"[DEBUG] Buffer limit hit, trying progressive fallback...")
                        return await self._get_issues_with_progressive_fallback(connection, clean_project_id, issue_type_id)
                    else:
                        logger.error(f"[DEBUG] Buffer limit hit and auto_limit disabled")
                        raise buffer_error
                else:
                    raise buffer_error
            
        except Exception as e:
            logger.error(f"[DEBUG] Error getting ACC issues: {e}")
            return {"success": False, "error": f"Failed to get issues: {str(e)}"}
    
    async def _get_issues_with_progressive_fallback(self, connection, project_id: str, issue_type_id: str = None) -> Dict[str, Any]:
        """Try progressively shorter time periods until we find one that works."""
        # Progressive fallback: 7 days → 3 days → 1 day → 12 hours → 6 hours → minimal response
        time_periods = [
            (7, "days"),
            (3, "days"), 
            (1, "days"),
            (12, "hours"),
            (6, "hours"),
            (2, "hours")
        ]
        
        from datetime import datetime, timedelta
        
        for period_value, period_unit in time_periods:
            try:
                logger.info(f"[DEBUG] Trying {period_value} {period_unit} filter...")
                
                # Calculate the date filter
                if period_unit == "days":
                    filter_date = (datetime.utcnow() - timedelta(days=period_value)).isoformat() + "Z"
                else:  # hours
                    filter_date = (datetime.utcnow() - timedelta(hours=period_value)).isoformat() + "Z"
                
                # Prepare environment with access token
                env = connection.config.get("env", {}).copy()
                access_token = connection.config.get("access_token")
                
                if access_token:
                    env["APS_ACCESS_TOKEN"] = access_token
                
                # Prepare arguments with time filter
                mcp_arguments = {
                    "projectId": project_id,
                    "createdAtStart": filter_date
                }
                
                if issue_type_id:
                    mcp_arguments["issueTypeId"] = issue_type_id
                
                logger.info(f"[DEBUG] Trying filter since: {filter_date}")
                
                result = await mcp_client_service._stdio_jsonrpc_request(
                    connection.config.get("command"),
                    connection.config.get("cwd"), 
                    env,
                    "tools/call",
                    {
                        "name": "GetIssuesAsync",
                        "arguments": mcp_arguments
                    },
                    connection.config.get("timeoutMs", 10000)  # Short timeout
                )
                
                logger.info(f"[DEBUG] {period_value} {period_unit} filter SUCCESS!")
                return result
                
            except Exception as e:
                if "chunk exceed the limit" in str(e) or "Separator is not found" in str(e):
                    logger.warning(f"[DEBUG] {period_value} {period_unit} filter failed, trying shorter period...")
                    continue  # Try next shorter period
                else:
                    # Different error, re-raise
                    logger.error(f"[DEBUG] Non-buffer error: {e}")
                    raise e
        
        # If all time periods failed, return a minimal success response
        logger.warning(f"[DEBUG] All time filters failed - project extremely busy. Returning minimal response.")
        return {
            "success": True,
            "data": [],
            "message": "Project has extremely high activity. Please use specific date/time filters for issue retrieval.",
            "fallback_used": True
        }
    
    async def get_issue_by_id(self, connection, project_id: str, issue_id: str) -> Dict[str, Any]:
        """Get a single ACC issue by its ID - much more efficient than fetching all issues."""
        try:
            logger.info(f"[DEBUG] ===== Getting Single ACC Issue by ID =====")
            logger.info(f"[DEBUG] Project ID: {project_id}")
            logger.info(f"[DEBUG] Issue ID: {issue_id}")
            
            # CRITICAL: Clean project_id for Issues API - remove "b." prefix
            clean_project_id = project_id.replace('b.', '') if project_id and project_id.startswith('b.') else project_id
            logger.info(f"[DEBUG] Cleaned Project ID: {clean_project_id}")
            
            # Prepare environment with access token
            env = connection.config.get("env", {}).copy()
            access_token = connection.config.get("access_token")
            
            if access_token:
                env["APS_ACCESS_TOKEN"] = access_token
                logger.info(f"[DEBUG] Added access token to environment")
            else:
                logger.warning("[DEBUG] No access token found in connection config")
            
            # Prepare arguments for GetIssueByIdAsync
            mcp_arguments = {
                "projectId": clean_project_id,
                "issueId": issue_id
            }
            
            logger.info(f"[DEBUG] MCP arguments: {mcp_arguments}")
            
            # Call the GetIssueByIdAsync tool through MCP tools/call
            logger.info("[DEBUG] Calling GetIssueByIdAsync tool...")
            result = await mcp_client_service._stdio_jsonrpc_request(
                connection.config.get("command"),
                connection.config.get("cwd"), 
                env,
                "tools/call",
                {
                    "name": "GetIssueByIdAsync",
                    "arguments": mcp_arguments
                },
                connection.config.get("timeoutMs", 15000)  # Much faster since it's just one issue
            )
            
            logger.info(f"[DEBUG] Get single issue result: SUCCESS")
            return result
            
        except Exception as e:
            logger.error(f"[DEBUG] Error getting single ACC issue: {e}")
            return {"success": False, "error": f"Failed to get issue by ID: {str(e)}"}
    
    async def create_issue(self, connection, project_id: str, title: str, description: str, **kwargs) -> Dict[str, Any]:
        """Create ACC issue."""
        try:
            logger.info("[DEBUG] ===== Creating ACC Issue =====")
            logger.info(f"[DEBUG] Connection ID: {connection.id}")
            logger.info(f"[DEBUG] Project ID: {project_id}")
            logger.info(f"[DEBUG] Project ID has 'b.' prefix: {project_id.startswith('b.') if project_id else False}")
            logger.info(f"[DEBUG] Title: {title}")
            logger.info(f"[DEBUG] Description: {description[:100]}...")
            
            # Prepare environment with access token
            env = connection.config.get("env", {}).copy()
            access_token = connection.config.get("access_token")
            
            if access_token:
                env["APS_ACCESS_TOKEN"] = access_token
                logger.info(f"[DEBUG] Added access token to environment (length: {len(access_token)})")
            else:
                logger.warning("[DEBUG] No access token found in connection config")
            
            # Prepare arguments for CreateIssueAsync with proper defaults
            # Extract status from kwargs with default
            status_value = kwargs.get("status", "open")  # Default to "open"
            
            mcp_arguments = {
                "projectId": project_id,  # ACC-MCP expects camelCase
                "title": title,
                "description": description,
                "status": status_value,  # Use extracted status with default
                "published": True,  # Default to True as required by API
                "snapshotHasMarkups": False  # Default to False
            }
            
            # Add optional parameters from kwargs
            # Support both snake_case and camelCase parameter names
            issue_subtype_id = kwargs.get("issue_subtype_id") or kwargs.get("issueSubtypeId")
            if issue_subtype_id:
                mcp_arguments["issueSubtypeId"] = issue_subtype_id
            
            # Override published default if explicitly provided
            if kwargs.get("published") is not None:
                mcp_arguments["published"] = kwargs["published"]
            # Handle all other optional parameters with both naming conventions
            assigned_to = kwargs.get("assigned_to") or kwargs.get("assignedTo")
            if assigned_to:
                mcp_arguments["assignedTo"] = assigned_to
            
            assigned_to_type = kwargs.get("assigned_to_type") or kwargs.get("assignedToType")
            if assigned_to_type:
                mcp_arguments["assignedToType"] = assigned_to_type
                
            due_date = kwargs.get("due_date") or kwargs.get("dueDate")
            if due_date:
                mcp_arguments["dueDate"] = due_date
                
            start_date = kwargs.get("start_date") or kwargs.get("startDate")
            if start_date:
                mcp_arguments["startDate"] = start_date
                
            location_id = kwargs.get("location_id") or kwargs.get("locationId")
            if location_id:
                mcp_arguments["locationId"] = location_id
                
            location_details = kwargs.get("location_details") or kwargs.get("locationDetails")
            if location_details:
                mcp_arguments["locationDetails"] = location_details
                
            root_cause_id = kwargs.get("root_cause_id") or kwargs.get("rootCauseId")
            if root_cause_id:
                mcp_arguments["rootCauseId"] = root_cause_id
                
            issue_template_id = kwargs.get("issue_template_id") or kwargs.get("issueTemplateId")
            if issue_template_id:
                mcp_arguments["issueTemplateId"] = issue_template_id
                
            permitted_actions = kwargs.get("permitted_actions") or kwargs.get("permittedActions")
            if permitted_actions:
                mcp_arguments["permittedActions"] = permitted_actions
                
            if kwargs.get("watchers"):
                mcp_arguments["watchers"] = kwargs["watchers"]
                
            custom_attributes = kwargs.get("custom_attributes") or kwargs.get("customAttributes")
            if custom_attributes:
                mcp_arguments["customAttributes"] = custom_attributes
            if kwargs.get("latitude") is not None:
                mcp_arguments["latitude"] = kwargs["latitude"]
            if kwargs.get("longitude") is not None:
                mcp_arguments["longitude"] = kwargs["longitude"]
            
            logger.info(f"[DEBUG] MCP arguments: {mcp_arguments}")
            logger.info(f"[DEBUG] ===== CREATION ARGUMENTS DETAIL =====")
            for key, value in mcp_arguments.items():
                logger.info(f"[DEBUG] {key}: {value} (type: {type(value)})")
            logger.info(f"[DEBUG] ========================================")
            
            # Call the CreateIssueAsync tool through MCP tools/call
            logger.info("[DEBUG] Calling CreateIssueAsync tool...")
            result = await mcp_client_service._stdio_jsonrpc_request(
                connection.config.get("command"),
                connection.config.get("cwd"), 
                env,  # Use updated environment with token
                "tools/call",
                {
                    "name": "CreateIssueAsync",
                    "arguments": mcp_arguments
                },
                connection.config.get("timeoutMs", 30000)
            )
            
            logger.info(f"[DEBUG] Create issue result: {result}")
            
            # Debug the created issue data structure
            if result and isinstance(result, dict) and 'content' in result:
                try:
                    import json
                    content = result['content']
                    if isinstance(content, list) and content:
                        content_text = content[0].get('text', '{}')
                        created_issue = json.loads(content_text)
                        logger.info(f"[DEBUG] ===== CREATED ISSUE DATA =====")
                        logger.info(f"[DEBUG] Created Issue ID: {created_issue.get('id')}")
                        logger.info(f"[DEBUG] Created Title: {created_issue.get('title')}")
                        logger.info(f"[DEBUG] Created AssignedTo: {created_issue.get('assignedTo')} (type: {type(created_issue.get('assignedTo'))})")
                        logger.info(f"[DEBUG] Created DueDate: {created_issue.get('dueDate')} (type: {type(created_issue.get('dueDate'))})")  
                        logger.info(f"[DEBUG] Created IssueSubtypeId: {created_issue.get('issueSubtypeId')} (type: {type(created_issue.get('issueSubtypeId'))})")
                        logger.info(f"[DEBUG] Created Issue Keys: {list(created_issue.keys())}")
                        logger.info(f"[DEBUG] ==============================")
                except Exception as e:
                    logger.error(f"[DEBUG] Error parsing created issue response: {e}")
            
            return result
            
        except Exception as e:
            logger.error(f"[DEBUG] Error creating ACC issue: {e}")
            return {"success": False, "error": f"Failed to create issue: {str(e)}"}
    
    async def update_issue(self, connection, project_id: str, issue_id: str, **kwargs) -> Dict[str, Any]:
        """Update ACC issue."""
        try:
            logger.info("[DEBUG] ===== Updating ACC Issue =====")
            logger.info(f"[DEBUG] Project ID: {project_id}")
            logger.info(f"[DEBUG] Issue ID: {issue_id}")
            
            # Prepare environment with access token
            env = connection.config.get("env", {}).copy()
            access_token = connection.config.get("access_token")
            
            if access_token:
                env["APS_ACCESS_TOKEN"] = access_token
            
            mcp_arguments = {
                "projectId": project_id,
                "issueId": issue_id
            }
            
            # Add optional update parameters
            for key, value in kwargs.items():
                if value is not None:
                    # Convert snake_case to camelCase for MCP
                    camel_key = key.replace("_", "").replace("id", "Id") if "_id" in key else key
                    mcp_arguments[camel_key] = value
            
            logger.info(f"[DEBUG] MCP arguments: {mcp_arguments}")
            
            result = await mcp_client_service._stdio_jsonrpc_request(
                connection.config.get("command"),
                connection.config.get("cwd"), 
                env,
                "tools/call",
                {
                    "name": "UpdateIssueAsync",
                    "arguments": mcp_arguments
                },
                connection.config.get("timeoutMs", 30000)
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[DEBUG] Error updating ACC issue: {e}")
            return {"success": False, "error": f"Failed to update issue: {str(e)}"}
    
    async def post_comment(self, connection, project_id: str, issue_id: str, body: str) -> Dict[str, Any]:
        """Post comment on ACC issue."""
        try:
            logger.info("[DEBUG] ===== Posting ACC Comment =====")
            logger.info(f"[DEBUG] Project ID: {project_id}")
            logger.info(f"[DEBUG] Issue ID: {issue_id}")
            
            # Prepare environment with access token
            env = connection.config.get("env", {}).copy()
            access_token = connection.config.get("access_token")
            
            if access_token:
                env["APS_ACCESS_TOKEN"] = access_token
            
            mcp_arguments = {
                "projectId": project_id,
                "issueId": issue_id,
                "body": body
            }
            
            result = await mcp_client_service._stdio_jsonrpc_request(
                connection.config.get("command"),
                connection.config.get("cwd"), 
                env,
                "tools/call",
                {
                    "name": "PostCommentOnIssueAsync",
                    "arguments": mcp_arguments
                },
                connection.config.get("timeoutMs", 30000)
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[DEBUG] Error posting ACC comment: {e}")
            return {"success": False, "error": f"Failed to post comment: {str(e)}"}
    
    async def get_comments(self, connection, project_id: str, issue_id: str) -> Dict[str, Any]:
        """Get comments for ACC issue."""
        try:
            logger.info("[DEBUG] ===== Getting ACC Comments =====")
            logger.info(f"[DEBUG] Project ID: {project_id}")
            logger.info(f"[DEBUG] Issue ID: {issue_id}")
            
            # Prepare environment with access token
            env = connection.config.get("env", {}).copy()
            access_token = connection.config.get("access_token")
            
            if access_token:
                env["APS_ACCESS_TOKEN"] = access_token
            
            mcp_arguments = {
                "projectId": project_id,
                "issueId": issue_id
            }
            
            result = await mcp_client_service._stdio_jsonrpc_request(
                connection.config.get("command"),
                connection.config.get("cwd"), 
                env,
                "tools/call",
                {
                    "name": "GetIssueCommentsAsync",
                    "arguments": mcp_arguments
                },
                connection.config.get("timeoutMs", 30000)
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[DEBUG] Error getting ACC comments: {e}")
            return {"success": False, "error": f"Failed to get comments: {str(e)}"}
    
    async def get_analytics_summary(self, connection) -> Dict[str, Any]:
        """Get ACC analytics summary."""
        return {"success": True, "data": {}, "message": "ACC analytics summary (placeholder)"}


# Global instance
acc_service = ACCService()
