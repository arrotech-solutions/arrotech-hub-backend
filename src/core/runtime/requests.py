import re
import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, field_validator, field_serializer, Field, ConfigDict
from src.core.skills.models import EnvironmentScope
from .version import RUNTIME_VERSION
from .immutability import freeze_structure, thaw_structure, validate_json_safe_payload
from .types import ImmutableJSON

class ToolExecutionRequest(BaseModel):
    skill_name: str
    tool_name: str
    payload: ImmutableJSON
    environment: EnvironmentScope
    approved_by_human: bool = False
    timestamp: datetime
    execution_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    runtime_version: str = RUNTIME_VERSION

    model_config = ConfigDict(
        frozen=True,
        extra="forbid"
    )

    @field_validator("payload", mode="before")
    @classmethod
    def validate_payload_types(cls, value: Any) -> Any:
        validate_json_safe_payload(value)
        return value

    @field_validator("payload", mode="after")
    @classmethod
    def freeze_payload(cls, value: Any) -> Any:
        return freeze_structure(value)

    @field_serializer("payload")
    def serialize_payload(self, value: Any) -> Any:
        return thaw_structure(value)

    @field_validator("skill_name", "tool_name")
    @classmethod
    def validate_names(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("Name cannot be empty")
        if not re.fullmatch(r"[a-z0-9_]+", cleaned):
            raise ValueError(
                "Name must contain only lowercase letters, numbers, and underscores"
            )
        return cleaned
