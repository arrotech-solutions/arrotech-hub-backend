import pytest
from datetime import datetime, timezone
from src.core.runtime.executor import GovernedToolExecutor
from src.core.runtime.requests import ToolExecutionRequest
from src.core.runtime.exceptions import RuntimeAuthorizationError, RuntimeGovernanceError
from src.core.runtime.registry import runtime_registry
from src.core.runtime.audit import audit_logger
from src.core.runtime.status import ExecutionStatus
import uuid
from src.core.skills.models import SkillDefinition, SkillCapability, SkillProtocol, SkillExecutionContract, ToolPermission, ExecutionConstraint, SkillRiskLevel, EnvironmentScope

@pytest.fixture
def skill():
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
            allowed_tools=[ToolPermission(tool_name="test_runner", read_only=False)],
            forbidden_actions=[],
            required_validations=[],
            constraints=ExecutionConstraint(
                require_human_approval=False,
                allow_network_access=False,
                allow_file_mutation=False,
                allow_shell_execution=True,  # test_runner requires shell
                allowed_environments=[EnvironmentScope.DEVELOPMENT]
            ),
            risk_level=SkillRiskLevel.MEDIUM
        )
    )

@pytest.fixture
def executor():
    return GovernedToolExecutor()

@pytest.fixture(autouse=True)
def setup_audit():
    audit_logger._clear_for_testing_only()
    yield

def test_successful_execution(skill, executor):
    request = ToolExecutionRequest(
        skill_name="test_skill",
        tool_name="test_runner",
        payload={"param": "value"},
        environment=EnvironmentScope.DEVELOPMENT,
        approved_by_human=False,
        timestamp=datetime.now(timezone.utc)
    )
    
    result = executor.execute(skill, request)
    assert result.status == ExecutionStatus.SUCCESS
    assert result.tool_name == "test_runner"
    
    # Verify audit
    records = audit_logger.all()
    assert len(records) == 1
    assert records[0].status == ExecutionStatus.SUCCESS
    assert records[0].tool_name == "test_runner"

def test_unregistered_runtime_tool(skill, executor):
    request = ToolExecutionRequest(
        skill_name="test_skill",
        tool_name="fake_tool",
        payload={},
        environment=EnvironmentScope.DEVELOPMENT,
        approved_by_human=False,
        timestamp=datetime.now(timezone.utc)
    )
    
    with pytest.raises(RuntimeAuthorizationError) as exc:
        executor.execute(skill, request)
    assert "not registered" in str(exc.value)
    
    # Failed execution should still be audited
    records = audit_logger.all()
    assert len(records) == 1
    assert records[0].status == ExecutionStatus.DENIED

def test_unauthorized_tool_by_contract(skill, executor):
    # route_inspector is registered but not in the skill's allowed_tools
    request = ToolExecutionRequest(
        skill_name="test_skill",
        tool_name="route_inspector",
        payload={},
        environment=EnvironmentScope.DEVELOPMENT,
        approved_by_human=False,
        timestamp=datetime.now(timezone.utc)
    )
    
    with pytest.raises(RuntimeAuthorizationError) as exc:
        executor.execute(skill, request)
    assert "not allowed by skill" in str(exc.value)

def test_environment_rejection(skill, executor):
    request = ToolExecutionRequest(
        skill_name="test_skill",
        tool_name="test_runner",
        payload={},
        environment=EnvironmentScope.PRODUCTION, # Not allowed by skill
        approved_by_human=False,
        timestamp=datetime.now(timezone.utc)
    )
    
    with pytest.raises(RuntimeGovernanceError) as exc:
        executor.execute(skill, request)
    assert "not authorized to execute in environment" in str(exc.value)

def test_approval_rejection(executor):
    skill = SkillDefinition(
        name="test_skill",
        description="Desc",
        capability=SkillCapability.BACKEND,
        triggers=["test"],
        system_prompt="Prompt",
        protocol=SkillProtocol(execution_steps=[], review_steps=[], failure_recovery=[]),
        validation_rules=[],
        execution_contract=SkillExecutionContract(
            contract_version=1,
            allowed_tools=[ToolPermission(tool_name="test_runner", read_only=False)],
            forbidden_actions=[],
            required_validations=[],
            constraints=ExecutionConstraint(
                require_human_approval=True, # Requires approval
                allow_network_access=False,
                allow_file_mutation=False,
                allow_shell_execution=True,
                allowed_environments=[EnvironmentScope.DEVELOPMENT]
            ),
            risk_level=SkillRiskLevel.MEDIUM
        )
    )
    
    request = ToolExecutionRequest(
        skill_name="test_skill",
        tool_name="test_runner",
        payload={},
        environment=EnvironmentScope.DEVELOPMENT,
        approved_by_human=False, # Missing approval
        timestamp=datetime.now(timezone.utc)
    )
    
    with pytest.raises(RuntimeAuthorizationError) as exc:
        executor.execute(skill, request)
    assert "requires human approval" in str(exc.value)
