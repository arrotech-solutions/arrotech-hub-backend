"""
Harness Engineering Framework for Arrotech Hub.

Implements OpenAI's Harness Engineering methodology — the execution environment
infrastructure that makes AI agents reliable, self-correcting, and observable.

Three pillars:
1. Guardrails — Preventive controls (pre-execution validation)
2. Feedback Loops — Corrective controls (automated self-correction)
3. Quality Gates — Evaluation checkpoints (output scoring)
4. Agent Context — Living documentation (AGENTS.md equivalent)

Reference: https://openai.com/index/harness-engineering/
"""

from .guardrails import AgentGuardrails, GuardrailResult
from .feedback_loops import FeedbackLoop, FeedbackAction
from .quality_gates import QualityGate, QualityScore
from .agent_context import AgentContext
from .mixin import HarnessedExecutionMixin

__all__ = [
    "AgentGuardrails",
    "GuardrailResult",
    "FeedbackLoop",
    "FeedbackAction",
    "QualityGate",
    "QualityScore",
    "AgentContext",
    "HarnessedExecutionMixin",
]
