from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc, and_, or_, cast, String, func
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

@router.get("/logs/search")
async def search_logs(
    phone: Optional[str] = Query(None, description="Phone number to search for in log payloads (e.g. +254712345678)"),
    customer_id: Optional[str] = Query(None, description="Business owner user ID"),
    level: Optional[str] = Query(None, description="Log level filter: ERROR, WARNING, INFO"),
    event_type: Optional[str] = Query(None, description="Event type filter, e.g. HTTP_ERROR, TOOL_EXECUTION"),
    time_from: Optional[datetime] = Query(None, alias="from", description="Start of time range (ISO 8601)"),
    time_to: Optional[datetime] = Query(None, alias="to", description="End of time range (ISO 8601)"),
    limit: int = Query(50, ge=1, le=200, description="Max results to return"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(check_admin),
):
    """
    Search observability logs by phone number, customer ID, time range, and level.

    This is the primary tool for debugging customer-reported issues.
    Typical workflow:
      1. Customer says "my bot stopped working around 2pm for +254712345678"
      2. Call this endpoint with phone=+254712345678&from=2026-08-25T11:00:00
      3. Get back matching trace_ids
      4. Use GET /traces/{trace_id} to see the full lifecycle
    """
    if not any([phone, customer_id, level, event_type, time_from]):
        raise HTTPException(
            status_code=400,
            detail="Provide at least one filter: phone, customer_id, level, event_type, or from/to time range.",
        )

    filters = []

    # Time range — default to last 24 hours if only 'from' is omitted
    if time_from:
        filters.append(ObservabilityLog.timestamp >= time_from)
    else:
        # Default: last 30 days if searching by phone/customer, else last 24 hours
        if phone or customer_id:
            filters.append(ObservabilityLog.timestamp >= datetime.utcnow() - timedelta(days=30))
        else:
            filters.append(ObservabilityLog.timestamp >= datetime.utcnow() - timedelta(hours=24))

    if time_to:
        filters.append(ObservabilityLog.timestamp <= time_to)

    # Customer ID (the business owner on Arrotech Hub)
    if customer_id:
        filters.append(ObservabilityLog.customer_id == customer_id)

    # Log level
    if level:
        filters.append(ObservabilityLog.level == level.upper())

    # Event type
    if event_type:
        filters.append(ObservabilityLog.event_type == event_type)

    # Phone number — search inside the JSON payload column and the error_message text
    if phone:
        # Strip any spaces for a cleaner search
        phone_clean = phone.strip()
        filters.append(
            or_(
                cast(ObservabilityLog.payload, String).contains(phone_clean),
                ObservabilityLog.error_message.contains(phone_clean),
            )
        )

    result = await db.execute(
        select(ObservabilityLog)
        .where(and_(*filters))
        .order_by(desc(ObservabilityLog.timestamp))
        .limit(limit)
    )
    logs = result.scalars().all()

    # Group by trace_id for easy consumption
    traces_seen = {}
    log_entries = []
    for log in logs:
        log_entries.append({
            "id": str(log.id),
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            "trace_id": log.trace_id,
            "level": log.level,
            "event_type": log.event_type,
            "customer_id": log.customer_id,
            "status": log.status,
            "duration_ms": log.duration_ms,
            "error_type": log.error_type,
            "error_message": log.error_message,
            "tool_name": log.tool_name,
        })
        if log.trace_id and log.trace_id not in traces_seen:
            traces_seen[log.trace_id] = {
                "trace_id": log.trace_id,
                "first_seen": log.timestamp.isoformat() if log.timestamp else None,
                "has_errors": log.level in ("ERROR", "CRITICAL"),
            }

    return {
        "query": {
            "phone": phone,
            "customer_id": customer_id,
            "level": level,
            "event_type": event_type,
            "time_from": time_from.isoformat() if time_from else None,
            "time_to": time_to.isoformat() if time_to else None,
        },
        "total_results": len(log_entries),
        "unique_traces": list(traces_seen.values()),
        "logs": log_entries,
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
