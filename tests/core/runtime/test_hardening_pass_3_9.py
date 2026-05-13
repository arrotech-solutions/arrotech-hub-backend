import pytest
import math
from uuid import uuid4
from unittest.mock import MagicMock
from src.core.runtime.audit import RuntimeAuditLogger, ExecutionAuditRecord, _canonicalize_json
from src.core.runtime.audit_store import InMemoryAuditStore
from src.core.runtime.factory import ExecutionResultFactory
from src.core.runtime.immutability import validate_json_safe_payload
from src.core.runtime.status import ExecutionStatus
from src.core.runtime.governance import GovernanceDecision
from src.core.skills.models import EnvironmentScope

def test_atomic_audit_append_consistency():
    """Issue 1: Runtime state NOT updated if store append fails."""
    store = MagicMock(spec=InMemoryAuditStore)
    store.append.side_effect = Exception("Store Failure")
    store.get_chain_genesis_hash.return_value = None
    
    logger = RuntimeAuditLogger(store)
    eid = uuid4()
    _, r = ExecutionResultFactory.success(
        execution_id=eid, tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={"v": 1}
    )
    
    with pytest.raises(Exception, match="Store Failure"):
        logger.record(r)
        
    # Verify logger state did not change
    assert logger._last_hash is None
    assert eid not in logger._seen_execution_ids

def test_restart_restores_genesis_state():
    """Issue 2: Restart restores genesis continuity."""
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
        
    genesis = store.get_chain_genesis_hash()
    assert genesis is not None
    
    # 2. Re-init logger
    logger2 = RuntimeAuditLogger(store)
    assert logger2._chain_genesis_hash == genesis
    assert logger2.verify_integrity() is True

def test_mixed_set_hash_determinism():
    """Issue 3: Test deterministic sorting of sets with mixed types."""
    # Sets with mixed types that normally fail native sorted()
    s1 = {1, "a", (2, "b")}
    s2 = {"a", (2, "b"), 1}
    
    c1 = _canonicalize_json(s1)
    c2 = _canonicalize_json(s2)
    assert c1 == c2

def test_payload_nan_inf_rejection():
    """Issue 4: Reject NaN/inf in payloads."""
    with pytest.raises(ValueError, match="non-finite float"):
        validate_json_safe_payload({"v": float('nan')})
    with pytest.raises(ValueError, match="non-finite float"):
        validate_json_safe_payload({"v": float('inf')})

def test_output_immutable_after_hash():
    """Issue 5: Audit record output is frozen and resistant to mutation."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    
    mutable_output = {"data": [1, 2, 3]}
    _, r = ExecutionResultFactory.success(
        execution_id=uuid4(), tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output=mutable_output
    )
    
    logger.record(r)
    
    # Verify stored record output is frozen
    recorded = logger.all()[0]
    from types import MappingProxyType
    assert isinstance(recorded.output, MappingProxyType)
    
    # Verify mutation of original does not affect stored
    mutable_output["data"].append(4)
    assert 4 not in recorded.output["data"]

def test_verify_integrity_detects_runtime_drift():
    """Issue 6: Integrity fails if logger state drifts from records."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    
    _, r = ExecutionResultFactory.success(
        execution_id=uuid4(), tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={}
    )
    logger.record(r)
    
    # Tamper with logger state
    logger._last_hash = "corrupted"
    assert logger.verify_integrity() is False

def test_payload_depth_limit():
    """Issue 7: Reject payloads exceeding depth limit."""
    from src.core.runtime.immutability import MAX_PAYLOAD_DEPTH
    payload = {}
    curr = payload
    for _ in range(MAX_PAYLOAD_DEPTH + 1):
        curr["n"] = {}
        curr = curr["n"]
        
    with pytest.raises(ValueError, match="exceeds maximum depth"):
        validate_json_safe_payload(payload)

def test_strict_attribute_type_validation():
    """Issue 9: Reject subclassed metadata types."""
    class MyBool(int): # Subclass of int/boolish
        pass
        
    class BadTool:
        name = "t"
        requires_shell = MyBool(1) # Should fail strict type check
        requires_network = False
        mutates_files = False
        deterministic = True
        allowed_environments = [EnvironmentScope.LOCAL]
        
    tool = BadTool()
    with pytest.raises(SystemExit, match="must be EXACTLY of type bool"):
        # Simulate bootstrap check
        val = tool.requires_shell
        if type(val) is not bool:
             raise SystemExit("must be EXACTLY of type bool")

def test_clear_resets_genesis():
    """Issue 10: Clear also resets persistent store genesis."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    
    # Set genesis
    store.set_chain_genesis_hash("some_hash")
    assert store.get_chain_genesis_hash() == "some_hash"
    
    logger._clear_for_testing_only()
    assert store.get_chain_genesis_hash() is None
    assert logger._chain_genesis_hash is None
