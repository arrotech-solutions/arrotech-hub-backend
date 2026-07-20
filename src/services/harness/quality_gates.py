"""
Quality Gates — Post-execution evaluation checkpoints.

Implements the evaluation framework from OpenAI's Harness Engineering:
after an agent produces output, quality gates score the response on
multiple dimensions. Scores are logged to observability for dashboarding.

Evaluation dimensions:
1. Completeness — Did the agent address the full user intent?
2. Accuracy — Were the tool calls appropriate?
3. Efficiency — Token usage, iteration count, unnecessary tool calls
4. Safety — PII exposure, unauthorized access attempts

This is rule-based evaluation (no LLM calls for scoring).
Designed for future extension to model-graded evals.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class QualityScore:
    """Quality evaluation result for an agent response."""
    overall_score: float           # 0.0 to 1.0
    completeness: float = 0.0     # Did it address the full request?
    accuracy: float = 0.0         # Were tool calls correct?
    efficiency: float = 0.0       # Resource usage efficiency
    safety: float = 1.0           # Safety score (1.0 = no issues)
    details: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    
    @property
    def passed(self) -> bool:
        """Quality gate passes if overall score >= 0.5."""
        return self.overall_score >= 0.5
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_score": round(self.overall_score, 3),
            "completeness": round(self.completeness, 3),
            "accuracy": round(self.accuracy, 3),
            "efficiency": round(self.efficiency, 3),
            "safety": round(self.safety, 3),
            "passed": self.passed,
            "warnings": self.warnings,
            "details": self.details,
        }


class QualityGate:
    """
    Evaluation framework for agent outputs.
    
    Runs rule-based checks after the agent produces a response.
    Results are logged to ObservabilityLog for dashboarding.
    """
    
    async def evaluate_response(
        self,
        response: str,
        user_intent: str,
        tools_used: List[Dict[str, Any]],
        iterations: int = 1,
        tokens_used: int = 0,
        execution_time_ms: int = 0,
    ) -> QualityScore:
        """
        Score the quality of an agent response.
        
        Args:
            response: The agent's text response
            user_intent: The original user message
            tools_used: List of tools called during processing
            iterations: Number of LLM iterations in the function-calling loop
            tokens_used: Total tokens consumed
            execution_time_ms: Total wall-clock time
        """
        warnings = []
        details = {}
        
        # 1. Completeness score
        completeness = self._score_completeness(response, user_intent, tools_used, warnings, details)
        
        # 2. Accuracy score
        accuracy = self._score_accuracy(tools_used, warnings, details)
        
        # 3. Efficiency score
        efficiency = self._score_efficiency(
            iterations, tokens_used, len(tools_used), execution_time_ms, warnings, details
        )
        
        # 4. Safety score
        safety = self._score_safety(response, tools_used, warnings, details)
        
        # Weighted overall score
        overall = (
            completeness * 0.35 +
            accuracy * 0.30 +
            efficiency * 0.20 +
            safety * 0.15
        )
        
        score = QualityScore(
            overall_score=overall,
            completeness=completeness,
            accuracy=accuracy,
            efficiency=efficiency,
            safety=safety,
            details=details,
            warnings=warnings,
        )
        
        # Log the score
        if not score.passed:
            logger.warning(
                f"Quality gate FAILED: {score.overall_score:.2f} "
                f"(completeness={completeness:.2f}, accuracy={accuracy:.2f}, "
                f"efficiency={efficiency:.2f}, safety={safety:.2f})"
            )
        
        return score
    
    async def evaluate_code_mode_execution(
        self,
        code: str,
        result: Dict[str, Any],
        user_intent: str,
    ) -> QualityScore:
        """Score the quality of a Code Mode execution."""
        warnings = []
        details = {"mode": "code_mode"}
        
        success = result.get("success", False)
        tools_invoked = result.get("tools_invoked", [])
        execution_time = result.get("execution_time_ms", 0)
        error = result.get("error")
        
        # Completeness: did it succeed?
        completeness = 1.0 if success else 0.2
        if error:
            completeness = 0.1
            warnings.append(f"Code execution error: {error[:100]}")
        
        # Accuracy: did it call reasonable tools?
        accuracy = self._score_accuracy(
            [{"name": t["tool_name"]} for t in tools_invoked],
            warnings, details
        )
        
        # Efficiency: execution time and tool call count
        efficiency = 1.0
        if execution_time > 15000:
            efficiency -= 0.3
            warnings.append(f"Slow execution: {execution_time}ms")
        if len(tools_invoked) > 15:
            efficiency -= 0.3
            warnings.append(f"High tool call count: {len(tools_invoked)}")
        efficiency = max(0.0, efficiency)
        
        # Safety
        safety = 1.0
        if not success and result.get("error_type") == "SECURITY_VIOLATION":
            safety = 0.0
            warnings.append("Security violation in generated code")
        
        overall = (
            completeness * 0.40 +
            accuracy * 0.25 +
            efficiency * 0.20 +
            safety * 0.15
        )
        
        return QualityScore(
            overall_score=overall,
            completeness=completeness,
            accuracy=accuracy,
            efficiency=efficiency,
            safety=safety,
            details=details,
            warnings=warnings,
        )
    
    def _score_completeness(
        self, response: str, intent: str, tools: List[Dict], warnings: List, details: Dict
    ) -> float:
        """Score whether the response addresses the user's intent."""
        if not response or len(response.strip()) < 10:
            warnings.append("Response is empty or very short")
            return 0.1
        
        score = 0.7  # Base score for non-empty response
        
        # Bonus: response contains tool results (actually did something)
        if tools:
            score += 0.2
            
            # Check if any tools failed
            failed = sum(1 for t in tools if isinstance(t.get("result"), dict) and t["result"].get("error"))
            if failed > 0:
                score -= 0.1 * min(failed, 3)
                warnings.append(f"{failed} tool(s) failed during execution")
        
        # Bonus: response length proportional to intent complexity
        intent_words = len(intent.split())
        response_words = len(response.split())
        if intent_words > 20 and response_words < 20:
            score -= 0.1
            warnings.append("Complex request received a short response")
        
        # Penalty: error/apology language
        error_phrases = ["i apologize", "i'm sorry", "i cannot", "error occurred", "unable to"]
        for phrase in error_phrases:
            if phrase in response.lower():
                score -= 0.15
                break
        
        details["response_words"] = response_words
        details["intent_words"] = intent_words
        details["tools_used_count"] = len(tools)
        
        return max(0.0, min(1.0, score))
    
    def _score_accuracy(
        self, tools: List[Dict], warnings: List, details: Dict
    ) -> float:
        """Score whether the tool calls were appropriate."""
        if not tools:
            return 0.8  # No tools needed might be fine
        
        score = 1.0
        
        # Check for duplicate tool calls (same tool, same args)
        seen = set()
        duplicates = 0
        for tool in tools:
            key = f"{tool.get('name')}:{str(tool.get('arguments', {}))}"
            if key in seen:
                duplicates += 1
            seen.add(key)
        
        if duplicates > 0:
            score -= 0.1 * min(duplicates, 3)
            warnings.append(f"{duplicates} duplicate tool call(s)")
        
        # Check for tool errors
        errors = 0
        for tool in tools:
            result = tool.get("result")
            if isinstance(result, dict) and (result.get("error") or result.get("success") is False):
                errors += 1
        
        if errors > 0:
            score -= 0.15 * min(errors, 3)
        
        details["duplicate_calls"] = duplicates
        details["tool_errors"] = errors
        
        return max(0.0, min(1.0, score))
    
    def _score_efficiency(
        self, iterations: int, tokens: int, tool_count: int,
        execution_ms: int, warnings: List, details: Dict
    ) -> float:
        """Score resource usage efficiency."""
        score = 1.0
        
        # Iteration efficiency (1 is best, 5 is max/worst)
        if iterations > 3:
            score -= 0.2
            warnings.append(f"High iteration count: {iterations}")
        elif iterations > 4:
            score -= 0.4
        
        # Token efficiency
        if tokens > 50000:
            score -= 0.3
            warnings.append(f"High token usage: {tokens}")
        elif tokens > 20000:
            score -= 0.1
        
        # Execution time
        if execution_ms > 30000:
            score -= 0.3
            warnings.append(f"Slow execution: {execution_ms}ms")
        elif execution_ms > 15000:
            score -= 0.1
        
        details["iterations"] = iterations
        details["tokens_used"] = tokens
        details["execution_time_ms"] = execution_ms
        
        return max(0.0, min(1.0, score))
    
    def _score_safety(
        self, response: str, tools: List[Dict], warnings: List, details: Dict
    ) -> float:
        """Score safety of the response."""
        score = 1.0
        
        # Check for PII patterns in response
        pii_patterns = [
            (r'\b\d{3}[-.]?\d{2}[-.]?\d{4}\b', "SSN-like pattern"),
            (r'\b(?:\d{4}[-\s]?){3}\d{4}\b', "Credit card-like pattern"),
            (r'(?:password|secret|token|api.?key)\s*[:=]\s*\S+', "Credential exposure"),
        ]
        
        for pattern, description in pii_patterns:
            if re.search(pattern, response, re.IGNORECASE):
                score -= 0.3
                warnings.append(f"Possible PII in response: {description}")
        
        details["safety_checks"] = len(pii_patterns)
        
        return max(0.0, min(1.0, score))


# Module-level singleton
quality_gate = QualityGate()
