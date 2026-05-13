from typing import Dict, Any, Optional
from pydantic import BaseModel
from uuid import UUID
from .status import ExecutionStatus
from .governance import GovernanceDecision
from .version import RUNTIME_VERSION

class ToolOutput(BaseModel):
    status: ExecutionStatus
    output: Dict[str, Any]
    error_message: Optional[str] = None

    model_config = {
        "extra": "forbid",
        "frozen": True
    }

class ToolExecutionResult(BaseModel):
    status: ExecutionStatus
    governance_decision: GovernanceDecision
    tool_name: str
    execution_time_ms: int
    execution_id: UUID
    runtime_version: str = RUNTIME_VERSION
    output: Dict[str, Any]
    error_message: Optional[str] = None

    model_config = {
        "extra": "forbid",
        "frozen": True
    }
