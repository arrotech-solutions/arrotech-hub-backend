import pytest
import threading
import time
import random
import math
import json
from uuid import uuid4
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from hypothesis import given, strategies as st, settings, HealthCheck

from src.core.runtime.audit import (
    RuntimeAuditLogger, 
    ExecutionAuditRecord, 
    _canonicalize_json, 
    _stable_json_repr
)
from src.core.runtime.audit_store import InMemoryAuditStore, MAX_AUDIT_RECORDS
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

# --- Determinism & Canonicalization ---

@given(st.recursive(
    st.one_of(st.text(), st.integers(), st.floats(allow_nan=False, allow_infinity=False), st.booleans(), st.none()),
    lambda children: st.one_of(
        st.lists(children),
        st.dictionaries(st.text(), children),
    )
))
@settings(suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_hypothesis_canonical_stability(val):
    """Property test: Canonical representation must be stable across permutations."""
    repr1 = _stable_json_repr(val)
    
    # Verify that re-canonicalization is idempotent.
    repr2 = _stable_json_repr(_canonicalize_json(val))
    assert repr1 == repr2

def test_randomized_set_ordering_determinism():
    """Ensure set order variations never change the hash."""
    items = ["a", "b", 1, 2, (3, 4)]
    for _ in range(10):
        shuffled = list(items)
        random.shuffle(shuffled)
        s1 = set(items)
        s2 = set(shuffled)
        assert _stable_json_repr(s1) == _stable_json_repr(s2)

# --- Immutability & Isolation ---

def test_shared_reference_aliasing_attack():
    """Attempting to leak mutations into frozen structures via shared references."""
    shared_list = [1, 2, 3]
    payload = {"a": shared_list, "b": shared_list}
    
    frozen = freeze_structure(payload)
    
    # Modify original shared reference
    shared_list.append(4)
    
    # Verify frozen structure is untouched
    assert 4 not in frozen["a"]
    assert 4 not in frozen["b"]
    
    # Verify both internal references are separate (aliasing broken)
    assert frozen["a"] is not frozen["b"]

def test_primitive_subclass_injection_attack():
    """Attempting to bypass validation with subclasses of primitives."""
    class EvilStr(str):
        def __repr__(self): return "evil"
        
    class EvilInt(int): pass
    
    with pytest.raises(ValueError, match="Forbidden payload type"):
        validate_json_safe_payload({"key": EvilStr("data")})
        
    with pytest.raises(ValueError, match="Forbidden payload type"):
        validate_json_safe_payload({"key": EvilInt(123)})

# --- Recursive & Bounded Logic ---

def test_cyclic_graph_attack():
    """Stress cycle detection in both requests and outputs."""
    # Request cycle
    cyclic_req = {}
    cyclic_req["self"] = cyclic_req
    with pytest.raises(ValueError, match="Circular reference detected"):
        validate_json_safe_payload(cyclic_req)
        
    # Output cycle
    cyclic_out = []
    cyclic_out.append(cyclic_out)
    with pytest.raises(RuntimeExecutionError, match="Circular reference detected"):
        _validate_json_safe(cyclic_out)

def test_recursive_depth_overflow_attack():
    """Pushing payloads beyond the depth limit."""
    deep = {}
    curr = deep
    for _ in range(MAX_PAYLOAD_DEPTH + 1):
        curr["n"] = {}
        curr = curr["n"]
        
    with pytest.raises(ValueError, match="exceeds maximum depth"):
        validate_json_safe_payload(deep)

# --- Audit Integrity & Genesis ---

def test_massive_rolling_eviction_integrity():
    """Verifying genesis continuity across 1,000 evictions."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    
    for i in range(MAX_AUDIT_RECORDS + 1000):
        _, r = ExecutionResultFactory.success(
            execution_id=uuid4(), tool_name="t", skill_name="s",
            environment=EnvironmentScope.LOCAL, approved_by_human=True,
            execution_time_ms=1, output={"i": i}
        )
        logger.record(r)
        
    assert logger.verify_integrity() is True
    assert store.get_chain_genesis_hash() is not None

def test_hash_tampering_detection():
    """Verify detection of record tampering."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    
    eid = uuid4()
    _, r = ExecutionResultFactory.success(
        execution_id=eid, tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={"data": "secret"}
    )
    logger.record(r)
    
    # Tamper with stored record
    all_records = list(store.all())
    tampered_record = all_records[0].model_copy(update={"output": {"data": "pwned"}})
    store._records[0] = tampered_record
    
    assert logger.verify_integrity() is False

# --- Concurrency & Races ---

def test_concurrent_append_stress():
    """High-concurrency record() calls."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    num_threads = 20
    iters = 50
    
    def worker():
        for _ in range(iters):
            _, r = ExecutionResultFactory.success(
                execution_id=uuid4(), tool_name="t", skill_name="s",
                environment=EnvironmentScope.LOCAL, approved_by_human=True,
                execution_time_ms=1, output={}
            )
            logger.record(r)
            
    threads = [threading.Thread(target=worker) for _ in range(num_threads)]
    for t in threads: t.start()
    for t in threads: t.join()
    
    # Verify no corruption and correct count
    # Note: store count may be less than total if MAX_AUDIT_RECORDS is exceeded
    total_requested = num_threads * iters
    expected_in_store = min(total_requested, MAX_AUDIT_RECORDS)
    assert len(store.all()) == expected_in_store
    assert logger.verify_integrity() is True

def test_replay_collision_race():
    """Simultaneous attempt to insert duplicate ID."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    eid = uuid4()
    _, r = ExecutionResultFactory.success(
        execution_id=eid, tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={}
    )
    
    results = []
    lock = threading.Lock()
    def worker():
        try:
            logger.record(r)
            with lock: results.append("success")
        except RuntimeExecutionError:
            with lock: results.append("rejected")
            
    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    
    # Exactly one must succeed
    assert results.count("success") == 1
    assert results.count("rejected") == 9

# --- Persistence & Atomicity ---

def test_persistence_restart_reconstruction():
    """Proving state recovery after simulated restart."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    
    # 1. Fill store and trigger eviction
    eids = []
    for i in range(MAX_AUDIT_RECORDS + 10):
        eid = uuid4()
        eids.append(eid)
        _, r = ExecutionResultFactory.success(
            execution_id=eid, tool_name="t", skill_name="s",
            environment=EnvironmentScope.LOCAL, approved_by_human=True,
            execution_time_ms=1, output={"i": i}
        )
        logger.record(r)
        
    last_hash = logger._last_hash
    genesis_hash = store.get_chain_genesis_hash()
    
    # 2. Simulate restart
    logger2 = RuntimeAuditLogger(store)
    
    assert logger2._last_hash == last_hash
    assert logger2._chain_genesis_hash == genesis_hash
    assert logger2.verify_integrity() is True
    
    # Verify replay protection still works for IDs still in store
    last_eid = eids[-1]
    _, r_dup = ExecutionResultFactory.success(
        execution_id=last_eid, tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={}
    )
    with pytest.raises(RuntimeExecutionError, match="Duplicate execution ID"):
        logger2.record(r_dup)

def test_audit_rollback_consistency():
    """Failed storage write leaves no trace in logger."""
    class FailingStore(InMemoryAuditStore):
        def append(self, record):
            raise RuntimeError("Disk Full")
            
    logger = RuntimeAuditLogger(FailingStore())
    eid = uuid4()
    _, r = ExecutionResultFactory.success(
        execution_id=eid, tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={}
    )
    
    with pytest.raises(RuntimeError, match="Disk Full"):
        logger.record(r)
        
    # Logger state must NOT have updated
    assert logger._last_hash is None
    assert eid not in logger._seen_execution_ids
