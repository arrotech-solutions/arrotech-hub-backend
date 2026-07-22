import pytest
import uuid
from datetime import datetime, timezone
from src.core.runtime.audit import RuntimeAuditLogger, ExecutionAuditRecord
from src.core.skills.models import EnvironmentScope
from src.core.runtime.status import ExecutionStatus
from src.core.runtime.governance import GovernanceDecision

def _sample_audit_record() -> ExecutionAuditRecord:
    return ExecutionAuditRecord(
        skill_name="test_skill",
        tool_name="test_tool",
        timestamp=datetime.now(timezone.utc),
        execution_time_ms=5,
        status=ExecutionStatus.SUCCESS,
        governance_decision=GovernanceDecision.ALLOWED,
        execution_id=uuid.uuid4(),
        approved_by_human=False,
        environment=EnvironmentScope.DEVELOPMENT,
    )

def test_audit_logger_append_only():
    logger = RuntimeAuditLogger()
    record = _sample_audit_record()
    
    logger.record(record)
    
    records = logger.all()
    assert len(records) == 1
    assert records[0].skill_name == record.skill_name
    assert records[0].tool_name == record.tool_name
    
    # Verify external modifications do not affect internal state (not applicable for tuple, but testing type)
    assert isinstance(records, tuple)
    assert len(logger.all()) == 1

def test_audit_logger_clear():
    logger = RuntimeAuditLogger()
    record = _sample_audit_record()
    
    logger.record(record)
    logger._clear_for_testing_only()
    
    assert len(logger.all()) == 0
