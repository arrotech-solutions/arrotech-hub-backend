import pytest
import uuid
import json
from unittest.mock import AsyncMock, patch, MagicMock

from src.models import User, MessageRole
from src.services.execution_orchestrator import ExecutionOrchestrator

@pytest.fixture
def mock_db():
    db = AsyncMock()
    
    # Mock execute() to return a scalar_one_or_none result for UserSettings and other queries
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalar.return_value = 0
    db.execute.return_value = mock_result
    
    return db

@pytest.fixture
def mock_user():
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.subscription_tier = "free"
    return user

@pytest.fixture
def orchestrator(mock_db, mock_user):
    conversation_id = uuid.uuid4()
    # Patch dependencies inside __init__
    with patch('src.services.execution_orchestrator.ToolRouter'), \
         patch('src.services.execution_orchestrator.IntentProcessor'):
        orch = ExecutionOrchestrator(mock_db, mock_user, conversation_id)
        # Mock internal attributes
        orch.tool_router = AsyncMock()
        orch.intent_processor = AsyncMock()
        
        # Mock harness components
        orch.guardrails = AsyncMock()
        orch.feedback_loop = AsyncMock()
        orch.quality_gate = AsyncMock()
        orch.agent_context = AsyncMock()
        orch._harness_enabled = True
        
        return orch

class TestExecutionOrchestrator:

    @pytest.mark.asyncio
    @patch('src.services.execution_orchestrator.FeatureGate')
    async def test_process_message_rate_limit(self, mock_feature_gate, orchestrator):
        """Test that process_message enforces daily AI message limits."""
        # Setup: user is not BYOK, and they exceeded limits
        mock_feature_gate.can_use_ai_message.return_value = False
        mock_feature_gate.get_limits.return_value = {"max_ai_messages_daily": 10}
        
        response, tools, tokens = await orchestrator.process_message("Hello", "openai")
        
        assert "Plan limit reached" in response
        assert tools == []
        assert tokens == 0
        mock_feature_gate.can_use_ai_message.assert_called_once()
        orchestrator.intent_processor.classify_intent.assert_not_called()

    @pytest.mark.asyncio
    @patch('src.services.execution_orchestrator.FeatureGate')
    async def test_process_message_byok_skips_rate_limit(self, mock_feature_gate, orchestrator):
        """Test that BYOK users skip the rate limit check."""
        # Setup BYOK
        mock_settings = MagicMock()
        mock_settings.openai_api_key = "sk-1234"
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_settings
        orchestrator.db.execute.return_value = mock_result
        
        # Mock IntentProcessor to return requires_tools = False to short-circuit
        mock_intent = MagicMock()
        mock_intent.requires_tools = False
        mock_intent.intent_type = "chat"
        mock_intent.confidence = 0.99
        orchestrator.intent_processor.classify_intent.return_value = mock_intent
        
        # Mock direct response
        with patch.object(orchestrator, '_generate_direct_response', new_callable=AsyncMock) as mock_direct:
            mock_direct.return_value = ("Direct response", [], 50)
            
            response, tools, tokens = await orchestrator.process_message("Hello", "openai")
            
            # Feature gate should NOT be called because BYOK is True
            mock_feature_gate.can_use_ai_message.assert_not_called()
            assert response == "Direct response"

    @pytest.mark.asyncio
    @patch('src.services.execution_orchestrator.FeatureGate')
    async def test_process_message_direct_response_no_tools_needed(self, mock_feature_gate, orchestrator):
        """Test routing to direct response when intent processor says no tools are needed."""
        mock_feature_gate.can_use_ai_message.return_value = True
        
        mock_intent = MagicMock()
        mock_intent.requires_tools = False
        mock_intent.intent_type = "chat"
        mock_intent.confidence = 0.99
        orchestrator.intent_processor.classify_intent.return_value = mock_intent
        
        with patch.object(orchestrator, '_generate_direct_response', new_callable=AsyncMock) as mock_direct:
            mock_direct.return_value = ("Hello there", [], 10)
            
            response, tools, tokens = await orchestrator.process_message("Hi", "openai")
            
            assert response == "Hello there"
            mock_direct.assert_called_once_with("Hi", "openai")

    @pytest.mark.asyncio
    @patch('src.services.execution_orchestrator.FeatureGate')
    async def test_process_message_direct_response_no_tools_found(self, mock_feature_gate, orchestrator):
        """Test routing to direct response when tools are needed but none are found by router."""
        mock_feature_gate.can_use_ai_message.return_value = True
        
        mock_intent = MagicMock()
        mock_intent.requires_tools = True
        mock_intent.intent_type = "chat"
        mock_intent.confidence = 0.99
        orchestrator.intent_processor.classify_intent.return_value = mock_intent
        
        orchestrator.tool_router.get_relevant_tools.return_value = []
        
        with patch.object(orchestrator, '_generate_direct_response', new_callable=AsyncMock) as mock_direct:
            mock_direct.return_value = ("No tools found", [], 10)
            
            response, tools, tokens = await orchestrator.process_message("Do something", "openai")
            
            assert response == "No tools found"
            mock_direct.assert_called_once_with("Do something", "openai")

    def test_should_use_code_mode_tier_check(self, orchestrator):
        """Test Code Mode heuristic based on subscription tier."""
        relevant_tools = [{"name": "tool1"}] * 20  # High tool count should trigger it...
        
        # Free tier
        orchestrator.user.subscription_tier = "free"
        assert orchestrator._should_use_code_mode(relevant_tools, "write code") is False
        
        # Pro tier
        orchestrator.user.subscription_tier = "pro"
        assert orchestrator._should_use_code_mode(relevant_tools, "write code") is True

    def test_should_use_code_mode_keywords(self, orchestrator):
        """Test Code Mode heuristic based on user input keywords."""
        orchestrator.user.subscription_tier = "pro"
        relevant_tools = [{"name": "tool1"}]
        
        assert orchestrator._should_use_code_mode(relevant_tools, "Please write a script to do this") is True
        assert orchestrator._should_use_code_mode(relevant_tools, "Just do this") is False

    @pytest.mark.asyncio
    @patch('src.routers.chat_router.get_optimized_context')
    async def test_generate_direct_response_fallback(self, mock_get_context, orchestrator):
        """Test BYOK fallback logic when primary provider fails."""
        mock_get_context.return_value = []
        
        # Mock settings with fallback keys
        mock_settings = MagicMock()
        mock_settings.anthropic_api_key = "sk-anthropic-123"
        mock_settings.openai_api_key = None
        
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_settings
        orchestrator.db.execute.return_value = mock_result
        
        # Primary provider (openai) returns an error
        with patch.object(orchestrator, '_call_llm_fallback', new_callable=AsyncMock) as mock_llm:
            # First call (openai) returns error, second call (anthropic fallback) succeeds
            mock_llm.side_effect = [
                None,
                {
                    "choices": [{"message": {"content": "Fallback success"}}],
                    "usage": {"total_tokens": 42}
                }
            ]
            
            response, tools, tokens = await orchestrator._generate_direct_response("Hello", "openai")
            
            assert response == "Fallback success"
            assert tokens == 42
            assert mock_llm.call_count == 2
            # Second call should be anthropic
            mock_llm.assert_called_with("anthropic", [{"role": "user", "content": "Hello"}])

    @pytest.mark.asyncio
    @patch('src.services.execution_orchestrator.dynamic_tool_registry.convert_tools_to_openai_format')
    @patch('src.routers.chat_router.get_optimized_context')
    @patch('src.routers.subscription_router.get_or_create_usage_record')
    @patch('src.services.execution_orchestrator.FeatureGate')
    async def test_process_message_quality_gate(
        self, mock_feature_gate, mock_usage, mock_get_context, mock_convert, orchestrator
    ):
        """Test the full function calling loop triggers the QualityGate correctly."""
        # Setup basic execution
        mock_feature_gate.can_use_ai_message.return_value = True
        
        mock_intent = MagicMock()
        mock_intent.requires_tools = True
        mock_intent.intent_type = "task"
        mock_intent.confidence = 0.99
        orchestrator.intent_processor.classify_intent.return_value = mock_intent
        
        orchestrator.tool_router.get_relevant_tools.return_value = [{"name": "fake_tool"}]
        orchestrator.user.subscription_tier = "free" # Ensure Code Mode is false
        
        mock_convert.return_value = [{"type": "function", "function": {"name": "fake_tool"}}]
        mock_get_context.return_value = []
        
        # Mock function calling loop to return successfully
        with patch.object(orchestrator, '_execute_function_calling_loop', new_callable=AsyncMock) as mock_loop:
            mock_loop.return_value = ("Success response", [{"name": "fake_tool"}], 150)
            
            # Mock usage record
            mock_usage_record = MagicMock()
            mock_usage_record.ai_actions_count = 0
            mock_usage_record.ai_actions_limit = 100
            mock_usage.return_value = mock_usage_record
            
            # Mock Quality Gate
            mock_qg_result = MagicMock()
            mock_qg_result.passed = True
            mock_qg_result.overall_score = 0.95
            orchestrator.quality_gate.evaluate_response.return_value = mock_qg_result
            
            response, tools, tokens = await orchestrator.process_message("Test", "openai")
            
            assert response == "Success response"
            orchestrator.quality_gate.evaluate_response.assert_called_once()
            
            # Verify AI action tracked
            assert mock_usage_record.ai_actions_count == 1
            orchestrator.db.commit.assert_called_once()

    @pytest.mark.asyncio
    @patch('src.services.execution_orchestrator.tool_executor.execute_tool')
    @patch('src.services.execution_orchestrator.ToolArgumentValidator.validate')
    async def test_execute_function_calling_loop_max_iterations(self, mock_validate, mock_exec_tool, orchestrator):
        """Test the loop breaks after max iterations if the LLM keeps returning tool calls."""
        
        messages = [{"role": "user", "content": "Keep looping"}]
        tools = [{"type": "function", "function": {"name": "test_tool"}}]
        
        # Validate always returns True
        mock_validate.return_value = (True, "")
        mock_exec_tool.return_value = {"result": "ok"}
        
        # Make the LLM ALWAYS return a tool call
        with patch.object(orchestrator, '_call_llm_fallback', new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {
                "choices": [{
                    "message": {
                        "content": "",
                        "tool_calls": [{
                            "id": "call_1",
                            "function": {
                                "name": "test_tool",
                                "arguments": "{}"
                            }
                        }]
                    }
                }],
                "usage": {"completion_tokens": 10}
            }
            
            response, tools_called, output_tokens = await orchestrator._execute_function_calling_loop(
                provider="openai", messages=messages, tools=tools, max_iterations=3
            )
            
            # It should have looped exactly 3 times
            assert mock_llm.call_count == 3
            # And executed the tool 3 times
            assert mock_exec_tool.call_count == 3
            assert len(tools_called) == 3
            assert output_tokens == 30

    @pytest.mark.asyncio
    @patch('src.services.execution_orchestrator.tool_executor.execute_tool')
    @patch('src.services.execution_orchestrator.ToolArgumentValidator.validate')
    async def test_execute_function_calling_loop_validation_failure_triggers_feedback(
        self, mock_validate, mock_exec_tool, orchestrator
    ):
        """Test that when tool arguments are invalid, the feedback loop is triggered."""
        
        messages = [{"role": "user", "content": "Do it"}]
        tools = [{"type": "function", "function": {"name": "test_tool"}}]
        
        # Mock validation to fail
        mock_validate.return_value = (False, "Missing required arg 'x'")
        
        # Mock feedback loop
        mock_feedback = MagicMock()
        mock_feedback.corrective_message = "Fix the arg x"
        orchestrator.feedback_loop.handle_tool_error.return_value = mock_feedback
        
        # Make the LLM return a tool call on first iteration, and text on second
        with patch.object(orchestrator, '_call_llm_fallback', new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = [
                # Iteration 1: returns tool call
                {
                    "choices": [{
                        "message": {
                            "content": "",
                            "tool_calls": [{
                                "id": "call_1",
                                "function": {
                                    "name": "test_tool",
                                    "arguments": "{}"
                                }
                            }]
                        }
                    }],
                    "usage": {"completion_tokens": 10}
                },
                # Iteration 2: LLM yields text because it was corrected
                {
                    "choices": [{
                        "message": {
                            "content": "I fixed it",
                        }
                    }],
                    "usage": {"completion_tokens": 10}
                }
            ]
            
            response, tools_called, output_tokens = await orchestrator._execute_function_calling_loop(
                provider="openai", messages=messages, tools=tools, max_iterations=3
            )
            
            # Exec tool should NOT be called because validation failed
            mock_exec_tool.assert_not_called()
            # Feedback loop should be called
            orchestrator.feedback_loop.handle_tool_error.assert_called_once_with(
                "test_tool", "Missing required arg 'x'", {}
            )
            assert response == "I fixed it"
