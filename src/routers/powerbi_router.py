"""
Power BI router for Mini-Hub.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..models import User
from ..routers.auth_router import get_current_user
from ..services.powerbi_service import PowerBIService

router = APIRouter(prefix="/powerbi", tags=["Power BI"])

# Initialize Power BI service
powerbi_service = PowerBIService()


class PowerBIConnectionConfig(BaseModel):
    """Power BI connection configuration."""
    client_id: str
    client_secret: str
    tenant_id: str


class PowerBIQueryRequest(BaseModel):
    """Power BI DAX query request."""
    dataset_id: str
    query: str
    workspace_id: Optional[str] = None


class PowerBIWorkspaceRequest(BaseModel):
    """Power BI workspace request."""
    name: str
    description: Optional[str] = None


@router.post("/test-connection")
async def test_powerbi_connection(
    config: Optional[PowerBIConnectionConfig] = None,
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Test Power BI connection."""
    try:
        config_dict = config.dict() if config else None
        result = await powerbi_service.test_connection(config_dict)
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workspaces")
async def get_powerbi_workspaces(
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get all Power BI workspaces."""
    try:
        result = await powerbi_service.get_workspaces()
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/datasets")
async def get_powerbi_datasets(
    workspace_id: Optional[str] = Query(None, description="Workspace ID"),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get datasets from Power BI."""
    try:
        result = await powerbi_service.get_datasets(workspace_id)
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports")
async def get_powerbi_reports(
    workspace_id: Optional[str] = Query(None, description="Workspace ID"),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get reports from Power BI."""
    try:
        result = await powerbi_service.get_reports(workspace_id)
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboards")
async def get_powerbi_dashboards(
    workspace_id: Optional[str] = Query(None, description="Workspace ID"),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get dashboards from Power BI."""
    try:
        result = await powerbi_service.get_dashboards(workspace_id)
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/datasets/{dataset_id}/schema")
async def get_dataset_schema(
    dataset_id: str,
    workspace_id: Optional[str] = Query(None, description="Workspace ID"),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get schema information for a dataset."""
    try:
        result = await powerbi_service.get_dataset_schema(dataset_id, workspace_id)
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute-query")
async def execute_dax_query(
    request: PowerBIQueryRequest,
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Execute a DAX query on a dataset."""
    try:
        result = await powerbi_service.execute_dax_query(
            request.dataset_id,
            request.query,
            request.workspace_id
        )
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/datasets/{dataset_id}/refresh")
async def refresh_dataset(
    dataset_id: str,
    workspace_id: Optional[str] = Query(None, description="Workspace ID"),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Refresh a dataset."""
    try:
        result = await powerbi_service.refresh_dataset(dataset_id, workspace_id)
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/datasets/{dataset_id}/refresh-history")
async def get_refresh_history(
    dataset_id: str,
    workspace_id: Optional[str] = Query(None, description="Workspace ID"),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get refresh history for a dataset."""
    try:
        result = await powerbi_service.get_refresh_history(dataset_id, workspace_id)
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reports/{report_id}/embed-token")
async def get_report_embed_token(
    report_id: str,
    workspace_id: Optional[str] = Query(None, description="Workspace ID"),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get embed token for a report."""
    try:
        result = await powerbi_service.get_report_embed_token(report_id, workspace_id)
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workspaces/{workspace_id}/users")
async def get_workspace_users(
    workspace_id: str,
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get users with access to a workspace."""
    try:
        result = await powerbi_service.get_workspace_users(workspace_id)
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/activity-logs")
async def get_activity_logs(
    start_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date (ISO format)"),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get Power BI activity logs."""
    try:
        result = await powerbi_service.get_activity_logs(start_date, end_date)
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workspaces")
async def create_workspace(
    request: PowerBIWorkspaceRequest,
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Create a new Power BI workspace."""
    try:
        result = await powerbi_service.create_workspace(request.name, request.description)
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Delete a Power BI workspace."""
    try:
        result = await powerbi_service.delete_workspace(workspace_id)
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics-summary")
async def get_analytics_summary(
    workspace_id: Optional[str] = Query(None, description="Workspace ID"),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get analytics summary for Power BI."""
    try:
        result = await powerbi_service.get_analytics_summary(workspace_id)
        
        if result["success"]:
            return result
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 