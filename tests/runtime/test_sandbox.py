import pytest
import uuid
from datetime import datetime, timezone
from src.core.runtime.sandbox import SandboxGovernance
from src.core.runtime.exceptions import RuntimeSandboxViolationError
from src.core.runtime.requests import ToolExecutionRequest
from src.core.skills.models import SkillDefinition, SkillCapability, SkillProtocol, SkillExecutionContract, ToolPermission, ExecutionConstraint, SkillRiskLevel, EnvironmentScope
from src.core.skills.contracts import ToolDefinition, ToolRiskLevel

def _mock_request(env=EnvironmentScope.DEVELOPMENT):
    return ToolExecutionRequest(
        skill_name="test_skill",
        tool_name="tool",
        payload={},
        environment=env,
        approved_by_human=False,
        timestamp=datetime.now(timezone.utc),
        execution_id=uuid.uuid4(),
    )

def create_mock_skill(allow_shell=False, allow_net=False, allow_file=False):
    return SkillDefinition(
        name="test_skill",
        description="Desc",
        capability=SkillCapability.BACKEND,
        triggers=["test"],
        system_prompt="Prompt",
        protocol=SkillProtocol(execution_steps=[], review_steps=[], failure_recovery=[]),
        validation_rules=[],
        execution_contract=SkillExecutionContract(
            contract_version=1,
            allowed_tools=[ToolPermission(tool_name="tool", read_only=False)],
            forbidden_actions=[],
            required_validations=[],
            constraints=ExecutionConstraint(
                require_human_approval=False,
                allow_network_access=allow_net,
                allow_file_mutation=allow_file,
                allow_shell_execution=allow_shell,
                allowed_environments=[EnvironmentScope.DEVELOPMENT]
            ),
            risk_level=SkillRiskLevel.MEDIUM
        )
    )

def create_mock_tool(requires_shell=False, requires_net=False, mutates_files=False):
    return ToolDefinition(
        name="tool",
        description="mock tool",
        risk_level=ToolRiskLevel.LOW,
        capabilities=[],
        mutates_files=mutates_files,
        requires_network=requires_net,
        requires_shell=requires_shell,
        allowed_environments=[EnvironmentScope.DEVELOPMENT],
    )

def test_sandbox_allows_valid_execution():
    skill = create_mock_skill(allow_shell=True, allow_net=True, allow_file=True)
    tool = create_mock_tool(requires_shell=True, requires_net=True, mutates_files=True)
    # Should not raise
    SandboxGovernance.validate(skill, tool, _mock_request())

def test_sandbox_rejects_shell():
    skill = create_mock_skill(allow_shell=False)
    tool = create_mock_tool(requires_shell=True)
    with pytest.raises(RuntimeSandboxViolationError) as exc:
        SandboxGovernance.validate(skill, tool, _mock_request())
    assert "requires shell access" in str(exc.value)

def test_sandbox_rejects_network():
    skill = create_mock_skill(allow_net=False)
    tool = create_mock_tool(requires_net=True)
    with pytest.raises(RuntimeSandboxViolationError) as exc:
        SandboxGovernance.validate(skill, tool, _mock_request())
    assert "requires network access" in str(exc.value)

def test_sandbox_rejects_file_mutation():
    skill = create_mock_skill(allow_file=False)
    tool = create_mock_tool(mutates_files=True)
    with pytest.raises(RuntimeSandboxViolationError) as exc:
        SandboxGovernance.validate(skill, tool, _mock_request())
    assert "mutates files" in str(exc.value)
