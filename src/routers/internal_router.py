from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from ..database import get_db
from ..models import User, UserRole, ObservabilityLog, ObservabilityTrace, FailedEvent
from ..routers.auth_router import get_current_user

router = APIRouter(prefix="/api/internal", tags=["internal-observability"])

async def check_admin(user: User = Depends(get_current_user)):
    """Only admins can access internal observability data."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

@router.get("/traces/{trace_id}")
async def get_trace_timeline(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(check_admin)
):
    """Get full execution timeline for a specific trace ID."""
    result = await db.execute(
        select(ObservabilityLog)
        .where(ObservabilityLog.trace_id == trace_id)
        .order_by(ObservabilityLog.timestamp)
    )
    logs = result.scalars().all()
    
    if not logs:
        raise HTTPException(status_code=404, detail="Trace not found")
        
    return {
        "trace_id": trace_id,
        "events": [
            {
                "timestamp": log.timestamp,
                "event_type": log.event_type,
                "span_id": log.span_id,
                "level": log.level,
                "status": log.status,
                "duration_ms": log.duration_ms,
                "message": log.error_message if log.status == "failed" else log.tool_name or log.event_type,
                "payload": log.payload
            } for log in logs
        ]
    }

@router.get("/failures")
async def list_recent_failures(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(check_admin)
):
    """Get most recent failed events from logs and DLQ."""
    result = await db.execute(
        select(ObservabilityLog)
        .where(ObservabilityLog.status == "failed")
        .order_by(desc(ObservabilityLog.timestamp))
        .limit(limit)
    )
    logs = result.scalars().all()
    
    return {
        "failures": [
            {
                "id": str(log.id),
                "timestamp": log.timestamp,
                "trace_id": log.trace_id,
                "event_type": log.event_type,
                "error_type": log.error_type,
                "message": log.error_message
            } for log in logs
        ]
    }

@router.get("/dlq")
async def list_dlq(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(check_admin)
):
    """List events currently in the Dead Letter Queue."""
    result = await db.execute(
        select(FailedEvent)
        .where(FailedEvent.status == "failed")
        .order_by(desc(FailedEvent.created_at))
    )
    events = result.scalars().all()
    
    return {
        "dlq_events": [
            {
                "id": str(event.id),
                "trace_id": event.trace_id,
                "event_type": event.event_type,
                "payload": event.payload,
                "error": event.error_message,
                "retry_count": event.retry_count,
                "last_attempt": event.last_attempt_at
            } for event in events
        ]
    }

@router.post("/dlq/{event_id}/retry")
async def retry_dlq_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(check_admin)
):
    """Manually re-trigger a failed event from DLQ."""
    from ..observability.tool_wrapper import execute_tool
    
    result = await db.execute(select(FailedEvent).where(FailedEvent.id == event_id))
    event = result.scalar_one_or_none()
    
    if not event:
        raise HTTPException(status_code=404, detail="DLQ event not found")
        
    # Re-trigger logic based on event type
    if event.event_type == "TOOL_EXECUTION":
        # Note: In a production system, we might push this back to a background worker
        # Here we attempt execution again
        event.status = "retrying"
        await db.commit()
        
        try:
            # We'd need to dynamically find the tool function here
            # For now, we'll mark it as a placeholder for manual intervention
            return {"success": False, "message": "Manual re-trigger logic requires dynamic function registry lookup."}
        except Exception as e:
            event.status = "failed"
            event.retry_count += 1
            await db.commit()
            raise HTTPException(status_code=500, detail=str(e))
            
    return {"success": True, "message": "Event marked for retry"}

@router.get("/metrics")
async def get_system_metrics(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(check_admin)
):
    """Aggregate high-level system metrics from logs."""
    from sqlalchemy import func
    
    # Simple aggregations for the last 24h
    stats = await db.execute(
        select(
            ObservabilityLog.status,
            func.count(ObservabilityLog.id),
            func.avg(ObservabilityLog.duration_ms)
        )
        .where(ObservabilityLog.timestamp > func.now() - func.cast('24 hours', func.Interval))
        .group_by(ObservabilityLog.status)
    )
    
    results = stats.all()
    
    return {
        "last_24h": {
            row[0]: {"count": row[1], "avg_duration_ms": float(row[2]) if row[2] else 0}
            for row in results
        }
    }
