"""
Planner Agent — Goal-Structured Development task decomposition.

Breaks high-level goals into structured task plans with:
- Skill selection based on task requirements
- Dependency ordering between tasks
- Estimated complexity and risk assessment
- Checkpoint markers for rollback safety

This is the "brain" of the GSD workflow — it plans BEFORE execution.
"""
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from uuid import uuid4

logger = logging.getLogger(__name__)


class TaskPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskStatus(str, Enum):
    PLANNED = "planned"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


@dataclass
class PlannedTask:
    """A single task within an execution plan."""
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    title: str = ""
    description: str = ""
    skill_name: str = ""
    tools_needed: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PLANNED
    estimated_complexity: int = 1  # 1-5 scale
    requires_human_approval: bool = False
    checkpoint: bool = False  # If True, pause for review after this task
    output: Optional[str] = None
    error: Optional[str] = None

    @property
    def is_ready(self) -> bool:
        """Task is ready when all dependencies are completed."""
        return self.status == TaskStatus.READY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "skill_name": self.skill_name,
            "tools_needed": self.tools_needed,
            "depends_on": self.depends_on,
            "priority": self.priority.value,
            "status": self.status.value,
            "estimated_complexity": self.estimated_complexity,
            "requires_human_approval": self.requires_human_approval,
            "checkpoint": self.checkpoint,
            "output": self.output,
            "error": self.error,
        }


@dataclass
class ExecutionPlan:
    """A structured plan for achieving a goal."""
    id: str = field(default_factory=lambda: str(uuid4())[:12])
    goal: str = ""
    tasks: List[PlannedTask] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    success: bool = False

    @property
    def is_complete(self) -> bool:
        return all(
            t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
            for t in self.tasks
        )

    @property
    def progress_percent(self) -> float:
        if not self.tasks:
            return 0.0
        done = sum(1 for t in self.tasks if t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED))
        return round(done / len(self.tasks) * 100, 1)

    @property
    def next_tasks(self) -> List[PlannedTask]:
        """Get tasks that are ready to execute (dependencies met)."""
        completed_ids = {t.id for t in self.tasks if t.status == TaskStatus.COMPLETED}
        ready = []
        for task in self.tasks:
            if task.status != TaskStatus.PLANNED:
                continue
            deps_met = all(dep in completed_ids for dep in task.depends_on)
            if deps_met:
                ready.append(task)
        return ready

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "progress": f"{self.progress_percent}%",
            "task_count": len(self.tasks),
            "success": self.success,
            "tasks": [t.to_dict() for t in self.tasks],
        }


class PlannerAgent:
    """
    Decomposes goals into structured task plans.

    The planner uses skill definitions and tool registries to determine
    which skills and tools are needed for each task, and orders them
    based on dependencies.

    Usage:
        planner = PlannerAgent()
        plan = planner.create_plan(
            goal="Add a health check endpoint",
            available_skills=registry.all(),
        )
        for task in plan.next_tasks:
            # execute task...
            planner.mark_completed(plan, task.id, output="Done")
    """

    def create_plan(
        self,
        goal: str,
        tasks: List[Dict[str, Any]],
    ) -> ExecutionPlan:
        """
        Create an execution plan from a structured task list.

        Args:
            goal: The high-level goal description
            tasks: List of task definitions, each containing:
                - title: str
                - description: str (optional)
                - skill_name: str
                - tools_needed: List[str] (optional)
                - depends_on: List[str] (task IDs, optional)
                - priority: str (optional, default "medium")
                - complexity: int (optional, 1-5)
                - checkpoint: bool (optional)
        """
        plan = ExecutionPlan(goal=goal)

        for task_def in tasks:
            task = PlannedTask(
                title=task_def["title"],
                description=task_def.get("description", ""),
                skill_name=task_def.get("skill_name", ""),
                tools_needed=task_def.get("tools_needed", []),
                depends_on=task_def.get("depends_on", []),
                priority=TaskPriority(task_def.get("priority", "medium")),
                estimated_complexity=task_def.get("complexity", 1),
                requires_human_approval=task_def.get("requires_human_approval", False),
                checkpoint=task_def.get("checkpoint", False),
            )
            plan.tasks.append(task)

        # Mark tasks with no dependencies as READY
        self._resolve_ready_tasks(plan)

        logger.info(
            f"Plan created: '{goal}' — {len(plan.tasks)} tasks, "
            f"{len(plan.next_tasks)} ready"
        )
        return plan

    def mark_completed(
        self, plan: ExecutionPlan, task_id: str, output: str = ""
    ) -> None:
        """Mark a task as completed and resolve dependencies."""
        task = self._find_task(plan, task_id)
        task.status = TaskStatus.COMPLETED
        task.output = output
        self._resolve_ready_tasks(plan)

        if plan.is_complete:
            plan.completed_at = time.time()
            plan.success = True
            logger.info(f"Plan completed: '{plan.goal}'")

    def mark_failed(
        self, plan: ExecutionPlan, task_id: str, error: str
    ) -> None:
        """Mark a task as failed and block dependents."""
        task = self._find_task(plan, task_id)
        task.status = TaskStatus.FAILED
        task.error = error

        # Block all tasks that depend on this one
        for other in plan.tasks:
            if task_id in other.depends_on and other.status == TaskStatus.PLANNED:
                other.status = TaskStatus.BLOCKED
                logger.warning(f"Task '{other.title}' blocked by failed '{task.title}'")

    def mark_in_progress(self, plan: ExecutionPlan, task_id: str) -> None:
        """Mark a task as in-progress."""
        task = self._find_task(plan, task_id)
        task.status = TaskStatus.IN_PROGRESS

    def skip_task(self, plan: ExecutionPlan, task_id: str, reason: str = "") -> None:
        """Skip a task and resolve dependencies."""
        task = self._find_task(plan, task_id)
        task.status = TaskStatus.SKIPPED
        task.output = reason or "Skipped"
        self._resolve_ready_tasks(plan)

    def _find_task(self, plan: ExecutionPlan, task_id: str) -> PlannedTask:
        for task in plan.tasks:
            if task.id == task_id:
                return task
        raise ValueError(f"Task not found: {task_id}")

    def _resolve_ready_tasks(self, plan: ExecutionPlan) -> None:
        """Mark tasks as READY when all their dependencies are met."""
        completed_ids = {
            t.id for t in plan.tasks
            if t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
        }
        for task in plan.tasks:
            if task.status != TaskStatus.PLANNED:
                continue
            if all(dep in completed_ids for dep in task.depends_on):
                task.status = TaskStatus.READY


# Module-level singleton
planner_agent = PlannerAgent()
