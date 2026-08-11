"""Tests for workflow router vs executable step classification."""
import uuid
from types import SimpleNamespace

import pytest

from src.services.workflow_builder_service import WorkflowBuilderService


def _step(tool_name: str, condition=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        step_number=1,
        tool_name=tool_name,
        tool_parameters={},
        condition=condition,
    )


class TestIsRouterStep:
    def test_condition_router_is_router(self):
        svc = WorkflowBuilderService()
        assert svc._is_router_step(_step("condition_router"), {"type": "router", "branches": {}})

    def test_rag_ingest_with_stale_router_condition_is_not_router(self):
        svc = WorkflowBuilderService()
        stale = {"type": "router", "expression": "", "branches": {}}
        assert not svc._is_router_step(_step("rag_ingest_source"), stale)

    def test_rag_ingest_with_branch_metadata_is_not_router(self):
        svc = WorkflowBuilderService()
        stale = {"type": "router", "expression": "", "branches": {"true": 2}}
        assert not svc._is_router_step(_step("rag_ingest_source"), stale)


class TestSanitizeStepCondition:
    def test_strips_condition_from_tool_steps(self):
        stale = {"type": "router", "branches": {"true": 2}}
        assert WorkflowBuilderService._sanitize_step_condition("rag_ingest_source", stale) is None

    def test_keeps_condition_on_router(self):
        cond = {"type": "router", "branches": {"true": 2}}
        assert WorkflowBuilderService._sanitize_step_condition("condition_router", cond) == cond
