import pytest
from pydantic import ValidationError
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


def _minimal_execution_contract() -> SkillExecutionContract:
    return SkillExecutionContract(
        allowed_tools=[ToolPermission(tool_name="coding_file_read", read_only=True)],
        forbidden_actions=[],
        required_validations=[],
        constraints=ExecutionConstraint(
            allowed_environments=[EnvironmentScope.DEVELOPMENT],
        ),
        risk_level=SkillRiskLevel.LOW,
        contract_version=1,
    )


def test_skill_name_normalization():
    skill = SkillDefinition(
        name="  Test_Skill  ",
        description="Desc",
        capability=SkillCapability.BACKEND,
        triggers=["test"],
        system_prompt="Prompt",
        protocol=SkillProtocol(execution_steps=[], review_steps=[], failure_recovery=[]),
        validation_rules=[],
        execution_contract=_minimal_execution_contract(),
    )
    assert skill.name == "test_skill"

def test_skill_name_invalid():
    with pytest.raises(ValueError) as exc:
        SkillDefinition(
            name="invalid-name!",
            description="Desc",
            capability=SkillCapability.BACKEND,
            triggers=["test"],
            system_prompt="Prompt",
            protocol=SkillProtocol(execution_steps=[], review_steps=[], failure_recovery=[]),
            validation_rules=[],
            execution_contract=_minimal_execution_contract(),
        )
    assert "only lowercase letters, numbers, and underscores" in str(exc.value)

def test_trigger_normalization_and_duplicates():
    # Duplicate triggers after normalization should fail
    with pytest.raises(ValueError) as exc:
        SkillDefinition(
            name="test",
            description="Desc",
            capability=SkillCapability.BACKEND,
            triggers=["  API  ", "api"],
            system_prompt="Prompt",
            protocol=SkillProtocol(execution_steps=[], review_steps=[], failure_recovery=[]),
            validation_rules=[],
            execution_contract=_minimal_execution_contract(),
        )
    assert "Duplicate trigger detected: api" in str(exc.value)

def test_empty_trigger():
    with pytest.raises(ValueError) as exc:
        SkillDefinition(
            name="test",
            description="Desc",
            capability=SkillCapability.BACKEND,
            triggers=["", " "],
            system_prompt="Prompt",
            protocol=SkillProtocol(execution_steps=[], review_steps=[], failure_recovery=[]),
            validation_rules=[],
            execution_contract=_minimal_execution_contract(),
        )
    assert "Trigger entries cannot be empty" in str(exc.value)
