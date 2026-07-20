from .models import SkillDefinition, EnvironmentScope
from .contracts import GovernancePolicy, RegisteredToolRegistry


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
    def is_tool_read_only(skill: SkillDefinition, tool_name: str) -> bool:
        """Check if a tool is restricted to read-only by the skill contract."""
        target = tool_name.strip().lower()
        for perm in skill.execution_contract.allowed_tools:
            if perm.tool_name.strip().lower() == target:
                return perm.read_only
        return True  # Default to read-only if not found

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

    @staticmethod
    def is_environment_allowed(skill: SkillDefinition, environment: EnvironmentScope) -> bool:
        """Check if the skill is allowed to execute in a given environment."""
        return environment in skill.execution_contract.constraints.allowed_environments

    @staticmethod
    def is_action_forbidden(skill: SkillDefinition, action: str) -> bool:
        """Check if an action is in the skill's forbidden actions list."""
        return action.strip().lower() in skill.execution_contract.forbidden_actions

    @staticmethod
    def validate_tool_against_policy(
        skill: SkillDefinition,
        tool_name: str,
        policy: GovernancePolicy,
    ) -> bool:
        """
        Cross-validate a tool against both the skill contract AND the governance policy.
        Returns True only if BOTH permit the tool.
        """
        if not SkillExecutionEnforcer.is_tool_allowed(skill, tool_name):
            return False

        if not RegisteredToolRegistry.exists(tool_name):
            return False

        tool_def = RegisteredToolRegistry.get(tool_name)
        return policy.permits_tool(tool_def)
