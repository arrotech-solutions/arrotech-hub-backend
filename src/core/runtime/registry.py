from typing import Dict
from .interfaces import RuntimeTool
from .requests import ToolExecutionRequest
from .results import ToolOutput
from .exceptions import RuntimeAuthorizationError
from src.core.skills.contracts import RegisteredToolRegistry

class RuntimeToolRegistry:
    """Registry for executable runtime tool implementations."""

    def __init__(self):
        self._TOOLS: Dict[str, RuntimeTool] = {}

    def register(self, tool: RuntimeTool) -> None:
        """Register a runtime tool. Forbids duplicate registrations and enforces governance."""
        name = tool.name.strip().lower()
        if not RegisteredToolRegistry.exists(name):
            raise RuntimeAuthorizationError(f"Tool {name} is not defined in governance registry")
        if name in self._TOOLS:
            raise ValueError(f"Runtime tool '{name}' is already registered.")
        self._TOOLS[name] = tool

    def get(self, name: str) -> RuntimeTool:
        """Get a registered runtime tool by name."""
        cleaned = name.strip().lower()
        if cleaned not in self._TOOLS:
            raise RuntimeAuthorizationError(f"Unknown runtime tool: {cleaned}")
        return self._TOOLS[cleaned]

    def exists(self, name: str) -> bool:
        """Check if a runtime tool is registered."""
        return name.strip().lower() in self._TOOLS

    def all(self) -> Dict[str, RuntimeTool]:
        """Get all registered runtime tools."""
        return self._TOOLS.copy()

    def clear_for_testing(self) -> None:
        """Clear the registry (for testing only)."""
        self._TOOLS.clear()

# Global singleton for this phase
runtime_registry = RuntimeToolRegistry()

# ==============================================================================
# MOCK RUNTIME TOOLS (Deterministic, no real execution)
# ==============================================================================

class MockTestRunner:
    name = "test_runner"

    def execute(self, request: ToolExecutionRequest) -> ToolOutput:
        return ToolOutput(
            success=True,
            output={"status": "mocked test execution complete", "payload_received": request.payload}
        )

class MockFileEditor:
    name = "file_editor"

    def execute(self, request: ToolExecutionRequest) -> ToolOutput:
        return ToolOutput(
            success=True,
            output={"status": "mocked file mutation complete", "payload_received": request.payload}
        )

class MockRouteInspector:
    name = "route_inspector"

    def execute(self, request: ToolExecutionRequest) -> ToolOutput:
        return ToolOutput(
            success=True,
            output={"status": "mocked route inspection complete", "routes": []}
        )

# Pre-register mock tools for the runtime environment
runtime_registry.register(MockTestRunner())
runtime_registry.register(MockFileEditor())
runtime_registry.register(MockRouteInspector())
