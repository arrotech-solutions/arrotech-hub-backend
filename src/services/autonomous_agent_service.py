"""
Autonomous Agent Service for converting workflows into self-executing agents.
"""
import asyncio
import json
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import (User, Workflow, WorkflowExecution,
                      WorkflowExecutionStatus, WorkflowStatus,
                      WorkflowTriggerType)
from .llm_service import LLMService
from .workflow_builder_service import WorkflowBuilderService


class AgentStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PAUSED = "paused"
    ERROR = "error"


class AgentTriggerType(Enum):
    SCHEDULED = "scheduled"
    EVENT_DRIVEN = "event_driven"
    WEBHOOK = "webhook"
    MANUAL = "manual"


class AgentScheduleType(Enum):
    ONCE = "once"
    REPEAT = "repeat"
    CRON = "cron"
    INTERVAL = "interval"


class AutonomousAgentService:
    def __init__(self):
        self.workflow_service = WorkflowBuilderService()
        self.llm_service = LLMService()
        self.active_agents: Dict[str, asyncio.Task] = {}
        
    async def create_agent_from_workflow(
        self,
        workflow_id: uuid.UUID,
        user_id: uuid.UUID,
        db: AsyncSession,
        agent_config: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Convert a workflow into an autonomous agent.
        """
        # Get the workflow
        workflow = await self.workflow_service.get_workflow(workflow_id, user_id, db)
        if not workflow:
            raise ValueError("Workflow not found")
        
        # Generate agent configuration
        agent_id = str(uuid.uuid4())
        agent_config = agent_config or {}
        
        # Create agent prompt
        agent_prompt = await self._generate_agent_prompt(workflow, agent_config)
        
        # Create agent metadata
        agent_metadata = {
            "agent_id": agent_id,
            "workflow_id": workflow_id,
            "user_id": user_id,
            "status": AgentStatus.ACTIVE.value,
            "trigger_type": agent_config.get("trigger_type", AgentTriggerType.MANUAL.value),
            "schedule": agent_config.get("schedule", {}),
            "monitoring": {
                "execution_count": 0,
                "success_count": 0,
                "error_count": 0,
                "last_execution": None,
                "average_execution_time": 0,
                "total_execution_time": 0
            },
            "performance_metrics": {
                "response_time": [],
                "success_rate": 0,
                "error_rate": 0,
                "cost_per_execution": 0
            },
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        # Update workflow with agent metadata
        workflow.workflow_metadata = workflow.workflow_metadata or {}
        workflow.workflow_metadata["agent"] = agent_metadata
        workflow.status = WorkflowStatus.ACTIVE
        
        await db.commit()
        await db.refresh(workflow)
        
        return {
            "agent_id": agent_id,
            "workflow_id": workflow_id,
            "agent_prompt": agent_prompt,
            "agent_config": agent_metadata,
            "status": "created"
        }
    
    async def _generate_agent_prompt(self, workflow: Workflow, agent_config: Dict[str, Any]) -> str:
        """
        Generate an autonomous agent prompt from a workflow.
        """
        # Base workflow prompt
        base_prompt = await self.workflow_service.create_agent_prompt(workflow)
        
        # Add autonomous capabilities
        autonomous_prompt = f"""
You are an autonomous agent created from the workflow: {workflow.name}

{base_prompt}

## Autonomous Agent Capabilities

### Self-Execution
- You can execute this workflow automatically when triggered
- You maintain context across multiple executions
- You can adapt to changing conditions and data

### Decision Making
- You can make decisions based on workflow conditions
- You can handle errors and retry failed steps
- You can optimize execution based on performance data

### Monitoring & Analytics
- You track your own performance metrics
- You report execution results and errors
- You can self-optimize based on historical data

### Trigger Types
- Scheduled: Execute at specific times
- Event-driven: Execute on specific events
- Webhook: Execute on HTTP requests
- Manual: Execute on user command

## Agent Configuration
- Trigger Type: {agent_config.get('trigger_type', 'manual')}
- Schedule: {json.dumps(agent_config.get('schedule', {}), indent=2)}
- Monitoring: Enabled
- Performance Tracking: Enabled

## Instructions
1. Execute the workflow when triggered
2. Monitor and report execution results
3. Adapt to changing conditions
4. Optimize performance over time
5. Handle errors gracefully
6. Maintain execution history

You are now an autonomous agent ready to execute this workflow independently.
"""
        
        return autonomous_prompt
    
    async def schedule_agent(
        self,
        agent_id: str,
        schedule_config: Dict[str, Any],
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Schedule an agent for automatic execution.
        """
        schedule_type = schedule_config.get("type", AgentScheduleType.REPEAT.value)
        
        if schedule_type == AgentScheduleType.ONCE.value:
            return await self._schedule_one_time(agent_id, schedule_config, db)
        elif schedule_type == AgentScheduleType.REPEAT.value:
            return await self._schedule_repeating(agent_id, schedule_config, db)
        elif schedule_type == AgentScheduleType.CRON.value:
            return await self._schedule_cron(agent_id, schedule_config, db)
        elif schedule_type == AgentScheduleType.INTERVAL.value:
            return await self._schedule_interval(agent_id, schedule_config, db)
        else:
            raise ValueError(f"Unsupported schedule type: {schedule_type}")
    
    async def _schedule_one_time(
        self,
        agent_id: str,
        schedule_config: Dict[str, Any],
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Schedule a one-time execution.
        """
        execution_time = datetime.fromisoformat(schedule_config["execution_time"])
        
        # Create scheduled execution task
        task = asyncio.create_task(
            self._execute_scheduled_agent(agent_id, execution_time, db)
        )
        
        self.active_agents[agent_id] = task
        
        return {
            "agent_id": agent_id,
            "schedule_type": "once",
            "execution_time": execution_time.isoformat(),
            "status": "scheduled"
        }
    
    async def _schedule_repeating(
        self,
        agent_id: str,
        schedule_config: Dict[str, Any],
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Schedule a repeating execution.
        """
        interval_seconds = schedule_config.get("interval_seconds", 3600)  # Default 1 hour
        max_executions = schedule_config.get("max_executions", None)
        
        # Create repeating execution task
        task = asyncio.create_task(
            self._execute_repeating_agent(agent_id, interval_seconds, max_executions, db)
        )
        
        self.active_agents[agent_id] = task
        
        return {
            "agent_id": agent_id,
            "schedule_type": "repeat",
            "interval_seconds": interval_seconds,
            "max_executions": max_executions,
            "status": "scheduled"
        }
    
    async def _schedule_cron(
        self,
        agent_id: str,
        schedule_config: Dict[str, Any],
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Schedule a cron-based execution.
        """
        cron_expression = schedule_config["cron_expression"]
        
        # Create cron execution task
        task = asyncio.create_task(
            self._execute_cron_agent(agent_id, cron_expression, db)
        )
        
        self.active_agents[agent_id] = task
        
        return {
            "agent_id": agent_id,
            "schedule_type": "cron",
            "cron_expression": cron_expression,
            "status": "scheduled"
        }
    
    async def _schedule_interval(
        self,
        agent_id: str,
        schedule_config: Dict[str, Any],
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Schedule an interval-based execution.
        """
        interval_seconds = schedule_config.get("interval_seconds", 3600)
        
        # Create interval execution task
        task = asyncio.create_task(
            self._execute_interval_agent(agent_id, interval_seconds, db)
        )
        
        self.active_agents[agent_id] = task
        
        return {
            "agent_id": agent_id,
            "schedule_type": "interval",
            "interval_seconds": interval_seconds,
            "status": "scheduled"
        }
    
    async def _execute_scheduled_agent(
        self,
        agent_id: str,
        execution_time: datetime,
        db: AsyncSession
    ):
        """
        Execute a scheduled agent at the specified time.
        """
        # Wait until execution time
        now = datetime.utcnow()
        if execution_time > now:
            await asyncio.sleep((execution_time - now).total_seconds())
        
        await self._execute_agent(agent_id, db)
    
    async def _execute_repeating_agent(
        self,
        agent_id: str,
        interval_seconds: int,
        max_executions: Optional[int],
        db: AsyncSession
    ):
        """
        Execute a repeating agent at specified intervals.
        """
        execution_count = 0
        
        while True:
            try:
                await self._execute_agent(agent_id, db)
                execution_count += 1
                
                if max_executions and execution_count >= max_executions:
                    break
                
                await asyncio.sleep(interval_seconds)
                
            except Exception as e:
                print(f"Error executing repeating agent {agent_id}: {str(e)}")
                await asyncio.sleep(interval_seconds)
    
    async def _execute_cron_agent(
        self,
        agent_id: str,
        cron_expression: str,
        db: AsyncSession
    ):
        """
        Execute a cron-based agent.
        """
        # Simple cron implementation (can be enhanced with croniter library)
        while True:
            try:
                # Check if it's time to execute based on cron expression
                if self._should_execute_cron(cron_expression):
                    await self._execute_agent(agent_id, db)
                
                # Check every minute
                await asyncio.sleep(60)
                
            except Exception as e:
                print(f"Error executing cron agent {agent_id}: {str(e)}")
                await asyncio.sleep(60)
    
    async def _execute_interval_agent(
        self,
        agent_id: str,
        interval_seconds: int,
        db: AsyncSession
    ):
        """
        Execute an interval-based agent.
        """
        while True:
            try:
                await self._execute_agent(agent_id, db)
                await asyncio.sleep(interval_seconds)
                
            except Exception as e:
                print(f"Error executing interval agent {agent_id}: {str(e)}")
                await asyncio.sleep(interval_seconds)
    
    def _should_execute_cron(self, cron_expression: str) -> bool:
        """
        Check if cron expression matches current time.
        Simple implementation - can be enhanced with croniter.
        """
        # Placeholder implementation
        # In production, use croniter library for proper cron parsing
        return True
    
    async def _execute_agent(self, agent_id: str, db: AsyncSession):
        """
        Execute an autonomous agent.
        """
        try:
            # Find workflow with this agent
            stmt = select(Workflow).where(
                Workflow.workflow_metadata.contains({"agent": {"agent_id": agent_id}})
            )
            result = await db.execute(stmt)
            workflow = result.scalar_one_or_none()
            
            if not workflow:
                print(f"Agent {agent_id} not found")
                return
            
            # Get agent metadata
            agent_metadata = workflow.workflow_metadata.get("agent", {})
            user_id = agent_metadata.get("user_id")
            
            # Execute workflow
            start_time = datetime.utcnow()
            execution = await self.workflow_service.execute_workflow(
                workflow.id, user_id, db, {}
            )
            end_time = datetime.utcnow()
            
            # Update agent monitoring data
            await self._update_agent_monitoring(agent_id, execution, start_time, end_time, db)
            
            print(f"Agent {agent_id} executed successfully")
            
        except Exception as e:
            print(f"Error executing agent {agent_id}: {str(e)}")
            await self._update_agent_error(agent_id, str(e), db)
    
    async def _update_agent_monitoring(
        self,
        agent_id: str,
        execution: WorkflowExecution,
        start_time: datetime,
        end_time: datetime,
        db: AsyncSession
    ):
        """
        Update agent monitoring data after execution.
        """
        # Find workflow with this agent
        stmt = select(Workflow).where(
            Workflow.workflow_metadata.contains({"agent": {"agent_id": agent_id}})
        )
        result = await db.execute(stmt)
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            return
        
        agent_metadata = workflow.workflow_metadata.get("agent", {})
        monitoring = agent_metadata.get("monitoring", {})
        performance = agent_metadata.get("performance_metrics", {})
        
        # Update monitoring data
        execution_time = (end_time - start_time).total_seconds()
        monitoring["execution_count"] = monitoring.get("execution_count", 0) + 1
        monitoring["last_execution"] = end_time.isoformat()
        
        if execution.status == WorkflowExecutionStatus.COMPLETED:
            monitoring["success_count"] = monitoring.get("success_count", 0) + 1
        else:
            monitoring["error_count"] = monitoring.get("error_count", 0) + 1
        
        # Update performance metrics
        total_time = monitoring.get("total_execution_time", 0) + execution_time
        monitoring["total_execution_time"] = total_time
        monitoring["average_execution_time"] = total_time / monitoring["execution_count"]
        
        # Update success rate
        total_executions = monitoring["execution_count"]
        success_count = monitoring["success_count"]
        performance["success_rate"] = (success_count / total_executions) * 100
        performance["error_rate"] = 100 - performance["success_rate"]
        
        # Update response time tracking
        response_times = performance.get("response_time", [])
        response_times.append(execution_time)
        if len(response_times) > 100:  # Keep last 100 executions
            response_times.pop(0)
        performance["response_time"] = response_times
        
        # Update workflow metadata
        workflow.workflow_metadata["agent"]["monitoring"] = monitoring
        workflow.workflow_metadata["agent"]["performance_metrics"] = performance
        workflow.workflow_metadata["agent"]["updated_at"] = datetime.utcnow().isoformat()
        
        await db.commit()
    
    async def _update_agent_error(self, agent_id: str, error_message: str, db: AsyncSession):
        """
        Update agent error tracking.
        """
        # Find workflow with this agent
        stmt = select(Workflow).where(
            Workflow.workflow_metadata.contains({"agent": {"agent_id": agent_id}})
        )
        result = await db.execute(stmt)
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            return
        
        agent_metadata = workflow.workflow_metadata.get("agent", {})
        monitoring = agent_metadata.get("monitoring", {})
        
        # Update error count
        monitoring["error_count"] = monitoring.get("error_count", 0) + 1
        monitoring["last_error"] = error_message
        monitoring["last_execution"] = datetime.utcnow().isoformat()
        
        # Update workflow metadata
        workflow.workflow_metadata["agent"]["monitoring"] = monitoring
        workflow.workflow_metadata["agent"]["updated_at"] = datetime.utcnow().isoformat()
        
        await db.commit()
    
    async def get_agent_status(self, agent_id: str, db: AsyncSession) -> Optional[Dict[str, Any]]:
        """
        Get the status and monitoring data for an agent.
        """
        stmt = select(Workflow).where(
            Workflow.workflow_metadata.contains({"agent": {"agent_id": agent_id}})
        )
        result = await db.execute(stmt)
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            return None
        
        agent_metadata = workflow.workflow_metadata.get("agent", {})
        
        return {
            "agent_id": agent_id,
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
            "status": agent_metadata.get("status"),
            "trigger_type": agent_metadata.get("trigger_type"),
            "schedule": agent_metadata.get("schedule", {}),
            "monitoring": agent_metadata.get("monitoring", {}),
            "performance_metrics": agent_metadata.get("performance_metrics", {}),
            "created_at": agent_metadata.get("created_at"),
            "updated_at": agent_metadata.get("updated_at")
        }
    
    async def pause_agent(self, agent_id: str, db: AsyncSession) -> bool:
        """
        Pause an autonomous agent.
        """
        stmt = select(Workflow).where(
            Workflow.workflow_metadata.contains({"agent": {"agent_id": agent_id}})
        )
        result = await db.execute(stmt)
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            return False
        
        # Update agent status
        workflow.workflow_metadata["agent"]["status"] = AgentStatus.PAUSED.value
        workflow.workflow_metadata["agent"]["updated_at"] = datetime.utcnow().isoformat()
        
        # Cancel active task if running
        if agent_id in self.active_agents:
            self.active_agents[agent_id].cancel()
            del self.active_agents[agent_id]
        
        await db.commit()
        return True
    
    async def resume_agent(self, agent_id: str, db: AsyncSession) -> bool:
        """
        Resume a paused autonomous agent.
        """
        stmt = select(Workflow).where(
            Workflow.workflow_metadata.contains({"agent": {"agent_id": agent_id}})
        )
        result = await db.execute(stmt)
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            return False
        
        # Update agent status
        workflow.workflow_metadata["agent"]["status"] = AgentStatus.ACTIVE.value
        workflow.workflow_metadata["agent"]["updated_at"] = datetime.utcnow().isoformat()
        
        # Restart scheduling if needed
        schedule = workflow.workflow_metadata["agent"].get("schedule", {})
        if schedule:
            await self.schedule_agent(agent_id, schedule, db)
        
        await db.commit()
        return True
    
    async def delete_agent(self, agent_id: str, db: AsyncSession) -> bool:
        """
        Delete an autonomous agent.
        """
        stmt = select(Workflow).where(
            Workflow.workflow_metadata.contains({"agent": {"agent_id": agent_id}})
        )
        result = await db.execute(stmt)
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            return False
        
        # Remove agent metadata
        if "agent" in workflow.workflow_metadata:
            del workflow.workflow_metadata["agent"]
        
        # Cancel active task if running
        if agent_id in self.active_agents:
            self.active_agents[agent_id].cancel()
            del self.active_agents[agent_id]
        
        await db.commit()
        return True
    
    async def get_user_agents(self, user_id: uuid.UUID, db: AsyncSession) -> List[Dict[str, Any]]:
        """
        Get all agents for a user.
        """
        stmt = select(Workflow).where(
            Workflow.user_id == user_id,
            Workflow.workflow_metadata.contains({"agent": {}})
        )
        result = await db.execute(stmt)
        workflows = result.scalars().all()
        
        agents = []
        for workflow in workflows:
            agent_metadata = workflow.workflow_metadata.get("agent", {})
            agents.append({
                "agent_id": agent_metadata.get("agent_id"),
                "workflow_id": workflow.id,
                "workflow_name": workflow.name,
                "status": agent_metadata.get("status"),
                "trigger_type": agent_metadata.get("trigger_type"),
                "monitoring": agent_metadata.get("monitoring", {}),
                "created_at": agent_metadata.get("created_at")
            })
        
        return agents 