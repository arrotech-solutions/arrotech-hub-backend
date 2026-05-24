"""Tests for src/services/conversational_agent_service.py"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.services.conversational_agent_service import ConversationalAgentService
from src.models import User
import json

@pytest.fixture
def mock_db():
    return AsyncMock()

@pytest.fixture
def mock_user():
    return User(id="user_123", subscription_tier="pro", email="test@arrotech.com")

class TestConversationalAgentService:

    def test_agent_initialization(self):
        """Test the agent initializes with internal services."""
        svc = ConversationalAgentService()
        assert svc.llm_service is not None
        assert svc.order_service is not None

    @pytest.mark.asyncio
    async def test_dynamic_mcp_harness_injection(self, mock_db, mock_user):
        """Test that MCP tools from business_config are fetched and injected into the LLM tools array."""
        svc = ConversationalAgentService()
        
        # We patch LLMService and DynamicToolRegistry
        with patch.object(svc.llm_service, 'chat_completion', new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value.error = None
            mock_chat.return_value.tools_called = []
            mock_chat.return_value.content = "How can I help you today?"

            with patch('src.services.dynamic_tool_registry.dynamic_tool_registry.get_tool') as mock_get_tool:
                # Return a dummy tool
                mock_get_tool.return_value = {
                    "name": "web_search",
                    "description": "Search the web",
                    "inputSchema": {"type": "object", "properties": {}}
                }

                result = await svc.execute(
                    user_message="Hello",
                    session_key="test_session",
                    business_config={"enabled_mcp_tools": ["web_search"]},
                    user=mock_user,
                    db=mock_db
                )

                # Verify get_tool was called
                mock_get_tool.assert_called_with("web_search")

                # Verify the tools array passed to the LLM has our dynamic tool
                # Original core tools + 1 dynamic tool
                call_kwargs = mock_chat.call_args.kwargs
                passed_tools = call_kwargs['tools']
                
                # Check if 'web_search' is in the passed tools list
                assert any(t.get("function", {}).get("name") == "web_search" for t in passed_tools)

    @pytest.mark.asyncio
    async def test_core_tool_routing(self, mock_db, mock_user):
        """Test that calling a core tool routes internally and not to ToolExecutor."""
        svc = ConversationalAgentService()
        
        with patch.object(svc.llm_service, 'chat_completion', new_callable=AsyncMock) as mock_chat:
            # Simulate the LLM calling the core tool 'calculate_total'
            class MockLLMResponse:
                error = None
                content = ""
                tools_called = [{"name": "calculate_total", "arguments": {"items": [{"price": 100, "quantity": 1}]}}]

            # Second iteration response (finish)
            class MockLLMFinalResponse:
                error = None
                content = "Total is 100"
                tools_called = []

            mock_chat.side_effect = [MockLLMResponse(), MockLLMFinalResponse()]

            with patch.object(svc, '_sub_calculate_total', new_callable=AsyncMock) as mock_calc:
                mock_calc.return_value = {"success": True, "result": "100"}
                
                with patch('src.services.tool_executor.ToolExecutor.execute_tool') as mock_exec:
                    await svc.execute(
                        user_message="Total?",
                        session_key="test_session",
                        business_config={},
                        user=mock_user,
                        db=mock_db
                    )
                    
                    # Core tool was routed internally
                    mock_calc.assert_called_once()
                    # Generic tool executor should NOT be called for core tools
                    mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_dynamic_tool_delegation(self, mock_db, mock_user):
        """Test that unknown/dynamic tools delegate gracefully to ToolExecutor."""
        svc = ConversationalAgentService()
        
        with patch.object(svc.llm_service, 'chat_completion', new_callable=AsyncMock) as mock_chat:
            # Simulate the LLM calling a dynamic MCP tool 'web_search'
            class MockLLMResponse:
                error = None
                content = ""
                tools_called = [{"name": "web_search", "arguments": {"query": "weather"}}]

            class MockLLMFinalResponse:
                error = None
                content = "It's sunny"
                tools_called = []

            mock_chat.side_effect = [MockLLMResponse(), MockLLMFinalResponse()]

            with patch('src.services.tool_executor.ToolExecutor.execute_tool', new_callable=AsyncMock) as mock_exec:
                mock_exec.return_value = {"success": True, "result": "Sunny"}
                
                await svc.execute(
                    user_message="Weather?",
                    session_key="test_session",
                    business_config={"enabled_mcp_tools": ["web_search"]},
                    user=mock_user,
                    db=mock_db
                )
                
                # Dynamic routing occurred
                mock_exec.assert_called_once()
                call_args = mock_exec.call_args[0]
                assert call_args[0] == "web_search"
                assert call_args[1] == {"query": "weather"}

    @pytest.mark.asyncio
    async def test_feedback_loop_context(self, mock_db, mock_user):
        """Test that tool failures provide the JSON error string back to the LLM loop."""
        svc = ConversationalAgentService()
        
        with patch.object(svc.llm_service, 'chat_completion', new_callable=AsyncMock) as mock_chat:
            # LLM calls a tool that fails
            class MockLLMResponse:
                error = None
                content = ""
                tools_called = [{"name": "some_tool", "arguments": {}}]

            class MockLLMFinalResponse:
                error = None
                content = "I fixed it"
                tools_called = []

            mock_chat.side_effect = [MockLLMResponse(), MockLLMFinalResponse()]

            with patch('src.services.tool_executor.ToolExecutor.execute_tool', new_callable=AsyncMock) as mock_exec:
                # ToolExecutor throws a standard MCP error
                mock_exec.return_value = {"success": False, "error": "API Key Invalid"}
                
                with patch('src.services.dynamic_tool_registry.dynamic_tool_registry.get_tool') as mock_get_tool:
                    mock_get_tool.return_value = {"name": "some_tool", "description": "desc", "inputSchema": {}}
                    
                    await svc.execute(
                        user_message="Do it",
                        session_key="test_session",
                        business_config={"enabled_mcp_tools": ["some_tool"]},
                        user=mock_user,
                        db=mock_db
                    )
                
                # Verify that on the second call to LLM, the messages array contains the error payload
                second_call_args = mock_chat.call_args_list[1]
                messages = second_call_args.kwargs['messages']
                
                # Last message should be the tool response with the error
                last_message = messages[-1]
                assert last_message["role"] == "tool"
                assert "API Key Invalid" in last_message["content"]

    def test_build_system_prompt_verticals(self):
        """Test system prompt building for new business verticals."""
        svc = ConversationalAgentService()
        
        # Test electronics vertical
        prompt_electronics = svc._build_system_prompt(
            business_name="TechStore",
            order_type="electronics",
            currency="USD",
            delivery_methods=["shipping"]
        )
        assert "electronics and gadgets store" in prompt_electronics
        assert "warranty info" in prompt_electronics
        assert "USD" in prompt_electronics
        assert "shipping" in prompt_electronics
        
        # Test pharmacy vertical
        prompt_pharmacy = svc._build_system_prompt(
            business_name="HealthMed",
            order_type="pharmacy",
            currency="KES",
            delivery_methods=["pickup", "delivery"]
        )
        assert "pharmacy and health store" in prompt_pharmacy
        assert "prescription" in prompt_pharmacy
        assert "KES" in prompt_pharmacy
        
        # Test agro_vet vertical
        prompt_agro = svc._build_system_prompt(
            business_name="FarmSupply",
            order_type="agro_vet",
            currency="KES",
            delivery_methods=["delivery"]
        )
        assert "agro-vet and farm supply" in prompt_agro
        assert "livestock feeds" in prompt_agro
        
        # Test drinks vertical
        prompt_drinks = svc._build_system_prompt(
            business_name="VinoLiquors",
            order_type="drinks",
            currency="KES",
            delivery_methods=["delivery"]
        )
        assert "drinks and beverages store" in prompt_drinks
        assert "legal drinking age" in prompt_drinks

        # Test grocery vertical
        prompt_grocery = svc._build_system_prompt(
            business_name="QuickMart",
            order_type="grocery",
            currency="KES",
            delivery_methods=["delivery"]
        )
        assert "grocery and supermarket store" in prompt_grocery
        assert "fresh produce" in prompt_grocery

        # Test beauty vertical
        prompt_beauty = svc._build_system_prompt(
            business_name="GlowBoutique",
            order_type="beauty",
            currency="KES",
            delivery_methods=["shipping"]
        )
        assert "beauty and cosmetics consultant" in prompt_beauty
        assert "skin type" in prompt_beauty

        # Test home_decor vertical
        prompt_decor = svc._build_system_prompt(
            business_name="DecoHaus",
            order_type="home_decor",
            currency="USD",
            delivery_methods=["shipping"]
        )
        assert "home styling and decor" in prompt_decor
        assert "furniture" in prompt_decor

        # Test services vertical
        prompt_services = svc._build_system_prompt(
            business_name="FixIt",
            order_type="services",
            currency="KES",
            delivery_methods=["pickup"]
        )
        assert "booking and services assistant" in prompt_services
        assert "schedule professional services" in prompt_services
