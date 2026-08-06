"""
Autonomous Agent Service for converting workflows into self-executing agents.
"""
import asyncio
import json
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from ..models import (User, Workflow, WorkflowExecution, WorkflowStep,
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
        
        # Create agent prompt (best-effort; never block agent creation)
        try:
            agent_prompt = await self._generate_agent_prompt(workflow, agent_config)
        except Exception as prompt_err:
            agent_prompt = f"Autonomous agent for workflow: {workflow.name}"
            # Log but continue — prompt is informational only
            import logging
            logging.getLogger(__name__).warning(
                "Failed to generate agent prompt for workflow %s: %s",
                workflow_id,
                prompt_err,
            )
        
        # Create agent metadata — UUIDs must be strings for JSON columns
        agent_metadata = {
            "agent_id": agent_id,
            "workflow_id": str(workflow_id),
            "user_id": str(user_id),
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
                "cost_per_execution": 0,
                "execution_count": 0,
            },
            "agent_kind": agent_config.get("agent_kind", "autonomous"),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        # Update workflow with agent metadata
        meta = dict(workflow.workflow_metadata or {})
        meta["agent"] = agent_metadata
        workflow.workflow_metadata = meta
        flag_modified(workflow, "workflow_metadata")
        workflow.status = WorkflowStatus.ACTIVE
        
        await db.commit()
        await db.refresh(workflow)
        
        return {
            "agent_id": agent_id,
            "workflow_id": str(workflow_id),
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
    
    async def _find_workflow_by_agent_id(
        self,
        agent_id: str,
        db: AsyncSession,
        *,
        user_id: Optional[uuid.UUID] = None,
    ) -> Optional[Workflow]:
        """Find a workflow by agent_id in metadata (DB-agnostic; scoped by user when provided)."""
        stmt = select(Workflow)
        if user_id is not None:
            stmt = stmt.where(Workflow.user_id == user_id)
        result = await db.execute(stmt)
        target = str(agent_id)
        for workflow in result.scalars().all():
            meta = workflow.workflow_metadata
            if not isinstance(meta, dict):
                continue
            agent_meta = meta.get("agent") or {}
            if str(agent_meta.get("agent_id") or "") == target:
                return workflow
        return None

    async def get_agent_status(
        self,
        agent_id: str,
        db: AsyncSession,
        user_id: Optional[uuid.UUID] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get the status and monitoring data for an agent.
        """
        workflow = await self._find_workflow_by_agent_id(agent_id, db, user_id=user_id)
        
        if not workflow:
            return None
        
        agent_metadata = (workflow.workflow_metadata or {}).get("agent", {})
        
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
    
    def _set_agent_metadata(self, workflow: Workflow, agent_metadata: Dict[str, Any]) -> None:
        meta = dict(workflow.workflow_metadata or {})
        meta["agent"] = agent_metadata
        workflow.workflow_metadata = meta
        flag_modified(workflow, "workflow_metadata")

    async def pause_agent(
        self,
        agent_id: str,
        db: AsyncSession,
        user_id: Optional[uuid.UUID] = None,
    ) -> bool:
        """
        Pause an autonomous agent.
        Also sets workflow.status to inactive so messaging triggers stop.
        """
        workflow = await self._find_workflow_by_agent_id(agent_id, db, user_id=user_id)

        if not workflow:
            return False

        agent_meta = dict((workflow.workflow_metadata or {}).get("agent") or {})
        agent_meta["status"] = AgentStatus.PAUSED.value
        agent_meta["updated_at"] = datetime.utcnow().isoformat()
        self._set_agent_metadata(workflow, agent_meta)
        workflow.status = WorkflowStatus.INACTIVE

        if agent_id in self.active_agents:
            try:
                self.active_agents[agent_id].cancel()
            except Exception:
                pass
            self.active_agents.pop(agent_id, None)

        await db.commit()
        return True

    async def resume_agent(
        self,
        agent_id: str,
        db: AsyncSession,
        user_id: Optional[uuid.UUID] = None,
    ) -> bool:
        """
        Resume a paused autonomous agent.
        Also sets workflow.status to active so messaging triggers resume.
        """
        workflow = await self._find_workflow_by_agent_id(agent_id, db, user_id=user_id)

        if not workflow:
            return False

        agent_meta = dict((workflow.workflow_metadata or {}).get("agent") or {})
        agent_meta["status"] = AgentStatus.ACTIVE.value
        agent_meta["updated_at"] = datetime.utcnow().isoformat()
        self._set_agent_metadata(workflow, agent_meta)
        workflow.status = WorkflowStatus.ACTIVE

        schedule = agent_meta.get("schedule") or {}
        if schedule:
            await self.schedule_agent(agent_id, schedule, db)

        await db.commit()
        return True

    async def delete_agent(
        self,
        agent_id: str,
        db: AsyncSession,
        user_id: Optional[uuid.UUID] = None,
    ) -> bool:
        """
        Delete an autonomous agent wrapper.
        Deactivates the underlying workflow so messaging triggers stop.
        """
        workflow = await self._find_workflow_by_agent_id(agent_id, db, user_id=user_id)

        if not workflow:
            return False

        meta = dict(workflow.workflow_metadata or {})
        if "agent" in meta:
            del meta["agent"]
            workflow.workflow_metadata = meta
            flag_modified(workflow, "workflow_metadata")

        workflow.status = WorkflowStatus.INACTIVE

        if agent_id in self.active_agents:
            try:
                self.active_agents[agent_id].cancel()
            except Exception:
                pass
            self.active_agents.pop(agent_id, None)

        await db.commit()
        return True

    async def get_user_agents(self, user_id: uuid.UUID, db: AsyncSession) -> List[Dict[str, Any]]:
        """
        Get all agents for a user.

        Includes:
        - Workflows with workflow_metadata.agent (autonomous wrappers)
        - Conversational messaging workflows (WhatsApp/Telegram ordering/support)
          even if agent metadata was never stamped
        """
        stmt = select(Workflow).where(Workflow.user_id == user_id)
        result = await db.execute(stmt)
        workflows = result.scalars().all()

        agents: List[Dict[str, Any]] = []
        seen_workflow_ids = set()
        dirty = False

        for workflow in workflows:
            meta = workflow.workflow_metadata or {}
            agent_meta = meta.get("agent") if isinstance(meta, dict) else None
            is_conversational = await self._is_conversational_messaging_workflow(workflow, db)

            if not agent_meta and not is_conversational:
                continue

            if not agent_meta and is_conversational:
                agent_meta = await self.ensure_agent_metadata(
                    workflow,
                    user_id,
                    db,
                    trigger_type=AgentTriggerType.EVENT_DRIVEN.value,
                    agent_kind="conversational",
                    commit=False,
                )
                dirty = True

            if workflow.id in seen_workflow_ids:
                continue
            seen_workflow_ids.add(workflow.id)

            channel = self._infer_channel(workflow, agent_meta)
            job_type = self._infer_job_type(workflow, agent_meta)
            agent_kind = (agent_meta or {}).get("agent_kind") or (
                "conversational" if is_conversational else "autonomous"
            )

            status = (agent_meta or {}).get("status") or "inactive"
            if is_conversational:
                if workflow.status == WorkflowStatus.ACTIVE:
                    status = AgentStatus.ACTIVE.value
                elif workflow.status in (
                    WorkflowStatus.INACTIVE,
                    WorkflowStatus.ARCHIVED,
                    WorkflowStatus.DRAFT,
                ):
                    if status != AgentStatus.ERROR.value:
                        status = AgentStatus.PAUSED.value

            monitoring = (agent_meta or {}).get("monitoring") or {}
            performance = dict((agent_meta or {}).get("performance_metrics") or {})
            if "execution_count" not in performance and monitoring:
                performance["execution_count"] = monitoring.get("execution_count", 0)

            trigger_type = (agent_meta or {}).get("trigger_type")
            if not trigger_type:
                trigger_type = (
                    workflow.trigger_type
                    if isinstance(workflow.trigger_type, str)
                    else getattr(workflow.trigger_type, "value", "manual")
                )

            agents.append({
                "agent_id": (agent_meta or {}).get("agent_id"),
                "workflow_id": workflow.id,
                "workflow_name": workflow.name,
                "status": status,
                "trigger_type": trigger_type,
                "schedule": (agent_meta or {}).get("schedule") or {},
                "monitoring": monitoring,
                "performance_metrics": performance,
                "created_at": (agent_meta or {}).get("created_at")
                or (workflow.created_at.isoformat() if workflow.created_at else datetime.utcnow().isoformat()),
                "updated_at": (agent_meta or {}).get("updated_at")
                or (workflow.updated_at.isoformat() if workflow.updated_at else datetime.utcnow().isoformat()),
                "channel": channel,
                "job_type": job_type,
                "agent_kind": agent_kind,
                "template_id": meta.get("template_id") or (workflow.variables or {}).get("template_id"),
            })

        if dirty:
            await db.commit()
        return agents

    async def _is_conversational_messaging_workflow(
        self, workflow: Workflow, db: AsyncSession
    ) -> bool:
        trigger_config = workflow.trigger_config or {}
        event_type = str(trigger_config.get("event_type") or "")
        messaging_events = (
            "whatsapp_message_received",
            "telegram_message_received",
        )
        is_messaging_event = (
            event_type in messaging_events or event_type.endswith("_message_received")
        )
        trigger_val = (
            workflow.trigger_type
            if isinstance(workflow.trigger_type, str)
            else getattr(workflow.trigger_type, "value", workflow.trigger_type)
        )
        is_event_trigger = trigger_val in (
            WorkflowTriggerType.EVENT,
            WorkflowTriggerType.EVENT.value,
            "event",
        )
        if not is_messaging_event and not is_event_trigger:
            return False

        step_result = await db.execute(
            select(WorkflowStep).where(
                WorkflowStep.workflow_id == workflow.id,
                WorkflowStep.tool_name == "conversational_agent",
            ).limit(1)
        )
        return step_result.scalar_one_or_none() is not None

    def _infer_channel(
        self, workflow: Workflow, agent_meta: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        if agent_meta and agent_meta.get("channel"):
            return agent_meta["channel"]
        meta = workflow.workflow_metadata or {}
        if meta.get("platform"):
            return meta["platform"]
        trigger = workflow.trigger_config or {}
        if trigger.get("platform"):
            return trigger["platform"]
        event = str(trigger.get("event_type") or "")
        if event.startswith("whatsapp"):
            return "whatsapp"
        if event.startswith("telegram"):
            return "telegram"
        return None

    def _infer_job_type(
        self, workflow: Workflow, agent_meta: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        if agent_meta and agent_meta.get("job_type"):
            return agent_meta["job_type"]
        meta = workflow.workflow_metadata or {}
        template_id = (
            meta.get("template_id")
            or (workflow.variables or {}).get("template_id")
            or ""
        )
        name = (workflow.name or "").lower()
        tid = str(template_id).lower()
        if "ordering" in tid or "ordering" in name:
            return "ordering"
        if "rent" in tid or "rent" in name:
            return "rent"
        if "support" in tid or "support" in name:
            return "support"
        if "real_estate" in tid or "estate" in name:
            return "real_estate"
        if "conversational" in tid:
            return "messaging"
        return "automation"

    async def ensure_agent_metadata(
        self,
        workflow: Workflow,
        user_id: uuid.UUID,
        db: AsyncSession,
        *,
        trigger_type: str = None,
        agent_kind: str = "autonomous",
        channel: str = None,
        job_type: str = None,
        template_id: str = None,
        commit: bool = True,
    ) -> Dict[str, Any]:
        """Ensure workflow_metadata.agent exists; create a lightweight stamp if missing."""
        existing = (workflow.workflow_metadata or {}).get("agent")
        if existing and existing.get("agent_id"):
            return existing

        inferred_channel = channel or self._infer_channel(workflow, None)
        inferred_job = job_type or self._infer_job_type(workflow, None)
        agent_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        resolved_trigger = trigger_type
        if not resolved_trigger:
            trigger_val = (
                workflow.trigger_type
                if isinstance(workflow.trigger_type, str)
                else getattr(workflow.trigger_type, "value", "manual")
            )
            resolved_trigger = (
                AgentTriggerType.EVENT_DRIVEN.value
                if trigger_val in (WorkflowTriggerType.EVENT, WorkflowTriggerType.EVENT.value, "event")
                else AgentTriggerType.MANUAL.value
            )

        agent_metadata = {
            "agent_id": agent_id,
            "workflow_id": str(workflow.id),
            "user_id": str(user_id),
            "status": (
                AgentStatus.ACTIVE.value
                if workflow.status == WorkflowStatus.ACTIVE
                else AgentStatus.PAUSED.value
            ),
            "trigger_type": resolved_trigger,
            "schedule": {},
            "monitoring": {
                "execution_count": 0,
                "success_count": 0,
                "error_count": 0,
                "last_execution": None,
                "average_execution_time": 0,
                "total_execution_time": 0,
            },
            "performance_metrics": {
                "response_time": [],
                "success_rate": 0,
                "error_rate": 0,
                "execution_count": 0,
            },
            "agent_kind": agent_kind,
            "channel": inferred_channel,
            "job_type": inferred_job,
            "template_id": template_id
            or (workflow.workflow_metadata or {}).get("template_id")
            or (workflow.variables or {}).get("template_id"),
            "created_at": now,
            "updated_at": now,
        }

        meta = dict(workflow.workflow_metadata or {})
        meta["agent"] = agent_metadata
        if template_id:
            meta["template_id"] = template_id
        workflow.workflow_metadata = meta
        flag_modified(workflow, "workflow_metadata")

        if commit:
            await db.commit()
            await db.refresh(workflow)
        return agent_metadata 