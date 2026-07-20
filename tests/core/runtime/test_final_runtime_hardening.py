import pytest
import threading
import time
import math
from uuid import uuid4
from datetime import datetime
from types import MappingProxyType
from concurrent.futures import ThreadPoolExecutor

from src.core.runtime.audit import (
    RuntimeAuditLogger, 
    ExecutionAuditRecord, 
    _canonicalize_json, 
    _stable_json_repr
)
from src.core.runtime.audit_store import InMemoryAuditStore
from src.core.runtime.factory import ExecutionResultFactory
from src.core.runtime.immutability import (
    validate_json_safe_payload, 
    freeze_structure, 
    MAX_PAYLOAD_DEPTH
)
from src.core.runtime.validators import _validate_json_safe, MAX_OUTPUT_DEPTH
from src.core.runtime.status import ExecutionStatus
from src.core.runtime.governance import GovernanceDecision
from src.core.skills.models import EnvironmentScope
from src.core.runtime.exceptions import RuntimeExecutionError

# --- Adversarial Tests ---

def test_cyclic_payload_rejection():
    """1. Reject circular references in payloads."""
    cyclic = {}
    cyclic["self"] = cyclic
    with pytest.raises(ValueError, match="Circular reference detected"):
        validate_json_safe_payload(cyclic)

def test_cyclic_output_rejection():
    """2. Reject circular references in tool outputs."""
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(RuntimeExecutionError, match="Circular reference detected"):
        _validate_json_safe(cyclic)

def test_replay_collision_race():
    """3. Verify atomicity under concurrent duplicate writes."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    eid = uuid4()
    
    _, r = ExecutionResultFactory.success(
        execution_id=eid, tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={"v": 1}
    )
    
    results = []
    def worker():
        try:
            logger.record(r)
            results.append("success")
        except RuntimeExecutionError:
            results.append("rejected")
            
    with ThreadPoolExecutor(max_workers=50) as executor:
        for _ in range(100):
            executor.submit(worker)
    
    assert results.count("success") == 1
    assert len(logger.all()) == 1

def test_restart_reconstruction():
    """4. Prove genesis and hash chain recovery after restart."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    
    for i in range(5):
        _, r = ExecutionResultFactory.success(
            execution_id=uuid4(), tool_name="t", skill_name="s",
            environment=EnvironmentScope.LOCAL, approved_by_human=True,
            execution_time_ms=1, output={"i": i}
        )
        logger.record(r)
        
    last_hash = logger._last_hash
    logger2 = RuntimeAuditLogger(store)
    assert logger2._last_hash == last_hash
    assert logger2.verify_integrity() is True

def test_atomic_store_failure_consistency():
    """5. Storage failure leaves logger state unchanged (no partial mutation)."""
    class FailingStore(InMemoryAuditStore):
        def append(self, record):
            raise RuntimeError("Storage failure")
            
    logger = RuntimeAuditLogger(FailingStore())
    eid = uuid4()
    _, r = ExecutionResultFactory.success(
        execution_id=eid, tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={}
    )
    with pytest.raises(RuntimeError, match="Storage failure"):
        logger.record(r)
        
    assert logger._last_hash is None
    assert eid not in logger._seen_execution_ids

def test_hash_drift_detection():
    """6. verify_integrity detects hash tampering."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    
    _, r = ExecutionResultFactory.success(
        execution_id=uuid4(), tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={"v": 1}
    )
    logger.record(r)
    
    original = store._records[0]
    store._records[0] = original.model_copy(update={"record_hash": "tampered"})
    assert logger.verify_integrity() is False

def test_replay_set_drift_detection():
    """7. verify_integrity detects drift in replay index."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    
    eid = uuid4()
    _, r = ExecutionResultFactory.success(
        execution_id=eid, tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={}
    )
    logger.record(r)
    
    # Tamper with seen ids
    logger._seen_execution_ids.add(uuid4())
    assert logger.verify_integrity() is False

def test_alias_breaking():
    """8. Prove freezing breaks all mutable references."""
    shared = [1, 2]
    payload = {"x": shared, "y": shared}
    frozen = freeze_structure(payload)
    
    shared.append(3)
    assert 3 not in frozen["x"]
    assert 3 not in frozen["y"]
    assert frozen["x"] is not frozen["y"]

def test_nan_inf_rejection():
    """9. Reject non-finite floats in payloads and outputs."""
    with pytest.raises(ValueError, match="Non-finite float detected"):
        validate_json_safe_payload({"v": float("nan")})
    with pytest.raises(RuntimeExecutionError, match="Non-finite float detected"):
        _validate_json_safe({"v": float("inf")})

def test_mixed_set_determinism():
    """10. Verify sets of mixed types sort deterministically."""
    s1 = {1, "2", (3, 4)}
    s2 = {(3, 4), 1, "2"}
    assert _stable_json_repr(s1) == _stable_json_repr(s2)

def test_payload_depth_rejection():
    """11. Reject deep recursive structures."""
    deep = {}
    curr = deep
    for _ in range(MAX_PAYLOAD_DEPTH + 1):
        curr["n"] = {}
        curr = curr["n"]
    with pytest.raises(ValueError, match="exceeds maximum depth"):
        validate_json_safe_payload(deep)

def test_subclass_spoof_rejection():
    """12. Reject subclasses of primitives."""
    class MyStr(str): pass
    with pytest.raises(ValueError, match="Forbidden payload type"):
        validate_json_safe_payload({"v": MyStr("data")})

def test_genesis_drift_detection():
    """13. verify_integrity detects drift in genesis hash."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    logger._chain_genesis_hash = "tampered"
    assert logger.verify_integrity() is False

def test_concurrent_duplicate_execution_ids():
    """14. Strict concurrent thread test for exact same execution_id rejection."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    eid = uuid4()
    
    results = []
    def worker():
        try:
            _, r = ExecutionResultFactory.success(
                execution_id=eid, tool_name="t", skill_name="s",
                environment=EnvironmentScope.LOCAL, approved_by_human=True,
                execution_time_ms=1, output={}
            )
            logger.record(r)
            results.append("success")
        except RuntimeExecutionError:
            results.append("rejected")

    with ThreadPoolExecutor(max_workers=10) as executor:
        for _ in range(20):
            executor.submit(worker)
            
    assert results.count("success") == 1
    assert logger.verify_integrity() is True

def test_store_restart_preserves_chain():
    """15. Restarting the logger uses the persistent store to preserve chain links exactly."""
    store = InMemoryAuditStore()
    logger1 = RuntimeAuditLogger(store)
    
    _, r1 = ExecutionResultFactory.success(
        execution_id=uuid4(), tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={"step": 1}
    )
    logger1.record(r1)
    
    hash1 = logger1._last_hash
    
    logger2 = RuntimeAuditLogger(store)
    assert logger2._last_hash == hash1
    
    _, r2 = ExecutionResultFactory.success(
        execution_id=uuid4(), tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={"step": 2}
    )
    logger2.record(r2)
    
    assert logger2._last_hash != hash1
    assert logger2.verify_integrity() is True
