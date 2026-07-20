"""
Harness Engineering — Internal monitoring API.

Provides endpoints for monitoring the health and effectiveness of the
harness engineering components: guardrails, feedback loops, quality gates,
and Code Mode execution metrics.

All endpoints are under /_internal/harness/ and are intended for
internal dashboarding and operational visibility.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import ObservabilityLog

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/_internal/harness", tags=["Harness Engineering"])


@router.get("/health")
async def harness_health():
    """Health check for harness engineering subsystem."""
    return {
        "status": "healthy",
        "components": {
            "guardrails": "active",
            "feedback_loops": "active",
            "quality_gates": "active",
            "agent_context": "active",
            "code_mode": "active",
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/guardrails/stats")
async def guardrail_stats(
    hours: int = Query(default=24, description="Lookback window in hours"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get guardrail trigger statistics.
    
    Returns counts of guardrail blocks and warnings grouped by rule name.
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    try:
        stmt = (
            select(
                ObservabilityLog.payload["rule_name"].as_string().label("rule_name"),
                ObservabilityLog.status,
                func.count().label("count"),
            )
            .where(
                and_(
                    ObservabilityLog.event_type == "GUARDRAIL_CHECK",
                    ObservabilityLog.timestamp >= cutoff,
                )
            )
            .group_by("rule_name", ObservabilityLog.status)
            .order_by(func.count().desc())
        )
        
        result = await db.execute(stmt)
        rows = result.fetchall()
        
        stats = {}
        for row in rows:
            rule = row.rule_name or "unknown"
            if rule not in stats:
                stats[rule] = {"blocked": 0, "warned": 0, "passed": 0}
            stats[rule][row.status or "passed"] = row.count
        
        return {
            "window_hours": hours,
            "rules": stats,
            "total_checks": sum(r.count for r in rows),
        }
    except Exception as e:
        logger.warning(f"Failed to fetch guardrail stats: {e}")
        return {
            "window_hours": hours,
            "rules": {},
            "total_checks": 0,
            "note": "Stats unavailable — observability logs may not have harness events yet.",
        }


@router.get("/feedback/patterns")
async def feedback_patterns(
    hours: int = Query(default=24, description="Lookback window in hours"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get error patterns and auto-correction success rates.
    
    Returns recurring error patterns grouped by tool and error category.
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    try:
        stmt = (
            select(
                ObservabilityLog.tool_name,
                ObservabilityLog.payload["error_category"].as_string().label("category"),
                ObservabilityLog.status,
                func.count().label("count"),
            )
            .where(
                and_(
                    ObservabilityLog.event_type == "FEEDBACK_LOOP",
                    ObservabilityLog.timestamp >= cutoff,
                )
            )
            .group_by(ObservabilityLog.tool_name, "category", ObservabilityLog.status)
            .order_by(func.count().desc())
        )
        
        result = await db.execute(stmt)
        rows = result.fetchall()
        
        patterns = []
        for row in rows:
            patterns.append({
                "tool_name": row.tool_name,
                "error_category": row.category,
                "status": row.status,
                "count": row.count,
            })
        
        return {
            "window_hours": hours,
            "patterns": patterns,
        }
    except Exception as e:
        logger.warning(f"Failed to fetch feedback patterns: {e}")
        return {
            "window_hours": hours,
            "patterns": [],
            "note": "Patterns unavailable — observability logs may not have harness events yet.",
        }


@router.get("/quality/scores")
async def quality_scores(
    hours: int = Query(default=24, description="Lookback window in hours"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get quality gate score distribution.
    
    Returns average scores and pass/fail counts.
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    try:
        # Get pass/fail counts
        stmt = (
            select(
                ObservabilityLog.status,
                func.count().label("count"),
            )
            .where(
                and_(
                    ObservabilityLog.event_type.in_(["QUALITY_GATE_PASS", "QUALITY_GATE_FAIL"]),
                    ObservabilityLog.timestamp >= cutoff,
                )
            )
            .group_by(ObservabilityLog.status)
        )
        
        result = await db.execute(stmt)
        rows = result.fetchall()
        
        counts = {row.status: row.count for row in rows}
        total = sum(counts.values())
        
        return {
            "window_hours": hours,
            "total_evaluations": total,
            "passed": counts.get("success", 0),
            "failed": counts.get("failed", 0),
            "pass_rate": counts.get("success", 0) / total if total > 0 else 0,
        }
    except Exception as e:
        logger.warning(f"Failed to fetch quality scores: {e}")
        return {
            "window_hours": hours,
            "total_evaluations": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0,
            "note": "Scores unavailable — observability logs may not have harness events yet.",
        }


@router.get("/codemode/metrics")
async def codemode_metrics(
    hours: int = Query(default=24, description="Lookback window in hours"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get Code Mode usage and performance metrics.
    
    Returns execution counts, success rates, token savings, and error distribution.
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    try:
        stmt = (
            select(
                ObservabilityLog.status,
                func.count().label("count"),
                func.avg(ObservabilityLog.duration_ms).label("avg_duration"),
            )
            .where(
                and_(
                    ObservabilityLog.event_type == "CODE_MODE_EXECUTION",
                    ObservabilityLog.timestamp >= cutoff,
                )
            )
            .group_by(ObservabilityLog.status)
        )
        
        result = await db.execute(stmt)
        rows = result.fetchall()
        
        total = sum(r.count for r in rows)
        success_count = sum(r.count for r in rows if r.status == "success")
        avg_duration = sum(r.avg_duration or 0 for r in rows) / len(rows) if rows else 0
        
        return {
            "window_hours": hours,
            "total_executions": total,
            "success_count": success_count,
            "failure_count": total - success_count,
            "success_rate": success_count / total if total > 0 else 0,
            "avg_execution_ms": round(avg_duration),
        }
    except Exception as e:
        logger.warning(f"Failed to fetch codemode metrics: {e}")
        return {
            "window_hours": hours,
            "total_executions": 0,
            "success_count": 0,
            "failure_count": 0,
            "success_rate": 0,
            "avg_execution_ms": 0,
            "note": "Metrics unavailable — observability logs may not have harness events yet.",
        }
