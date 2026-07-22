import pytest
import yaml
from pathlib import Path
from src.core.skills.loader import load_skill
from src.core.skills.exceptions import SkillLoadError
from src.core.skills.models import SkillDefinition
from tests.core.skill_fixtures import make_skill_definition

def _skill_yaml_dict(**overrides):
    skill = make_skill_definition()
    data = skill.model_dump(mode="json")
    data.update(overrides)
    return data

def test_load_skill_valid(tmp_path):
    skill_yaml = tmp_path / "skill.yaml"
    content = _skill_yaml_dict(
        description="A test skill",
        protocol={
            "execution_steps": ["step1"],
            "review_steps": ["step2"],
            "failure_recovery": ["step3"],
        },
        validation_rules=[{"name": "rule1", "required": True}],
    )
    skill_yaml.write_text(yaml.dump(content))
    
    skill = load_skill(skill_yaml)
    assert skill.name == "test_skill"
    assert isinstance(skill, SkillDefinition)

def test_load_skill_malformed_yaml(tmp_path):
    skill_yaml = tmp_path / "skill.yaml"
    skill_yaml.write_text("name: : : :")
    
    with pytest.raises(SkillLoadError) as exc:
        load_skill(skill_yaml)
    assert "Malformed YAML" in str(exc.value)

def test_load_skill_unknown_field(tmp_path):
    skill_yaml = tmp_path / "skill.yaml"
    content = _skill_yaml_dict(
        description="A test skill",
        protocol={
            "execution_steps": ["step1"],
            "review_steps": ["step2"],
            "failure_recovery": ["step3"],
        },
        validation_rules=[{"name": "rule1", "required": True}],
        unknown_field="oops",
    )
    skill_yaml.write_text(yaml.dump(content))
    
    with pytest.raises(SkillLoadError) as exc:
        load_skill(skill_yaml)
    assert "validation failed" in str(exc.value)

def test_load_skill_missing_file():
    with pytest.raises(SkillLoadError) as exc:
        load_skill(Path("non_existent.yaml"))
    assert "not found" in str(exc.value)

def test_load_skill_empty_file(tmp_path):
    skill_yaml = tmp_path / "skill.yaml"
    skill_yaml.write_text("")
    
    with pytest.raises(SkillLoadError) as exc:
        load_skill(skill_yaml)
    assert "is empty" in str(exc.value)

def test_load_skill_directory_rejection(tmp_path):
    # Pass a directory path instead of a file path
    dir_path = tmp_path / "subdir"
    dir_path.mkdir()
    
    with pytest.raises(SkillLoadError) as exc:
        load_skill(dir_path)
    assert "is not a file" in str(exc.value)
