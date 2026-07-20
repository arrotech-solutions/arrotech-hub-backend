"""
Feedback Loops — Automated self-correction for agent errors.

Implements the "corrective controls" from OpenAI's Harness Engineering:
when an agent fails, the harness automatically classifies the error,
generates a corrective instruction, and retries — without human intervention.

This formalizes the error-feedback pattern already partially implemented in
ExecutionOrchestrator._execute_function_calling_loop (lines 536-550).
"""

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FeedbackAction(str, Enum):
    """Action to take after an error."""
    RETRY_WITH_FIX = "retry_with_fix"           # Retry with corrective instructions
    RETRY_DIFFERENT_TOOL = "retry_different_tool"  # Try a different tool
    ESCALATE_TO_USER = "escalate_to_user"        # Ask user for help
    ABANDON = "abandon"                           # Give up (max retries exceeded)


class ErrorCategory(str, Enum):
    """Classification of errors for feedback routing."""
    INVALID_ARGUMENTS = "invalid_arguments"      # Wrong params, missing required fields
    TOOL_NOT_FOUND = "tool_not_found"            # Hallucinated tool name
    AUTHENTICATION = "authentication"             # Auth/connection issues
    RATE_LIMIT = "rate_limit"                    # API rate limiting
    EXTERNAL_API = "external_api"                # Third-party API errors
    CODE_EXECUTION = "code_execution"            # Sandbox code errors
    VALIDATION = "validation"                    # Input validation failures
    TIMEOUT = "timeout"                          # Operation timed out
    UNKNOWN = "unknown"                          # Unclassified errors


@dataclass
class FeedbackResult:
    """Result of a feedback loop iteration."""
    action: FeedbackAction
    corrective_message: str = ""
    error_category: ErrorCategory = ErrorCategory.UNKNOWN
    retry_count: int = 0
    max_retries: int = 3
    metadata: Dict[str, Any] = field(default_factory=dict)


# Error patterns → category classification
ERROR_CLASSIFIERS = [
    (r"missing.*required.*(?:field|param|argument)", ErrorCategory.INVALID_ARGUMENTS),
    (r"invalid.*(?:type|format|value)", ErrorCategory.INVALID_ARGUMENTS),
    (r"(?:tool|function).*(?:not found|does not exist|unknown)", ErrorCategory.TOOL_NOT_FOUND),
    (r"(?:401|403|unauthorized|forbidden|authentication)", ErrorCategory.AUTHENTICATION),
    (r"(?:429|rate.?limit|too many requests|throttl)", ErrorCategory.RATE_LIMIT),
    (r"(?:500|502|503|504|server error|internal error)", ErrorCategory.EXTERNAL_API),
    (r"(?:timeout|timed? out|deadline exceeded)", ErrorCategory.TIMEOUT),
    (r"(?:syntax error|name.*error|type.*error|index.*error)", ErrorCategory.CODE_EXECUTION),
    (r"(?:validation|schema|constraint)", ErrorCategory.VALIDATION),
]


class FeedbackLoop:
    """
    Manages error feedback and iterative self-correction for agents.
    
    The feedback loop sits between the agent and the tool execution layer.
    When an error occurs, it:
    1. Classifies the error (what went wrong?)
    2. Determines the corrective action (retry, switch, escalate?)
    3. Generates a corrective message (instructions for the LLM to fix it)
    4. Tracks error patterns (detect systemic issues)
    """
    
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self._error_history: List[Dict[str, Any]] = []
        self._retry_counts: Dict[str, int] = {}  # tool_name → retry count
    
    async def handle_tool_error(
        self,
        tool_name: str,
        error: str,
        arguments: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> FeedbackResult:
        """
        Handle a tool execution error and determine corrective action.
        
        Args:
            tool_name: Name of the tool that failed
            error: Error message
            arguments: Arguments that caused the error
            context: Additional context (available tools, user info, etc.)
            
        Returns:
            FeedbackResult with action and corrective message
        """
        # Classify the error
        category = self._classify_error(error)
        
        # Track retry count
        retry_key = f"{tool_name}:{category.value}"
        self._retry_counts[retry_key] = self._retry_counts.get(retry_key, 0) + 1
        retry_count = self._retry_counts[retry_key]
        
        # Record in history
        self._error_history.append({
            "tool_name": tool_name,
            "error": error,
            "category": category.value,
            "retry_count": retry_count,
            "timestamp": time.time(),
        })
        
        # Check if max retries exceeded
        if retry_count > self.max_retries:
            return FeedbackResult(
                action=FeedbackAction.ABANDON,
                corrective_message=(
                    f"Tool '{tool_name}' has failed {retry_count} times. "
                    "Stopping retries. Inform the user about the issue and suggest alternatives."
                ),
                error_category=category,
                retry_count=retry_count,
                max_retries=self.max_retries,
            )
        
        # Generate corrective action based on category
        return self._generate_correction(
            tool_name, error, arguments, category, retry_count, context
        )
    
    async def handle_validation_failure(
        self,
        guardrail_result: Any,
        tool_name: str = "",
        arguments: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate a corrective prompt from a guardrail failure.
        
        Returns a message that can be injected into the conversation to guide
        the LLM toward a valid action.
        """
        rule = getattr(guardrail_result, 'rule_name', 'UNKNOWN')
        reason = getattr(guardrail_result, 'reason', 'Validation failed')
        suggestion = getattr(guardrail_result, 'suggestion', '')
        
        correction = f"⚠️ Your previous action was blocked by guardrail [{rule}]: {reason}"
        
        if suggestion:
            correction += f"\n💡 Suggestion: {suggestion}"
        
        if arguments:
            correction += f"\n📋 Arguments used: {arguments}"
        
        correction += "\nPlease fix the issue and try again."
        
        return correction
    
    async def handle_code_error(
        self,
        code: str,
        error: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> FeedbackResult:
        """
        Handle a Code Mode sandbox execution error.
        
        Generates a fix suggestion based on the error type.
        """
        category = self._classify_error(error)
        
        retry_key = f"code_execution:{category.value}"
        self._retry_counts[retry_key] = self._retry_counts.get(retry_key, 0) + 1
        retry_count = self._retry_counts[retry_key]
        
        if retry_count > self.max_retries:
            return FeedbackResult(
                action=FeedbackAction.ESCALATE_TO_USER,
                corrective_message=(
                    "Code execution has failed multiple times. "
                    "Consider using individual tool calls instead of Code Mode, "
                    "or ask the user for clarification."
                ),
                error_category=category,
                retry_count=retry_count,
                max_retries=self.max_retries,
            )
        
        # Generate code-specific fix suggestions
        fix_suggestion = self._generate_code_fix(error, code, category)
        
        return FeedbackResult(
            action=FeedbackAction.RETRY_WITH_FIX,
            corrective_message=fix_suggestion,
            error_category=category,
            retry_count=retry_count,
            max_retries=self.max_retries,
        )
    
    def get_error_patterns(self) -> List[Dict[str, Any]]:
        """
        Return error patterns for monitoring.
        
        Used by the harness dashboard to identify systemic issues.
        """
        if not self._error_history:
            return []
        
        # Group by tool + category
        patterns: Dict[str, Dict[str, Any]] = {}
        for entry in self._error_history:
            key = f"{entry['tool_name']}:{entry['category']}"
            if key not in patterns:
                patterns[key] = {
                    "tool_name": entry["tool_name"],
                    "category": entry["category"],
                    "count": 0,
                    "last_error": "",
                    "last_seen": 0,
                }
            patterns[key]["count"] += 1
            patterns[key]["last_error"] = entry["error"][:200]
            patterns[key]["last_seen"] = entry["timestamp"]
        
        return sorted(patterns.values(), key=lambda x: x["count"], reverse=True)
    
    def reset(self):
        """Reset retry counts for a new conversation turn."""
        self._retry_counts.clear()
    
    def _classify_error(self, error: str) -> ErrorCategory:
        """Classify an error message into a category."""
        error_lower = error.lower()
        
        for pattern, category in ERROR_CLASSIFIERS:
            if re.search(pattern, error_lower):
                return category
        
        return ErrorCategory.UNKNOWN
    
    def _generate_correction(
        self,
        tool_name: str,
        error: str,
        arguments: Dict[str, Any],
        category: ErrorCategory,
        retry_count: int,
        context: Optional[Dict[str, Any]] = None,
    ) -> FeedbackResult:
        """Generate a corrective action based on error category."""
        
        if category == ErrorCategory.INVALID_ARGUMENTS:
            return FeedbackResult(
                action=FeedbackAction.RETRY_WITH_FIX,
                corrective_message=(
                    f"Tool '{tool_name}' failed due to invalid arguments: {error}\n"
                    f"Arguments used: {arguments}\n"
                    "Please check the tool's schema and fix the arguments. "
                    "Use get_tool_schema() to inspect the expected parameters."
                ),
                error_category=category,
                retry_count=retry_count,
            )
        
        if category == ErrorCategory.TOOL_NOT_FOUND:
            return FeedbackResult(
                action=FeedbackAction.RETRY_DIFFERENT_TOOL,
                corrective_message=(
                    f"Tool '{tool_name}' was not found. "
                    "Use search_tools() to find the correct tool name, "
                    "then retry with the correct tool."
                ),
                error_category=category,
                retry_count=retry_count,
            )
        
        if category == ErrorCategory.AUTHENTICATION:
            return FeedbackResult(
                action=FeedbackAction.ESCALATE_TO_USER,
                corrective_message=(
                    f"Tool '{tool_name}' failed due to an authentication issue: {error}\n"
                    "The user may need to reconnect this integration. "
                    "Inform them and suggest going to the Connections page."
                ),
                error_category=category,
                retry_count=retry_count,
            )
        
        if category == ErrorCategory.RATE_LIMIT:
            return FeedbackResult(
                action=FeedbackAction.RETRY_WITH_FIX,
                corrective_message=(
                    f"Tool '{tool_name}' was rate-limited. "
                    "Wait a moment before retrying, or reduce the number of calls."
                ),
                error_category=category,
                retry_count=retry_count,
            )
        
        if category == ErrorCategory.EXTERNAL_API:
            return FeedbackResult(
                action=FeedbackAction.RETRY_WITH_FIX,
                corrective_message=(
                    f"Tool '{tool_name}' encountered an external API error: {error}\n"
                    f"This is a temporary issue. Retry the operation. (Attempt {retry_count}/{self.max_retries})"
                ),
                error_category=category,
                retry_count=retry_count,
            )
        
        if category == ErrorCategory.TIMEOUT:
            return FeedbackResult(
                action=FeedbackAction.RETRY_WITH_FIX,
                corrective_message=(
                    f"Tool '{tool_name}' timed out. Try simplifying the request "
                    "or breaking it into smaller operations."
                ),
                error_category=category,
                retry_count=retry_count,
            )
        
        # Default: generic retry
        return FeedbackResult(
            action=FeedbackAction.RETRY_WITH_FIX,
            corrective_message=(
                f"Tool '{tool_name}' failed with error: {error}\n"
                f"Please review and retry. (Attempt {retry_count}/{self.max_retries})"
            ),
            error_category=category,
            retry_count=retry_count,
        )
    
    def _generate_code_fix(
        self, error: str, code: str, category: ErrorCategory
    ) -> str:
        """Generate a fix suggestion for Code Mode errors."""
        
        if category == ErrorCategory.CODE_EXECUTION:
            return (
                f"Your code encountered an error: {error}\n"
                "Please fix the code and try again. Common issues:\n"
                "- Use 'await' before _call() or any tool API method\n"
                "- Assign your final output to the 'result' variable\n"
                "- Use try/except for error handling\n"
                "- Check variable names and types"
            )
        
        if "not allowed" in error.lower() or "security" in error.lower():
            return (
                f"Your code was blocked by a security check: {error}\n"
                "The sandbox does not allow:\n"
                "- File system access (os, pathlib, open)\n"
                "- Network access (requests, urllib, socket)\n"
                "- System commands (subprocess, os.system)\n"
                "- Dangerous operations (eval, exec, compile)\n"
                "Use only the provided tool API and standard library modules."
            )
        
        return (
            f"Code execution failed: {error}\n"
            "Please review the code and fix the issue. "
            "Make sure to use 'await' for async calls and assign output to 'result'."
        )
