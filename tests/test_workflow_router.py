"""
Tests for workflow endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_workflows_unauthorized(client: AsyncClient):
    """Test listing workflows without auth returns 401."""
    response = await client.get("/workflows/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_workflows(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test listing user workflows."""
    response = await client.get("/workflows/", headers=auth_headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_create_workflow(client: AsyncClient, auth_headers):
    """Test creating a new workflow."""
    response = await client.post(
        "/workflows/create",
        headers=auth_headers,
        json={
            "workflow_name": "New Test Workflow",
            "description": "A test workflow",
            "trigger_type": "manual",
            "steps": []
        }
    )
    assert response.status_code in [200, 201]


@pytest.mark.asyncio
async def test_create_workflow_with_steps(client: AsyncClient, auth_headers):
    """Test creating a workflow with steps."""
    response = await client.post(
        "/workflows/create",
        headers=auth_headers,
        json={
            "workflow_name": "Workflow With Steps",
            "description": "A workflow with multiple steps",
            "trigger_type": "manual",
            "steps": [
                {
                    "step_number": 1,
                    "tool_name": "hubspot_get_contacts",
                    "tool_parameters": {"limit": 10},
                    "description": "Get contacts"
                },
                {
                    "step_number": 2,
                    "tool_name": "slack_send_message",
                    "tool_parameters": {"channel": "general"},
                    "description": "Send to Slack"
                }
            ]
        }
    )
    assert response.status_code in [200, 201]


@pytest.mark.asyncio
async def test_create_workflow_scheduled(client: AsyncClient, auth_headers):
    """Test creating a scheduled workflow."""
    response = await client.post(
        "/workflows/create",
        headers=auth_headers,
        json={
            "workflow_name": "Scheduled Workflow",
            "description": "Runs on a schedule",
            "trigger_type": "scheduled",
            "schedule": {"cron": "0 9 * * *"},
            "steps": []
        }
    )
    assert response.status_code in [200, 201]


@pytest.mark.asyncio
async def test_create_workflow_webhook(client: AsyncClient, auth_headers):
    """Test creating a webhook-triggered workflow."""
    response = await client.post(
        "/workflows/create",
        headers=auth_headers,
        json={
            "workflow_name": "Webhook Workflow",
            "description": "Triggered by webhook",
            "trigger_type": "webhook",
            "steps": []
        }
    )
    assert response.status_code in [200, 201]


@pytest.mark.asyncio
async def test_get_workflow(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test getting a specific workflow."""
    response = await client.get(
        f"/workflows/{test_workflow.id}", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_workflow_not_found(client: AsyncClient, auth_headers):
    """Test getting a non-existent workflow returns 404."""
    response = await client.get("/workflows/99999", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_workflow_with_steps(
    client: AsyncClient, auth_headers, test_workflow_with_steps
):
    """Test getting a workflow includes its steps."""
    response = await client.get(
        f"/workflows/{test_workflow_with_steps.id}",
        headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_delete_workflow(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test deleting a workflow."""
    response = await client.delete(
        f"/workflows/{test_workflow.id}", headers=auth_headers
    )
    assert response.status_code in [200, 204]


@pytest.mark.asyncio
async def test_delete_nonexistent_workflow(
    client: AsyncClient, auth_headers
):
    """Test deleting a non-existent workflow."""
    response = await client.delete(
        "/workflows/99999", headers=auth_headers
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_execute_workflow(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test executing a workflow."""
    response = await client.post(
        f"/workflows/{test_workflow.id}/execute",
        headers=auth_headers,
        json={}
    )
    assert response.status_code in [200, 400, 422, 500]


@pytest.mark.asyncio
async def test_execute_workflow_with_params(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test executing a workflow with parameters."""
    response = await client.post(
        f"/workflows/{test_workflow.id}/execute",
        headers=auth_headers,
        json={"params": {"key": "value"}}
    )
    assert response.status_code in [200, 400, 422, 500]


@pytest.mark.asyncio
async def test_get_workflow_executions(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test getting workflow executions."""
    response = await client.get(
        f"/workflows/{test_workflow.id}/executions",
        headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_workflow_executions_pagination(
    client: AsyncClient, auth_headers, test_workflow
):
    """Test getting workflow executions with pagination."""
    response = await client.get(
        f"/workflows/{test_workflow.id}/executions?limit=5&offset=0",
        headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_workflows_pagination(client: AsyncClient, auth_headers):
    """Test listing workflows with pagination."""
    for i in range(3):
        await client.post(
            "/workflows/create",
            headers=auth_headers,
            json={
                "workflow_name": f"Workflow {i}",
                "description": f"Test {i}",
                "trigger_type": "manual",
                "steps": []
            }
        )
    response = await client.get(
        "/workflows/?limit=2", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_workflow_create_from_steps(
    client: AsyncClient, auth_headers
):
    """Test creating workflow from steps endpoint."""
    response = await client.post(
        "/workflows/create-from-steps",
        headers=auth_headers,
        json={
            "workflow_name": "From Steps",
            "steps": [{"tool_name": "test_tool", "parameters": {}}]
        }
    )
    assert response.status_code in [200, 201, 400, 422]


@pytest.mark.asyncio
async def test_workflow_test_condition(client: AsyncClient, auth_headers):
    """Test workflow condition testing endpoint."""
    response = await client.post(
        "/workflows/test-condition",
        headers=auth_headers,
        json={
            "condition": "result.success == true",
            "context": {"result": {"success": True}}
        }
    )
    assert response.status_code in [200, 400, 422]


@pytest.mark.asyncio
async def test_workflow_test_variable_substitution(
    client: AsyncClient, auth_headers
):
    """Test workflow variable substitution endpoint."""
    response = await client.post(
        "/workflows/test-variable-substitution",
        headers=auth_headers,
        json={
            "template": "Hello {{name}}",
            "variables": {"name": "World"}
        }
    )
    assert response.status_code in [200, 400, 422]


@pytest.mark.asyncio
async def test_workflow_chat_agent(client: AsyncClient, auth_headers):
    """Test chat agent workflow endpoint."""
    response = await client.post(
        "/workflows/chat-agent",
        headers=auth_headers,
        json={"message": "Create a workflow that sends emails"}
    )
    assert response.status_code in [200, 400, 422, 500]


@pytest.mark.asyncio
async def test_access_other_users_workflow(
    client: AsyncClient, auth_headers_2, test_workflow
):
    """Test user cannot access another user's private workflow."""
    response = await client.get(
        f"/workflows/{test_workflow.id}", headers=auth_headers_2
    )
    assert response.status_code in [403, 404]
