import re
from datetime import datetime
from typing import Dict, Any
from pydantic import BaseModel, field_validator
from src.core.skills.models import EnvironmentScope

class ToolExecutionRequest(BaseModel):
    skill_name: str
    tool_name: str
    payload: Dict[str, Any]
    environment: EnvironmentScope
    approved_by_human: bool = False
    timestamp: datetime

    model_config = {
        "extra": "forbid",
        "frozen": True
    }

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
