from typing import Dict, Any, Optional
from pydantic import BaseModel

class ToolOutput(BaseModel):
    success: bool
    output: Dict[str, Any]
    error_message: Optional[str] = None

    model_config = {
        "extra": "forbid",
        "frozen": True
    }

class ToolExecutionResult(BaseModel):
    success: bool
    tool_name: str
    execution_time_ms: int
    output: Dict[str, Any]
    error_message: Optional[str] = None

    model_config = {
        "extra": "forbid",
        "frozen": True
    }
