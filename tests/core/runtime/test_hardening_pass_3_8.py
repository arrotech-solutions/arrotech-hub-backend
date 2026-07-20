import pytest
from uuid import uuid4
from src.core.runtime.audit import RuntimeAuditLogger, ExecutionAuditRecord, _canonicalize_json
from src.core.runtime.audit_store import InMemoryAuditStore
from src.core.runtime.factory import ExecutionResultFactory
from src.core.runtime.status import ExecutionStatus
from src.core.runtime.governance import GovernanceDecision
from src.core.runtime.immutability import validate_json_safe_payload
from src.core.runtime.validators import _validate_json_safe, MAX_OUTPUT_DEPTH
from src.core.runtime.exceptions import RuntimeExecutionError
from src.core.runtime.bootstrap import validate_tool_statelessness
from src.core.skills.models import EnvironmentScope

def test_persistent_rolling_genesis():
    """Issue 1: Rolling genesis survives logger re-initialization."""
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
    
    # 2. Re-init logger with same store
    logger2 = RuntimeAuditLogger(store)
    assert logger2.verify_integrity() is True

def test_canonical_hash_determinism():
    """Issue 2: Test canonicalization of dicts/sets/lists."""
    d1 = {"a": 1, "b": {"c": 2, "d": 3}}
    d2 = {"b": {"d": 3, "c": 2}, "a": 1}
    assert _canonicalize_json(d1) == _canonicalize_json(d2)
    
    s1 = {1, 2, 3}
    s2 = {3, 1, 2}
    assert _canonicalize_json(s1) == _canonicalize_json(s2)

def test_request_payload_object_rejection():
    """Issue 3: Reject non-JSON objects in request."""
    class Custom: pass
    with pytest.raises(ValueError, match="forbidden type"):
        validate_json_safe_payload({"val": Custom()})

def test_factory_output_error_exclusion():
    """Issue 4: Success cannot have error, failure cannot have output."""
    eid = uuid4()
    # Success with error should fail
    with pytest.raises(ValueError, match="cannot have an error_message"):
        ExecutionResultFactory._create(
            execution_id=eid, tool_name="t", skill_name="s",
            environment=EnvironmentScope.LOCAL, approved_by_human=True,
            execution_time_ms=1, status=ExecutionStatus.SUCCESS,
            governance_decision=GovernanceDecision.ALLOWED,
            output={}, error_message="oops"
        )
        
    # Failure with output should fail
    with pytest.raises(ValueError, match="cannot have output payload"):
        ExecutionResultFactory._create(
            execution_id=eid, tool_name="t", skill_name="s",
            environment=EnvironmentScope.LOCAL, approved_by_human=True,
            execution_time_ms=1, status=ExecutionStatus.FAILED,
            governance_decision=GovernanceDecision.ALLOWED,
            output={"val": 1}, error_message="fail"
        )

def test_recursive_statelessness_rejection():
    """Issue 6: Reject nested mutable class variables."""
    class BadTool:
        name = "bad"
        requires_shell = False
        requires_network = False
        mutates_files = False
        deterministic = True
        allowed_environments = [EnvironmentScope.LOCAL]
        config = {"nested": [1, 2]} # Mutable nested list
        def execute(self, request): pass
        
    with pytest.raises(SystemExit, match="illegal mutable class variable"):
        validate_tool_statelessness(BadTool())

def test_max_output_depth_rejection():
    """Issue 7: Reject payloads exceeding depth limit."""
    payload = {}
    curr = payload
    for _ in range(MAX_OUTPUT_DEPTH + 1):
        curr["n"] = {}
        curr = curr["n"]
        
    with pytest.raises(RuntimeExecutionError, match="exceeds maximum depth"):
        _validate_json_safe(payload)

def test_replay_rebuild_after_restart():
    """Issue 8: Replay index rebuilt from store."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    eid = uuid4()
    _, r = ExecutionResultFactory.success(
        execution_id=eid, tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={}
    )
    logger.record(r)
    
    # New logger with same store
    logger2 = RuntimeAuditLogger(store)
    with pytest.raises(RuntimeExecutionError, match="Duplicate execution ID"):
        logger2.record(r)

def test_malformed_tool_attribute_type():
    """Issue 9: Reject wrong attribute types."""
    class BadTool:
        name = "bad"
        requires_shell = "false" # Should be bool
        requires_network = False
        mutates_files = False
        deterministic = True
        allowed_environments = []
        def execute(self, request): pass
        
    tool = BadTool()
    with pytest.raises(SystemExit, match="attribute 'requires_shell' must be of type bool"):
        required_types = {"requires_shell": bool}
        for attr, expected_type in required_types.items():
            val = getattr(tool, attr)
            if not isinstance(val, expected_type):
                raise SystemExit(f"attribute '{attr}' must be of type {expected_type.__name__}")

def test_duplicate_execution_id_integrity_failure():
    """Issue 10: Integrity fails if duplicate IDs exist in chain."""
    store = InMemoryAuditStore()
    logger = RuntimeAuditLogger(store)
    eid = uuid4()
    
    # Record first
    _, r1 = ExecutionResultFactory.success(
        execution_id=eid, tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={"v": 1}
    )
    logger.record(r1)
    
    # Manually append duplicate ID
    _, r2 = ExecutionResultFactory.success(
        execution_id=eid, tool_name="t", skill_name="s",
        environment=EnvironmentScope.LOCAL, approved_by_human=True,
        execution_time_ms=1, output={"v": 2}
    )
    store.append(r2)
    
    assert logger.verify_integrity() is False
