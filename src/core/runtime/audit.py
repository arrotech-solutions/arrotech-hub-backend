from typing import List, Optional, Tuple, Dict, Any
from types import MappingProxyType
from datetime import datetime
from uuid import UUID
import threading
import hashlib
import json
from pydantic import BaseModel
from src.core.skills.models import EnvironmentScope
from .status import ExecutionStatus
from .governance import GovernanceDecision
from .version import RUNTIME_VERSION
from .audit_store import AuditStore, InMemoryAuditStore

class ExecutionAuditRecord(BaseModel):
    skill_name: str
    tool_name: str
    timestamp: datetime
    execution_time_ms: int
    status: ExecutionStatus
    governance_decision: GovernanceDecision
    execution_id: UUID
    runtime_version: str = RUNTIME_VERSION
    approved_by_human: bool
    environment: EnvironmentScope
    output: Optional[Dict[str, Any]] = None
    record_hash: Optional[str] = None
    previous_record_hash: Optional[str] = None
    error_message: Optional[str] = None

    model_config = {
        "extra": "forbid",
        "frozen": True
    }

def _canonicalize_json(obj: Any) -> Any:
    """Issue 2: Deterministic recursive canonicalization."""
    if isinstance(obj, (dict, MappingProxyType)):
        return {k: _canonicalize_json(v) for k, v in sorted(obj.items())}
    elif isinstance(obj, (list, tuple)):
        return [_canonicalize_json(v) for v in obj]
    elif isinstance(obj, (set, frozenset)):
        return [_canonicalize_json(v) for v in sorted(list(obj))]
    return obj

class RuntimeAuditLogger:
    """Append-only audit logger for runtime tool execution."""
    
    def __init__(self, store: AuditStore = None):
        self._store = store or InMemoryAuditStore()
        self._last_hash: Optional[str] = None
        self._seen_execution_ids: set[UUID] = set()
        self._lock = threading.Lock()
        self._rebuild_replay_index()

    def _rebuild_replay_index(self) -> None:
        """Issue 8: Rebuild seen IDs from persistent store."""
        records = self._store.all()
        with self._lock:
            self._seen_execution_ids.clear()
            for record in records:
                self._seen_execution_ids.add(record.execution_id)
            if records:
                self._last_hash = records[-1].record_hash

    def _compute_hash(self, previous_hash: Optional[str], record: ExecutionAuditRecord) -> str:
        payload = json.dumps(
            _canonicalize_json({
                "previous_hash": previous_hash,
                "execution_id": str(record.execution_id),
                "timestamp": record.timestamp.isoformat(),
                "skill_name": record.skill_name,
                "tool_name": record.tool_name,
                "status": record.status.value,
                "governance_decision": record.governance_decision.value,
                "execution_time_ms": record.execution_time_ms,
                "environment": record.environment.value,
                "approved_by_human": record.approved_by_human,
                "runtime_version": record.runtime_version,
                "error_message": record.error_message,
                "output": record.output,
            }),
            sort_keys=True,
            separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def record(self, record: ExecutionAuditRecord) -> None:
        """Record an execution audit event."""
        from .exceptions import RuntimeExecutionError
        
        genesis = self._store.get_chain_genesis_hash()
        
        with self._lock:
            if record.execution_id in self._seen_execution_ids:
                raise RuntimeExecutionError(f"Duplicate execution ID: {record.execution_id}")

            prev_hash = self._last_hash if self._last_hash is not None else genesis
            new_hash = self._compute_hash(prev_hash, record)
            
            hashed_record = record.model_copy(update={
                'previous_record_hash': prev_hash,
                'record_hash': new_hash
            })
            self._last_hash = new_hash
            self._seen_execution_ids.add(record.execution_id)
            
        evicted = self._store.append(hashed_record)
        if evicted:
            self._store.set_chain_genesis_hash(evicted.record_hash)
            with self._lock:
                if evicted.execution_id in self._seen_execution_ids:
                    self._seen_execution_ids.remove(evicted.execution_id)

    def all(self) -> Tuple[ExecutionAuditRecord, ...]:
        """Get all recorded execution audit events."""
        with self._lock:
            return self._store.all()

    def verify_integrity(self) -> bool:
        """Verify the integrity of the entire audit chain."""
        records = self._store.all()
        genesis = self._store.get_chain_genesis_hash()
        
        seen_ids = set()
        expected_prev_hash = genesis
        
        for record in records:
            if record.execution_id in seen_ids:
                return False
            seen_ids.add(record.execution_id)
            
            if record.previous_record_hash != expected_prev_hash:
                return False
            
            computed = self._compute_hash(expected_prev_hash, record)
            if record.record_hash != computed:
                return False
                
            expected_prev_hash = computed
            
        return True

    def _clear_for_testing_only(self) -> None:
        """Clear all audit records (for testing purposes only)."""
        with self._lock:
            self._store.clear()
            self._last_hash = None
            self._seen_execution_ids.clear()

# Global singleton for simplicity in this phase
audit_logger = RuntimeAuditLogger()
