import pytest
import threading
import math
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from datetime import datetime
from types import MappingProxyType

from src.core.runtime.audit import RuntimeAuditLogger
from src.core.runtime.audit_store import InMemoryAuditStore
from src.core.runtime.immutability import (
    validate_json_safe_payload, 
    freeze_structure, 
    MAX_PAYLOAD_DEPTH,
    _stable_json_repr,
    _canonicalize_json
)
from src.core.runtime.validators import _validate_json_safe
from src.core.runtime.factory import ExecutionResultFactory
from src.core.skills.models import EnvironmentScope
from src.core.runtime.exceptions import RuntimeExecutionError

# 1. cyclic payload rejection
def test_cyclic_payload_rejection():
    payload = {}
    payload["self"] = payload
    with pytest.raises(ValueError, match="Circular reference detected"):
        validate_json_safe_payload(payload)

# 2. cyclic output rejection
def test_cyclic_output_rejection():
    output = {}
    output["self"] = output
    with pytest.raises(RuntimeExecutionError, match="Circular reference detected"):
        _validate_json_safe(output)

# 3. aliasing attacks
def test_aliasing_attack_prevention():
    shared = [1, 2]
    payload = {"x": shared, "y": shared}
    frozen = freeze_structure(payload)
    # Breaking aliasing means they are different objects in memory
    assert frozen["x"] is not frozen["y"]

# 4. nested MappingProxyType mutation attacks
def test_mutable_nested_mapping_proxy_reconstruction():
    inner = {"a": 1}
    proxy = MappingProxyType(inner)
    outer = {"data": proxy}
    frozen = freeze_structure(outer)
    
    # Ensure it's not just a shallow copy of the proxy
    assert frozen["data"] is not proxy
    # Ensure the inner content is frozen
    assert type(frozen["data"]) is MappingProxyType
    
    # Attempt to mutate inner and see if frozen reflects it (should not)
    inner["a"] = 2
    assert frozen["data"]["a"] == 1

# 5. replay collisions
def test_replay_collision_race():
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
    assert results.count("rejected") == 99
    assert logger.verify_integrity() is True

# 6. replay drift
def test_replay_set_drift_detection():
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    _, r = ExecutionResultFactory.success(
        execution_id=uuid4(), tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={}
    )
    logger.record(r)
    
    logger._seen_execution_ids.add(uuid4()) # Inject fake ID into memory
    assert logger.verify_integrity() is False

# 7. genesis drift
def test_genesis_drift_detection():
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    logger._chain_genesis_hash = "tampered"
    assert logger.verify_integrity() is False

# 8. restart reconstruction
def test_restart_reconstruction():
    store = InMemoryAuditStore()
    logger1 = RuntimeAuditLogger(store)
    _, r = ExecutionResultFactory.success(
        execution_id=uuid4(), tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={"step": 1}
    )
    logger1.record(r)
    hash1 = logger1._last_hash
    
    # Restart
    logger2 = RuntimeAuditLogger(store)
    assert logger2._last_hash == hash1
    assert logger2.verify_integrity() is True

# 9. deterministic set hashing
def test_deterministic_set_hashing():
    data1 = {"x": {3, 2, 1}}
    data2 = {"x": {1, 2, 3}}
    assert _stable_json_repr(data1) == _stable_json_repr(data2)

# 10. non-finite float rejection
def test_nonfinite_float_rejection():
    with pytest.raises(ValueError, match="Non-finite float detected"):
        validate_json_safe_payload({"v": float("nan")})
    with pytest.raises(ValueError, match="Non-finite float detected"):
        validate_json_safe_payload({"v": float("inf")})

# 11. subclass spoofing rejection
def test_subclass_spoofing_rejection():
    class EvilFloat(float):
        pass
    with pytest.raises(ValueError, match="Forbidden payload type"):
        validate_json_safe_payload({"v": EvilFloat(1.0)})

# 12. persistence crash atomicity
def test_persistence_crash_atomicity():
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
    
    with pytest.raises(RuntimeError):
        logger.record(r)
        
    assert logger._last_hash is None
    assert eid not in logger._seen_execution_ids
    assert logger.verify_integrity() is True

# 13. post-freeze mutation attacks
def test_post_freeze_mutation_isolation():
    shared = [1, 2]
    payload = {"x": shared}
    frozen = freeze_structure(payload)
    shared.append(3)
    assert 3 not in frozen["x"]

# 14. visited-set unwind correctness
def test_visited_set_unwind_safety():
    # Construct a structure that fails validation deep inside
    payload = {"a": {"b": float("nan")}, "c": {}}
    try:
        validate_json_safe_payload(payload)
    except ValueError:
        pass
        
    # The dictionary 'payload' and its children should NOT be left in any global visited state.
    # We can test this by validating the safe part again.
    validate_json_safe_payload(payload["c"]) # Should succeed, no "Circular reference"

# 15. deep recursion bounds
def test_deep_recursion_limit_enforcement():
    deep = {}
    curr = deep
    for _ in range(MAX_PAYLOAD_DEPTH + 1):
        curr["n"] = {}
        curr = curr["n"]
    
    with pytest.raises(ValueError, match="exceeds maximum depth"):
        validate_json_safe_payload(deep)

# 16. append race collisions
def test_concurrent_append_race():
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    
    def worker(i):
        _, r = ExecutionResultFactory.success(
            execution_id=uuid4(), tool_name=f"t{i}", skill_name="s",
            environment=EnvironmentScope.LOCAL, approved_by_human=True,
            execution_time_ms=1, output={"i": i}
        )
        logger.record(r)

    with ThreadPoolExecutor(max_workers=10) as executor:
        for i in range(50):
            executor.submit(worker, i)
            
    assert len(store._records) == 50
    assert logger.verify_integrity() is True

# 17. replay set parity
def test_replay_set_parity_exact_verification():
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    
    eid = uuid4()
    _, r = ExecutionResultFactory.success(
        execution_id=eid, tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={}
    )
    logger.record(r)
    
    # Verify that removing an ID from seen_ids fails integrity even if records are same
    logger._seen_execution_ids.remove(eid)
    assert logger.verify_integrity() is False

# 18. store tampering detection
def test_store_tampering_detection():
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    
    _, r = ExecutionResultFactory.success(
        execution_id=uuid4(), tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={"v": 1}
    )
    logger.record(r)
    
    # Corrupt record data
    store._records[0] = store._records[0].model_copy(update={"tool_name": "tampered"})
    assert logger.verify_integrity() is False

# 19. canonical serialization stability
def test_canonical_serialization_stability():
    # Different types that should have same JSON representation
    obj1 = MappingProxyType({"b": 2, "a": 1})
    obj2 = {"a": 1, "b": 2}
    assert _stable_json_repr(obj1) == _stable_json_repr(obj2)
    
    # Nesting
    obj3 = {"x": [obj1, {3, 2, 1}]}
    obj4 = {"x": [obj2, {1, 2, 3}]}
    assert _stable_json_repr(obj3) == _stable_json_repr(obj4)

# 20. mixed nested set determinism
def test_mixed_nested_set_determinism():
    # Sets containing mixed types should sort deterministically
    s1 = {1, "a", (2, 3), None, True}
    s2 = {True, None, (2, 3), "a", 1}
    assert _stable_json_repr(s1) == _stable_json_repr(s2)
    
    # Deeply nested
    data1 = {"data": [1, { "s": s1 }]}
    data2 = {"data": [1, { "s": s2 }]}
    assert _stable_json_repr(data1) == _stable_json_repr(data2)

# 21. rapid restart simulation
def test_rapid_restart_simulation():
    store = InMemoryAuditStore()
    
    for i in range(10):
        logger = RuntimeAuditLogger(store)
        _, r = ExecutionResultFactory.success(
            execution_id=uuid4(), tool_name=f"t{i}", skill_name="s",
            environment=EnvironmentScope.LOCAL, approved_by_human=True,
            execution_time_ms=1, output={"i": i}
        )
        logger.record(r)
        assert logger.verify_integrity() is True
    
    # Final check on reconstructed logger
    final_logger = RuntimeAuditLogger(store)
    assert len(final_logger._seen_execution_ids) == 10
    assert final_logger.verify_integrity() is True
