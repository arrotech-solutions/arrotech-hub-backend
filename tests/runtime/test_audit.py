import pytest
from datetime import datetime, timezone
from src.core.runtime.audit import RuntimeAuditLogger, ExecutionAuditRecord
from src.core.skills.models import EnvironmentScope

def test_audit_logger_append_only():
    logger = RuntimeAuditLogger()
    record = ExecutionAuditRecord(
        skill_name="test_skill",
        tool_name="test_tool",
        timestamp=datetime.now(timezone.utc),
        execution_time_ms=5,
        success=True,
        approved_by_human=False,
        environment=EnvironmentScope.DEVELOPMENT
    )
    
    logger.record(record)
    
    records = logger.all()
    assert len(records) == 1
    assert records[0] == record
    
    # Verify external modifications do not affect internal state (not applicable for tuple, but testing type)
    assert isinstance(records, tuple)
    assert len(logger.all()) == 1

def test_audit_logger_clear():
    logger = RuntimeAuditLogger()
    record = ExecutionAuditRecord(
        skill_name="test_skill",
        tool_name="test_tool",
        timestamp=datetime.now(timezone.utc),
        execution_time_ms=5,
        success=True,
        approved_by_human=False,
        environment=EnvironmentScope.DEVELOPMENT
    )
    
    logger.record(record)
    logger.clear_for_testing()
    
    assert len(logger.all()) == 0
