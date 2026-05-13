from src.core.skills.models import SkillDefinition
from src.core.skills.contracts import ToolDefinition
from .exceptions import RuntimeGovernanceError

class SandboxGovernance:
    """Enforces sandbox governance rules before tool execution."""

    @staticmethod
    def validate(skill: SkillDefinition, tool: ToolDefinition) -> None:
        """
        Validate that the requested tool's capabilities do not exceed 
        the skill's execution contract constraints.
        
        Args:
            skill: The skill definition containing the execution contract.
            tool: The definition of the tool being requested.
            
        Raises:
            RuntimeGovernanceError: If the tool violates the sandbox constraints.
        """
        constraints = skill.execution_contract.constraints

        if tool.requires_shell and not constraints.allow_shell_execution:
            raise RuntimeGovernanceError(
                f"Sandbox violation: Tool '{tool.name}' requires shell access, "
                f"but contract forbids it."
            )

        if tool.requires_network and not constraints.allow_network_access:
            raise RuntimeGovernanceError(
                f"Sandbox violation: Tool '{tool.name}' requires network access, "
                f"but contract forbids it."
            )

        if tool.mutates_files and not constraints.allow_file_mutation:
            raise RuntimeGovernanceError(
                f"Sandbox violation: Tool '{tool.name}' mutates files, "
                f"but contract forbids it."
            )
