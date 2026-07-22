"""Shared SkillDefinition fixtures for core skill tests."""
from src.core.skills.models import (
    SkillDefinition,
    SkillCapability,
    SkillProtocol,
    SkillExecutionContract,
    ExecutionConstraint,
    ToolPermission,
    SkillRiskLevel,
    EnvironmentScope,
)


def make_skill_definition(
    *,
    name: str = "test_skill",
    capability: SkillCapability = SkillCapability.BACKEND,
    triggers=None,
) -> SkillDefinition:
    return SkillDefinition(
        name=name,
        description="Test skill",
        capability=capability,
        triggers=triggers or ["test"],
        system_prompt="Prompt",
        protocol=SkillProtocol(
            execution_steps=[],
            review_steps=[],
            failure_recovery=[],
        ),
        validation_rules=[],
        execution_contract=SkillExecutionContract(
            allowed_tools=[ToolPermission(tool_name="coding_file_read", read_only=True)],
            forbidden_actions=[],
            required_validations=[],
            constraints=ExecutionConstraint(
                allowed_environments=[
                    EnvironmentScope.LOCAL,
                    EnvironmentScope.DEVELOPMENT,
                ],
            ),
            risk_level=SkillRiskLevel.LOW,
            contract_version=1,
        ),
    )
