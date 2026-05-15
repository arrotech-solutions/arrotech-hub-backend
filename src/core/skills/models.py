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

class SkillRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class EnvironmentScope(str, Enum):
    LOCAL = "local"
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"

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

class ToolPermission(BaseModel):
    tool_name: str
    read_only: bool = False

    model_config = {
        "extra": "forbid",
        "frozen": True
    }

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("tool_name cannot be empty")
        if not re.fullmatch(r"[a-z0-9_]+", cleaned):
            raise ValueError(
                "tool_name must contain only lowercase letters, numbers, and underscores"
            )
        return cleaned

class ExecutionConstraint(BaseModel):
    require_human_approval: bool = False
    allow_network_access: bool = False
    allow_file_mutation: bool = False
    allow_shell_execution: bool = False
    allowed_environments: List[EnvironmentScope]
    max_execution_time_ms: int = Field(
        default=30000,
        ge=1,
        le=300000
    )

    model_config = {
        "extra": "forbid",
        "frozen": True
    }

class SkillExecutionContract(BaseModel):
    allowed_tools: List[ToolPermission]
    forbidden_actions: List[str]
    required_validations: List[str]
    constraints: ExecutionConstraint
    risk_level: SkillRiskLevel
    contract_version: int = Field(ge=1)

    model_config = {
        "extra": "forbid",
        "frozen": True
    }

    @field_validator("forbidden_actions")
    @classmethod
    def validate_forbidden_actions(cls, actions: List[str]) -> List[str]:
        normalized = []
        seen = set()
        for action in actions:
            cleaned = action.strip().lower()
            if not cleaned:
                raise ValueError("Forbidden actions cannot contain empty entries")
            if cleaned in seen:
                raise ValueError(f"Duplicate forbidden action: {cleaned}")
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized

    @field_validator("required_validations")
    @classmethod
    def validate_required_validations(cls, validations: List[str]) -> List[str]:
        normalized = []
        seen = set()
        for val in validations:
            cleaned = val.strip().lower()
            if not cleaned:
                raise ValueError("Required validation entries cannot be empty")
            if cleaned in seen:
                raise ValueError(f"Duplicate required validation: {cleaned}")
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized

class SkillDefinition(BaseModel):
    name: str
    description: str
    capability: SkillCapability
    triggers: List[str]
    system_prompt: str
    protocol: SkillProtocol
    validation_rules: List[ValidationRule]
    execution_contract: SkillExecutionContract
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
