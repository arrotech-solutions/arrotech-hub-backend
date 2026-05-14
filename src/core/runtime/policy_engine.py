"""
Policy Engine — Runtime governance policy enforcement.

Evaluates tool execution requests against active governance policies
BEFORE any tool is dispatched to the executor.
"""
from typing import Optional
from src.core.skills.models import SkillDefinition, EnvironmentScope
from src.core.skills.contracts import (
    GovernancePolicy,
    ToolDefinition,
    RegisteredToolRegistry,
    DEFAULT_POLICY,
    ToolRiskLevel,
)
from src.core.runtime.exceptions import (
    RuntimeGovernanceError,
    RuntimeAuthorizationError,
)


class PolicyEngine:
    """
    Stateless governance policy evaluator.

    Enforces:
    - Tool risk level boundaries
    - Capability constraints (shell, network, file mutation)
    - Environment authorization
    - Human approval gates for high/critical risk tools
    """

    @staticmethod
    def evaluate(
        tool_name: str,
        environment: EnvironmentScope,
        approved_by_human: bool,
        policy: GovernancePolicy = DEFAULT_POLICY,
    ) -> None:
        """
        Evaluate a tool execution request against a governance policy.

        Raises:
            RuntimeAuthorizationError: If the tool is unknown.
            RuntimeGovernanceError: If the policy forbids the tool or environment.
        """

        # 1. Tool must exist in governance registry
        if not RegisteredToolRegistry.exists(tool_name):
            raise RuntimeAuthorizationError(
                f"Tool '{tool_name}' is not registered in the governance registry."
            )

        tool_def = RegisteredToolRegistry.get(tool_name)

        # 2. Policy must permit the tool
        if not policy.permits_tool(tool_def):
            raise RuntimeGovernanceError(
                f"Policy '{policy.name}' forbids tool '{tool_name}' "
                f"(risk={tool_def.risk_level.value}, "
                f"shell={tool_def.requires_shell}, "
                f"network={tool_def.requires_network}, "
                f"mutates={tool_def.mutates_files})."
            )

        # 3. Environment must be in tool's allowed list
        if environment not in tool_def.allowed_environments:
            raise RuntimeGovernanceError(
                f"Tool '{tool_name}' is not authorized for "
                f"environment '{environment.value}'. "
                f"Allowed: {[e.value for e in tool_def.allowed_environments]}."
            )

        # 4. Human approval gate for HIGH and CRITICAL risk tools
        if tool_def.risk_level in (ToolRiskLevel.HIGH, ToolRiskLevel.CRITICAL):
            if policy.require_human_approval_for_high_risk and not approved_by_human:
                raise RuntimeGovernanceError(
                    f"Tool '{tool_name}' has risk level '{tool_def.risk_level.value}' "
                    f"and requires human approval under policy '{policy.name}'."
                )

    @staticmethod
    def get_permitted_tools(
        policy: GovernancePolicy,
        environment: Optional[EnvironmentScope] = None,
    ) -> list[ToolDefinition]:
        """
        Returns all tools permitted by a policy, optionally filtered by environment.
        """
        permitted = []
        for _name, tool_def in RegisteredToolRegistry.all().items():
            if not policy.permits_tool(tool_def):
                continue
            if environment is not None and environment not in tool_def.allowed_environments:
                continue
            permitted.append(tool_def)
        return permitted
