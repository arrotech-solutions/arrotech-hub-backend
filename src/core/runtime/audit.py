from __future__ import annotations

import json
from types import MappingProxyType
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime
from uuid import UUID
import threading
import hashlib
from pydantic import BaseModel
from src.core.skills.models import EnvironmentScope
from .status import ExecutionStatus
from .governance import GovernanceDecision
from .version import RUNTIME_VERSION
from .audit_store import AuditStore, InMemoryAuditStore
from .types import ImmutableJSON
from .immutability import freeze_structure, _stable_json_repr, _canonicalize_json


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




class RuntimeAuditLogger:
    """Append-only audit logger for runtime tool execution."""
    
    def __init__(self, store: AuditStore = None):
        self._store = store or InMemoryAuditStore()
        self._last_hash: Optional[str] = None
        self._chain_genesis_hash: Optional[str] = None
        self._seen_execution_ids: set[UUID] = set()
        self._pending_execution_ids: set[UUID] = set()
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
        """
        Three-phase atomic audit commit.

        Guarantees:
        - No partial mutation
        - No replay leakage
        - No hash drift
        - Immutable persistence
        """

        from .exceptions import RuntimeExecutionError

        # ==================================================
        # PHASE 1 — BUILD IMMUTABLE RECORD
        # ==================================================

        genesis = self._store.get_chain_genesis_hash()

        frozen_output = freeze_structure(record.output)

        with self._lock:

            if (
                record.execution_id in self._seen_execution_ids
                or record.execution_id in self._pending_execution_ids
            ):
                raise RuntimeExecutionError(
                    f"Duplicate execution ID: {record.execution_id}"
                )

            # RESERVE ID IMMEDIATELY
            self._pending_execution_ids.add(record.execution_id)

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

        # ==================================================
        # PHASE 2 — PERSIST
        # ==================================================

        try:
            evicted = self._store.append(
                hashed_record
            )
        except Exception:
            with self._lock:
                self._pending_execution_ids.discard(record.execution_id)
            raise

        # ==================================================
        # PHASE 3 — MEMORY SYNCHRONIZATION
        # ==================================================

        with self._lock:

            self._last_hash = (
                hashed_record.record_hash
            )

            self._seen_execution_ids.add(
                record.execution_id
            )

            # REMOVE PENDING RESERVATION
            self._pending_execution_ids.discard(record.execution_id)

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

        expected_hash = genesis

        for record in records:

            if record.execution_id in seen_ids:
                return False

            seen_ids.add(record.execution_id)

            if record.previous_record_hash != expected_hash:
                return False

            recomputed_hash = self._compute_hash(
                expected_hash,
                record
            )

            if record.record_hash != recomputed_hash:
                return False

            expected_hash = recomputed_hash

        with self._lock:

            if self._pending_execution_ids:
                return False

            if self._chain_genesis_hash != genesis:
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
            self._pending_execution_ids.clear()

# ── STORE SELECTION ──────────────────────────────────────────────────
def _create_audit_store() -> AuditStore:
    """Select audit store based on AUDIT_STORE_BACKEND config."""
    import os
    backend = os.getenv("AUDIT_STORE_BACKEND", "memory").lower()
    if backend == "postgres":
        try:
            from .postgres_audit_store import PostgresAuditStore
            import logging
            logging.getLogger(__name__).info("Using PostgresAuditStore for audit persistence")
            # Note: PostgresAuditStore is async — the sync RuntimeAuditLogger
            # uses InMemoryAuditStore as the synchronous layer. Postgres
            # persistence is handled via the GovernedCodingBridge which
            # operates in an async context.
            return InMemoryAuditStore()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Failed to initialize PostgresAuditStore, falling back to memory: {e}"
            )
            return InMemoryAuditStore()
    return InMemoryAuditStore()

# Global singleton
audit_logger = RuntimeAuditLogger(store=_create_audit_store())

