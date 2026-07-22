"""
Tests for the governed coding bridge, policy engine, and tool registry.
Validates that governance enforcement works correctly for all 27 registered tools.
"""
import pytest
from pathlib import Path

from src.core.skills.models import (
    EnvironmentScope,
    SkillCapability,
    SkillRiskLevel,
    SkillDefinition,
    SkillProtocol,
    ValidationRule,
    SkillExecutionContract,
    ExecutionConstraint,
    ToolPermission,
)
from src.core.skills.contracts import (
    RegisteredToolRegistry,
    ToolRiskLevel,
    GovernancePolicy,
    DEFAULT_POLICY,
    CODING_AGENT_POLICY,
    READ_ONLY_POLICY,
)
from src.core.skills.enforcer import SkillExecutionEnforcer
from src.core.skills.loader import load_skill
from src.core.skills.validators import validate_execution_contract
from src.core.skills.exceptions import SkillValidationError
from src.core.runtime.policy_engine import PolicyEngine
from src.core.runtime.governed_bridge import GovernedCodingBridge
from src.core.runtime.exceptions import (
    RuntimeGovernanceError,
    RuntimeAuthorizationError,
)


# ==================================================================
# TOOL REGISTRY TESTS
# ==================================================================

class TestToolRegistry:
    def test_all_27_tools_registered(self):
        """All registered tools (3 original + 24 coding + 3 planning) must be present."""
        tools = RegisteredToolRegistry.all()
        assert len(tools) == 30

    def test_original_tools_exist(self):
        assert RegisteredToolRegistry.exists("test_runner")
        assert RegisteredToolRegistry.exists("file_editor")
        assert RegisteredToolRegistry.exists("route_inspector")

    def test_coding_fs_tools_exist(self):
        fs_tools = [
            "coding_file_read", "coding_file_write", "coding_file_edit",
            "coding_file_delete", "coding_directory_list", "coding_file_search",
            "coding_grep_search", "coding_get_definition", "coding_read_file_summary",
            "coding_get_project_structure", "coding_write_scratchpad", "coding_read_scratchpad",
        ]
        for tool in fs_tools:
            assert RegisteredToolRegistry.exists(tool), f"Missing: {tool}"

    def test_coding_ops_tools_exist(self):
        ops_tools = [
            "coding_run_command", "coding_run_tests", "coding_install_dependencies",
            "coding_git_status", "coding_git_diff", "coding_git_commit",
            "coding_git_push", "coding_git_create_branch", "coding_git_read_log",
            "coding_github_create_pr", "coding_github_get_pr_status",
            "coding_github_get_check_logs",
        ]
        for tool in ops_tools:
            assert RegisteredToolRegistry.exists(tool), f"Missing: {tool}"

    def test_risk_levels_correct(self):
        # Read-only tools should be LOW
        assert RegisteredToolRegistry.get("coding_file_read").risk_level == ToolRiskLevel.LOW
        assert RegisteredToolRegistry.get("coding_grep_search").risk_level == ToolRiskLevel.LOW
        # File mutation tools should be MEDIUM
        assert RegisteredToolRegistry.get("coding_file_write").risk_level == ToolRiskLevel.MEDIUM
        # Delete should be HIGH
        assert RegisteredToolRegistry.get("coding_file_delete").risk_level == ToolRiskLevel.HIGH
        # Run command should be CRITICAL
        assert RegisteredToolRegistry.get("coding_run_command").risk_level == ToolRiskLevel.CRITICAL

    def test_coding_run_command_is_nondeterministic(self):
        tool = RegisteredToolRegistry.get("coding_run_command")
        assert tool.deterministic is False

    def test_by_risk_level_filter(self):
        critical = RegisteredToolRegistry.by_risk_level(ToolRiskLevel.CRITICAL)
        assert "coding_run_command" in critical

    def test_unknown_tool_raises(self):
        with pytest.raises(KeyError):
            RegisteredToolRegistry.get("nonexistent_tool")


# ==================================================================
# POLICY ENGINE TESTS
# ==================================================================

class TestPolicyEngine:
    def test_default_policy_permits_low_risk(self):
        # Should NOT raise
        PolicyEngine.evaluate(
            tool_name="coding_file_read",
            environment=EnvironmentScope.LOCAL,
            approved_by_human=False,
            policy=DEFAULT_POLICY,
        )

    def test_default_policy_blocks_high_risk(self):
        with pytest.raises(RuntimeGovernanceError, match="forbids tool"):
            PolicyEngine.evaluate(
                tool_name="coding_file_delete",
                environment=EnvironmentScope.LOCAL,
                approved_by_human=True,
                policy=DEFAULT_POLICY,
            )

    def test_default_policy_blocks_critical_risk(self):
        with pytest.raises(RuntimeGovernanceError, match="forbids tool"):
            PolicyEngine.evaluate(
                tool_name="coding_run_command",
                environment=EnvironmentScope.LOCAL,
                approved_by_human=True,
                policy=DEFAULT_POLICY,
            )

    def test_coding_agent_policy_permits_all_risk_with_approval(self):
        PolicyEngine.evaluate(
            tool_name="coding_run_command",
            environment=EnvironmentScope.LOCAL,
            approved_by_human=True,
            policy=CODING_AGENT_POLICY,
        )

    def test_coding_agent_policy_blocks_critical_without_approval(self):
        with pytest.raises(RuntimeGovernanceError, match="requires human approval"):
            PolicyEngine.evaluate(
                tool_name="coding_run_command",
                environment=EnvironmentScope.LOCAL,
                approved_by_human=False,
                policy=CODING_AGENT_POLICY,
            )

    def test_read_only_policy_blocks_shell(self):
        with pytest.raises(RuntimeGovernanceError, match="forbids tool"):
            PolicyEngine.evaluate(
                tool_name="coding_run_tests",
                environment=EnvironmentScope.LOCAL,
                approved_by_human=False,
                policy=READ_ONLY_POLICY,
            )

    def test_environment_enforcement(self):
        # coding_git_push only allowed in LOCAL and DEVELOPMENT
        with pytest.raises(RuntimeGovernanceError, match="not authorized for environment"):
            PolicyEngine.evaluate(
                tool_name="coding_git_push",
                environment=EnvironmentScope.STAGING,
                approved_by_human=True,
                policy=CODING_AGENT_POLICY,
            )

    def test_unknown_tool_rejected(self):
        with pytest.raises(RuntimeAuthorizationError, match="not registered"):
            PolicyEngine.evaluate(
                tool_name="evil_tool",
                environment=EnvironmentScope.LOCAL,
                approved_by_human=False,
            )

    def test_get_permitted_tools_filters_correctly(self):
        permitted = PolicyEngine.get_permitted_tools(READ_ONLY_POLICY)
        for tool in permitted:
            assert tool.risk_level == ToolRiskLevel.LOW
            assert tool.requires_shell is False
            assert tool.requires_network is False
            assert tool.mutates_files is False


# ==================================================================
# GOVERNANCE POLICY TESTS
# ==================================================================

class TestGovernancePolicy:
    def test_permits_tool_low_risk(self):
        tool = RegisteredToolRegistry.get("coding_file_read")
        assert DEFAULT_POLICY.permits_tool(tool) is True

    def test_blocks_tool_high_risk(self):
        tool = RegisteredToolRegistry.get("coding_file_delete")
        assert DEFAULT_POLICY.permits_tool(tool) is False

    def test_blocks_network_tool(self):
        tool = RegisteredToolRegistry.get("coding_git_push")
        assert DEFAULT_POLICY.permits_tool(tool) is False

    def test_coding_policy_permits_network(self):
        tool = RegisteredToolRegistry.get("coding_git_push")
        assert CODING_AGENT_POLICY.permits_tool(tool) is True


# ==================================================================
# GOVERNED BRIDGE TESTS
# ==================================================================

class TestGovernedBridge:
    def test_authorize_permits_allowed_tool(self):
        bridge = GovernedCodingBridge(
            policy=CODING_AGENT_POLICY,
            environment=EnvironmentScope.LOCAL,
            approved_by_human=True,
        )
        # Should not raise
        bridge.authorize("coding_file_read")

    def test_authorize_blocks_unknown_tool(self):
        bridge = GovernedCodingBridge(
            policy=CODING_AGENT_POLICY,
            environment=EnvironmentScope.LOCAL,
        )
        with pytest.raises(RuntimeAuthorizationError):
            bridge.authorize("evil_tool")

    def test_authorize_blocks_high_risk_without_approval(self):
        bridge = GovernedCodingBridge(
            policy=CODING_AGENT_POLICY,
            environment=EnvironmentScope.LOCAL,
            approved_by_human=False,
        )
        with pytest.raises(RuntimeGovernanceError, match="requires human approval"):
            bridge.authorize("coding_git_push")

    def test_authorize_permits_high_risk_with_approval(self):
        bridge = GovernedCodingBridge(
            policy=CODING_AGENT_POLICY,
            environment=EnvironmentScope.LOCAL,
            approved_by_human=True,
        )
        bridge.authorize("coding_git_push")

    def test_skill_contract_enforcement(self):
        """Bridge should reject tools not in the skill's allowed list."""
        skill = SkillDefinition(
            name="test_skill",
            description="Test",
            capability=SkillCapability.BACKEND,
            triggers=["test"],
            system_prompt="Test",
            protocol=SkillProtocol(
                execution_steps=["step"],
                review_steps=["review"],
                failure_recovery=["recover"],
            ),
            validation_rules=[ValidationRule(name="test_rule")],
            execution_contract=SkillExecutionContract(
                allowed_tools=[
                    ToolPermission(tool_name="coding_file_read", read_only=True),
                ],
                forbidden_actions=["delete"],
                required_validations=["test_rule"],
                constraints=ExecutionConstraint(
                    allowed_environments=[EnvironmentScope.LOCAL, EnvironmentScope.DEVELOPMENT],
                ),
                risk_level=SkillRiskLevel.LOW,
                contract_version=1,
            ),
        )

        bridge = GovernedCodingBridge(
            skill=skill,
            policy=CODING_AGENT_POLICY,
            environment=EnvironmentScope.LOCAL,
            approved_by_human=True,
        )

        # Allowed by skill contract
        bridge.authorize("coding_file_read")

        # NOT allowed by skill contract
        with pytest.raises(RuntimeAuthorizationError, match="not allowed by skill"):
            bridge.authorize("coding_file_write")


# ==================================================================
# SKILL MANIFEST LOADING TESTS
# ==================================================================

class TestSkillManifests:
    SKILLS_DIR = Path(__file__).resolve().parents[3] / "src" / "skills"

    def test_coding_read_loads(self):
        skill = load_skill(self.SKILLS_DIR / "coding_read" / "skill.yaml")
        assert skill.name == "coding_read"
        assert skill.execution_contract.risk_level == SkillRiskLevel.LOW

    def test_coding_write_loads(self):
        skill = load_skill(self.SKILLS_DIR / "coding_write" / "skill.yaml")
        assert skill.name == "coding_write"
        assert skill.execution_contract.risk_level == SkillRiskLevel.MEDIUM

    def test_coding_test_loads(self):
        skill = load_skill(self.SKILLS_DIR / "coding_test" / "skill.yaml")
        assert skill.name == "coding_test"

    def test_coding_git_loads(self):
        skill = load_skill(self.SKILLS_DIR / "coding_git" / "skill.yaml")
        assert skill.name == "coding_git"
        assert skill.execution_contract.constraints.require_human_approval is True

    def test_coding_github_loads(self):
        skill = load_skill(self.SKILLS_DIR / "coding_github" / "skill.yaml")
        assert skill.name == "coding_github"

    def test_coding_command_loads(self):
        skill = load_skill(self.SKILLS_DIR / "coding_command" / "skill.yaml")
        assert skill.name == "coding_command"
        assert skill.execution_contract.risk_level == SkillRiskLevel.CRITICAL

    def test_backend_api_loads(self):
        skill = load_skill(self.SKILLS_DIR / "backend_api" / "skill.yaml")
        assert skill.name == "backend_api"

    def test_testing_loads(self):
        skill = load_skill(self.SKILLS_DIR / "testing" / "skill.yaml")
        assert skill.name == "testing"


# ==================================================================
# ENFORCER TESTS
# ==================================================================

class TestEnforcer:
    def _make_skill(self, **kwargs):
        defaults = dict(
            name="test_skill",
            description="Test",
            capability=SkillCapability.BACKEND,
            triggers=["test"],
            system_prompt="Test",
            protocol=SkillProtocol(
                execution_steps=["s"], review_steps=["r"], failure_recovery=["f"],
            ),
            validation_rules=[ValidationRule(name="v")],
            execution_contract=SkillExecutionContract(
                allowed_tools=[
                    ToolPermission(tool_name="coding_file_read"),
                    ToolPermission(tool_name="coding_file_write"),
                ],
                forbidden_actions=["delete"],
                required_validations=["v"],
                constraints=ExecutionConstraint(
                    allowed_environments=[EnvironmentScope.LOCAL, EnvironmentScope.DEVELOPMENT],
                    allow_file_mutation=True,
                ),
                risk_level=SkillRiskLevel.MEDIUM,
                contract_version=1,
            ),
        )
        defaults.update(kwargs)
        return SkillDefinition(**defaults)

    def test_is_tool_allowed(self):
        skill = self._make_skill()
        assert SkillExecutionEnforcer.is_tool_allowed(skill, "coding_file_read") is True
        assert SkillExecutionEnforcer.is_tool_allowed(skill, "coding_run_command") is False

    def test_is_environment_allowed(self):
        skill = self._make_skill()
        assert SkillExecutionEnforcer.is_environment_allowed(skill, EnvironmentScope.LOCAL) is True
        assert SkillExecutionEnforcer.is_environment_allowed(skill, EnvironmentScope.PRODUCTION) is False

    def test_is_action_forbidden(self):
        skill = self._make_skill()
        assert SkillExecutionEnforcer.is_action_forbidden(skill, "delete") is True
        assert SkillExecutionEnforcer.is_action_forbidden(skill, "create") is False

    def test_validate_tool_against_policy(self):
        skill = self._make_skill()
        assert SkillExecutionEnforcer.validate_tool_against_policy(
            skill, "coding_file_read", DEFAULT_POLICY
        ) is True
        assert SkillExecutionEnforcer.validate_tool_against_policy(
            skill, "coding_run_command", DEFAULT_POLICY
        ) is False


# ==================================================================
# CONTRACT VALIDATION TESTS
# ==================================================================

class TestContractValidation:
    def test_nondeterministic_tool_requires_high_risk(self):
        """Non-deterministic tools must be in HIGH/CRITICAL risk skills."""
        contract = SkillExecutionContract(
            allowed_tools=[ToolPermission(tool_name="coding_run_command")],
            forbidden_actions=["x"],
            required_validations=["y"],
            constraints=ExecutionConstraint(
                allowed_environments=[EnvironmentScope.LOCAL, EnvironmentScope.DEVELOPMENT],
                allow_shell_execution=True,
                allow_file_mutation=True,
            ),
            risk_level=SkillRiskLevel.MEDIUM,  # Too low for non-deterministic
            contract_version=1,
        )
        with pytest.raises(SkillValidationError, match="non-deterministic"):
            validate_execution_contract(contract)

    def test_nondeterministic_tool_requires_human_approval(self):
        """Non-deterministic tools must require human approval."""
        contract = SkillExecutionContract(
            allowed_tools=[ToolPermission(tool_name="coding_run_command")],
            forbidden_actions=["x"],
            required_validations=["y"],
            constraints=ExecutionConstraint(
                allowed_environments=[EnvironmentScope.LOCAL, EnvironmentScope.DEVELOPMENT],
                allow_shell_execution=True,
                allow_file_mutation=True,
                require_human_approval=False,
            ),
            risk_level=SkillRiskLevel.CRITICAL,
            contract_version=1,
        )
        with pytest.raises(SkillValidationError, match="human approval"):
            validate_execution_contract(contract)
