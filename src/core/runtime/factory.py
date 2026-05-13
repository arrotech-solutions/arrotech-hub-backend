from datetime import datetime, timezone
from typing import Dict, Any, Optional
from uuid import UUID

from src.core.skills.models import EnvironmentScope
from .status import ExecutionStatus
from .governance import GovernanceDecision
from .results import ToolExecutionResult
from .audit import ExecutionAuditRecord
from .version import RUNTIME_VERSION

class ExecutionResultFactory:
    """Central factory for constructing deterministic execution results and audit records."""

    @staticmethod
    def _create(
        execution_id: UUID,
        tool_name: str,
        skill_name: str,
        environment: EnvironmentScope,
        approved_by_human: bool,
        execution_time_ms: int,
        status: ExecutionStatus,
        governance_decision: GovernanceDecision,
        output: Dict[str, Any] = None,
        error_message: Optional[str] = None
    ) -> tuple[ToolExecutionResult, ExecutionAuditRecord]:
        
        # Issue 4: Enforce output/error mutual exclusion
        if status == ExecutionStatus.SUCCESS:
            if error_message is not None:
                raise ValueError("SUCCESS status cannot have an error_message")
        else:
            if output is not None and output != {}:
                raise ValueError(f"Non-SUCCESS status {status} cannot have output payload")

        now = datetime.now(timezone.utc)
        
        result = ToolExecutionResult(
            status=status,
            governance_decision=governance_decision,
            tool_name=tool_name,
            execution_time_ms=execution_time_ms,
            execution_id=execution_id,
            runtime_version=RUNTIME_VERSION,
            output=output or {},
            error_message=error_message
        )
        
        audit_record = ExecutionAuditRecord(
            skill_name=skill_name,
            tool_name=tool_name,
            timestamp=now,
            execution_time_ms=execution_time_ms,
            status=status,
            governance_decision=governance_decision,
            execution_id=execution_id,
            runtime_version=RUNTIME_VERSION,
            approved_by_human=approved_by_human,
            environment=environment,
            output=output,
            error_message=error_message
        )
        
        return result, audit_record

    @staticmethod
    def success(execution_id: UUID, tool_name: str, skill_name: str, environment: EnvironmentScope, approved_by_human: bool, execution_time_ms: int, output: Dict[str, Any]) -> tuple[ToolExecutionResult, ExecutionAuditRecord]:
        return ExecutionResultFactory._create(
            execution_id=execution_id,
            tool_name=tool_name,
            skill_name=skill_name,
            environment=environment,
            approved_by_human=approved_by_human,
            execution_time_ms=execution_time_ms,
            status=ExecutionStatus.SUCCESS,
            governance_decision=GovernanceDecision.ALLOWED,
            output=output
        )

    @staticmethod
    def failure(
        *,
        execution_id: UUID,
        tool_name: str,
        skill_name: str,
        environment: EnvironmentScope,
        approved_by_human: bool,
        execution_time_ms: int,
        status: ExecutionStatus,
        error_message: str
    ) -> tuple[ToolExecutionResult, ExecutionAuditRecord]:
        if status == ExecutionStatus.SUCCESS:
            raise ValueError("SUCCESS status cannot be processed via the failure factory method.")
            
        # Internal semantic mapping (Issue 7)
        mapping = {
            ExecutionStatus.FAILED: GovernanceDecision.ALLOWED,
            ExecutionStatus.TIMEOUT: GovernanceDecision.ALLOWED,
            ExecutionStatus.DENIED: GovernanceDecision.DENIED,
            ExecutionStatus.GOVERNANCE_REJECTED: GovernanceDecision.REJECTED
        }
        
        if status not in mapping:
            raise ValueError(f"Invalid failure status: {status}")
            
        governance_decision = mapping[status]
            
        return ExecutionResultFactory._create(
            execution_id=execution_id,
            tool_name=tool_name,
            skill_name=skill_name,
            environment=environment,
            approved_by_human=approved_by_human,
            execution_time_ms=execution_time_ms,
            status=status,
            governance_decision=governance_decision,
            error_message=error_message
        )
