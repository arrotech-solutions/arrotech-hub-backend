"""
Governed Coding Bridge — Connects coding agent tool execution
to the governed runtime substrate.

This bridge ensures every coding agent tool call passes through:
1. Policy Engine evaluation (risk, capability, environment gates)
2. Skill contract enforcement (allowed tools, forbidden actions)
3. Audit chain recording (immutable, tamper-evident logging)

The bridge wraps the async CodingAgentToolExecutor with synchronous
governance validation that runs BEFORE any tool dispatch.
"""
import time
import logging
from typing import Any, Dict, Optional
from uuid import uuid4

from src.core.skills.models import SkillDefinition, EnvironmentScope
from src.core.skills.contracts import (
    GovernancePolicy,
    CODING_AGENT_POLICY,
    RegisteredToolRegistry,
)
from src.core.skills.enforcer import SkillExecutionEnforcer
from src.core.runtime.policy_engine import PolicyEngine
from src.core.runtime.audit import audit_logger, ExecutionAuditRecord
from src.core.runtime.factory import ExecutionResultFactory
from src.core.runtime.status import ExecutionStatus
from src.core.runtime.governance import GovernanceDecision
from src.core.runtime.exceptions import (
    RuntimeAuthorizationError,
    RuntimeGovernanceError,
    RuntimeExecutionError,
)

logger = logging.getLogger(__name__)


class GovernedCodingBridge:
    """
    Governance layer that sits between the coding agent and raw tool execution.

    Usage:
        bridge = GovernedCodingBridge(skill=coding_skill, policy=CODING_AGENT_POLICY)

        # Before dispatching to CodingAgentToolExecutor:
        bridge.authorize(tool_name="coding_file_write", environment=EnvironmentScope.LOCAL)

        # After execution completes:
        bridge.record_success(tool_name, execution_time_ms, output)
        # OR on failure:
        bridge.record_failure(tool_name, execution_time_ms, error_message, status)
    """

    def __init__(
        self,
        skill: Optional[SkillDefinition] = None,
        policy: GovernancePolicy = CODING_AGENT_POLICY,
        environment: EnvironmentScope = EnvironmentScope.LOCAL,
        approved_by_human: bool = False,
    ):
        self._skill = skill
        self._policy = policy
        self._environment = environment
        self._approved_by_human = approved_by_human

    def authorize(
        self,
        tool_name: str,
        environment: Optional[EnvironmentScope] = None,
        approved_by_human: Optional[bool] = None,
    ) -> None:
        """
        Validate governance constraints BEFORE tool execution.

        Checks:
        1. Policy permits the tool (risk level, capabilities)
        2. Environment is authorized
        3. Human approval gate (if required for HIGH/CRITICAL)
        4. Skill contract allows the tool (if a skill context is active)

        Raises:
            RuntimeAuthorizationError: Tool not registered or not allowed.
            RuntimeGovernanceError: Policy or environment violation.
        """
        env = environment or self._environment
        approved = approved_by_human if approved_by_human is not None else self._approved_by_human

        # 1. Policy engine evaluation
        PolicyEngine.evaluate(
            tool_name=tool_name,
            environment=env,
            approved_by_human=approved,
            policy=self._policy,
        )

        # 2. Skill contract enforcement (if skill context is active)
        if self._skill is not None:
            if not SkillExecutionEnforcer.is_tool_allowed(self._skill, tool_name):
                raise RuntimeAuthorizationError(
                    f"Tool '{tool_name}' is not allowed by skill "
                    f"'{self._skill.name}' execution contract."
                )

            if env not in self._skill.execution_contract.constraints.allowed_environments:
                raise RuntimeGovernanceError(
                    f"Skill '{self._skill.name}' does not permit "
                    f"environment '{env.value}'."
                )

    def record_success(
        self,
        tool_name: str,
        skill_name: str,
        execution_time_ms: int,
        output: Dict[str, Any],
        execution_id: Optional[Any] = None,
    ) -> None:
        """Record a successful tool execution to the audit chain."""
        eid = execution_id or uuid4()
        try:
            _, audit_record = ExecutionResultFactory.success(
                execution_id=eid,
                tool_name=tool_name,
                skill_name=skill_name,
                environment=self._environment,
                approved_by_human=self._approved_by_human,
                execution_time_ms=execution_time_ms,
                output=output,
            )
            audit_logger.record(audit_record)
        except Exception as e:
            logger.error(f"Audit recording failed for {tool_name}: {e}")

    def record_failure(
        self,
        tool_name: str,
        skill_name: str,
        execution_time_ms: int,
        error_message: str,
        status: ExecutionStatus = ExecutionStatus.FAILED,
        execution_id: Optional[Any] = None,
    ) -> None:
        """Record a failed tool execution to the audit chain."""
        eid = execution_id or uuid4()
        try:
            _, audit_record = ExecutionResultFactory.failure(
                execution_id=eid,
                tool_name=tool_name,
                skill_name=skill_name,
                environment=self._environment,
                approved_by_human=self._approved_by_human,
                execution_time_ms=execution_time_ms,
                status=status,
                error_message=error_message,
            )
            audit_logger.record(audit_record)
        except Exception as e:
            logger.error(f"Audit recording failed for {tool_name}: {e}")

    @property
    def policy(self) -> GovernancePolicy:
        return self._policy

    @property
    def environment(self) -> EnvironmentScope:
        return self._environment
