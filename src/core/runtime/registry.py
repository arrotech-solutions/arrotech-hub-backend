import threading
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
        self._lock = threading.Lock()

    def register(self, tool: RuntimeTool) -> None:
        """Register a runtime tool. Forbids duplicate registrations and enforces governance."""
        name = tool.name.strip().lower()
        if not RegisteredToolRegistry.exists(name):
            raise RuntimeAuthorizationError(f"Tool {name} is not defined in governance registry")
            
        with self._lock:
            if name in self._TOOLS:
                raise ValueError(f"Runtime tool '{name}' is already registered.")
            self._TOOLS[name] = tool

    def get(self, name: str) -> RuntimeTool:
        """Get a registered runtime tool by name."""
        cleaned = name.strip().lower()
        with self._lock:
            if cleaned not in self._TOOLS:
                raise RuntimeAuthorizationError(f"Unknown runtime tool: {cleaned}")
            return self._TOOLS[cleaned]

    def exists(self, name: str) -> bool:
        """Check if a runtime tool is registered."""
        with self._lock:
            return name.strip().lower() in self._TOOLS

    def all(self) -> Dict[str, RuntimeTool]:
        """Get all registered runtime tools."""
        with self._lock:
            return self._TOOLS.copy()

    def _clear_for_testing_only(self) -> None:
        """Clear the registry (for testing only)."""
        with self._lock:
            self._TOOLS.clear()

# Global singleton for this phase
runtime_registry = RuntimeToolRegistry()

# ==============================================================================
# MOCK RUNTIME TOOLS (Deterministic, no real execution)
# ==============================================================================

from .status import ExecutionStatus
from src.core.skills.models import EnvironmentScope

class MockTestRunner:
    name = "test_runner"
    requires_shell = True
    requires_network = False
    mutates_files = False
    deterministic = True
    allowed_environments = [EnvironmentScope.LOCAL, EnvironmentScope.DEVELOPMENT, EnvironmentScope.STAGING]

    def execute(self, request: ToolExecutionRequest) -> ToolOutput:
        return ToolOutput(
            status=ExecutionStatus.SUCCESS,
            output={"status": "mocked test execution complete", "payload_received": request.payload}
        )

class MockFileEditor:
    name = "file_editor"
    requires_shell = False
    requires_network = False
    mutates_files = True
    deterministic = True
    allowed_environments = [EnvironmentScope.LOCAL, EnvironmentScope.DEVELOPMENT, EnvironmentScope.STAGING, EnvironmentScope.PRODUCTION]

    def execute(self, request: ToolExecutionRequest) -> ToolOutput:
        return ToolOutput(
            status=ExecutionStatus.SUCCESS,
            output={"status": "mocked file mutation complete", "payload_received": request.payload}
        )

class MockRouteInspector:
    name = "route_inspector"
    requires_shell = False
    requires_network = False
    mutates_files = False
    deterministic = True
    allowed_environments = [EnvironmentScope.LOCAL, EnvironmentScope.DEVELOPMENT, EnvironmentScope.STAGING, EnvironmentScope.PRODUCTION]

    def execute(self, request: ToolExecutionRequest) -> ToolOutput:
        return ToolOutput(
            status=ExecutionStatus.SUCCESS,
            output={"status": "mocked route inspection complete", "routes": []}
        )

# Pre-register mock tools for the runtime environment
runtime_registry.register(MockTestRunner())
runtime_registry.register(MockFileEditor())
runtime_registry.register(MockRouteInspector())
