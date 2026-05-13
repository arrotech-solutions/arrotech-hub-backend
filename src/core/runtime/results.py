from typing import Optional
from pydantic import BaseModel, ConfigDict
from uuid import UUID
from .status import ExecutionStatus
from .governance import GovernanceDecision
from .version import RUNTIME_VERSION
from .types import ImmutableJSON

class ToolOutput(BaseModel):
    status: ExecutionStatus
    output: ImmutableJSON
    error_message: Optional[str] = None

    model_config = ConfigDict(
        frozen=True,
        extra="forbid"
    )

class ToolExecutionResult(BaseModel):
    status: ExecutionStatus
    governance_decision: GovernanceDecision
    tool_name: str
    execution_time_ms: int
    execution_id: UUID
    runtime_version: str = RUNTIME_VERSION
    output: ImmutableJSON
    error_message: Optional[str] = None

    model_config = ConfigDict(
        frozen=True,
        extra="forbid"
    )
