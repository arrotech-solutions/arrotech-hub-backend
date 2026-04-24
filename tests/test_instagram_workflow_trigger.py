"""Tests for src/services/instagram_workflow_trigger.py"""
import pytest

class TestInstagramWorkflowTrigger:
    def test_import(self):
        from src.services.instagram_workflow_trigger import InstagramWorkflowTrigger
        assert InstagramWorkflowTrigger is not None
