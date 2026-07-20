import pytest
from src.core.runtime.registry import RuntimeToolRegistry
from src.core.runtime.exceptions import RuntimeAuthorizationError
from src.core.runtime.results import ToolOutput
from src.core.runtime.status import ExecutionStatus

class TestRunnerMockTool:
    name = "test_runner"
    def execute(self, request):
        return ToolOutput(status=ExecutionStatus.SUCCESS, output={})

def test_registry_registration():
    registry = RuntimeToolRegistry()
    registry._TOOLS.clear() # clear for testing
    tool = TestRunnerMockTool()
    registry.register(tool)
    
    assert registry.exists("test_runner") is True
    assert registry.get("test_runner") == tool

def test_duplicate_registration_rejected():
    registry = RuntimeToolRegistry()
    registry._TOOLS.clear()
    tool = TestRunnerMockTool()
    registry.register(tool)
    
    with pytest.raises(ValueError) as exc:
        registry.register(tool)
    assert "already registered" in str(exc.value)

def test_unknown_tool_rejection():
    registry = RuntimeToolRegistry()
    
    with pytest.raises(RuntimeAuthorizationError) as exc:
        registry.get("fake_tool")
    assert "Unknown runtime tool" in str(exc.value)
