from typing import Protocol
from .requests import ToolExecutionRequest
from .results import ToolOutput

class RuntimeTool(Protocol):
    name: str

    def execute(self, request: ToolExecutionRequest) -> ToolOutput:
        ...
