"""
Agent Router for managing autonomous agents.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User
from ..services.autonomous_agent_service import AutonomousAgentService
from .auth_router import get_current_user

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentCreate(BaseModel):
    workflow_id: int
    agent_config: Optional[Dict[str, Any]] = None


class AgentSchedule(BaseModel):
    agent_id: str
    schedule_config: Dict[str, Any]


class AgentResponse(BaseModel):
    agent_id: str
    workflow_id: int
    workflow_name: str
    status: str
    trigger_type: str
    schedule: Optional[Dict[str, Any]]
    monitoring: Dict[str, Any]
    performance_metrics: Dict[str, Any]
    created_at: str
    updated_at: str


class AgentStatusResponse(BaseModel):
    agent_id: str
    workflow_id: int
    workflow_name: str
    status: str
    trigger_type: str
    schedule: Optional[Dict[str, Any]]
    monitoring: Dict[str, Any]
    performance_metrics: Dict[str, Any]
    created_at: str
    updated_at: str


@router.post("/create", response_model=Dict[str, Any])
async def create_agent(
    data: AgentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Create an autonomous agent from a workflow."""
    try:
        agent_service = AutonomousAgentService()

        agent = await agent_service.create_agent_from_workflow(
            data.workflow_id, user.id, db, data.agent_config
        )

        return {
            "success": True,
            "agent_id": agent["agent_id"],
            "workflow_id": agent["workflow_id"],
            "agent_prompt": agent["agent_prompt"],
            "agent_config": agent["agent_config"],
            "message": "Autonomous agent created successfully"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create agent: {str(e)}"
        )


@router.post("/schedule", response_model=Dict[str, Any])
async def schedule_agent(
    data: AgentSchedule,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Schedule an agent for automatic execution."""
    try:
        agent_service = AutonomousAgentService()

        schedule_result = await agent_service.schedule_agent(
            data.agent_id, data.schedule_config, db
        )

        return {
            "success": True,
            "agent_id": schedule_result["agent_id"],
            "schedule_type": schedule_result["schedule_type"],
            "status": schedule_result["status"],
            "message": "Agent scheduled successfully"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to schedule agent: {str(e)}"
        )


@router.get("/", response_model=List[AgentResponse])
async def get_user_agents(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Get all agents for the current user."""
    try:
        agent_service = AutonomousAgentService()
        agents = await agent_service.get_user_agents(user.id, db)

        return [
            AgentResponse(
                agent_id=agent["agent_id"],
                workflow_id=agent["workflow_id"],
                workflow_name=agent["workflow_name"],
                status=agent["status"],
                trigger_type=agent["trigger_type"],
                schedule=None,  # Will be populated from agent status
                monitoring=agent["monitoring"],
                performance_metrics={},  # Will be populated from agent status
                created_at=agent["created_at"],
                updated_at=agent["created_at"]  # Placeholder
            ) for agent in agents
        ]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agents: {str(e)}"
        )


@router.get("/{agent_id}/status", response_model=AgentStatusResponse)
async def get_agent_status(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Get detailed status and monitoring data for an agent."""
    try:
        agent_service = AutonomousAgentService()
        agent_status = await agent_service.get_agent_status(agent_id, db)

        if not agent_status:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found"
            )

        return AgentStatusResponse(
            agent_id=agent_status["agent_id"],
            workflow_id=agent_status["workflow_id"],
            workflow_name=agent_status["workflow_name"],
            status=agent_status["status"],
            trigger_type=agent_status["trigger_type"],
            schedule=agent_status["schedule"],
            monitoring=agent_status["monitoring"],
            performance_metrics=agent_status["performance_metrics"],
            created_at=agent_status["created_at"],
            updated_at=agent_status["updated_at"]
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agent status: {str(e)}"
        )


@router.post("/{agent_id}/pause")
async def pause_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Pause an autonomous agent."""
    try:
        agent_service = AutonomousAgentService()
        success = await agent_service.pause_agent(agent_id, db)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found"
            )

        return {
            "success": True,
            "agent_id": agent_id,
            "message": "Agent paused successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to pause agent: {str(e)}"
        )


@router.post("/{agent_id}/resume")
async def resume_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Resume a paused autonomous agent."""
    try:
        agent_service = AutonomousAgentService()
        success = await agent_service.resume_agent(agent_id, db)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found"
            )

        return {
            "success": True,
            "agent_id": agent_id,
            "message": "Agent resumed successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resume agent: {str(e)}"
        )


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Delete an autonomous agent."""
    try:
        agent_service = AutonomousAgentService()
        success = await agent_service.delete_agent(agent_id, db)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found"
            )

        return {
            "success": True,
            "agent_id": agent_id,
            "message": "Agent deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete agent: {str(e)}"
        )


@router.post("/{agent_id}/execute")
async def execute_agent_manual(
    agent_id: str,
    input_data: Optional[Dict[str, Any]] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Manually execute an autonomous agent."""
    try:
        agent_service = AutonomousAgentService()

        # Get agent status first to verify it exists
        agent_status = await agent_service.get_agent_status(agent_id, db)
        if not agent_status:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found"
            )

        # Execute the agent
        await agent_service._execute_agent(agent_id, db)

        return {
            "success": True,
            "agent_id": agent_id,
            "message": "Agent executed successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute agent: {str(e)}"
        )


@router.get("/{agent_id}/analytics")
async def get_agent_analytics(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Get detailed analytics for an agent."""
    try:
        agent_service = AutonomousAgentService()
        agent_status = await agent_service.get_agent_status(agent_id, db)

        if not agent_status:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found"
            )

        monitoring = agent_status["monitoring"]
        performance = agent_status["performance_metrics"]

        # Calculate additional analytics
        analytics = {
            "execution_summary": {
                "total_executions": monitoring.get("execution_count", 0),
                "successful_executions": monitoring.get("success_count", 0),
                "failed_executions": monitoring.get("error_count", 0),
                "success_rate": performance.get("success_rate", 0),
                "error_rate": performance.get("error_rate", 0)
            },
            "performance_metrics": {
                "average_execution_time": monitoring.get("average_execution_time", 0),
                "total_execution_time": monitoring.get("total_execution_time", 0),
                "response_time_trend": performance.get("response_time", [])
            },
            "recent_activity": {
                "last_execution": monitoring.get("last_execution"),
                "last_error": monitoring.get("last_error"),
                "status": agent_status["status"]
            },
            "schedule_info": {
                "trigger_type": agent_status["trigger_type"],
                "schedule": agent_status["schedule"]
            }
        }

        return analytics
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agent analytics: {str(e)}"
        )


@router.get("/templates")
async def get_agent_templates():
    """Get available agent templates and configurations."""
    templates = [
        {
            "name": "Scheduled Lead Processing",
            "description": "Automatically process leads at scheduled intervals",
            "agent_config": {
                "trigger_type": "scheduled",
                "schedule": {
                    "type": "repeat",
                    "interval_seconds": 3600,  # Every hour
                    "max_executions": None
                }
            },
            "use_case": "Lead qualification and processing"
        },
        {
            "name": "Daily Report Generator",
            "description": "Generate daily reports automatically",
            "agent_config": {
                "trigger_type": "scheduled",
                "schedule": {
                    "type": "cron",
                    "cron_expression": "0 9 * * *"  # Daily at 9 AM
                }
            },
            "use_case": "Automated reporting"
        },
        {
            "name": "Event-Driven Notification",
            "description": "Send notifications based on events",
            "agent_config": {
                "trigger_type": "event_driven",
                "schedule": {
                    "type": "manual"
                }
            },
            "use_case": "Real-time notifications"
        },
        {
            "name": "Webhook-Triggered Agent",
            "description": "Execute workflows on webhook events",
            "agent_config": {
                "trigger_type": "webhook",
                "schedule": {
                    "type": "manual"
                }
            },
            "use_case": "External system integration"
        }
    ]

    return {"templates": templates}
