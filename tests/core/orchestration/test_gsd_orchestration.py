"""
Tests for GSD orchestration components: Protocol Enforcer, Planner, Reviewer, Memory.
"""
import pytest
from src.core.skills.models import (
    SkillDefinition, SkillCapability, SkillProtocol,
    ValidationRule, SkillExecutionContract, ExecutionConstraint,
    ToolPermission, SkillRiskLevel, EnvironmentScope,
)
from src.core.skills.protocol_enforcer import (
    SkillProtocolEnforcer, ProtocolExecution, StepStatus, ProtocolPhase,
)
from src.core.orchestration.planner import (
    PlannerAgent, ExecutionPlan, TaskStatus, TaskPriority,
)
from src.core.orchestration.reviewer import ReviewerAgent, ReviewResult
from src.core.orchestration.memory import AgentMemoryStore


def _make_skill(name="test_skill"):
    return SkillDefinition(
        name=name,
        description="Test skill",
        capability=SkillCapability.BACKEND,
        triggers=["test"],
        system_prompt="Test",
        protocol=SkillProtocol(
            execution_steps=["Analyze code", "Implement changes", "Verify"],
            review_steps=["Validate syntax", "Check coverage"],
            failure_recovery=["Rollback changes"],
        ),
        validation_rules=[ValidationRule(name="syntax_valid")],
        execution_contract=SkillExecutionContract(
            allowed_tools=[
                ToolPermission(tool_name="coding_file_read"),
                ToolPermission(tool_name="coding_file_write"),
            ],
            forbidden_actions=["delete_database"],
            required_validations=["syntax_valid"],
            constraints=ExecutionConstraint(
                allowed_environments=[EnvironmentScope.LOCAL, EnvironmentScope.DEVELOPMENT],
                allow_file_mutation=True,
            ),
            risk_level=SkillRiskLevel.MEDIUM,
            contract_version=1,
        ),
    )


# ==================================================================
# PROTOCOL ENFORCER TESTS
# ==================================================================

class TestProtocolEnforcer:
    def test_begin_creates_execution(self):
        enforcer = SkillProtocolEnforcer()
        skill = _make_skill()
        execution = enforcer.begin(skill)
        assert len(execution.execution_steps) == 3
        assert len(execution.review_steps) == 2
        assert len(execution.recovery_steps) == 1
        assert execution.phase == ProtocolPhase.EXECUTION

    def test_step_lifecycle(self):
        enforcer = SkillProtocolEnforcer()
        execution = enforcer.begin(_make_skill())

        step = enforcer.start_step(execution, "Analyze code")
        assert step.status == StepStatus.IN_PROGRESS

        step = enforcer.complete_step(execution, output="Found 5 files")
        assert step.status == StepStatus.COMPLETED
        assert step.output == "Found 5 files"
        assert step.duration_ms >= 0

    def test_fail_step(self):
        enforcer = SkillProtocolEnforcer()
        execution = enforcer.begin(_make_skill())

        enforcer.start_step(execution, "Analyze code")
        step = enforcer.fail_step(execution, error="File not found")
        assert step.status == StepStatus.FAILED
        assert step.error == "File not found"

    def test_cannot_advance_with_pending_steps(self):
        enforcer = SkillProtocolEnforcer()
        execution = enforcer.begin(_make_skill())

        with pytest.raises(ValueError, match="Cannot advance"):
            enforcer.advance_to_review(execution)

    def test_full_protocol_lifecycle(self):
        enforcer = SkillProtocolEnforcer()
        execution = enforcer.begin(_make_skill())

        # Execute all steps
        for name in ["Analyze code", "Implement changes", "Verify"]:
            enforcer.start_step(execution, name)
            enforcer.complete_step(execution, output=f"{name} done")

        # Advance to review
        enforcer.advance_to_review(execution)
        assert execution.phase == ProtocolPhase.REVIEW

        # Review steps
        for name in ["Validate syntax", "Check coverage"]:
            enforcer.start_step(execution, name)
            enforcer.complete_step(execution, output="Passed")

        # Finalize
        result = enforcer.finalize(execution)
        assert result.success is True
        assert result.is_complete is True

    def test_skip_step(self):
        enforcer = SkillProtocolEnforcer()
        execution = enforcer.begin(_make_skill())

        enforcer.skip_step(execution, "Analyze code", reason="Already analyzed")
        assert execution.execution_steps[0].status == StepStatus.SKIPPED

    def test_progress_tracking(self):
        enforcer = SkillProtocolEnforcer()
        execution = enforcer.begin(_make_skill())

        progress = enforcer.get_progress(execution)
        assert progress["percent"] == 0.0

        enforcer.start_step(execution, "Analyze code")
        enforcer.complete_step(execution)

        progress = enforcer.get_progress(execution)
        assert progress["percent"] == 20.0  # 1 of 5 total steps

    def test_recovery_phase(self):
        enforcer = SkillProtocolEnforcer()
        execution = enforcer.begin(_make_skill())

        enforcer.trigger_recovery(execution)
        assert execution.phase == ProtocolPhase.RECOVERY

        enforcer.start_step(execution, "Rollback changes")
        enforcer.complete_step(execution, output="Rolled back")


# ==================================================================
# PLANNER TESTS
# ==================================================================

class TestPlanner:
    def test_create_plan(self):
        planner = PlannerAgent()
        plan = planner.create_plan(
            goal="Add health endpoint",
            tasks=[
                {"title": "Read router", "skill_name": "coding_read"},
                {"title": "Add endpoint", "skill_name": "coding_write", "depends_on": []},
            ],
        )
        assert len(plan.tasks) == 2
        assert plan.progress_percent == 0.0

    def test_dependency_resolution(self):
        planner = PlannerAgent()
        plan = planner.create_plan(
            goal="Test feature",
            tasks=[
                {"title": "Write code", "skill_name": "coding_write"},
                {"title": "Write tests", "skill_name": "coding_write"},
            ],
        )

        # Both should be READY (no deps)
        ready = plan.next_tasks
        assert len(ready) == 2

    def test_dependency_blocking(self):
        planner = PlannerAgent()
        plan = planner.create_plan(
            goal="Test feature",
            tasks=[
                {"title": "Write code", "skill_name": "coding_write"},
            ],
        )

        # Add a dependent task manually
        from src.core.orchestration.planner import PlannedTask
        code_task = plan.tasks[0]
        test_task = PlannedTask(
            title="Run tests", skill_name="coding_test",
            depends_on=[code_task.id],
        )
        plan.tasks.append(test_task)

        # Only first task should be ready
        assert len(plan.next_tasks) == 1
        assert plan.next_tasks[0].title == "Write code"

        # Complete first task
        planner.mark_completed(plan, code_task.id, output="Done")

        # Now second should be ready
        planner._resolve_ready_tasks(plan)
        assert test_task.status == TaskStatus.READY

    def test_failure_blocks_dependents(self):
        planner = PlannerAgent()
        plan = planner.create_plan(
            goal="Deploy",
            tasks=[
                {"title": "Build", "skill_name": "coding_command"},
            ],
        )
        from src.core.orchestration.planner import PlannedTask
        build_task = plan.tasks[0]
        deploy_task = PlannedTask(
            title="Deploy", skill_name="coding_command",
            depends_on=[build_task.id],
        )
        plan.tasks.append(deploy_task)

        planner.mark_failed(plan, build_task.id, error="Build failed")
        assert deploy_task.status == TaskStatus.BLOCKED

    def test_plan_completion(self):
        planner = PlannerAgent()
        plan = planner.create_plan(
            goal="Simple task",
            tasks=[{"title": "Do it", "skill_name": "coding_write"}],
        )
        planner.mark_completed(plan, plan.tasks[0].id, output="Done")
        assert plan.is_complete is True
        assert plan.success is True


# ==================================================================
# REVIEWER TESTS
# ==================================================================

class TestReviewer:
    def test_clean_review_passes(self):
        reviewer = ReviewerAgent()
        skill = _make_skill()
        result = reviewer.review(
            skill=skill,
            tool_calls=[
                {"tool": "coding_file_read", "result": {"success": True}},
            ],
            output="Implementation complete. All files validated.",
        )
        assert result.passed is True
        assert result.score >= 0.7

    def test_forbidden_tool_detection(self):
        reviewer = ReviewerAgent()
        skill = _make_skill()
        result = reviewer.review(
            skill=skill,
            tool_calls=[
                {"tool": "coding_run_command", "result": {"success": True}},
            ],
            output="Ran shell command",
        )
        assert len(result.findings) > 0
        assert any("Unauthorized" in f for f in result.findings)

    def test_security_violation_detection(self):
        reviewer = ReviewerAgent()
        skill = _make_skill()
        result = reviewer.review(
            skill=skill,
            tool_calls=[],
            output="Your API key is sk-1234567890abcdefghijklmnop",
        )
        assert any("SECURITY" in f for f in result.findings)

    def test_high_error_rate_detection(self):
        reviewer = ReviewerAgent()
        skill = _make_skill()
        result = reviewer.review(
            skill=skill,
            tool_calls=[
                {"tool": "coding_file_read", "result": {"error": "Not found"}},
                {"tool": "coding_file_read", "result": {"error": "Timeout"}},
                {"tool": "coding_file_read", "result": {"success": True}},
            ],
            output="Partially completed",
        )
        assert len(result.findings) > 0 or len(result.warnings) > 0


# ==================================================================
# MEMORY TESTS
# ==================================================================

class TestMemory:
    def test_remember_and_recall(self):
        memory = AgentMemoryStore()
        memory.remember("convention", "naming", "Use snake_case")
        entry = memory.recall("convention", "naming")
        assert entry is not None
        assert entry.content == "Use snake_case"
        assert entry.access_count == 1

    def test_recall_category(self):
        memory = AgentMemoryStore()
        memory.remember("convention", "naming", "Use snake_case")
        memory.remember("convention", "imports", "Sort imports alphabetically")
        entries = memory.recall_category("convention")
        assert len(entries) == 2

    def test_recall_context_formatting(self):
        memory = AgentMemoryStore()
        memory.remember("convention", "naming", "Use snake_case")
        memory.remember("error", "circular", "Don't import audit from immutability")
        context = memory.recall_context(categories=["convention", "error"])
        assert "## Convention" in context
        assert "## Error" in context
        assert "snake_case" in context

    def test_search(self):
        memory = AgentMemoryStore()
        memory.remember("convention", "naming", "Use snake_case for Python")
        memory.remember("convention", "typing", "Use type hints everywhere")
        results = memory.search("snake")
        assert len(results) == 1
        assert results[0].key == "naming"

    def test_forget(self):
        memory = AgentMemoryStore()
        memory.remember("convention", "naming", "Use snake_case")
        assert memory.forget("convention", "naming") is True
        assert memory.recall("convention", "naming") is None

    def test_eviction_at_capacity(self):
        memory = AgentMemoryStore(max_entries_per_category=3)
        memory.remember("test", "a", "First")
        memory.remember("test", "b", "Second")
        memory.remember("test", "c", "Third")
        memory.remember("test", "d", "Fourth")  # Should evict "a"
        assert memory.recall("test", "a") is None
        assert memory.recall("test", "d") is not None

    def test_stats(self):
        memory = AgentMemoryStore()
        memory.remember("convention", "a", "X")
        memory.remember("error", "b", "Y")
        stats = memory.stats()
        assert stats["total_entries"] == 2
        assert stats["categories"]["convention"] == 1

    def test_singleton_has_preloaded_knowledge(self):
        from src.core.orchestration.memory import agent_memory
        entry = agent_memory.recall("architecture", "governance_model")
        assert entry is not None
        assert "GovernedCodingBridge" in entry.content
