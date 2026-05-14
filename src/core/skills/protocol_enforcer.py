"""
Skill Protocol Enforcer — Structured execution step tracking.

Enforces the Superpowers-style discipline:
1. Execution steps must be completed in order
2. Review steps must pass after execution
3. Failure recovery steps are triggered on errors
4. All transitions are logged for observability

This is the behavioral backbone of skill-governed agent execution.
"""
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ProtocolPhase(str, Enum):
    EXECUTION = "execution"
    REVIEW = "review"
    RECOVERY = "recovery"


@dataclass
class StepRecord:
    """Record of a single protocol step execution."""
    name: str
    phase: ProtocolPhase
    status: StepStatus = StepStatus.PENDING
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_ms: int = 0
    output: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "phase": self.phase.value,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "output": self.output,
            "error": self.error,
        }


@dataclass
class ProtocolExecution:
    """Tracks the full execution of a skill protocol."""
    skill_name: str
    execution_steps: List[StepRecord] = field(default_factory=list)
    review_steps: List[StepRecord] = field(default_factory=list)
    recovery_steps: List[StepRecord] = field(default_factory=list)
    phase: ProtocolPhase = ProtocolPhase.EXECUTION
    started_at: float = 0.0
    completed_at: Optional[float] = None
    success: bool = False
    error: Optional[str] = None

    @property
    def current_step_index(self) -> int:
        """Index of the current step in the active phase."""
        steps = self._current_steps()
        for i, step in enumerate(steps):
            if step.status in (StepStatus.PENDING, StepStatus.IN_PROGRESS):
                return i
        return len(steps)

    @property
    def is_complete(self) -> bool:
        """Whether all phases have completed."""
        return self.completed_at is not None

    @property
    def total_duration_ms(self) -> int:
        end = self.completed_at or time.time()
        return int((end - self.started_at) * 1000)

    def _current_steps(self) -> List[StepRecord]:
        if self.phase == ProtocolPhase.EXECUTION:
            return self.execution_steps
        elif self.phase == ProtocolPhase.REVIEW:
            return self.review_steps
        return self.recovery_steps

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "phase": self.phase.value,
            "success": self.success,
            "total_duration_ms": self.total_duration_ms,
            "error": self.error,
            "execution_steps": [s.to_dict() for s in self.execution_steps],
            "review_steps": [s.to_dict() for s in self.review_steps],
            "recovery_steps": [s.to_dict() for s in self.recovery_steps],
        }


class SkillProtocolEnforcer:
    """
    Enforces structured step-by-step execution of skill protocols.

    Usage:
        from src.core.skills.models import SkillDefinition
        enforcer = SkillProtocolEnforcer()

        execution = enforcer.begin(skill)

        enforcer.start_step(execution, "Inspect router structure")
        # ... do work ...
        enforcer.complete_step(execution, output="Found 12 routes")

        enforcer.start_step(execution, "Add endpoint")
        # ... do work ...
        enforcer.complete_step(execution, output="Added GET /api/v1/health")

        enforcer.advance_to_review(execution)

        enforcer.start_step(execution, "Validate route registration")
        enforcer.complete_step(execution, output="Route registered successfully")

        enforcer.finalize(execution)
    """

    def begin(self, skill: Any) -> ProtocolExecution:
        """Begin protocol execution for a skill."""
        protocol = skill.protocol
        execution = ProtocolExecution(
            skill_name=skill.name,
            started_at=time.time(),
            execution_steps=[
                StepRecord(name=step, phase=ProtocolPhase.EXECUTION)
                for step in protocol.execution_steps
            ],
            review_steps=[
                StepRecord(name=step, phase=ProtocolPhase.REVIEW)
                for step in protocol.review_steps
            ],
            recovery_steps=[
                StepRecord(name=step, phase=ProtocolPhase.RECOVERY)
                for step in protocol.failure_recovery
            ],
        )
        logger.info(f"Protocol started: {skill.name} ({len(execution.execution_steps)} exec, {len(execution.review_steps)} review)")
        return execution

    def start_step(self, execution: ProtocolExecution, step_name: str) -> StepRecord:
        """Mark a step as in-progress."""
        steps = execution._current_steps()
        for step in steps:
            if step.name == step_name and step.status == StepStatus.PENDING:
                step.status = StepStatus.IN_PROGRESS
                step.started_at = time.time()
                logger.info(f"[{execution.skill_name}] Step started: {step_name}")
                return step

        raise ValueError(
            f"Step '{step_name}' not found or not pending in "
            f"{execution.phase.value} phase of '{execution.skill_name}'."
        )

    def complete_step(
        self,
        execution: ProtocolExecution,
        output: Optional[str] = None,
    ) -> StepRecord:
        """Mark the current in-progress step as completed."""
        steps = execution._current_steps()
        for step in steps:
            if step.status == StepStatus.IN_PROGRESS:
                step.status = StepStatus.COMPLETED
                step.completed_at = time.time()
                step.duration_ms = int((step.completed_at - (step.started_at or step.completed_at)) * 1000)
                step.output = output
                logger.info(f"[{execution.skill_name}] Step completed: {step.name} ({step.duration_ms}ms)")
                return step

        raise ValueError(
            f"No in-progress step found in {execution.phase.value} "
            f"phase of '{execution.skill_name}'."
        )

    def fail_step(
        self,
        execution: ProtocolExecution,
        error: str,
    ) -> StepRecord:
        """Mark the current in-progress step as failed."""
        steps = execution._current_steps()
        for step in steps:
            if step.status == StepStatus.IN_PROGRESS:
                step.status = StepStatus.FAILED
                step.completed_at = time.time()
                step.duration_ms = int((step.completed_at - (step.started_at or step.completed_at)) * 1000)
                step.error = error
                logger.warning(f"[{execution.skill_name}] Step failed: {step.name} — {error}")
                return step

        raise ValueError(
            f"No in-progress step found in {execution.phase.value} "
            f"phase of '{execution.skill_name}'."
        )

    def advance_to_review(self, execution: ProtocolExecution) -> None:
        """Transition from execution to review phase."""
        # Verify all execution steps are done
        incomplete = [
            s for s in execution.execution_steps
            if s.status not in (StepStatus.COMPLETED, StepStatus.SKIPPED)
        ]
        if incomplete:
            names = [s.name for s in incomplete]
            raise ValueError(
                f"Cannot advance to review: {len(incomplete)} execution step(s) "
                f"still pending: {names}"
            )
        execution.phase = ProtocolPhase.REVIEW
        logger.info(f"[{execution.skill_name}] Advanced to REVIEW phase")

    def trigger_recovery(self, execution: ProtocolExecution) -> None:
        """Transition to recovery phase after a failure."""
        execution.phase = ProtocolPhase.RECOVERY
        logger.warning(f"[{execution.skill_name}] Entered RECOVERY phase")

    def skip_step(self, execution: ProtocolExecution, step_name: str, reason: str = "") -> StepRecord:
        """Skip a pending step (with logged reason)."""
        steps = execution._current_steps()
        for step in steps:
            if step.name == step_name and step.status == StepStatus.PENDING:
                step.status = StepStatus.SKIPPED
                step.output = reason or "Skipped"
                logger.info(f"[{execution.skill_name}] Step skipped: {step_name} — {reason}")
                return step
        raise ValueError(f"Step '{step_name}' not found or not pending.")

    def finalize(self, execution: ProtocolExecution) -> ProtocolExecution:
        """Finalize the protocol execution."""
        execution.completed_at = time.time()

        # Check if all review steps passed
        failed_reviews = [s for s in execution.review_steps if s.status == StepStatus.FAILED]
        failed_exec = [s for s in execution.execution_steps if s.status == StepStatus.FAILED]

        if failed_reviews:
            execution.success = False
            execution.error = f"Review failed: {[s.name for s in failed_reviews]}"
        elif failed_exec:
            execution.success = False
            execution.error = f"Execution failed: {[s.name for s in failed_exec]}"
        else:
            execution.success = True

        logger.info(
            f"[{execution.skill_name}] Protocol finalized: "
            f"{'SUCCESS' if execution.success else 'FAILED'} "
            f"({execution.total_duration_ms}ms)"
        )
        return execution

    def get_progress(self, execution: ProtocolExecution) -> Dict[str, Any]:
        """Get current progress summary."""
        total = len(execution.execution_steps) + len(execution.review_steps)
        completed = sum(
            1 for s in execution.execution_steps + execution.review_steps
            if s.status == StepStatus.COMPLETED
        )
        return {
            "skill_name": execution.skill_name,
            "phase": execution.phase.value,
            "progress": f"{completed}/{total}",
            "percent": round(completed / total * 100, 1) if total > 0 else 0,
            "current_step": execution.current_step_index,
            "is_complete": execution.is_complete,
        }


# Module-level singleton
protocol_enforcer = SkillProtocolEnforcer()
