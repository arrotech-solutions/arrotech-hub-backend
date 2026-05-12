from .models import SkillDefinition

class SkillExecutionEnforcer:
    """
    Governance enforcement layer for skill execution.
    This class answers governance questions based on skill contracts.
    """
    
    @staticmethod
    def is_tool_allowed(skill: SkillDefinition, tool_name: str) -> bool:
        """Check if a tool is permitted by the skill contract."""
        target = tool_name.strip().lower()
        for perm in skill.execution_contract.allowed_tools:
            if perm.tool_name.strip().lower() == target:
                return True
        return False

    @staticmethod
    def requires_human_approval(skill: SkillDefinition) -> bool:
        """Check if the skill requires human approval for execution."""
        return skill.execution_contract.constraints.require_human_approval

    @staticmethod
    def can_mutate_files(skill: SkillDefinition) -> bool:
        """Check if the skill is allowed to mutate files."""
        return skill.execution_contract.constraints.allow_file_mutation

    @staticmethod
    def can_execute_shell(skill: SkillDefinition) -> bool:
        """Check if the skill is allowed to execute shell commands."""
        return skill.execution_contract.constraints.allow_shell_execution

    @staticmethod
    def can_access_network(skill: SkillDefinition) -> bool:
        """Check if the skill is allowed to access the network."""
        return skill.execution_contract.constraints.allow_network_access
