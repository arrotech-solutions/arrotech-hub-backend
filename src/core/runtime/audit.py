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
from .types import ImmutableJSON

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
    output: Optional[ImmutableJSON] = None
    record_hash: Optional[str] = None
    previous_record_hash: Optional[str] = None
    error_message: Optional[str] = None

    model_config = {
        "extra": "forbid",
        "frozen": True
    }

def _stable_json_repr(obj: Any) -> str:
    return json.dumps(
        _canonicalize_json(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False
    )


def _canonicalize_json(obj: Any) -> Any:

    if isinstance(obj, (dict, MappingProxyType)):
        return {
            k: _canonicalize_json(v)
            for k, v in sorted(obj.items())
        }

    if isinstance(obj, (list, tuple)):
        return [
            _canonicalize_json(v)
            for v in obj
        ]

    if isinstance(obj, (set, frozenset)):
        canonical_items = [
            _canonicalize_json(v)
            for v in obj
        ]

        return sorted(
            canonical_items,
            key=_stable_json_repr
        )

    return obj

class RuntimeAuditLogger:
    """Append-only audit logger for runtime tool execution."""
    
    def __init__(self, store: AuditStore = None):
        self._store = store or InMemoryAuditStore()
        self._last_hash: Optional[str] = None
        self._chain_genesis_hash: Optional[str] = None
        self._seen_execution_ids: set[UUID] = set()
        self._lock = threading.Lock()
        self._rebuild_replay_index()

    def _rebuild_replay_index(self) -> None:
        """Rebuild state from persistent store."""
        records = self._store.all()
        genesis = self._store.get_chain_genesis_hash()
        with self._lock:
            self._seen_execution_ids.clear()
            for record in records:
                self._seen_execution_ids.add(record.execution_id)
            if records:
                self._last_hash = records[-1].record_hash
            self._chain_genesis_hash = genesis

    def _compute_hash(self, previous_hash: Optional[str], record: ExecutionAuditRecord) -> str:
        payload = _stable_json_repr({
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
        })
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def record(self, record: ExecutionAuditRecord) -> None:

        from .immutability import freeze_structure
        from .exceptions import RuntimeExecutionError

        genesis = self._store.get_chain_genesis_hash()

        frozen_output = freeze_structure(record.output)

        with self._lock:

            if record.execution_id in self._seen_execution_ids:
                raise RuntimeExecutionError(
                    f"Duplicate execution ID: {record.execution_id}"
                )

            previous_hash = (
                self._last_hash
                if self._last_hash is not None
                else genesis
            )

            immutable_record = record.model_copy(
                update={
                    "output": frozen_output
                }
            )

            new_hash = self._compute_hash(
                previous_hash,
                immutable_record
            )

            hashed_record = immutable_record.model_copy(
                update={
                    "previous_record_hash": previous_hash,
                    "record_hash": new_hash
                }
            )

        evicted = self._store.append(hashed_record)

        with self._lock:

            self._last_hash = new_hash

            self._seen_execution_ids.add(
                record.execution_id
            )

            if evicted:

                self._store.set_chain_genesis_hash(
                    evicted.record_hash
                )

                self._chain_genesis_hash = (
                    evicted.record_hash
                )

                self._seen_execution_ids.discard(
                    evicted.execution_id
                )

    def all(self) -> Tuple[ExecutionAuditRecord, ...]:
        """Get all recorded execution audit events."""
        with self._lock:
            return self._store.all()

    def verify_integrity(self) -> bool:

        records = self._store.all()

        genesis = self._store.get_chain_genesis_hash()

        with self._lock:
            if self._chain_genesis_hash != genesis:
                return False

        seen_ids = set()

        expected_prev_hash = genesis

        for record in records:

            if record.execution_id in seen_ids:
                return False

            seen_ids.add(record.execution_id)

            if record.previous_record_hash != expected_prev_hash:
                return False

            computed_hash = self._compute_hash(
                expected_prev_hash,
                record
            )

            if record.record_hash != computed_hash:
                return False

            expected_prev_hash = computed_hash

        with self._lock:

            if self._last_hash != expected_prev_hash:
                return False

            if self._seen_execution_ids != seen_ids:
                return False

        return True

    def _clear_for_testing_only(self) -> None:
        """Clear all audit records (for testing purposes only)."""
        with self._lock:
            self._store.clear()
            self._store.set_chain_genesis_hash(None)
            self._last_hash = None
            self._chain_genesis_hash = None
            self._seen_execution_ids.clear()

# Global singleton for simplicity in this phase
audit_logger = RuntimeAuditLogger()
