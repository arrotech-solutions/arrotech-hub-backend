import pytest
import math
from uuid import uuid4
from src.core.runtime.audit import RuntimeAuditLogger, ExecutionAuditRecord, _canonicalize_json, _stable_json_repr
from src.core.runtime.audit_store import InMemoryAuditStore
from src.core.runtime.factory import ExecutionResultFactory
from src.core.runtime.immutability import validate_json_safe_payload, freeze_structure
from src.core.skills.models import EnvironmentScope

def test_cyclic_payload_rejection():
    """Issue 7: Reject circular references in payloads."""
    cyclic = {}
    cyclic["a"] = cyclic
    with pytest.raises(ValueError, match="Circular reference detected"):
        validate_json_safe_payload(cyclic)

def test_cyclic_output_rejection():
    """Issue 7: Reject circular references in tool output validation."""
    from src.core.runtime.validators import _validate_json_safe
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(Exception, match="Circular reference detected"):
        _validate_json_safe(cyclic)

def test_replay_index_exact_match_validation():
    """Issue 8: Integrity fails if replay sets do not match EXACTLY."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    
    eid1 = uuid4()
    _, r1 = ExecutionResultFactory.success(
        execution_id=eid1, tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={"v": 1}
    )
    logger.record(r1)
    
    # Tamper with seen ids (same size, different content)
    eid2 = uuid4()
    logger._seen_execution_ids.clear()
    logger._seen_execution_ids.add(eid2)
    
    assert logger.verify_integrity() is False

def test_store_logger_genesis_drift_detection():
    """Issue 2: Integrity fails if local genesis drifts from store."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    
    # 1. Trigger eviction to set genesis
    from src.core.runtime.audit_store import MAX_AUDIT_RECORDS
    for i in range(MAX_AUDIT_RECORDS + 1):
        _, r = ExecutionResultFactory.success(
            execution_id=uuid4(), tool_name="t", skill_name="s",
            environment=EnvironmentScope.LOCAL, approved_by_human=True,
            execution_time_ms=1, output={"i": i}
        )
        logger.record(r)
        
    # Drift
    logger._chain_genesis_hash = "tampered"
    assert logger.verify_integrity() is False

def test_stable_json_repr_determinism():
    """Issue 3: Nested equivalent structures serialize identically."""
    # Nested sets/dicts that should have same stable repr
    d1 = {"s": {1, "a"}, "l": [3, 2]}
    d2 = {"l": [3, 2], "s": {"a", 1}}
    
    assert _stable_json_repr(d1) == _stable_json_repr(d2)

def test_freeze_structure_breaks_aliasing():
    """Issue 5: Shared mutable references are broken during freeze."""
    shared = [1, 2]
    mutable = {"a": shared, "b": shared}
    
    frozen = freeze_structure(mutable)
    
    # Verify mutation of original shared doesn't affect either
    shared.append(3)
    assert 3 not in frozen["a"]
    assert 3 not in frozen["b"]

def test_strict_primitive_typing():
    """Issue 4: Reject subclassed primitives."""
    class MyStr(str): pass
    with pytest.raises(ValueError, match="Forbidden payload type"):
        validate_json_safe_payload({"v": MyStr("tamper")})
        
    class MyInt(int): pass
    with pytest.raises(ValueError, match="Forbidden payload type"):
        validate_json_safe_payload({"v": MyInt(1)})
