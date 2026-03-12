"""
Workflow Builder Service for creating and executing multi-step business workflows.
"""
import asyncio
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from jinja2 import Template
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import (Conversation, Message, User, Workflow, WorkflowExecution,
                      WorkflowExecutionStatus, WorkflowStatus, WorkflowStep,
                      WorkflowStepExecution, WorkflowTriggerType)
from .dynamic_tool_registry import DynamicToolRegistry
from .llm_service import LLMService
from .tool_executor import ToolExecutor
from .feature_flags import FeatureGate
from .websocket_manager import connection_manager
# Note: get_or_create_usage_record imported inside execute_workflow() to avoid circular import

import logging
logger = logging.getLogger(__name__)


class WorkflowBuilderService:
    def __init__(self):
        self.tool_registry = DynamicToolRegistry()
        self.llm_service = LLMService()
        self.tool_executor = ToolExecutor()
        
    async def create_workflow_from_nlp(self, user_id: int, description: str, db: AsyncSession, name: str = None) -> Workflow:
        """
        Create a workflow from natural language description and save to database.
        """
        # Get user for subscription check
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            raise ValueError("User not found")

        # Check plan limits
        active_workflows = await self.get_active_workflow_count(user_id, db)
        if not FeatureGate.can_activate_workflow(user, active_workflows):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plan limit reached: {user.subscription_tier} plan allows only {FeatureGate.get_limits(user.subscription_tier)['max_active_workflows']} active workflows. Please upgrade."
            )

        # Analyze the description to identify required tools and steps
        workflow_steps = await self._analyze_workflow_requirements(description, user_id, db)
        
        # Create workflow in database
        workflow = Workflow(
            user_id=user_id,
            name=name or f"Workflow from: {description[:50]}...",
            description=description,
            status=WorkflowStatus.DRAFT,
            trigger_type=WorkflowTriggerType.MANUAL,
            variables={},
            workflow_metadata={}
        )
        
        db.add(workflow)
        await db.flush()  # Get the workflow ID
        
        # Create workflow steps
        for step_data in workflow_steps:
            step = WorkflowStep(
                workflow_id=workflow.id,
                step_number=step_data['step_number'],
                tool_name=step_data['tool_name'],
                tool_parameters=step_data['parameters'],
                description=step_data['description'],
                condition=step_data.get('condition'),
                retry_config=step_data.get('retry_config', {"max_retries": 3, "retry_delay": 5}),
                timeout=step_data.get('timeout', 30)
            )
            db.add(step)
        
        await db.commit()
        await db.refresh(workflow)
        
        return workflow
    
    async def get_workflow(self, workflow_id: int, user_id: int, db: AsyncSession) -> Optional[Workflow]:
        """
        Get a workflow by ID for a specific user.
        """
        stmt = select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.user_id == user_id
        ).options(selectinload(Workflow.steps))
        
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_user_workflows(self, user_id: int, db: AsyncSession) -> List[Workflow]:
        """
        Get all workflows for a user.
        """
        stmt = select(Workflow).where(
            Workflow.user_id == user_id
        ).options(selectinload(Workflow.steps)).order_by(Workflow.created_at.desc())
        
        result = await db.execute(stmt)
        return result.scalars().all()
    
    async def update_workflow(self, workflow_id: int, user_id: int, updates: Dict[str, Any], db: AsyncSession) -> Optional[Workflow]:
        """
        Update a workflow.
        """
        workflow = await self.get_workflow(workflow_id, user_id, db)
        if not workflow:
            return None
        
        # Handle steps update separately
        if 'steps' in updates:
            steps_data = updates.pop('steps')
            
            # Delete existing steps
            # First delete executions associated with these steps to avoid FK violation
            # We use a subquery to identify step executions to delete
            from ..models import WorkflowStepExecution
            
            # Find steps to be deleted
            steps_subquery = select(WorkflowStep.id).where(WorkflowStep.workflow_id == workflow_id)
            
            # Delete executions referencing these steps
            delete_executions_stmt = delete(WorkflowStepExecution).where(WorkflowStepExecution.step_id.in_(steps_subquery))
            await db.execute(delete_executions_stmt)
            
            # Now delete the steps
            stmt = delete(WorkflowStep).where(WorkflowStep.workflow_id == workflow_id)
            await db.execute(stmt)
            
            # Create new steps
            for step_data in steps_data:
                # Handle both dict and object (if pydantic model passed)
                s_data = step_data if isinstance(step_data, dict) else step_data.dict()
                
                step = WorkflowStep(
                    workflow_id=workflow.id,
                    step_number=s_data.get('step_number'),
                    tool_name=s_data.get('tool_name'),
                    tool_parameters=s_data.get('tool_parameters', {}),
                    description=s_data.get('description', ''),
                    condition=s_data.get('condition'),
                    retry_config=s_data.get('retry_config', {"max_retries": 3, "retry_delay": 5}),
                    timeout=s_data.get('timeout', 30)
                )
                db.add(step)
        
        # Update other workflow fields
        for field, value in updates.items():
            if hasattr(workflow, field):
                setattr(workflow, field, value)
        
        await db.commit()
        await db.refresh(workflow)
        return workflow
    
    async def delete_workflow(self, workflow_id: int, user_id: int, db: AsyncSession) -> bool:
        """
        Delete a workflow.
        """
        workflow = await self.get_workflow(workflow_id, user_id, db)
        if not workflow:
            return False
        
        await db.delete(workflow)
        await db.commit()
        return True

    @staticmethod
    async def get_active_workflow_count(user_id: int, db: AsyncSession) -> int:
        """
        Count active workflows for a user.
        """
        from sqlalchemy import func
        stmt = select(func.count(Workflow.id)).where(
            Workflow.user_id == user_id,
            Workflow.status == WorkflowStatus.ACTIVE
        )
        result = await db.execute(stmt)
        return result.scalar() or 0
    
    async def _analyze_workflow_requirements(self, description: str, user_id: int, db: AsyncSession) -> List[Dict[str, Any]]:
        """
        Analyze natural language description to create workflow steps with conditional logic.
        """
        # Get available tools
        available_tools = await self.tool_registry.get_available_tools(user_id, db)
        
        # Use LLM to analyze requirements and create steps with conditions
        prompt = f"""
        Analyze this workflow description and create structured workflow steps with conditional logic:
        
        Description: {description}
        
        Available tools: {json.dumps(available_tools, indent=2)}
        
        Create a JSON array of workflow steps. Each step should include:
        - step_number: sequential number
        - tool_name: from available tools
        - parameters: tool parameters with variable substitution (use {{input.field_name}} or {{step_X.field_name}})
        - description: what this step does
        - condition: optional conditional logic (if, field, operator, value)
        - retry_config: retry settings
        - timeout: execution timeout
        
        Example conditions:
        - {{"type": "if", "field": "customer_type", "operator": "equals", "value": "enterprise"}}
        - {{"type": "if", "field": "step_1.status", "operator": "equals", "value": "success"}}
        
        Return only valid JSON array.
        """
        
        try:
            # For now, skip LLM analysis to avoid async context issues
            # and use the simple workflow creation as the primary method
            workflow_steps = self._create_simple_workflow(description, available_tools)
            
            # TODO: Re-enable LLM analysis once async context is properly resolved
            # response = await self.llm_service.generate_response(prompt)
            # json_match = re.search(r'\[.*\]', response, re.DOTALL)
            # if json_match:
            #     workflow_steps = json.loads(json_match.group())
            
        except Exception as e:
            print(f"Error analyzing workflow requirements: {e}")
            workflow_steps = self._create_simple_workflow(description, available_tools)
        
        return workflow_steps
    
    def _create_simple_workflow(self, description: str, available_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Create a workflow based on description patterns.
        Enhanced to handle GA4 + Asana + Slack automation scenarios.
        """
        steps = []
        step_number = 1
        
        # Enhanced pattern matching for the user's specific request
        
        # Check for GA4 analytics workflow
        if ("ga4" in description.lower() or "analytics" in description.lower() or 
            "traffic" in description.lower() or "sessions" in description.lower()):
            steps.append({
                "step_number": step_number,
                "tool_name": "ga4_get_traffic_data",
                "parameters": {
                    "date_range": "last_7_days",
                    "metrics": ["sessions", "users", "page_views"]
                },
                "description": "Get website traffic data from GA4",
                "condition": None,
                "retry_config": {"max_retries": 3, "retry_delay": 5},
                "timeout": 30
            })
            step_number += 1
        
        # Check for Asana task creation with conditions
        if "asana" in description.lower() and "below" in description.lower():
            steps.append({
                "step_number": step_number,
                "tool_name": "asana_create_task",
                "parameters": {
                    "name": "SEO Optimization Required - Low Traffic Alert",
                    "notes": "Website sessions ({{step_1.sessions}}) below target. Need immediate SEO review.",
                    "priority": "high"
                },
                "description": "Create high-priority Asana task for low traffic",
                "condition": {
                    "type": "if",
                    "field": "step_1.sessions",
                    "operator": "less_than",
                    "value": 1000
                },
                "retry_config": {"max_retries": 3, "retry_delay": 5},
                "timeout": 30
            })
            step_number += 1
        
        # Check for celebration task
        if "asana" in description.lower() and ("above" in description.lower() or 
                                               "celebrate" in description.lower()):
            steps.append({
                "step_number": step_number,
                "tool_name": "asana_create_task",
                "parameters": {
                    "name": "Celebrate Great Performance! 🎉",
                    "notes": "Amazing week! {{step_1.sessions}} sessions exceeded our goals!",
                    "priority": "normal"
                },
                "description": "Create celebration task for high traffic",
                "condition": {
                    "type": "if",
                    "field": "step_1.sessions",
                    "operator": "greater_than",
                    "value": 5000
                },
                "retry_config": {"max_retries": 3, "retry_delay": 5},
                "timeout": 30
            })
            step_number += 1
        
        # Check for Slack notifications
        if "slack" in description.lower():
            steps.append({
                "step_number": step_number,
                "tool_name": "slack_send_message",
                "parameters": {
                    "channel": "#marketing",
                    "message": "📊 **Weekly Performance Report**\\n\\n🔢 Sessions: {{step_1.sessions}}\\n👥 Users: {{step_1.users}}\\n📄 Page Views: {{step_1.page_views}}\\n\\n{{step_1.sessions < 1000 ? '⚠️ Action needed - check Asana for tasks' : '✅ Great performance this week!'}}"
                },
                "description": "Send performance summary to Slack",
                "condition": None,
                "retry_config": {"max_retries": 3, "retry_delay": 5},
                "timeout": 30
            })
            step_number += 1
        
        # Fallback patterns for other common scenarios
        if not steps:
            if "hubspot" in description.lower() or "contact" in description.lower():
                steps.append({
                    "step_number": step_number,
                    "tool_name": "hubspot_contact_create",
                    "parameters": {"email": "{{input.email}}", "first_name": "{{input.first_name}}", "last_name": "{{input.last_name}}"},
                    "description": "Create HubSpot contact",
                    "condition": None,
                    "retry_config": {"max_retries": 3, "retry_delay": 5},
                    "timeout": 30
                })
            else:
                # Very basic default
                steps.append({
                    "step_number": 1,
                    "tool_name": "marketing_campaign_automation",
                    "parameters": {"campaign_type": "multi_channel", "target_audience": "{{input.audience}}"},
                    "description": "Basic marketing automation",
                    "condition": None,
                    "retry_config": {"max_retries": 3, "retry_delay": 5},
                    "timeout": 30
                })
        
        return steps
    
    async def execute_workflow(self, workflow_id: int, user_id: int, db: AsyncSession, input_data: Dict[str, Any] = None) -> WorkflowExecution:
        """
        Execute a workflow with enhanced conditional logic and variable substitution.
        """
        workflow = await self.get_workflow(workflow_id, user_id, db)
        if not workflow:
            raise ValueError("Workflow not found")
        
        # ===== AUTOMATION RUN USAGE TRACKING =====
        # Get user for usage tracking
        user_stmt = select(User).where(User.id == user_id)
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()
        
        if user:
            try:
                # Lazy import to avoid circular dependency
                from ..routers.subscription_router import get_or_create_usage_record
                usage_record = await get_or_create_usage_record(db, user)
                # Check if at limit
                if usage_record.automation_runs_count >= usage_record.automation_runs_limit:
                    logger.warning(f"User {user_id} exceeded automation run limit: {usage_record.automation_runs_count}/{usage_record.automation_runs_limit}")
                    raise ValueError(f"Monthly automation run limit reached ({usage_record.automation_runs_limit}). Please upgrade to continue.")
                # Increment counter
                usage_record.automation_runs_count += 1
                await db.commit()
                logger.info(f"Automation run tracked: {usage_record.automation_runs_count}/{usage_record.automation_runs_limit}")
            except ValueError:
                raise  # Re-raise limit exceeded error
            except Exception as tracking_error:
                logger.error(f"Failed to track automation run: {tracking_error}")
        # ===== END USAGE TRACKING =====
        
        # Create execution record
        execution = WorkflowExecution(
            workflow_id=workflow_id,
            user_id=user_id,
            status=WorkflowExecutionStatus.RUNNING,
            trigger_type=WorkflowTriggerType.MANUAL,
            trigger_data={},
            input_data=input_data or {},
            output_data={},
            started_at=datetime.utcnow()
        )
        
        db.add(execution)
        await db.flush()
        
        # Notify clients that workflow execution started
        if user_id:
            await connection_manager.push_to_user(
                user_id, 
                "workflow_execution_started", 
                {"workflow_id": workflow.id, "execution_id": execution.id}
            )
        
        try:
            # Initialize execution context with variables
            context = {
                "input": input_data or {},
                "workflow": workflow.workflow_metadata or {},
                "steps": {}
            }
            
            # GAP 1 FIX: Merge input_data keys to top-level context
            # so Jinja2 can resolve {{Trigger.id}} directly (not {{input.Trigger.id}})
            if input_data:
                for key, value in input_data.items():
                    if key not in context:  # Don't overwrite existing keys like 'input', 'workflow', 'steps'
                        context[key] = value
            
            # Execute steps in order
            for step in workflow.steps:
                # Check conditional logic
                if step.condition and not await self._evaluate_condition(step.condition, context):
                    print(f"Step {step.step_number} skipped due to condition")
                    continue
                
                # Execute step with variable substitution
                step_execution = await self._execute_workflow_step(step, execution.id, db, context, user_id)
                
                # Update context with step results
                step_result = step_execution.output_data or {}
                context["steps"][f"step_{step.step_number}"] = step_result
                
                # Also add to root context for easier variable access (e.g. {{step_1.field}})
                context[f"step_{step.step_number}"] = step_result
                
                # GAP 2 FIX: Also store by operation name for intuitive access
                # e.g. {{auto_resolve_ticket.resolved}} instead of {{step_2.resolved}}
                operation_name = (step.tool_parameters or {}).get("operation", "")
                if operation_name:
                    context[operation_name] = step_result
                
                # Check if step failed
                if step_execution.status == WorkflowExecutionStatus.FAILED:
                    execution.status = WorkflowExecutionStatus.FAILED
                    execution.error_message = f"Step {step.step_number} failed: {step_execution.error_message}"
                    break
            
            if execution.status == WorkflowExecutionStatus.RUNNING:
                execution.status = WorkflowExecutionStatus.COMPLETED
                execution.output_data = context["steps"]
            
        except Exception as e:
            execution.status = WorkflowExecutionStatus.FAILED
            execution.error_message = str(e)
        
        execution.completed_at = datetime.utcnow()
        await db.commit()
        await db.refresh(execution)
        
        # Notify clients that workflow execution completed
        if user_id:
            await connection_manager.push_to_user(
                user_id, 
                "workflow_execution_completed", 
                {
                    "workflow_id": workflow.id,
                    "execution_id": execution.id,
                    "status": execution.status.value if hasattr(execution.status, 'value') else str(execution.status),
                    "completed_at": execution.completed_at.isoformat()
                }
            )
        
        return execution
    
    async def _evaluate_condition(self, condition: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """
        Evaluate conditional logic for workflow steps.
        """
        if not condition or condition.get("type") != "if":
            return True
        
        field_path = condition.get("field", "")
        operator = condition.get("operator", "equals")
        expected_value = condition.get("value")
        
        # Extract actual value from context
        actual_value = self._extract_value_from_context(field_path, context)
        
        # Apply operator
        if operator == "equals":
            return actual_value == expected_value
        elif operator == "not_equals":
            return actual_value != expected_value
        elif operator == "contains":
            return expected_value in str(actual_value)
        elif operator == "not_contains":
            return expected_value not in str(actual_value)
        elif operator == "greater_than":
            return float(actual_value) > float(expected_value)
        elif operator == "less_than":
            return float(actual_value) < float(expected_value)
        elif operator == "exists":
            return actual_value is not None and actual_value != ""
        elif operator == "not_exists":
            return actual_value is None or actual_value == ""
        
        return True
    
    def _extract_value_from_context(self, field_path: str, context: Dict[str, Any]) -> Any:
        """
        Extract value from context using dot notation (e.g., "input.email", "step_1.status").
        """
        try:
            parts = field_path.split(".")
            current = context
            
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return None
            
            return current
        except Exception:
            return None
    
    async def _execute_workflow_step(self, step: WorkflowStep, execution_id: int, db: AsyncSession, context: Dict[str, Any] = None, user_id: int = None) -> WorkflowStepExecution:
        """
        Execute a single workflow step with variable substitution and enhanced error handling.
        """
        # Create step execution record
        step_execution = WorkflowStepExecution(
            workflow_execution_id=execution_id,
            step_id=step.id,
            status=WorkflowExecutionStatus.PENDING,
            input_data={},
            output_data={},
            started_at=datetime.utcnow()
        )
        
        db.add(step_execution)
        await db.flush()
        
        try:
            # Prepare parameters with overrides first
            effective_params = step.tool_parameters.copy() if step.tool_parameters else {}
            
            # Add direct overrides from input_data if they follow the step_N_param pattern
            input_overrides = context.get("input", {})
            for param_name in list(effective_params.keys()):
                override_key = f"step_{step.step_number}_{param_name}"
                if override_key in input_overrides:
                    # Only apply override if it's not None/Empty, otherwise stick to default
                    if input_overrides[override_key]:
                        effective_params[param_name] = input_overrides[override_key]
            
            # Substitute variables in parameters (now including any overrides)
            substituted_params = self._substitute_variables(effective_params, context or {})
            
            # Update step execution with substituted parameters
            step_execution.input_data = substituted_params
            step_execution.status = WorkflowExecutionStatus.RUNNING
            await db.commit() # Commit to make RUNNING status visible
            
            # Notify clients that step started
            if user_id:
                await connection_manager.push_to_user(
                    user_id,
                    "workflow_step_started",
                    {"execution_id": execution_id, "step_id": step.id, "step_number": step.step_number}
                )
            
            # Execute tool using the real ToolExecutor
            if user_id:
                # Get user object for tool execution
                from sqlalchemy import select

                from ..models import User
                
                user_stmt = select(User).where(User.id == user_id)
                user_result = await db.execute(user_stmt)
                user = user_result.scalar_one_or_none()
                
                if user:
                    tool_result = await self.tool_executor.execute_tool(
                        step.tool_name, substituted_params, user, db
                    )
                else:
                    raise Exception(f"User {user_id} not found")
            else:
                # Fallback to old method (will fail but preserves existing behavior)
                tool_result = await self._execute_tool_legacy(step.tool_name, substituted_params)
            
            step_execution.output_data = tool_result
            step_execution.status = WorkflowExecutionStatus.COMPLETED
            
        except Exception as e:
            step_execution.status = WorkflowExecutionStatus.FAILED
            step_execution.error_message = str(e)
            
            # Apply retry logic
            if step.retry_config and step_execution.retry_count < step.retry_config.get("max_retries", 3):
                await self._retry_step_execution(step_execution, step, db, context)
        
        step_execution.completed_at = datetime.utcnow()
        await db.commit()
        await db.refresh(step_execution)
        
        # Notify clients that step finished
        if user_id:
            await connection_manager.push_to_user(
                user_id,
                "workflow_step_completed",
                {
                    "execution_id": execution_id,
                    "step_id": step.id,
                    "step_number": step.step_number,
                    "status": step_execution.status.value if hasattr(step_execution.status, 'value') else str(step_execution.status)
                }
            )
        
        return step_execution
    
    def _substitute_variables(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Substitute variables in parameters using Jinja2 templates for full expression support.
        """
        if not parameters:
            return parameters
        
        substituted = {}
        for key, value in parameters.items():
            if isinstance(value, str) and "{{" in value:
                try:
                    # Use Jinja2 for robust expression evaluation (e.g. {{ a if b else c }})
                    template = Template(value)
                    # Use render to get string result
                    rendered = template.render(**context)
                    # Handle cases where Jinja returns 'None' for missing attributes in some contexts
                    substituted[key] = rendered
                except Exception as e:
                    # Log rendering errors but don't crash the whole workflow
                    print(f"Variable substitution failed for '{value}': {e}")
                    substituted[key] = value
            elif isinstance(value, dict):
                substituted[key] = self._substitute_variables(value, context)
            elif isinstance(value, list):
                # Handle lists of dicts or strings
                new_list = []
                for item in value:
                    if isinstance(item, dict):
                        new_list.append(self._substitute_variables(item, context))
                    elif isinstance(item, str) and "{{" in item:
                        try:
                            template = Template(item)
                            new_list.append(template.render(**context))
                        except Exception:
                            new_list.append(item)
                    else:
                        new_list.append(item)
                substituted[key] = new_list
            else:
                substituted[key] = value
        
        return substituted
    
    async def _execute_tool_legacy(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool with error handling.
        """
        try:
            # Get tool from registry
            tool = self.tool_registry.get_tool(tool_name)
            if not tool:
                raise ValueError(f"Tool '{tool_name}' not found")
            
            # This is a legacy fallback method - tools are now executed via ToolExecutor
            # Return a placeholder response since this method should not be used with real user_id
            return {
                "success": False,
                "error": "Tool execution requires user context. Use real ToolExecutor instead.",
                "tool_name": tool_name,
                "fallback": True
            }
            
        except Exception as e:
            raise Exception(f"Tool execution failed: {str(e)}")
    
    async def _retry_step_execution(self, step_execution: WorkflowStepExecution, step: WorkflowStep, db: AsyncSession, context: Dict[str, Any]):
        """
        Retry a failed step execution.
        """
        retry_delay = step.retry_config.get("retry_delay", 5)
        await asyncio.sleep(retry_delay)
        
        step_execution.retry_count += 1
        step_execution.status = WorkflowExecutionStatus.PENDING
        step_execution.error_message = None
        
        # Re-execute the step - need to get user_id from execution
        execution_stmt = select(WorkflowExecution).where(WorkflowExecution.id == step_execution.workflow_execution_id)
        execution_result = await db.execute(execution_stmt)
        execution = execution_result.scalar_one_or_none()
        
        if execution:
            await self._execute_workflow_step(step, step_execution.workflow_execution_id, db, context, execution.user_id)
    
    async def get_workflow_executions(self, workflow_id: int, user_id: int, db: AsyncSession) -> List[WorkflowExecution]:
        """
        Get all executions for a specific workflow.
        """
        stmt = select(WorkflowExecution).where(
            WorkflowExecution.workflow_id == workflow_id,
            WorkflowExecution.user_id == user_id
        ).order_by(WorkflowExecution.started_at.desc())
        
        result = await db.execute(stmt)
        return result.scalars().all()
    
    async def create_agent_prompt(self, workflow: Workflow) -> str:
        """
        Create an agent prompt from a workflow.
        """
        prompt = f"""You are an autonomous agent created from the workflow: {workflow.name}

Workflow Description: {workflow.description}

Your task is to execute the following workflow steps:

"""
        
        for step in workflow.steps:
            prompt += f"""
Step {step.step_number}: {step.description}
- Tool: {step.tool_name}
- Parameters: {json.dumps(step.tool_parameters, indent=2)}
"""
            if step.condition:
                prompt += f"- Condition: {json.dumps(step.condition, indent=2)}\n"
        
        prompt += """

Instructions:
1. Execute each step in order
2. Respect conditional logic
3. Handle errors gracefully
4. Use variable substitution for dynamic values
5. Report results after each step

You have access to all the tools mentioned above. Execute the workflow step by step and provide detailed feedback.
"""
        
        return prompt
    
    async def create_workflow_template(self, name: str, description: str, steps: List[Dict[str, Any]], user_id: int, db: AsyncSession) -> Workflow:
        """
        Create a workflow template with conditional logic support.
        """
        workflow = Workflow(
            user_id=user_id,
            name=name,
            description=description,
            status=WorkflowStatus.ACTIVE,
            is_template=True,
            trigger_type=WorkflowTriggerType.MANUAL,
            variables={},
            workflow_metadata={}
        )
        
        db.add(workflow)
        await db.flush()
        
        # Create workflow steps with conditional logic
        for step_data in steps:
            step = WorkflowStep(
                workflow_id=workflow.id,
                step_number=step_data['step_number'],
                tool_name=step_data['tool_name'],
                tool_parameters=step_data['parameters'],
                description=step_data['description'],
                condition=step_data.get('condition'),
                retry_config=step_data.get('retry_config', {"max_retries": 3, "retry_delay": 5}),
                timeout=step_data.get('timeout', 30)
            )
            db.add(step)
        
        await db.commit()
        await db.refresh(workflow)
        
        return workflow 