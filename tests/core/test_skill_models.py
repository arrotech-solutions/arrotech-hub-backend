import pytest
from src.core.skills.models import SkillDefinition, SkillCapability, SkillProtocol

def test_skill_name_normalization():
    skill = SkillDefinition(
        name="  Test_Skill  ",
        description="Desc",
        capability=SkillCapability.BACKEND,
        triggers=["test"],
        system_prompt="Prompt",
        protocol=SkillProtocol(execution_steps=[], review_steps=[], failure_recovery=[]),
        validation_rules=[]
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
            validation_rules=[]
        )
    assert "only lowercase letters, numbers, and underscores" in str(exc.value)

def test_trigger_normalization_and_duplicates():
    skill = SkillDefinition(
        name="test",
        description="Desc",
        capability=SkillCapability.BACKEND,
        triggers=["  API  ", "api"],
    )
    # This should fail due to duplicates after normalization
    with pytest.raises(ValueError) as exc:
        SkillDefinition(
            name="test",
            description="Desc",
            capability=SkillCapability.BACKEND,
            triggers=["  API  ", "api"],
            system_prompt="Prompt",
            protocol=SkillProtocol(execution_steps=[], review_steps=[], failure_recovery=[]),
            validation_rules=[]
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
            validation_rules=[]
        )
    assert "Trigger entries cannot be empty" in str(exc.value)
