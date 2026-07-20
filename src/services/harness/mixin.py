"""
Harnessed Execution Mixin — Reusable harness integration for any agent type.

This mixin provides composable harness capabilities that any agent class
can inherit. Instead of duplicating guardrail/feedback/quality logic across
ConversationalAgentService, BaseAgent, and future agent types, they all
compose in this mixin.

Usage:
    class MyAgent(HarnessedExecutionMixin):
        def __init__(self):
            self._init_harness("my_agent")

        async def execute(self, message, user, db):
            self._harness_reset_turn()
            context = await self._harness_build_context(user, "chat", db)
            # ... agent logic ...
            score = await self._harness_evaluate_response(response, message, tools)
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class HarnessedExecutionMixin:
    """
    Composable harness integration for any agent type.

    Provides four capabilities:
    1. Pre-execution guardrails (validate tool calls before execution)
    2. Error feedback loops (classify errors, generate corrective instructions)
    3. Post-execution quality gates (score response quality)
    4. Agent context injection (living documentation in system prompts)

    All methods are prefixed with _harness_ to avoid name collisions
    with the host agent class.
    """

    def _init_harness(self, agent_type: str = "generic"):
        """
        Initialize harness components. Call this in the agent's __init__.

        Args:
            agent_type: Identifier for this agent type (for observability tagging)
        """
        from .guardrails import AgentGuardrails
        from .feedback_loops import FeedbackLoop
        from .quality_gates import QualityGate
        from .agent_context import AgentContext

        self._harness_guardrails = AgentGuardrails()
        self._harness_feedback = FeedbackLoop(max_retries=3)
        self._harness_quality = QualityGate()
        self._harness_context = AgentContext()
        self._harness_agent_type = agent_type
        self._harness_turn_start: float = 0.0
        self._harness_tools_used: List[Dict[str, Any]] = []

    def _harness_reset_turn(self):
        """
        Reset per-turn state. Call at the start of each message processing.
        Clears retry counts and tool tracking from the previous turn.
        """
        if hasattr(self, '_harness_feedback'):
            self._harness_feedback.reset()
        self._harness_turn_start = time.time()
        self._harness_tools_used = []

    async def _harness_validate_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: Any,
        available_tools: Optional[List[str]] = None,
    ) -> "GuardrailResult":
        """
        Pre-execution: validate a tool call through guardrails.

        Returns:
            GuardrailResult — check .passed to decide whether to proceed.
            If not passed, use .suggestion for corrective instruction.
        """
        from .guardrails import GuardrailResult as GR

        if not hasattr(self, '_harness_guardrails'):
            return GR.ok()

        if available_tools is None:
            available_tools = [tool_name]  # Skip existence check if list not provided

        result = await self._harness_guardrails.validate_tool_call(
            tool_name=tool_name,
            arguments=arguments,
            user=user,
            available_tools=available_tools,
        )

        # Log the guardrail check
        self._harness_log_event(
            "GUARDRAIL_CHECK",
            {
                "tool_name": tool_name,
                "passed": result.passed,
                "rule_name": result.rule_name,
                "reason": result.reason,
                "severity": result.severity.value if result.severity else "info",
                "agent_type": self._harness_agent_type,
            }
        )

        return result

    async def _harness_handle_tool_error(
        self,
        tool_name: str,
        error: str,
        arguments: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> "FeedbackResult":
        """
        On error: classify the error and generate corrective instruction.

        Returns:
            FeedbackResult with .action (RETRY_WITH_FIX, ESCALATE, ABANDON)
            and .corrective_message to inject into the LLM conversation.
        """
        from .feedback_loops import FeedbackResult, FeedbackAction

        if not hasattr(self, '_harness_feedback'):
            return FeedbackResult(
                action=FeedbackAction.RETRY_WITH_FIX,
                corrective_message=f"Tool '{tool_name}' failed: {error}. Please retry."
            )

        result = await self._harness_feedback.handle_tool_error(
            tool_name=tool_name,
            error=error,
            arguments=arguments,
            context=context,
        )

        # Log the feedback loop event
        self._harness_log_event(
            "FEEDBACK_LOOP",
            {
                "tool_name": tool_name,
                "error_category": result.error_category.value,
                "action": result.action.value,
                "retry_count": result.retry_count,
                "agent_type": self._harness_agent_type,
            }
        )

        return result

    async def _harness_handle_guardrail_failure(
        self,
        guardrail_result: Any,
        tool_name: str = "",
        arguments: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate a corrective message from a guardrail failure.

        Returns a string to inject into the LLM conversation as a system/tool message.
        """
        if not hasattr(self, '_harness_feedback'):
            return f"Action blocked: {getattr(guardrail_result, 'reason', 'validation failed')}. Please try a different approach."

        return await self._harness_feedback.handle_validation_failure(
            guardrail_result=guardrail_result,
            tool_name=tool_name,
            arguments=arguments,
        )

    async def _harness_evaluate_response(
        self,
        response: str,
        user_intent: str,
        tools_used: Optional[List[Dict[str, Any]]] = None,
        iterations: int = 1,
        tokens_used: int = 0,
    ) -> "QualityScore":
        """
        Post-execution: score the response quality.

        Returns:
            QualityScore with .overall_score, .passed, .safety, etc.
            For WhatsApp agents, if safety < 0.3, the response should be
            replaced with a generic fallback.
        """
        from .quality_gates import QualityScore

        if not hasattr(self, '_harness_quality'):
            return QualityScore(overall_score=1.0)

        elapsed_ms = int((time.time() - self._harness_turn_start) * 1000) if self._harness_turn_start else 0

        score = await self._harness_quality.evaluate_response(
            response=response,
            user_intent=user_intent,
            tools_used=tools_used or self._harness_tools_used,
            iterations=iterations,
            tokens_used=tokens_used,
            execution_time_ms=elapsed_ms,
        )

        # Log the quality gate result
        event_type = "QUALITY_GATE_PASS" if score.passed else "QUALITY_GATE_FAIL"
        self._harness_log_event(
            event_type,
            {
                "overall_score": score.overall_score,
                "completeness": score.completeness,
                "accuracy": score.accuracy,
                "efficiency": score.efficiency,
                "safety": score.safety,
                "warnings": score.warnings,
                "agent_type": self._harness_agent_type,
            }
        )

        return score

    async def _harness_build_context(
        self,
        user: Any,
        conversation_type: str = "chat",
        db: Any = None,
    ) -> str:
        """
        Build the agent context document for system prompt injection.

        Returns a string to append to the system prompt.
        """
        if not hasattr(self, '_harness_context'):
            return ""

        try:
            # Fetch connected platforms if db is available
            connected = []
            if db:
                connected = await self._harness_context.get_connected_platforms(user, db)

            # Get recent error patterns from feedback loop
            recent_errors = []
            if hasattr(self, '_harness_feedback'):
                recent_errors = self._harness_feedback.get_error_patterns()

            return await self._harness_context.get_context(
                user=user,
                conversation_type=conversation_type,
                connected_platforms=connected,
                recent_errors=recent_errors,
            )
        except Exception as e:
            logger.warning(f"[HARNESS] Failed to build agent context: {e}")
            return ""

    def _harness_track_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any,
    ):
        """Track a tool call for quality gate evaluation."""
        self._harness_tools_used.append({
            "name": tool_name,
            "arguments": arguments,
            "result": result,
        })

    def _harness_should_block_response(self, quality_score: "QualityScore") -> bool:
        """
        Determine if a response should be blocked based on quality score.

        Only blocks for critical safety issues (PII exposure, credential leaks).
        All other quality dimensions are log-only.
        """
        return quality_score.safety < 0.3

    def _harness_get_safe_fallback(self, business_name: str = "our team") -> str:
        """
        Get a safe generic fallback response when the original is blocked.
        """
        return (
            f"Thank you for your message! {business_name} will get back to you shortly. "
            "If you need immediate assistance, please contact us directly."
        )

    def _harness_log_event(self, event_type: str, data: Dict[str, Any]):
        """Log a harness event to the observability system."""
        try:
            from ...observability.logger import log_event
            log_event(
                event_type=event_type,
                data=data,
                logger_name=f"harness.{self._harness_agent_type}",
            )
        except Exception:
            # Fallback to standard logging if observability isn't available
            logger.info(f"[HARNESS:{event_type}] {data}")
