from typing import Protocol, List
from .requests import ToolExecutionRequest
from .results import ToolOutput
from src.core.skills.models import EnvironmentScope

class RuntimeTool(Protocol):
    name: str
    requires_shell: bool
    requires_network: bool
    mutates_files: bool
    deterministic: bool
    allowed_environments: List[EnvironmentScope]

    def execute(self, request: ToolExecutionRequest) -> ToolOutput:
        ...
