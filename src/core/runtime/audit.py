from typing import List, Optional, Tuple
from datetime import datetime
import threading
from pydantic import BaseModel
from src.core.skills.models import EnvironmentScope

class ExecutionAuditRecord(BaseModel):
    skill_name: str
    tool_name: str
    timestamp: datetime
    execution_time_ms: int
    success: bool
    approved_by_human: bool
    environment: EnvironmentScope
    error_message: Optional[str] = None

    model_config = {
        "extra": "forbid",
        "frozen": True
    }

class RuntimeAuditLogger:
    """Append-only audit logger for runtime tool execution."""
    
    def __init__(self):
        self._records: List[ExecutionAuditRecord] = []
        self._lock = threading.Lock()

    def record(self, record: ExecutionAuditRecord) -> None:
        """Record an execution audit event."""
        with self._lock:
            self._records.append(record)

    def all(self) -> Tuple[ExecutionAuditRecord, ...]:
        """Get all recorded execution audit events."""
        with self._lock:
            return tuple(self._records)

    def clear_for_testing(self) -> None:
        """Clear all audit records (for testing purposes only)."""
        with self._lock:
            self._records.clear()

# Global singleton for simplicity in this phase
audit_logger = RuntimeAuditLogger()
