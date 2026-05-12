import re
from enum import Enum
from pydantic import BaseModel, Field, field_validator
from typing import List, Dict

class SkillCapability(str, Enum):
    BACKEND = "backend"
    FRONTEND = "frontend"
    TESTING = "testing"
    DEBUGGING = "debugging"
    REFACTORING = "refactoring"
    ARCHITECTURE = "architecture"
    OBSERVABILITY = "observability"
    SECURITY = "security"

class ValidationRule(BaseModel):
    name: str
    required: bool = True

    model_config = {
        "extra": "forbid",
        "frozen": True
    }

class SkillProtocol(BaseModel):
    execution_steps: List[str]
    review_steps: List[str]
    failure_recovery: List[str]

    model_config = {
        "extra": "forbid",
        "frozen": True
    }

class SkillDefinition(BaseModel):
    name: str
    description: str
    capability: SkillCapability
    triggers: List[str]
    system_prompt: str
    protocol: SkillProtocol
    validation_rules: List[ValidationRule]
    metadata: Dict[str, str] = Field(default_factory=dict)

    model_config = {
        "extra": "forbid",
        "frozen": True
    }

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9_]+", cleaned):
            raise ValueError(
                "Skill name must contain only lowercase "
                "letters, numbers, and underscores"
            )
        return cleaned

    @field_validator("triggers")
    @classmethod
    def validate_triggers(cls, triggers: List[str]) -> List[str]:
        normalized = []
        seen = set()
        for trigger in triggers:
            cleaned = trigger.strip().lower()
            if not cleaned:
                raise ValueError("Trigger entries cannot be empty")
            if cleaned in seen:
                raise ValueError(f"Duplicate trigger detected: {cleaned}")
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized
