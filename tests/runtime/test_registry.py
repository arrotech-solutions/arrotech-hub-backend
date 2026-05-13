import pytest
from src.core.runtime.registry import RuntimeToolRegistry, MockTestRunner
from src.core.runtime.exceptions import RuntimeAuthorizationError
from src.core.runtime.interfaces import RuntimeTool
from src.core.runtime.results import ToolExecutionResult

class AnotherMockTool:
    name = "another_mock"
    def execute(self, request):
        return ToolExecutionResult(success=True, tool_name=self.name, execution_time_ms=1, output={})

def test_registry_registration():
    registry = RuntimeToolRegistry()
    tool = AnotherMockTool()
    registry.register(tool)
    
    assert registry.exists("another_mock") is True
    assert registry.get("another_mock") == tool

def test_duplicate_registration_rejected():
    registry = RuntimeToolRegistry()
    tool = AnotherMockTool()
    registry.register(tool)
    
    with pytest.raises(ValueError) as exc:
        registry.register(tool)
    assert "already registered" in str(exc.value)

def test_unknown_tool_rejection():
    registry = RuntimeToolRegistry()
    
    with pytest.raises(RuntimeAuthorizationError) as exc:
        registry.get("fake_tool")
    assert "Unknown runtime tool" in str(exc.value)
