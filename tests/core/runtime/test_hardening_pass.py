import pytest
import math
import time
from uuid import uuid4
from src.core.runtime.audit import RuntimeAuditLogger, ExecutionAuditRecord
from src.core.runtime.audit_store import InMemoryAuditStore, MAX_AUDIT_RECORDS
from src.core.runtime.factory import ExecutionResultFactory
from src.core.runtime.status import ExecutionStatus
from src.core.runtime.governance import GovernanceDecision
from src.core.runtime.executor import GovernedToolExecutor
from src.core.runtime.validators import _validate_json_safe
from src.core.runtime.exceptions import RuntimeExecutionError
from src.core.runtime.bootstrap import validate_tool_statelessness
from src.core.skills.models import EnvironmentScope

def test_rolling_audit_chain_verification():
    """Issue 1: Test rolling chain continuity after FIFO eviction."""
    logger = RuntimeAuditLogger(InMemoryAuditStore())
    
    # Fill up to limit
    for i in range(MAX_AUDIT_RECORDS + 5):
        _, record = ExecutionResultFactory.success(
            execution_id=uuid4(),
            tool_name="test_tool",
            skill_name="test_skill",
            environment=EnvironmentScope.LOCAL,
            approved_by_human=True,
            execution_time_ms=10,
            output={"val": i}
        )
        logger.record(record)
        
    assert logger.verify_integrity() is True
    assert len(logger._store.all()) == MAX_AUDIT_RECORDS

def test_replay_reset_correctness():
    """Issue 2: Test that clearing resets all state."""
    logger = RuntimeAuditLogger(InMemoryAuditStore())
    eid = uuid4()
    _, record = ExecutionResultFactory.success(
        execution_id=eid,
        tool_name="test_tool",
        skill_name="test_skill",
        environment=EnvironmentScope.LOCAL,
        approved_by_human=True,
        execution_time_ms=10,
        output={}
    )
    logger.record(record)
    
    logger._clear_for_testing_only()
    assert logger._last_hash is None
    assert logger._chain_genesis_hash is None
    assert len(logger._seen_execution_ids) == 0
    
    # Should be able to record same ID again
    logger.record(record)

def test_nan_inf_rejection():
    """Issue 5: Reject non-finite floats."""
    with pytest.raises(RuntimeExecutionError, match="non-finite float"):
        _validate_json_safe({"val": float("nan")})
    with pytest.raises(RuntimeExecutionError, match="non-finite float"):
        _validate_json_safe({"val": float("inf")})

def test_failure_factory_internal_mapping():
    """Issue 7: Test internal governance mapping in factory."""
    eid = uuid4()
    # Should automatically map FAILED to ALLOWED
    _, record = ExecutionResultFactory.failure(
        execution_id=eid,
        tool_name="test",
        skill_name="test",
        environment=EnvironmentScope.LOCAL,
        approved_by_human=True,
        execution_time_ms=10,
        status=ExecutionStatus.FAILED,
        error_message="fail"
    )
    assert record.governance_decision == GovernanceDecision.ALLOWED
    
    # Should automatically map DENIED to DENIED
    _, record = ExecutionResultFactory.failure(
        execution_id=eid,
        tool_name="test",
        skill_name="test",
        environment=EnvironmentScope.LOCAL,
        approved_by_human=True,
        execution_time_ms=10,
        status=ExecutionStatus.DENIED,
        error_message="denied"
    )
    assert record.governance_decision == GovernanceDecision.DENIED

def test_output_tamper_detection():
    """Issue 8: Test that changing output breaks the hash."""
    logger = RuntimeAuditLogger(InMemoryAuditStore())
    _, record = ExecutionResultFactory.success(
        execution_id=uuid4(),
        tool_name="test",
        skill_name="test",
        environment=EnvironmentScope.LOCAL,
        approved_by_human=True,
        execution_time_ms=10,
        output={"secret": "original"}
    )
    logger.record(record)
    
    # Maliciously tamper with the stored record
    stored = logger._store._records[0]
    # We can't mutate directly because it's frozen, but we can replace it in the private list
    tampered = stored.model_copy(update={"output": {"secret": "tampered"}})
    logger._store._records[0] = tampered
    
    assert logger.verify_integrity() is False

def test_statelessness_class_variable_rejection():
    """Issue 4: Reject mutable class variables."""
    class BadTool:
        name = "bad"
        requires_shell = False
        requires_network = False
        mutates_files = False
        deterministic = True
        allowed_environments = []
        cache = {} # Mutable class variable
        def execute(self, request): pass
        
    tool = BadTool()
    with pytest.raises(SystemExit, match="illegal mutable class variable"):
        validate_tool_statelessness(tool)

def test_replay_protection_boundedness():
    """Issue 9: Test that seen IDs are pruned on eviction."""
    logger = RuntimeAuditLogger(InMemoryAuditStore())
    first_eid = uuid4()
    _, first_record = ExecutionResultFactory.success(
        execution_id=first_eid,
        tool_name="test",
        skill_name="test",
        environment=EnvironmentScope.LOCAL,
        approved_by_human=True,
        execution_time_ms=10,
        output={}
    )
    logger.record(first_record)
    assert first_eid in logger._seen_execution_ids
    
    # Fill until eviction
    for _ in range(MAX_AUDIT_RECORDS):
         _, r = ExecutionResultFactory.success(
            execution_id=uuid4(),
            tool_name="test",
            skill_name="test",
            environment=EnvironmentScope.LOCAL,
            approved_by_human=True,
            execution_time_ms=10,
            output={}
        )
         logger.record(r)
         
    # First ID should now be evicted from memory
    assert first_eid not in logger._seen_execution_ids

def test_timing_monotonicity():
    """Issue 6: Timing should use monotonic clock."""
    executor = GovernedToolExecutor()
    start = time.perf_counter()
    time.sleep(0.01)
    elapsed = executor._elapsed_ms(start)
    assert elapsed >= 10
