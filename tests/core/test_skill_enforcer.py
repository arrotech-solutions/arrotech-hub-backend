import pytest
from src.core.skills.models import SkillDefinition, SkillCapability, SkillProtocol, SkillExecutionContract, ToolPermission, ExecutionConstraint, SkillRiskLevel
from src.core.skills.enforcer import SkillExecutionEnforcer

@pytest.fixture
def mock_skill():
    return SkillDefinition(
        name="test_skill",
        description="Desc",
        capability=SkillCapability.BACKEND,
        triggers=["test"],
        system_prompt="Prompt",
        protocol=SkillProtocol(execution_steps=[], review_steps=[], failure_recovery=[]),
        validation_rules=[],
        execution_contract=SkillExecutionContract(
            allowed_tools=[ToolPermission(tool_name="file_editor", read_only=False)],
            forbidden_actions=[],
            required_validations=[],
            constraints=ExecutionConstraint(
                require_human_approval=True,
                allow_network_access=False,
                allow_file_mutation=True,
                allow_shell_execution=False
            ),
            risk_level=SkillRiskLevel.MEDIUM
        )
    )

def test_enforcer_tool_permissions(mock_skill):
    assert SkillExecutionEnforcer.is_tool_allowed(mock_skill, "file_editor") is True
    assert SkillExecutionEnforcer.is_tool_allowed(mock_skill, "FILE_EDITOR") is True
    assert SkillExecutionEnforcer.is_tool_allowed(mock_skill, "shell_exec") is False

def test_enforcer_human_approval(mock_skill):
    assert SkillExecutionEnforcer.requires_human_approval(mock_skill) is True

def test_enforcer_file_mutation(mock_skill):
    assert SkillExecutionEnforcer.can_mutate_files(mock_skill) is True

def test_enforcer_shell_execution(mock_skill):
    assert SkillExecutionEnforcer.can_execute_shell(mock_skill) is False

def test_enforcer_network_access(mock_skill):
    assert SkillExecutionEnforcer.can_access_network(mock_skill) is False
