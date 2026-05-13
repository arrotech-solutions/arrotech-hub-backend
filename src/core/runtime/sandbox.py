from src.core.skills.models import SkillDefinition
from src.core.skills.contracts import ToolDefinition
from src.core.runtime.requests import ToolExecutionRequest
from .exceptions import RuntimeSandboxViolationError, RuntimeEnvironmentError

class SandboxGovernance:
    """Enforces sandbox governance rules before tool execution."""

    @staticmethod
    def validate(skill: SkillDefinition, tool: ToolDefinition, request: ToolExecutionRequest) -> None:
        """
        Validate that the requested tool's capabilities do not exceed 
        the skill's execution contract constraints and environment policies.
        """
        constraints = skill.execution_contract.constraints

        if request.environment not in tool.allowed_environments:
            raise RuntimeEnvironmentError(
                f"Sandbox violation: Tool '{tool.name}' is not authorized "
                f"to execute in environment '{request.environment.value}'."
            )

        if tool.requires_shell and not constraints.allow_shell_execution:
            raise RuntimeSandboxViolationError(
                f"Sandbox violation: Tool '{tool.name}' requires shell access, "
                f"but contract forbids it."
            )

        if tool.requires_network and not constraints.allow_network_access:
            raise RuntimeSandboxViolationError(
                f"Sandbox violation: Tool '{tool.name}' requires network access, "
                f"but contract forbids it."
            )

        if tool.mutates_files and not constraints.allow_file_mutation:
            raise RuntimeSandboxViolationError(
                f"Sandbox violation: Tool '{tool.name}' mutates files, "
                f"but contract forbids it."
            )
