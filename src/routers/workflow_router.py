"""
Workflow Router for creating and executing business workflows.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import (User, Workflow, WorkflowExecution,
                      WorkflowExecutionStatus, WorkflowStatus, WorkflowStep,
                      WorkflowTriggerType)
from ..services.workflow_builder_service import WorkflowBuilderService
from .auth_router import get_current_user

router = APIRouter()


class WorkflowCreate(BaseModel):
    description: str
    name: str = None


class WorkflowFromConversation(BaseModel):
    """Request model for extracting workflow from conversation."""
    conversation_id: int
    workflow_name: str
    description: str = None
    selected_step_ids: List[str] = None  # Optional: subset of steps to include
    parameterize_fields: List[str] = None  # Fields to make dynamic
    trigger_type: str = "manual"
    trigger_config: Dict[str, Any] = None


class WorkflowFromSteps(BaseModel):
    """Request model for creating workflow from explicit steps."""
    workflow_name: str
    description: str
    steps: List[Dict[str, Any]]
    trigger_type: str = "manual"
    trigger_config: Dict[str, Any] = None
    variables: Dict[str, Any] = None


class WorkflowUpdate(BaseModel):
    name: str = None
    description: str = None
    status: str = None
    trigger_type: str = None
    trigger_config: Dict[str, Any] = None
    variables: Dict[str, Any] = None


class WorkflowExecute(BaseModel):
    input_data: Dict[str, Any] = {}


class ConditionTest(BaseModel):
    condition: Dict[str, Any]
    context: Dict[str, Any]


class VariableSubstitution(BaseModel):
    parameters: Dict[str, Any]
    context: Dict[str, Any]


class WorkflowResponse(BaseModel):
    id: int
    name: str
    description: str
    status: str
    version: int
    is_template: bool
    trigger_type: str
    trigger_config: Optional[Dict[str, Any]]
    variables: Optional[Dict[str, Any]]
    workflow_metadata: Optional[Dict[str, Any]]
    created_at: str
    updated_at: Optional[str]
    steps: List[Dict[str, Any]]


class WorkflowExecutionResponse(BaseModel):
    id: int
    workflow_id: int
    status: str
    trigger_type: str
    input_data: Optional[Dict[str, Any]]
    output_data: Optional[Dict[str, Any]]
    error_message: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str


class ConditionTestResponse(BaseModel):
    result: bool
    evaluated_value: Any
    expected_value: Any
    operator: str


class VariableSubstitutionResponse(BaseModel):
    original_parameters: Dict[str, Any]
    substituted_parameters: Dict[str, Any]
    substitutions_made: List[str]


@router.post("/create", response_model=WorkflowResponse)
async def create_workflow(
    data: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Create a workflow from natural language description."""
    try:
        # Return a mock successful response to test if the issue is in database operations
        # This will help isolate if the problem is in DB operations or elsewhere
        
        mock_workflow_response = WorkflowResponse(
            id=1,
            name=data.name or "Weekly Performance Dashboard",
            description=data.description,
            status="draft",
            version=1,
            is_template=False,
            trigger_type="manual",
            trigger_config=None,
            variables={},
            workflow_metadata={},
            created_at="2024-01-15T13:45:00Z",
            updated_at=None,
            steps=[
                {
                    "id": 1,
                    "step_number": 1,
                    "tool_name": "ga4_get_traffic_data",
                    "tool_parameters": {
                        "date_range": "last_7_days",
                        "metrics": ["sessions", "users", "page_views"]
                    },
                    "description": "Get website traffic data from GA4",
                    "condition": None,
                    "retry_config": {"max_retries": 3, "retry_delay": 5},
                    "timeout": 30
                },
                {
                    "id": 2,
                    "step_number": 2,
                    "tool_name": "asana_create_task",
                    "tool_parameters": {
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
                },
                {
                    "id": 3,
                    "step_number": 3,
                    "tool_name": "asana_create_task",
                    "tool_parameters": {
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
                },
                {
                    "id": 4,
                    "step_number": 4,
                    "tool_name": "slack_send_message",
                    "tool_parameters": {
                        "channel": "#marketing",
                        "message": "📊 **Weekly Performance Report**\\n\\n🔢 Sessions: {{step_1.sessions}}\\n👥 Users: {{step_1.users}}\\n📄 Page Views: {{step_1.page_views}}"
                    },
                    "description": "Send performance summary to Slack",
                    "condition": None,
                    "retry_config": {"max_retries": 3, "retry_delay": 5},
                    "timeout": 30
                }
            ]
        )
        
        return mock_workflow_response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create workflow: {str(e)}"
        )


@router.get("/")
async def get_workflows(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Get all workflows for the current user."""
    try:
        workflow_service = WorkflowBuilderService()
        workflows = await workflow_service.get_user_workflows(user.id, db)
        
        workflows_data = [
            {
                "id": workflow.id,
                "name": workflow.name,
                "description": workflow.description,
                "status": workflow.status,
                "version": workflow.version,
                "is_template": workflow.is_template,
                "trigger_type": workflow.trigger_type,
                "trigger_config": workflow.trigger_config,
                "variables": workflow.variables,
                "workflow_metadata": workflow.workflow_metadata,
                "created_at": workflow.created_at.isoformat(),
                "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
                "steps": [{
                    "id": step.id,
                    "step_number": step.step_number,
                    "tool_name": step.tool_name,
                    "tool_parameters": step.tool_parameters,
                    "description": step.description,
                    "condition": step.condition,
                    "retry_config": step.retry_config,
                    "timeout": step.timeout
                } for step in workflow.steps]
            } for workflow in workflows
        ]
        
        return {
            "success": True,
            "data": workflows_data
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get workflows: {str(e)}"
        )


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Get a specific workflow by ID."""
    try:
        workflow_service = WorkflowBuilderService()
        workflow = await workflow_service.get_workflow(workflow_id, user.id, db)
        
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found"
            )
        
        workflow_data = {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "status": workflow.status,
            "version": workflow.version,
            "is_template": workflow.is_template,
            "trigger_type": workflow.trigger_type,
            "trigger_config": workflow.trigger_config,
            "variables": workflow.variables,
            "workflow_metadata": workflow.workflow_metadata,
            "created_at": workflow.created_at.isoformat(),
            "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
            "steps": [{
                "id": step.id,
                "step_number": step.step_number,
                "tool_name": step.tool_name,
                "tool_parameters": step.tool_parameters,
                "description": step.description,
                "condition": step.condition,
                "retry_config": step.retry_config,
                "timeout": step.timeout
            } for step in workflow.steps]
        }
        
        return {
            "success": True,
            "data": workflow_data
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get workflow: {str(e)}"
        )


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: int,
    data: WorkflowUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Update a workflow."""
    try:
        workflow_service = WorkflowBuilderService()
        
        # Prepare updates
        updates = {}
        if data.name is not None:
            updates["name"] = data.name
        if data.description is not None:
            updates["description"] = data.description
        if data.status is not None:
            updates["status"] = data.status
        if data.trigger_type is not None:
            updates["trigger_type"] = data.trigger_type
        if data.trigger_config is not None:
            updates["trigger_config"] = data.trigger_config
        if data.variables is not None:
            updates["variables"] = data.variables
        
        workflow = await workflow_service.update_workflow(workflow_id, user.id, updates, db)
        
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found"
            )
        
        return WorkflowResponse(
            id=workflow.id,
            name=workflow.name,
            description=workflow.description,
            status=workflow.status,
            version=workflow.version,
            is_template=workflow.is_template,
            trigger_type=workflow.trigger_type,
            trigger_config=workflow.trigger_config,
            variables=workflow.variables,
            workflow_metadata=workflow.workflow_metadata,
            created_at=workflow.created_at.isoformat(),
            updated_at=workflow.updated_at.isoformat() if workflow.updated_at else None,
            steps=[{
                "id": step.id,
                "step_number": step.step_number,
                "tool_name": step.tool_name,
                "tool_parameters": step.tool_parameters,
                "description": step.description,
                "condition": step.condition,
                "retry_config": step.retry_config,
                "timeout": step.timeout
            } for step in workflow.steps]
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update workflow: {str(e)}"
        )


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Delete a workflow."""
    try:
        workflow_service = WorkflowBuilderService()
        success = await workflow_service.delete_workflow(workflow_id, user.id, db)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found"
            )
        
        return {"message": "Workflow deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete workflow: {str(e)}"
        )


@router.post("/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: int,
    data: WorkflowExecute,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Execute a workflow with input data."""
    try:
        workflow_service = WorkflowBuilderService()
        execution = await workflow_service.execute_workflow(
            workflow_id, user.id, db, data.input_data
        )
        
        # Format response data
        execution_data = {
            "id": execution.id,
            "workflow_id": execution.workflow_id,
            "status": execution.status,
            "trigger_type": execution.trigger_type,
            "trigger_data": execution.trigger_data,
            "input_data": execution.input_data,
            "output_data": execution.output_data,
            "error_message": execution.error_message,
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
            "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
            "created_at": execution.created_at.isoformat()
        }
        
        return {
            "success": True,
            "data": execution_data
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error executing workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute workflow: {str(e)}"
        )


@router.get("/{workflow_id}/executions")
async def get_workflow_executions(
    workflow_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Get all executions for a specific workflow."""
    try:
        workflow_service = WorkflowBuilderService()
        executions = await workflow_service.get_workflow_executions(workflow_id, user.id, db)
        
        executions_data = [
            {
                "id": execution.id,
                "workflow_id": execution.workflow_id,
                "status": execution.status,
                "trigger_type": execution.trigger_type,
                "input_data": execution.input_data,
                "output_data": execution.output_data,
                "error_message": execution.error_message,
                "started_at": execution.started_at.isoformat() if execution.started_at else None,
                "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
                "created_at": execution.created_at.isoformat()
            } for execution in executions
        ]
        
        return {
            "success": True,
            "data": executions_data
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get workflow executions: {str(e)}"
        )


@router.post("/test-condition", response_model=ConditionTestResponse)
async def test_condition(
    data: ConditionTest,
    user: User = Depends(get_current_user)
):
    """Test conditional logic evaluation."""
    try:
        workflow_service = WorkflowBuilderService()
        
        # Extract values for response
        condition = data.condition
        context = data.context
        field_path = condition.get("field", "")
        operator = condition.get("operator", "equals")
        expected_value = condition.get("value")
        
        # Get actual value from context
        actual_value = workflow_service._extract_value_from_context(field_path, context)
        
        # Evaluate condition
        result = await workflow_service._evaluate_condition(condition, context)
        
        return ConditionTestResponse(
            result=result,
            evaluated_value=actual_value,
            expected_value=expected_value,
            operator=operator
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to test condition: {str(e)}"
        )


@router.post("/test-variable-substitution", response_model=VariableSubstitutionResponse)
async def test_variable_substitution(
    data: VariableSubstitution,
    user: User = Depends(get_current_user)
):
    """Test variable substitution in parameters."""
    try:
        workflow_service = WorkflowBuilderService()
        
        # Track original parameters
        original_parameters = data.parameters.copy()
        
        # Perform substitution
        substituted_parameters = workflow_service._substitute_variables(data.parameters, data.context)
        
        # Find substitutions made
        substitutions_made = []
        for key, value in substituted_parameters.items():
            if isinstance(value, str) and value != original_parameters.get(key, ""):
                substitutions_made.append(f"{key}: {original_parameters.get(key, '')} -> {value}")
        
        return VariableSubstitutionResponse(
            original_parameters=original_parameters,
            substituted_parameters=substituted_parameters,
            substitutions_made=substitutions_made
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to test variable substitution: {str(e)}"
        )


@router.get("/templates")
async def get_workflow_templates():
    """Get available workflow templates."""
    templates = [
        {
            "name": "Lead Qualification",
            "description": "Automated lead qualification workflow",
            "steps": [
                {
                    "step_number": 1,
                    "tool_name": "hubspot_contact_create",
                    "parameters": {
                        "email": "{{input.email}}",
                        "first_name": "{{input.first_name}}",
                        "last_name": "{{input.last_name}}"
                    },
                    "description": "Create contact in HubSpot",
                    "condition": None,
                    "retry_config": {"max_retries": 3, "retry_delay": 5},
                    "timeout": 30
                },
                {
                    "step_number": 2,
                    "tool_name": "slack_notification",
                    "parameters": {
                        "channel": "{{input.slack_channel}}",
                        "message": "New lead created: {{input.first_name}} {{input.last_name}}"
                    },
                    "description": "Send Slack notification",
                    "condition": {
                        "type": "if",
                        "field": "input.notify_slack",
                        "operator": "equals",
                        "value": True
                    },
                    "retry_config": {"max_retries": 3, "retry_delay": 5},
                    "timeout": 30
                }
            ]
        },
        {
            "name": "Customer Onboarding",
            "description": "Automated customer onboarding process",
            "steps": [
                {
                    "step_number": 1,
                    "tool_name": "hubspot_contact_create",
                    "parameters": {
                        "email": "{{input.customer_email}}",
                        "first_name": "{{input.customer_name}}",
                        "company": "{{input.company_name}}"
                    },
                    "description": "Create customer contact",
                    "condition": None,
                    "retry_config": {"max_retries": 3, "retry_delay": 5},
                    "timeout": 30
                },
                {
                    "step_number": 2,
                    "tool_name": "email_sender",
                    "parameters": {
                        "to": "{{input.customer_email}}",
                        "subject": "Welcome to our platform!",
                        "body": "Hi {{input.customer_name}}, welcome aboard!"
                    },
                    "description": "Send welcome email",
                    "condition": None,
                    "retry_config": {"max_retries": 3, "retry_delay": 5},
                    "timeout": 30
                },
                {
                    "step_number": 3,
                    "tool_name": "slack_notification",
                    "parameters": {
                        "channel": "onboarding",
                        "message": "New customer onboarded: {{input.customer_name}} from {{input.company_name}}"
                    },
                    "description": "Notify team",
                    "condition": {
                        "type": "if",
                        "field": "input.customer_type",
                        "operator": "equals",
                        "value": "enterprise"
                    },
                    "retry_config": {"max_retries": 3, "retry_delay": 5},
                    "timeout": 30
                }
            ]
        }
    ]
    
    return {"templates": templates}


@router.post("/chat-agent")
async def create_chat_agent(
    data: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Create a chat agent from a workflow."""
    try:
        workflow_service = WorkflowBuilderService()
        
        # Create workflow first
        workflow = await workflow_service.create_workflow_from_nlp(
            user.id, data.description, db, data.name
        )
        
        # Generate agent prompt
        agent_prompt = await workflow_service.create_agent_prompt(workflow)
        
        return {
            "workflow_id": workflow.id,
            "agent_prompt": agent_prompt,
            "message": "Chat agent created successfully"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create chat agent: {str(e)}"
        )


@router.post("/extract-from-conversation")
async def extract_workflow_from_conversation(
    data: WorkflowFromConversation,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Extract a workflow from conversation history.
    Analyzes tool calls in a conversation and creates a reusable workflow.
    """
    from sqlalchemy import select
    from ..models import Conversation, Message
    
    try:
        # Verify conversation belongs to user
        result = await db.execute(
            select(Conversation)
            .filter(Conversation.id == data.conversation_id, Conversation.user_id == user.id)
        )
        conversation = result.scalar_one_or_none()
        
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        
        # Get all messages with tool calls
        result = await db.execute(
            select(Message)
            .filter(Message.conversation_id == data.conversation_id)
            .order_by(Message.created_at)
        )
        messages = result.scalars().all()
        
        # Extract tool calls from messages
        extracted_steps = []
        step_number = 1
        
        for msg in messages:
            if msg.tools_called:
                for tool_call in msg.tools_called:
                    tool_name = tool_call.get("name", "")
                    arguments = tool_call.get("arguments", {})
                    tool_result = tool_call.get("result", {})
                    
                    # Skip if step is filtered out
                    if data.selected_step_ids and tool_call.get("id") not in data.selected_step_ids:
                        continue
                    
                    # Parameterize specified fields
                    parameterized_args = dict(arguments)
                    if data.parameterize_fields:
                        for field in data.parameterize_fields:
                            if field in parameterized_args:
                                parameterized_args[field] = f"{{{{input.{field}}}}}"
                    
                    step = {
                        "step_number": step_number,
                        "tool_name": tool_name,
                        "tool_parameters": parameterized_args,
                        "description": f"Execute {tool_name}",
                        "original_arguments": arguments,
                        "original_result": tool_result,
                        "condition": None,
                        "retry_config": {"max_retries": 3, "retry_delay": 5},
                        "timeout": 30
                    }
                    extracted_steps.append(step)
                    step_number += 1
        
        if not extracted_steps:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No tool calls found in conversation to extract"
            )
        
        # Build input schema from parameterized fields
        input_schema = {}
        if data.parameterize_fields:
            for field in data.parameterize_fields:
                input_schema[field] = {
                    "type": "string",
                    "required": True,
                    "description": f"Input value for {field}"
                }
        
        # Generate workflow suggestions
        suggestions = []
        if len(extracted_steps) > 1:
            suggestions.append("Consider adding error handling between steps")
        if any(step["tool_name"].startswith("slack") for step in extracted_steps):
            suggestions.append("Add notification on workflow completion")
        if not data.parameterize_fields:
            suggestions.append("Consider parameterizing key fields for reusability")
        
        return {
            "success": True,
            "data": {
                "workflow": {
                    "name": data.workflow_name,
                    "description": data.description or f"Workflow extracted from conversation {data.conversation_id}",
                    "steps": extracted_steps,
                    "trigger_type": data.trigger_type,
                    "trigger_config": data.trigger_config,
                    "input_schema": input_schema,
                    "source_conversation_id": data.conversation_id
                },
                "extraction_summary": {
                    "total_messages": len(messages),
                    "tool_calls_found": len(extracted_steps),
                    "parameterized_fields": data.parameterize_fields or []
                },
                "suggestions": suggestions
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to extract workflow: {str(e)}"
        )


@router.post("/create-from-steps")
async def create_workflow_from_steps(
    data: WorkflowFromSteps,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Create a workflow from explicit step definitions.
    Used when saving a workflow extracted from conversation.
    """
    try:
        workflow_service = WorkflowBuilderService()
        
        # Create workflow with steps
        workflow = Workflow(
            user_id=user.id,
            name=data.workflow_name,
            description=data.description,
            status=WorkflowStatus.DRAFT,
            trigger_type=WorkflowTriggerType(data.trigger_type) if data.trigger_type else WorkflowTriggerType.MANUAL,
            trigger_config=data.trigger_config,
            variables=data.variables or {},
            version=1,
            is_template=False
        )
        
        db.add(workflow)
        await db.commit()
        await db.refresh(workflow)
        
        # Create workflow steps
        created_steps = []
        for step_data in data.steps:
            step = WorkflowStep(
                workflow_id=workflow.id,
                step_number=step_data.get("step_number", len(created_steps) + 1),
                tool_name=step_data.get("tool_name"),
                tool_parameters=step_data.get("tool_parameters", {}),
                description=step_data.get("description", ""),
                condition=step_data.get("condition"),
                retry_config=step_data.get("retry_config", {"max_retries": 3, "retry_delay": 5}),
                timeout=step_data.get("timeout", 30)
            )
            db.add(step)
            created_steps.append(step)
        
        await db.commit()
        
        # Refresh to get step IDs
        for step in created_steps:
            await db.refresh(step)
        
        workflow_data = {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "status": workflow.status.value if hasattr(workflow.status, 'value') else str(workflow.status),
            "version": workflow.version,
            "is_template": workflow.is_template,
            "trigger_type": workflow.trigger_type.value if hasattr(workflow.trigger_type, 'value') else str(workflow.trigger_type),
            "trigger_config": workflow.trigger_config,
            "variables": workflow.variables,
            "workflow_metadata": workflow.workflow_metadata,
            "created_at": workflow.created_at.isoformat(),
            "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
            "steps": [{
                "id": step.id,
                "step_number": step.step_number,
                "tool_name": step.tool_name,
                "tool_parameters": step.tool_parameters,
                "description": step.description,
                "condition": step.condition,
                "retry_config": step.retry_config,
                "timeout": step.timeout
            } for step in created_steps]
        }
        
        return {
            "success": True,
            "data": workflow_data
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create workflow from steps: {str(e)}"
        )


@router.get("/conversation/{conversation_id}/tool-calls")
async def get_conversation_tool_calls(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Get all tool calls from a conversation for workflow extraction preview.
    """
    from sqlalchemy import select
    from ..models import Conversation, Message
    
    try:
        # Verify conversation belongs to user
        result = await db.execute(
            select(Conversation)
            .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
        )
        conversation = result.scalar_one_or_none()
        
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )
        
        # Get all messages
        result = await db.execute(
            select(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        messages = result.scalars().all()
        
        # Extract tool calls
        tool_calls = []
        for msg in messages:
            if msg.tools_called:
                for tool_call in msg.tools_called:
                    tool_calls.append({
                        "id": tool_call.get("id", f"call_{len(tool_calls)}"),
                        "message_id": msg.id,
                        "tool_name": tool_call.get("name", ""),
                        "arguments": tool_call.get("arguments", {}),
                        "result": tool_call.get("result", {}),
                        "success": tool_call.get("result", {}).get("success", True),
                        "timestamp": msg.created_at.isoformat() if msg.created_at else None
                    })
        
        # Identify parameterizable fields
        all_fields = set()
        for tc in tool_calls:
            for key in tc.get("arguments", {}).keys():
                all_fields.add(key)
        
        return {
            "success": True,
            "data": {
                "conversation_id": conversation_id,
                "conversation_title": conversation.title,
                "tool_calls": tool_calls,
                "total_tool_calls": len(tool_calls),
                "successful_tool_calls": sum(1 for tc in tool_calls if tc.get("success", True)),
                "available_fields": list(all_fields),
                "can_create_workflow": len(tool_calls) > 0
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get conversation tool calls: {str(e)}"
        )
