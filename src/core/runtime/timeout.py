"""
Execution Timeout Enforcement — Pre-execution budget enforcement.

Wraps async tool execution with asyncio.wait_for to enforce
hard time limits BEFORE the tool returns, not after.

This prevents runaway commands from holding the execution
pipeline hostage indefinitely.
"""
import asyncio
import logging
from typing import Any, Callable, Coroutine, Optional

from src.core.runtime.exceptions import RuntimeTimeoutError

logger = logging.getLogger(__name__)

# Default timeout budgets per risk level (in seconds)
DEFAULT_TIMEOUTS = {
    "low": 30,
    "medium": 60,
    "high": 120,
    "critical": 300,
}


async def execute_with_timeout(
    coroutine: Coroutine,
    timeout_seconds: int,
    tool_name: str = "unknown",
) -> Any:
    """
    Execute a coroutine with a hard timeout.

    Args:
        coroutine: The async function to execute
        timeout_seconds: Maximum seconds to allow
        tool_name: Tool name for error messages

    Returns:
        The coroutine result

    Raises:
        RuntimeTimeoutError: If execution exceeds the timeout
    """
    try:
        result = await asyncio.wait_for(coroutine, timeout=timeout_seconds)
        return result
    except asyncio.TimeoutError:
        raise RuntimeTimeoutError(
            f"Tool '{tool_name}' exceeded {timeout_seconds}s timeout. "
            f"Execution was forcibly terminated."
        )


def get_timeout_for_risk(risk_level: str) -> int:
    """Get the default timeout for a tool's risk level."""
    return DEFAULT_TIMEOUTS.get(risk_level, DEFAULT_TIMEOUTS["medium"])


class TimeoutBudget:
    """
    Manages a time budget for a sequence of tool executions.

    Usage:
        budget = TimeoutBudget(total_seconds=300)

        remaining = budget.remaining
        result = await execute_with_timeout(tool(), remaining, "my_tool")
        budget.consume(elapsed_ms)

        if budget.expired:
            raise RuntimeTimeoutError("Budget exhausted")
    """

    def __init__(self, total_seconds: int = 600):
        self._total = total_seconds
        self._consumed_ms = 0

    @property
    def remaining(self) -> int:
        """Remaining seconds in the budget."""
        remaining = self._total - (self._consumed_ms / 1000)
        return max(0, int(remaining))

    @property
    def expired(self) -> bool:
        """Whether the budget is exhausted."""
        return self.remaining <= 0

    @property
    def consumed_ms(self) -> int:
        return self._consumed_ms

    def consume(self, elapsed_ms: int) -> None:
        """Record time consumed by a tool execution."""
        self._consumed_ms += elapsed_ms

    def to_dict(self):
        return {
            "total_seconds": self._total,
            "consumed_ms": self._consumed_ms,
            "remaining_seconds": self.remaining,
            "expired": self.expired,
        }
