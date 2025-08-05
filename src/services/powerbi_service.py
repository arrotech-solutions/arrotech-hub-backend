"""
Power BI integration service for Mini-Hub.
"""

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from ..config import settings


class PowerBIService:
    def __init__(self):
        self.client_id = settings.POWERBI_CLIENT_ID
        self.client_secret = settings.POWERBI_CLIENT_SECRET
        self.tenant_id = settings.POWERBI_TENANT_ID
        self.base_url = "https://api.powerbi.com/v1.0/myorg"
        self.auth_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        self.access_token = None
        self.token_expires_at = None

    async def _get_access_token(self) -> str:
        """Get or refresh Power BI access token."""
        if (self.access_token and self.token_expires_at and 
            datetime.now() < self.token_expires_at):
            return self.access_token

        auth_data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://analysis.windows.net/powerbi/api/.default"
        }

        response = requests.post(self.auth_url, data=auth_data)
        
        if response.status_code == 200:
            token_data = response.json()
            self.access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
            return self.access_token
        else:
            raise Exception(f"Failed to get access token: {response.status_code}")

    async def _get_headers(self) -> Dict[str, str]:
        """Get headers with access token."""
        token = await self._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    async def test_connection(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Test Power BI connection."""
        try:
            if config:
                client_id = config.get("client_id")
                client_secret = config.get("client_secret")
                tenant_id = config.get("tenant_id")
            else:
                client_id = settings.POWERBI_CLIENT_ID
                client_secret = settings.POWERBI_CLIENT_SECRET
                tenant_id = settings.POWERBI_TENANT_ID

            if not all([client_id, client_secret, tenant_id]):
                return {
                    "success": False,
                    "error": "Power BI credentials not configured"
                }

            # Test by getting workspaces
            headers = await self._get_headers()
            response = requests.get(f"{self.base_url}/groups", headers=headers)

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "Power BI connection successful",
                    "workspaces_count": len(response.json().get("value", []))
                }
            else:
                return {
                    "success": False,
                    "error": f"Connection failed: {response.status_code} - {response.text}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Connection error: {str(e)}"
            }

    async def get_workspaces(self) -> Dict[str, Any]:
        """Get all Power BI workspaces."""
        try:
            headers = await self._get_headers()
            response = requests.get(f"{self.base_url}/groups", headers=headers)

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "workspaces": data.get("value", []),
                        "total": len(data.get("value", []))
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to fetch workspaces: {response.status_code}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error fetching workspaces: {str(e)}"
            }

    async def get_datasets(self, workspace_id: str = None) -> Dict[str, Any]:
        """Get datasets from a workspace."""
        try:
            headers = await self._get_headers()
            
            if workspace_id:
                url = f"{self.base_url}/groups/{workspace_id}/datasets"
            else:
                url = f"{self.base_url}/datasets"

            response = requests.get(url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "datasets": data.get("value", []),
                        "total": len(data.get("value", []))
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to fetch datasets: {response.status_code}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error fetching datasets: {str(e)}"
            }

    async def get_reports(self, workspace_id: str = None) -> Dict[str, Any]:
        """Get reports from a workspace."""
        try:
            headers = await self._get_headers()
            
            if workspace_id:
                url = f"{self.base_url}/groups/{workspace_id}/reports"
            else:
                url = f"{self.base_url}/reports"

            response = requests.get(url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "reports": data.get("value", []),
                        "total": len(data.get("value", []))
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to fetch reports: {response.status_code}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error fetching reports: {str(e)}"
            }

    async def get_dashboards(self, workspace_id: str = None) -> Dict[str, Any]:
        """Get dashboards from a workspace."""
        try:
            headers = await self._get_headers()
            
            if workspace_id:
                url = f"{self.base_url}/groups/{workspace_id}/dashboards"
            else:
                url = f"{self.base_url}/dashboards"

            response = requests.get(url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "dashboards": data.get("value", []),
                        "total": len(data.get("value", []))
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to fetch dashboards: {response.status_code}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error fetching dashboards: {str(e)}"
            }

    async def get_dataset_schema(self, dataset_id: str, workspace_id: str = None) -> Dict[str, Any]:
        """Get schema information for a dataset."""
        try:
            headers = await self._get_headers()
            
            if workspace_id:
                url = f"{self.base_url}/groups/{workspace_id}/datasets/{dataset_id}/tables"
            else:
                url = f"{self.base_url}/datasets/{dataset_id}/tables"

            response = requests.get(url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "tables": data.get("value", []),
                        "total": len(data.get("value", []))
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to fetch dataset schema: {response.status_code}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error fetching dataset schema: {str(e)}"
            }

    async def execute_dax_query(self, dataset_id: str, query: str, workspace_id: str = None) -> Dict[str, Any]:
        """Execute a DAX query on a dataset."""
        try:
            headers = await self._get_headers()
            
            if workspace_id:
                url = f"{self.base_url}/groups/{workspace_id}/datasets/{dataset_id}/executeQueries"
            else:
                url = f"{self.base_url}/datasets/{dataset_id}/executeQueries"

            payload = {
                "queries": [
                    {
                        "query": query
                    }
                ]
            }

            response = requests.post(url, headers=headers, json=payload)

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "data": data
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to execute DAX query: {response.status_code}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error executing DAX query: {str(e)}"
            }

    async def refresh_dataset(self, dataset_id: str, workspace_id: str = None) -> Dict[str, Any]:
        """Refresh a dataset."""
        try:
            headers = await self._get_headers()
            
            if workspace_id:
                url = f"{self.base_url}/groups/{workspace_id}/datasets/{dataset_id}/refreshes"
            else:
                url = f"{self.base_url}/datasets/{dataset_id}/refreshes"

            response = requests.post(url, headers=headers)

            if response.status_code == 202:
                return {
                    "success": True,
                    "message": "Dataset refresh initiated successfully"
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to refresh dataset: {response.status_code}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error refreshing dataset: {str(e)}"
            }

    async def get_refresh_history(self, dataset_id: str, workspace_id: str = None) -> Dict[str, Any]:
        """Get refresh history for a dataset."""
        try:
            headers = await self._get_headers()
            
            if workspace_id:
                url = f"{self.base_url}/groups/{workspace_id}/datasets/{dataset_id}/refreshes"
            else:
                url = f"{self.base_url}/datasets/{dataset_id}/refreshes"

            response = requests.get(url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "refreshes": data.get("value", []),
                        "total": len(data.get("value", []))
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to fetch refresh history: {response.status_code}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error fetching refresh history: {str(e)}"
            }

    async def get_report_embed_token(self, report_id: str, workspace_id: str = None) -> Dict[str, Any]:
        """Get embed token for a report."""
        try:
            headers = await self._get_headers()
            
            if workspace_id:
                url = f"{self.base_url}/groups/{workspace_id}/reports/{report_id}/GenerateToken"
            else:
                url = f"{self.base_url}/reports/{report_id}/GenerateToken"

            payload = {
                "accessLevel": "View",
                "allowSaveAs": False
            }

            response = requests.post(url, headers=headers, json=payload)

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "embed_token": data.get("token"),
                        "expiration": data.get("expiration")
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to generate embed token: {response.status_code}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error generating embed token: {str(e)}"
            }

    async def get_workspace_users(self, workspace_id: str) -> Dict[str, Any]:
        """Get users with access to a workspace."""
        try:
            headers = await self._get_headers()
            url = f"{self.base_url}/groups/{workspace_id}/users"

            response = requests.get(url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "users": data.get("value", []),
                        "total": len(data.get("value", []))
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to fetch workspace users: {response.status_code}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error fetching workspace users: {str(e)}"
            }

    async def get_activity_logs(self, start_date: str = None, end_date: str = None) -> Dict[str, Any]:
        """Get Power BI activity logs."""
        try:
            headers = await self._get_headers()
            url = f"{self.base_url}/activityevents"

            params = {}
            if start_date:
                params["startDateTime"] = start_date
            if end_date:
                params["endDateTime"] = end_date

            response = requests.get(url, headers=headers, params=params)

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "data": {
                        "activities": data.get("value", []),
                        "total": len(data.get("value", []))
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to fetch activity logs: {response.status_code}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error fetching activity logs: {str(e)}"
            }

    async def create_workspace(self, name: str, description: str = None) -> Dict[str, Any]:
        """Create a new Power BI workspace."""
        try:
            headers = await self._get_headers()
            url = f"{self.base_url}/groups"

            payload = {
                "name": name
            }
            if description:
                payload["description"] = description

            response = requests.post(url, headers=headers, json=payload)

            if response.status_code == 201:
                data = response.json()
                return {
                    "success": True,
                    "data": data
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to create workspace: {response.status_code}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error creating workspace: {str(e)}"
            }

    async def delete_workspace(self, workspace_id: str) -> Dict[str, Any]:
        """Delete a Power BI workspace."""
        try:
            headers = await self._get_headers()
            url = f"{self.base_url}/groups/{workspace_id}"

            response = requests.delete(url, headers=headers)

            if response.status_code == 204:
                return {
                    "success": True,
                    "message": "Workspace deleted successfully"
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to delete workspace: {response.status_code}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error deleting workspace: {str(e)}"
            }

    async def get_analytics_summary(self, workspace_id: str = None) -> Dict[str, Any]:
        """Get analytics summary for workspaces, datasets, and reports."""
        try:
            summary = {
                "workspaces": 0,
                "datasets": 0,
                "reports": 0,
                "dashboards": 0,
                "recent_activities": []
            }

            # Get workspaces
            workspaces_result = await self.get_workspaces()
            if workspaces_result["success"]:
                summary["workspaces"] = workspaces_result["data"]["total"]

            # Get datasets
            datasets_result = await self.get_datasets(workspace_id)
            if datasets_result["success"]:
                summary["datasets"] = datasets_result["data"]["total"]

            # Get reports
            reports_result = await self.get_reports(workspace_id)
            if reports_result["success"]:
                summary["reports"] = reports_result["data"]["total"]

            # Get dashboards
            dashboards_result = await self.get_dashboards(workspace_id)
            if dashboards_result["success"]:
                summary["dashboards"] = dashboards_result["data"]["total"]

            # Get recent activities
            activities_result = await self.get_activity_logs()
            if activities_result["success"]:
                summary["recent_activities"] = activities_result["data"]["activities"][:10]

            return {
                "success": True,
                "data": summary
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Error generating analytics summary: {str(e)}"
            } 