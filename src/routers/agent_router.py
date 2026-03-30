"""
Agent Router for managing autonomous agents.
"""
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User
from ..services.autonomous_agent_service import AutonomousAgentService
from .auth_router import get_current_user

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentCreate(BaseModel):
    workflow_id: uuid.UUID = Field(
        ..., 
        description="The unique ID of the workflow that this agent will automate. The workflow must exist and be accessible by the user.",
        example=42
    )
    agent_config: Optional[Dict[str, Any]] = Field(
        None, 
        description="Optional configuration overrides for the agent, such as specific prompt instructions or execution parameters.",
        example={"persona": "helpful assistant", "verbosity": "high"}
    )


class AgentSchedule(BaseModel):
    agent_id: str = Field(..., description="The unique UUID of the agent to schedule.")
    schedule_config: Dict[str, Any] = Field(
        ..., 
        description="Configuration for the execution schedule. Supports 'interval' (seconds) or 'cron' (standard cron expression).",
        example={"type": "cron", "cron_expression": "0 9 * * *"}
    )


class AgentResponse(BaseModel):
    agent_id: str = Field(..., description="The unique UUID of the autonomous agent.")
    workflow_id: uuid.UUID = Field(..., description="The ID of the underlying workflow.")
    workflow_name: str = Field(..., description="The human-readable name of the workflow.")
    status: str = Field(..., description="Current operational status (e.g., 'active', 'paused', 'failed').")
    trigger_type: str = Field(..., description="How the agent is triggered (e.g., 'scheduled', 'event_driven').")
    schedule: Optional[Dict[str, Any]] = Field(None, description="The configured schedule, if any.")
    monitoring: Dict[str, Any] = Field(..., description="Live monitoring statistics for the agent.")
    performance_metrics: Dict[str, Any] = Field(..., description="Aggregated performance data (success rates, latencies).")
    created_at: str = Field(..., description="ISO 8601 timestamp of agent creation.")
    updated_at: str = Field(..., description="ISO 8601 timestamp of last update.")


class AgentStatusResponse(BaseModel):
    agent_id: str
    workflow_id: uuid.UUID
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
    """
    ### Deploy an Autonomous Agent
    
    Transforms a static workflow into a dynamic, autonomous agent. Agents are the "living" versions of your automations that can run on schedules or respond to events.
    
    **When to deploy an agent:**
    - When you need a workflow to run periodically (e.g., every hour).
    - When you want an AI to monitor a channel (like WhatsApp or Slack) and take action automatically.
    - When building a complex, multi-stage business process that requires state management.
    
    **Configuration Overrides:**
    You can pass specialized instructions to the agent during creation to fine-tune its "personality" or "reasoning" style beyond the basic workflow definition.
    """
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
    """
    ### Agent Pulse & Health Monitoring
    
    Retrieves deep diagnostic information and current health metrics for a specific agent.
    
    **Monitoring Data includes:**
    - `execution_count`: Total number of times the agent has run.
    - `success_count`: Number of successful goal completions.
    - `last_error`: The last exception encountered (if any).
    - `success_rate`: Percentage of successful executions.
    
    **Use this endpoint to:**
    - Build a health dashboard for your automations.
    - Trigger alerts if an agent's success rate falls below a threshold.
    - Inspect real-time performance of business-critical bots.
    """
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
