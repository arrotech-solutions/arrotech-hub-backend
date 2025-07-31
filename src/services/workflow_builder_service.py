"""
Workflow Builder Service for creating and executing multi-step business workflows.
"""
import asyncio
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import (Conversation, Message, User, Workflow, WorkflowExecution,
                      WorkflowExecutionStatus, WorkflowStatus, WorkflowStep,
                      WorkflowStepExecution, WorkflowTriggerType)
from .dynamic_tool_registry import DynamicToolRegistry
from .llm_service import LLMService


class WorkflowBuilderService:
    def __init__(self):
        self.tool_registry = DynamicToolRegistry()
        self.llm_service = LLMService()
        
    async def create_workflow_from_nlp(self, user_id: int, description: str, db: AsyncSession, name: str = None) -> Workflow:
        """
        Create a workflow from natural language description and save to database.
        """
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
        
        # Update workflow fields
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
    
    async def _analyze_workflow_requirements(self, description: str, user_id: int, db: AsyncSession) -> List[Dict[str, Any]]:
        """
        Analyze natural language description to create workflow steps with conditional logic.
        """
        # Get available tools
        available_tools = await self.tool_registry.get_available_tools()
        
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
            response = await self.llm_service.generate_response(prompt)
            # Extract JSON from response
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                workflow_steps = json.loads(json_match.group())
            else:
                # Fallback to simple workflow creation
                workflow_steps = await self._create_simple_workflow(description, available_tools)
        except Exception as e:
            print(f"Error analyzing workflow requirements: {e}")
            workflow_steps = await self._create_simple_workflow(description, available_tools)
        
        return workflow_steps
    
    async def _create_simple_workflow(self, description: str, available_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Create a simple workflow when LLM analysis fails.
        """
        # Simple fallback logic
        steps = []
        step_number = 1
        
        # Try to identify common patterns
        if "email" in description.lower() or "notification" in description.lower():
            steps.append({
                "step_number": step_number,
                "tool_name": "email_sender",
                "parameters": {"to": "{{input.email}}", "subject": "{{input.subject}}", "body": "{{input.message}}"},
                "description": "Send email notification",
                "condition": None,
                "retry_config": {"max_retries": 3, "retry_delay": 5},
                "timeout": 30
            })
            step_number += 1
        
        if "slack" in description.lower():
            steps.append({
                "step_number": step_number,
                "tool_name": "slack_notification",
                "parameters": {"channel": "{{input.channel}}", "message": "{{input.message}}"},
                "description": "Send Slack notification",
                "condition": None,
                "retry_config": {"max_retries": 3, "retry_delay": 5},
                "timeout": 30
            })
            step_number += 1
        
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
            step_number += 1
        
        if not steps:
            # Default step
            steps.append({
                "step_number": 1,
                "tool_name": "web_search",
                "parameters": {"query": "{{input.query}}"},
                "description": "Perform web search",
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
        
        try:
            # Initialize execution context with variables
            context = {
                "input": input_data or {},
                "workflow": workflow.workflow_metadata or {},
                "steps": {}
            }
            
            # Execute steps in order
            for step in workflow.steps:
                # Check conditional logic
                if step.condition and not await self._evaluate_condition(step.condition, context):
                    print(f"Step {step.step_number} skipped due to condition")
                    continue
                
                # Execute step with variable substitution
                step_execution = await self._execute_workflow_step(step, execution.id, db, context)
                
                # Update context with step results
                context["steps"][f"step_{step.step_number}"] = step_execution.output_data or {}
                
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
    
    async def _execute_workflow_step(self, step: WorkflowStep, execution_id: int, db: AsyncSession, context: Dict[str, Any] = None) -> WorkflowStepExecution:
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
            # Substitute variables in parameters
            substituted_params = self._substitute_variables(step.tool_parameters, context or {})
            
            # Update step execution with substituted parameters
            step_execution.input_data = substituted_params
            step_execution.status = WorkflowExecutionStatus.RUNNING
            
            # Execute tool
            tool_result = await self._execute_tool(step.tool_name, substituted_params)
            
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
        
        return step_execution
    
    def _substitute_variables(self, parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Substitute variables in parameters using {{variable}} syntax.
        """
        if not parameters:
            return parameters
        
        substituted = {}
        for key, value in parameters.items():
            if isinstance(value, str):
                # Find all variable placeholders
                matches = re.findall(r'\{\{([^}]+)\}\}', value)
                substituted_value = value
                
                for match in matches:
                    variable_value = self._extract_value_from_context(match.strip(), context)
                    if variable_value is not None:
                        substituted_value = substituted_value.replace(f'{{{{{match}}}}}', str(variable_value))
                
                substituted[key] = substituted_value
            elif isinstance(value, dict):
                substituted[key] = self._substitute_variables(value, context)
            elif isinstance(value, list):
                substituted[key] = [self._substitute_variables(item, context) if isinstance(item, dict) else item for item in value]
            else:
                substituted[key] = value
        
        return substituted
    
    async def _execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool with error handling.
        """
        try:
            # Get tool from registry
            tool = await self.tool_registry.get_tool(tool_name)
            if not tool:
                raise ValueError(f"Tool '{tool_name}' not found")
            
            # Execute tool
            result = await tool.execute(parameters)
            return result
            
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
        
        # Re-execute the step
        await self._execute_workflow_step(step, step_execution.workflow_execution_id, db, context)
    
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