import json
import logging
import datetime
import asyncio
from typing import Any, Dict, Optional
import sys

from .tracer import get_trace_id, get_span_id, get_customer_id

class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for production logs."""
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "trace_id": get_trace_id(),
            "span_id": get_span_id(),
            "customer_id": get_customer_id(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add extra attributes from record if they exist
        if hasattr(record, "event_type"):
            log_data["event_type"] = record.event_type
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms
        if hasattr(record, "status"):
            log_data["status"] = record.status
        
        # Add exception info if present
        if record.exc_info:
            log_data["error_type"] = record.exc_info[0].__name__
            log_data["error_message"] = str(record.exc_info[1])
            log_data["stack_trace"] = self.formatException(record.exc_info)
            
        return json.dumps(log_data)

# Global queue for async DB logging
log_queue = asyncio.Queue()

async def db_log_worker():
    """Background worker to persist logs from queue to database."""
    from ..database import get_session_maker
    from ..models import ObservabilityLog
    
    session_maker = get_session_maker()
    
    while True:
        # Get a batch of logs
        logs_to_persist = []
        try:
            # Wait for at least one log
            first_log = await log_queue.get()
            logs_to_persist.append(first_log)
            
            # Try to get more logs quickly (up to 50 or until queue empty)
            for _ in range(49):
                try:
                    next_log = log_queue.get_nowait()
                    logs_to_persist.append(next_log)
                except asyncio.QueueEmpty:
                    break
            
            # Persist batch
            async with session_maker() as session:
                for log_data in logs_to_persist:
                    db_log = ObservabilityLog(
                        level=log_data.get("level", "INFO"),
                        trace_id=log_data.get("trace_id"),
                        span_id=log_data.get("span_id"),
                        event_type=log_data.get("event_type", "GENERIC"),
                        customer_id=log_data.get("customer_id"),
                        agent_id=log_data.get("agent_id"),
                        workflow_id=log_data.get("workflow_id"),
                        tool_name=log_data.get("tool_name"),
                        step_name=log_data.get("step_name"),
                        status=log_data.get("status"),
                        duration_ms=log_data.get("duration_ms"),
                        retry_count=log_data.get("retry_count", 0),
                        payload=log_data.get("payload"),
                        error_type=log_data.get("error_type"),
                        error_message=log_data.get("error_message"),
                        stack_trace=log_data.get("stack_trace")
                    )
                    session.add(db_log)
                await session.commit()
                
            # Mark tasks as done
            for _ in range(len(logs_to_persist)):
                log_queue.task_done()
                
        except Exception as e:
            # Fallback to stderr if DB logging fails to avoid losing logs entirely
            print(f"CRITICAL: Failed to persist logs to DB: {e}", file=sys.stderr)
            await asyncio.sleep(5) # Backoff

async def log_cleanup_job(retention_days: int = 14):
    """Periodically delete logs older than the retention period."""
    from ..database import get_session_maker
    from ..models import ObservabilityLog
    from sqlalchemy import delete
    import datetime
    
    session_maker = get_session_maker()
    
    while True:
        try:
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)
            async with session_maker() as session:
                # Delete old logs
                result = await session.execute(
                    delete(ObservabilityLog).where(ObservabilityLog.timestamp < cutoff)
                )
                await session.commit()
                deleted_count = result.rowcount
                if deleted_count > 0:
                    logging.info(f"Cleaned up {deleted_count} old logs from database.")
            
            # Run cleanup once a day
            await asyncio.sleep(86400)
            
        except Exception as e:
            logging.error(f"Error in log cleanup job: {e}")
            await asyncio.sleep(3600) # Retry in an hour if it fails

def setup_observability_logging():
    """Configure structured logging and start DB worker."""
    root_logger = logging.getLogger()
    
    # Standard output handler (JSON)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(JSONFormatter())
    
    # Clear existing handlers and add ours
    root_logger.handlers = [stdout_handler]
    root_logger.setLevel(logging.INFO)
    
    return root_logger

def log_event(
    level: int,
    event_type: str,
    message: str,
    status: str = "success",
    duration_ms: Optional[int] = None,
    payload: Optional[Dict[str, Any]] = None,
    **kwargs
):
    """Helper to log structured events to both stdout and DB queue."""
    logger = logging.getLogger("observability")
    
    # Extra data for JSON formatter (stdout)
    extra = {
        "event_type": event_type,
        "status": status,
        "duration_ms": duration_ms,
        **kwargs
    }
    
    logger.log(level, message, extra=extra)
    
    # Add to DB queue for persistence
    db_data = {
        "level": logging.getLevelName(level),
        "trace_id": get_trace_id(),
        "span_id": get_span_id(),
        "customer_id": get_customer_id(),
        "event_type": event_type,
        "status": status,
        "duration_ms": duration_ms,
        "payload": payload,
        **kwargs
    }
    
    try:
        # Non-blocking add to queue
        loop = asyncio.get_event_loop()
        if loop.is_running():
            log_queue.put_nowait(db_data)
    except Exception:
        # If no loop or queue full, we still have stdout log
        pass
