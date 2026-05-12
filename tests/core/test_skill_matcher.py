import pytest
from src.core.skills.matcher import match_skills
from src.core.skills.registry import SkillRegistry
from src.core.skills.models import SkillDefinition, SkillCapability, SkillProtocol

@pytest.fixture
def registry():
    reg = SkillRegistry()
    reg._clear_for_testing()
    
    # Register some skills for matching
    skill1 = SkillDefinition(
        name="testing",
        description="Testing skill",
        capability=SkillCapability.TESTING,
        triggers=["test", "unit test"],
        system_prompt="Prompt",
        protocol=SkillProtocol(execution_steps=[], review_steps=[], failure_recovery=[]),
        validation_rules=[]
    )
    skill2 = SkillDefinition(
        name="api",
        description="API skill",
        capability=SkillCapability.BACKEND,
        triggers=["api", "endpoint"],
        system_prompt="Prompt",
        protocol=SkillProtocol(execution_steps=[], review_steps=[], failure_recovery=[]),
        validation_rules=[]
    )
    
    reg.register(skill1)
    reg.register(skill2)
    return reg

def test_match_skills_lexical(registry):
    # Matches "test" twice and "api" once
    task = "I need to run a test and another unit test for the api."
    matches = match_skills(task, registry)
    
    assert len(matches) == 2
    assert matches[0].name == "testing"  # Higher score (2 triggers)
    assert matches[1].name == "api"      # Lower score (1 trigger)

def test_match_skills_case_insensitive(registry):
    task = "TEST the API"
    matches = match_skills(task, registry)
    
    assert len(matches) == 2
    assert matches[0].name == "testing"
    assert matches[1].name == "api"

def test_match_skills_no_match(registry):
    task = "Just a random task"
    matches = match_skills(task, registry)
    assert matches == []

def test_match_skills_empty_task(registry):
    matches = match_skills("", registry)
    assert matches == []

def test_match_skills_word_boundary(registry):
    # "contest" contains "test" but should not match due to \b boundary
    task = "This is a contest."
    matches = match_skills(task, registry)
    assert matches == []
    
    task = "This is a test."
    matches = match_skills(task, registry)
    assert len(matches) == 1
    assert matches[0].name == "testing"
