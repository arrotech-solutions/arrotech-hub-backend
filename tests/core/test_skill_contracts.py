import pytest
import yaml
from pathlib import Path
from pydantic import ValidationError
from src.core.skills.loader import load_skill
from src.core.skills.exceptions import SkillLoadError
from src.core.skills.contracts import RegisteredToolRegistry, GovernancePolicy, ToolDefinition
from src.core.skills.models import SkillDefinition, SkillCapability, SkillProtocol, SkillRiskLevel, SkillExecutionContract, ToolPermission

def create_valid_skill_data(name="test_skill", risk_level="medium", require_approval=False, contract_version=1, allow_shell=True, allow_net=False, allow_file=True):
    return {
        "name": name,
        "description": "Desc",
        "capability": "backend",
        "triggers": ["test"],
        "system_prompt": "Prompt",
        "protocol": {
            "execution_steps": [],
            "review_steps": [],
            "failure_recovery": []
        },
        "validation_rules": [],
        "execution_contract": {
            "contract_version": contract_version,
            "allowed_tools": [{"tool_name": "test_runner", "read_only": True}],
            "forbidden_actions": ["action1"],
            "required_validations": ["val1"],
            "constraints": {
                "require_human_approval": require_approval,
                "allow_network_access": allow_net,
                "allow_file_mutation": allow_file,
                "allow_shell_execution": allow_shell,
                "allowed_environments": ["development"]
            },
            "risk_level": risk_level
        }
    }

def test_tool_registry_returns_definition():
    tool = RegisteredToolRegistry.get("test_runner")
    assert isinstance(tool, ToolDefinition)
    assert tool.name == "test_runner"

def test_unknown_tool_raises_keyerror():
    with pytest.raises(KeyError):
        RegisteredToolRegistry.get("non_existent_tool")

def test_shell_incompatibility_rejected(tmp_path):
    # test_runner requires shell, so setting allow_shell_execution: false should fail
    data = create_valid_skill_data(allow_shell=False)
    skill_yaml = tmp_path / "skill.yaml"
    skill_yaml.write_text(yaml.dump(data))
    
    with pytest.raises(SkillLoadError) as exc:
        load_skill(skill_yaml)
    assert "Tool requires shell execution but contract forbids shell access" in str(exc.value)

def test_file_mutation_incompatibility_rejected(tmp_path):
    # file_editor mutates files, so setting allow_file_mutation: false should fail
    data = create_valid_skill_data(allow_file=False)
    data["execution_contract"]["allowed_tools"] = [{"tool_name": "file_editor"}]
    skill_yaml = tmp_path / "skill.yaml"
    skill_yaml.write_text(yaml.dump(data))
    
    with pytest.raises(SkillLoadError) as exc:
        load_skill(skill_yaml)
    assert "Tool requires file mutation but contract forbids file mutation" in str(exc.value)

def test_allowed_environments_persists(tmp_path):
    data = create_valid_skill_data()
    data["execution_contract"]["constraints"]["allowed_environments"] = ["development", "staging"]
    skill_yaml = tmp_path / "skill.yaml"
    skill_yaml.write_text(yaml.dump(data))
    
    skill = load_skill(skill_yaml)
    assert "development" in skill.execution_contract.constraints.allowed_environments
    assert "staging" in skill.execution_contract.constraints.allowed_environments

def test_governance_policy_immutability():
    from src.core.skills.contracts import DEFAULT_POLICY
    with pytest.raises(ValidationError):
        # This is a bit tricky with Pydantic frozen models, but assignment should fail
        DEFAULT_POLICY.allow_shell_execution = False

def test_tool_definition_immutability():
    tool = RegisteredToolRegistry.get("test_runner")
    with pytest.raises(ValidationError):
        tool.mutates_files = True
