import pytest
from src.core.skills.registry import SkillRegistry
from src.core.skills.models import SkillDefinition, SkillCapability, SkillProtocol
from src.core.skills.exceptions import SkillValidationError, SkillNotFoundError

@pytest.fixture
def registry():
    reg = SkillRegistry()
    reg._clear_for_testing()
    return reg

@pytest.fixture
def mock_skill():
    return SkillDefinition(
        name="test_skill",
        description="A test skill",
        capability=SkillCapability.TESTING,
        triggers=["test"],
        system_prompt="Prompt",
        protocol=SkillProtocol(
            execution_steps=["step1"],
            review_steps=["step2"],
            failure_recovery=["step3"]
        ),
        validation_rules=[]
    )

def test_registry_register_and_get(registry, mock_skill):
    registry.register(mock_skill)
    assert registry.get("test_skill") == mock_skill
    assert mock_skill in registry.all()

def test_registry_duplicate_rejection(registry, mock_skill):
    registry.register(mock_skill)
    with pytest.raises(SkillValidationError) as exc:
        registry.register(mock_skill)
    assert "already registered" in str(exc.value)

def test_registry_get_missing(registry):
    with pytest.raises(SkillNotFoundError):
        registry.get("non_existent")

def test_registry_by_capability(registry, mock_skill):
    registry.register(mock_skill)
    backend_skill = mock_skill.model_copy(update={"name": "backend_skill", "capability": SkillCapability.BACKEND})
    registry.register(backend_skill)
    
    testing_skills = registry.by_capability(SkillCapability.TESTING)
    assert len(testing_skills) == 1
    assert testing_skills[0].name == "test_skill"
