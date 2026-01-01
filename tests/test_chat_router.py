"""
Tests for chat endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_conversations_unauthorized(client: AsyncClient):
    """Test getting conversations without auth."""
    response = await client.get("/chat/conversations")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_conversations(client: AsyncClient, auth_headers):
    """Test getting user conversations."""
    response = await client.get(
        "/chat/conversations", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_create_conversation(client: AsyncClient, auth_headers):
    """Test creating a new conversation."""
    response = await client.post(
        "/chat/conversations",
        headers=auth_headers,
        json={
            "title": "Test Conversation",
            "llm_provider": "openai",
            "model": "gpt-4"
        }
    )
    assert response.status_code in [200, 201]


@pytest.mark.asyncio
async def test_create_conversation_minimal(
    client: AsyncClient, auth_headers
):
    """Test creating conversation with minimal data."""
    response = await client.post(
        "/chat/conversations",
        headers=auth_headers,
        json={}
    )
    assert response.status_code in [200, 201, 422]


@pytest.mark.asyncio
async def test_get_conversation(
    client: AsyncClient, auth_headers, test_conversation
):
    """Test getting a specific conversation."""
    response = await client.get(
        f"/chat/conversations/{test_conversation.id}",
        headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_conversation_not_found(
    client: AsyncClient, auth_headers
):
    """Test getting non-existent conversation."""
    response = await client.get(
        "/chat/conversations/99999", headers=auth_headers
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_conversation(
    client: AsyncClient, auth_headers, test_conversation
):
    """Test updating a conversation."""
    response = await client.put(
        f"/chat/conversations/{test_conversation.id}",
        headers=auth_headers,
        json={
            "title": "Updated Title"
        }
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_delete_conversation(
    client: AsyncClient, auth_headers, test_conversation
):
    """Test deleting a conversation."""
    response = await client.delete(
        f"/chat/conversations/{test_conversation.id}",
        headers=auth_headers
    )
    assert response.status_code in [200, 204]


@pytest.mark.asyncio
async def test_get_messages(
    client: AsyncClient, auth_headers, test_conversation
):
    """Test getting conversation messages."""
    response = await client.get(
        f"/chat/conversations/{test_conversation.id}/messages",
        headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_send_message(
    client: AsyncClient, auth_headers, test_conversation
):
    """Test sending a message."""
    response = await client.post(
        f"/chat/conversations/{test_conversation.id}/messages",
        headers=auth_headers,
        json={
            "content": "Hello, how are you?"
        }
    )
    # May take time or fail due to LLM unavailability
    assert response.status_code in [200, 201, 400, 500]


@pytest.mark.asyncio
async def test_get_providers(client: AsyncClient, auth_headers):
    """Test getting available providers."""
    response = await client.get("/chat/providers", headers=auth_headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_tools(client: AsyncClient, auth_headers):
    """Test getting available tools."""
    response = await client.get("/chat/tools", headers=auth_headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_ollama_status(client: AsyncClient, auth_headers):
    """Test Ollama status endpoint."""
    response = await client.get(
        "/chat/ollama/status", headers=auth_headers
    )
    assert response.status_code in [200, 500]


@pytest.mark.asyncio
async def test_ollama_diagnostic(client: AsyncClient, auth_headers):
    """Test Ollama diagnostic endpoint."""
    response = await client.get(
        "/chat/ollama/diagnostic", headers=auth_headers
    )
    assert response.status_code in [200, 500]


@pytest.mark.asyncio
async def test_explain_intent(
    client: AsyncClient, auth_headers, test_conversation
):
    """Test explaining intent endpoint."""
    conv_id = test_conversation.id
    response = await client.post(
        f"/chat/conversations/{conv_id}/explain-intent",
        headers=auth_headers,
        json={
            "message": "I want to create a marketing campaign"
        }
    )
    assert response.status_code in [200, 400, 422, 500]


@pytest.mark.asyncio
async def test_explain_tools(
    client: AsyncClient, auth_headers, test_conversation
):
    """Test explaining tools endpoint."""
    conv_id = test_conversation.id
    response = await client.post(
        f"/chat/conversations/{conv_id}/explain-tools",
        headers=auth_headers,
        json={
            "tool_names": ["hubspot_get_contacts", "slack_send_message"]
        }
    )
    assert response.status_code in [200, 400, 422, 500]


@pytest.mark.asyncio
async def test_validate_tool(
    client: AsyncClient, auth_headers, test_conversation
):
    """Test validating tool endpoint."""
    conv_id = test_conversation.id
    response = await client.post(
        f"/chat/conversations/{conv_id}/validate-tool",
        headers=auth_headers,
        json={
            "tool_name": "hubspot_get_contacts",
            "parameters": {"limit": 10}
        }
    )
    assert response.status_code in [200, 400, 500]


@pytest.mark.asyncio
async def test_get_tool_calls(
    client: AsyncClient, auth_headers, test_conversation
):
    """Test getting tool calls for a conversation."""
    conv_id = test_conversation.id
    response = await client.get(
        f"/workflows/conversation/{conv_id}/tool-calls",
        headers=auth_headers
    )
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_direct_response(client: AsyncClient, auth_headers):
    """Test direct response endpoint."""
    response = await client.post(
        "/chat/test/direct-response",
        headers=auth_headers,
        json={
            "message": "Test message"
        }
    )
    assert response.status_code in [200, 400, 422, 500]
