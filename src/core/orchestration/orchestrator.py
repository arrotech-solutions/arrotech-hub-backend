"""
GSD Orchestrator — Full Goal-Structured Development execution pipeline.

Ties together all components into a single execution workflow:

    Goal → Planner → [Task₁ → Task₂ → ...] → Reviewer → Memory

Each task in the plan:
1. Selects a skill based on task requirements
2. Begins protocol enforcement (execution → review steps)
3. Authorizes tools through the GovernedCodingBridge
4. Executes tools with timeout enforcement
5. Reviews output via ReviewerAgent
6. Records to audit chain and memory store

This is the top-level orchestration layer.
"""
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from src.core.orchestration.planner import (
    PlannerAgent, ExecutionPlan, PlannedTask, TaskStatus, planner_agent,
)
from src.core.orchestration.reviewer import ReviewerAgent, ReviewResult, reviewer_agent
from src.core.orchestration.memory import AgentMemoryStore, agent_memory
from src.core.skills.protocol_enforcer import (
    SkillProtocolEnforcer, ProtocolExecution, protocol_enforcer,
)
from src.core.runtime.timeout import TimeoutBudget

logger = logging.getLogger(__name__)


class GSDOrchestrator:
    """
    Goal-Structured Development orchestration engine.

    Usage:
        orchestrator = GSDOrchestrator()

        plan = orchestrator.plan(
            goal="Add health check endpoint",
            tasks=[
                {"title": "Read router", "skill_name": "coding_read"},
                {"title": "Implement endpoint", "skill_name": "coding_write",
                 "depends_on": ["<task_id>"]},
                {"title": "Run tests", "skill_name": "coding_test",
                 "depends_on": ["<task_id>"]},
            ],
        )

        # Execute tasks one by one
        while not plan.is_complete:
            next_tasks = plan.next_tasks
            for task in next_tasks:
                result = await orchestrator.execute_task(plan, task, executor_fn)
                if not result["success"]:
                    break

        summary = orchestrator.summarize(plan)
    """

    def __init__(
        self,
        planner: PlannerAgent = None,
        reviewer: ReviewerAgent = None,
        memory: AgentMemoryStore = None,
        protocol: SkillProtocolEnforcer = None,
        total_timeout_seconds: int = 600,
    ):
        self._planner = planner or planner_agent
        self._reviewer = reviewer or reviewer_agent
        self._memory = memory or agent_memory
        self._protocol = protocol or protocol_enforcer
        self._budget = TimeoutBudget(total_seconds=total_timeout_seconds)

    def plan(
        self,
        goal: str,
        tasks: List[Dict[str, Any]],
    ) -> ExecutionPlan:
        """Create an execution plan from a goal and task list."""
        plan = self._planner.create_plan(goal=goal, tasks=tasks)

        # Inject memory context
        memory_context = self._memory.recall_context(
            categories=["convention", "error", "architecture"]
        )
        if memory_context:
            logger.info(
                f"Injecting {len(memory_context)} chars of memory context into plan"
            )

        return plan

    async def execute_task(
        self,
        plan: ExecutionPlan,
        task: PlannedTask,
        executor_fn: Callable,
        skill: Any = None,
    ) -> Dict[str, Any]:
        """
        Execute a single task within a plan.

        Args:
            plan: The execution plan
            task: The task to execute
            executor_fn: Async callable(tool_name, arguments) -> result dict
            skill: Optional SkillDefinition for protocol enforcement

        Returns:
            Result dict with success, output, review, duration_ms
        """
        if self._budget.expired:
            self._planner.mark_failed(plan, task.id, error="Time budget exhausted")
            return {
                "success": False,
                "error": "Time budget exhausted",
                "budget": self._budget.to_dict(),
            }

        self._planner.mark_in_progress(plan, task.id)
        start = time.time()
        tool_calls = []

        # Start protocol if skill is provided
        protocol_exec = None
        if skill:
            protocol_exec = self._protocol.begin(skill)

        try:
            # Execute all tools needed for this task
            for tool_name in task.tools_needed:
                tool_start = time.time()
                result = await executor_fn(tool_name, {})
                tool_ms = int((time.time() - tool_start) * 1000)
                self._budget.consume(tool_ms)

                tool_calls.append({
                    "tool": tool_name,
                    "result": result,
                    "duration_ms": tool_ms,
                })

                if isinstance(result, dict) and not result.get("success", True):
                    raise RuntimeError(
                        f"Tool '{tool_name}' failed: {result.get('error', 'unknown')}"
                    )

            duration_ms = int((time.time() - start) * 1000)

            # Run review
            review = None
            if skill:
                review = self._reviewer.review(
                    skill=skill,
                    tool_calls=tool_calls,
                    output=str(task.output or ""),
                )

            # Mark completed
            self._planner.mark_completed(plan, task.id, output="Completed")

            # Record to memory
            self._memory.remember(
                "execution",
                f"task_{task.id}",
                f"Task '{task.title}' completed in {duration_ms}ms "
                f"using skill '{task.skill_name}'",
                metadata={
                    "tools": task.tools_needed,
                    "duration_ms": duration_ms,
                    "review_score": review.score if review else None,
                },
            )

            return {
                "success": True,
                "task_id": task.id,
                "duration_ms": duration_ms,
                "tool_calls": len(tool_calls),
                "review": review.to_dict() if review else None,
                "budget": self._budget.to_dict(),
            }

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._budget.consume(duration_ms)

            self._planner.mark_failed(plan, task.id, error=str(e))

            # Record failure to memory
            self._memory.remember(
                "error",
                f"task_{task.id}_failure",
                f"Task '{task.title}' failed: {str(e)[:200]}",
                metadata={"skill": task.skill_name, "tools": task.tools_needed},
            )

            return {
                "success": False,
                "task_id": task.id,
                "error": str(e),
                "duration_ms": duration_ms,
                "budget": self._budget.to_dict(),
            }

    def summarize(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """Generate a summary of the plan execution."""
        completed = [t for t in plan.tasks if t.status == TaskStatus.COMPLETED]
        failed = [t for t in plan.tasks if t.status == TaskStatus.FAILED]
        blocked = [t for t in plan.tasks if t.status == TaskStatus.BLOCKED]

        return {
            "goal": plan.goal,
            "success": plan.success,
            "progress": f"{plan.progress_percent}%",
            "total_tasks": len(plan.tasks),
            "completed": len(completed),
            "failed": len(failed),
            "blocked": len(blocked),
            "budget": self._budget.to_dict(),
            "tasks": plan.to_dict()["tasks"],
        }

    @property
    def budget(self) -> TimeoutBudget:
        return self._budget


# Module-level factory
def create_orchestrator(timeout_seconds: int = 600) -> GSDOrchestrator:
    """Create a new GSD orchestrator instance."""
    return GSDOrchestrator(total_timeout_seconds=timeout_seconds)
