"""
Architectural Guardrails — Preventive controls that constrain agent behavior.

These are the "taste invariants" from OpenAI's Harness Engineering: hard rules
that enforce safety, security, and quality before any action is taken. Unlike
post-hoc review, guardrails prevent bad outcomes proactively.

Guardrail layers:
1. Tool Access Control — Block tools the user can't access
2. Argument Sanitization — Detect injection attacks in tool arguments
3. Code Safety — AST analysis of LLM-generated code
4. Output Quality — Detect hallucinated tools, validate structure
5. Rate Guards — Per-user, per-tool limits within a conversation turn
"""

import ast
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GuardrailSeverity(str, Enum):
    """Severity level of a guardrail violation."""
    BLOCK = "block"          # Hard stop — action is prevented
    WARN = "warn"            # Allow but log a warning
    INFO = "info"            # Informational — no action needed


@dataclass
class GuardrailResult:
    """Result of a guardrail check."""
    passed: bool
    severity: GuardrailSeverity = GuardrailSeverity.INFO
    rule_name: str = ""
    reason: str = ""
    suggestion: str = ""     # Corrective suggestion for the LLM
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @staticmethod
    def ok() -> "GuardrailResult":
        return GuardrailResult(passed=True)
    
    @staticmethod
    def blocked(rule: str, reason: str, suggestion: str = "") -> "GuardrailResult":
        return GuardrailResult(
            passed=False,
            severity=GuardrailSeverity.BLOCK,
            rule_name=rule,
            reason=reason,
            suggestion=suggestion,
        )
    
    @staticmethod
    def warning(rule: str, reason: str) -> "GuardrailResult":
        return GuardrailResult(
            passed=True,
            severity=GuardrailSeverity.WARN,
            rule_name=rule,
            reason=reason,
        )


# Common prompt injection patterns
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"disregard\s+(all\s+)?prior",
    r"you\s+are\s+now\s+(?:a|an|the)",
    r"system\s*:\s*",
    r"<\s*/?system\s*>",
    r"(?:admin|root|sudo)\s+override",
    r"IMPORTANT:\s*ignore",
    r"\[\[SYSTEM\]\]",
]

# SQL injection patterns
SQL_PATTERNS = [
    r"(?:--|#|/\*)",
    r"(?:;\s*DROP|;\s*DELETE|;\s*UPDATE|;\s*INSERT)",
    r"(?:UNION\s+SELECT|OR\s+1\s*=\s*1|AND\s+1\s*=\s*1)",
    r"(?:'\s*OR\s+'|'\s*AND\s+')",
]


class AgentGuardrails:
    """
    Enforce invariants on agent-generated outputs.
    
    This class implements the "constraint harness" from OpenAI's methodology:
    rules that reduce the failure volume by limiting the agent's solution space.
    """
    
    def __init__(self):
        self._rate_tracker: Dict[str, Dict[str, Any]] = {}
    
    async def validate_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: Any,
        available_tools: List[str],
    ) -> GuardrailResult:
        """
        Pre-execution validation for a tool call.
        
        Runs all guardrail rules against a proposed tool call before execution.
        Returns BLOCK if any hard rule fails, WARN for soft violations.
        """
        # Rule 1: Tool existence check
        result = self._check_tool_exists(tool_name, available_tools)
        if not result.passed:
            return result
        
        # Rule 2: Argument sanitization (injection detection)
        result = self._check_argument_injection(tool_name, arguments)
        if not result.passed:
            return result
        
        # Rule 3: Rate limiting per tool per user
        result = self._check_rate_limit(tool_name, str(getattr(user, 'id', 'unknown')))
        if not result.passed:
            return result
        
        # Rule 4: Sensitive operation confirmation
        result = self._check_sensitive_operation(tool_name, arguments)
        if not result.passed:
            return result
        
        return GuardrailResult.ok()
    
    async def validate_code_output(self, code: str) -> GuardrailResult:
        """
        AST-level validation of LLM-generated code for Code Mode.
        
        This is an additional layer on top of the sandbox's own validation.
        Focuses on intent-level checks rather than syntax-level safety.
        """
        if not code or not code.strip():
            return GuardrailResult.blocked(
                "EMPTY_CODE",
                "Generated code is empty",
                "Please write Python code that performs the requested task."
            )
        
        # Check for suspiciously short code (likely hallucination)
        if len(code.strip()) < 10:
            return GuardrailResult.warning(
                "MINIMAL_CODE",
                f"Generated code is very short ({len(code.strip())} chars)"
            )
        
        # Check for infinite loop patterns
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.While):
                    # Check for `while True` without break
                    if isinstance(node.test, ast.Constant) and node.test.value is True:
                        has_break = any(
                            isinstance(n, ast.Break) for n in ast.walk(node)
                        )
                        if not has_break:
                            return GuardrailResult.blocked(
                                "INFINITE_LOOP",
                                "Detected 'while True' without a break statement",
                                "Add a break condition or use a for loop with a limit."
                            )
        except SyntaxError:
            pass  # Syntax errors handled by the sandbox
        
        return GuardrailResult.ok()
    
    async def validate_response(
        self,
        response: str,
        user_intent: str,
        tools_used: List[Dict[str, Any]],
    ) -> GuardrailResult:
        """
        Post-generation response quality check.
        
        Validates that the response meets minimum quality standards.
        """
        if not response or not response.strip():
            return GuardrailResult.blocked(
                "EMPTY_RESPONSE",
                "Agent generated an empty response",
                "Generate a response that addresses the user's request."
            )
        
        # Check for common hallucination markers
        hallucination_markers = [
            "I don't have access to",
            "I cannot actually",
            "As an AI, I",
            "I apologize, but I can't",
        ]
        
        has_tools = len(tools_used) > 0
        for marker in hallucination_markers:
            if marker.lower() in response.lower() and has_tools:
                return GuardrailResult.warning(
                    "POSSIBLE_HALLUCINATION",
                    f"Response contains '{marker}' despite having tool results"
                )
        
        return GuardrailResult.ok()
    
    def _check_tool_exists(
        self, tool_name: str, available_tools: List[str]
    ) -> GuardrailResult:
        """Verify the tool exists in the available tool set."""
        if tool_name not in available_tools:
            # Find closest match for suggestion
            closest = self._find_closest_tool(tool_name, available_tools)
            suggestion = f"Did you mean '{closest}'?" if closest else "Use search_tools() to find available tools."
            
            return GuardrailResult.blocked(
                "TOOL_NOT_FOUND",
                f"Tool '{tool_name}' does not exist or is not available to this user",
                suggestion
            )
        return GuardrailResult.ok()
    
    def _check_argument_injection(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> GuardrailResult:
        """Detect prompt injection and SQL injection in tool arguments."""
        for key, value in arguments.items():
            if not isinstance(value, str):
                continue
            
            # Check for prompt injection
            for pattern in INJECTION_PATTERNS:
                if re.search(pattern, value, re.IGNORECASE):
                    return GuardrailResult.blocked(
                        "PROMPT_INJECTION",
                        f"Possible prompt injection detected in argument '{key}'",
                        "Remove any instruction-like content from the argument value."
                    )
            
            # Check for SQL injection (only in query-like fields)
            if key in ("query", "search", "filter", "where", "sql", "search_query"):
                for pattern in SQL_PATTERNS:
                    if re.search(pattern, value, re.IGNORECASE):
                        return GuardrailResult.blocked(
                            "SQL_INJECTION",
                            f"Possible SQL injection detected in argument '{key}'",
                            "Use plain text search terms without SQL operators."
                        )
        
        return GuardrailResult.ok()
    
    def _check_rate_limit(
        self, tool_name: str, user_id: str, max_calls: int = 50, window_seconds: int = 60
    ) -> GuardrailResult:
        """Per-tool, per-user rate limiting within a conversation turn."""
        key = f"{user_id}:{tool_name}"
        now = time.time()
        
        if key not in self._rate_tracker:
            self._rate_tracker[key] = {"count": 0, "window_start": now}
        
        tracker = self._rate_tracker[key]
        
        # Reset window if expired
        if now - tracker["window_start"] > window_seconds:
            tracker["count"] = 0
            tracker["window_start"] = now
        
        tracker["count"] += 1
        
        if tracker["count"] > max_calls:
            return GuardrailResult.blocked(
                "RATE_LIMIT",
                f"Tool '{tool_name}' called {tracker['count']} times in {window_seconds}s (max {max_calls})",
                "Reduce the number of calls or batch operations together."
            )
        
        return GuardrailResult.ok()
    
    def _check_sensitive_operation(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> GuardrailResult:
        """Flag sensitive operations that might need extra scrutiny."""
        sensitive_patterns = {
            "delete": "Deletion operations are irreversible.",
            "remove": "Removal operations are irreversible.",
            "drop": "Drop operations are destructive.",
            "payment": "Payment operations involve financial transactions.",
            "transfer": "Transfer operations move data or money.",
        }
        
        name_lower = tool_name.lower()
        for pattern, warning_msg in sensitive_patterns.items():
            if pattern in name_lower:
                return GuardrailResult.warning(
                    "SENSITIVE_OPERATION",
                    f"Sensitive operation detected: {tool_name}. {warning_msg}"
                )
        
        return GuardrailResult.ok()
    
    def _find_closest_tool(self, name: str, available: List[str]) -> Optional[str]:
        """Find the closest matching tool name using simple edit distance."""
        if not available:
            return None
        
        best_match = None
        best_score = 0
        
        name_tokens = set(name.lower().replace(".", "_").split("_"))
        
        for tool in available:
            tool_tokens = set(tool.lower().replace(".", "_").split("_"))
            overlap = len(name_tokens & tool_tokens)
            if overlap > best_score:
                best_score = overlap
                best_match = tool
        
        return best_match if best_score > 0 else None


# Module-level singleton
agent_guardrails = AgentGuardrails()
