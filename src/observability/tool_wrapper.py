import time
import logging
import traceback
from typing import Any, Callable, Dict, Optional
import uuid

from .tracer import start_span, get_trace_id, get_span_id
from .logger import log_event
from .retry_system import with_retry
from .errors import AppError, ErrorType

async def execute_tool(
    tool_name: str,
    fn: Callable,
    arguments: Dict[str, Any],
    customer_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    max_retries: int = 3
) -> Any:
    """
    Standardized tool execution wrapper with tracing, logging, and DLQ support.
    """
    span_id = start_span()
    start_time = time.time()
    
    log_event(
        level=logging.INFO,
        event_type="TOOL_START",
        message=f"Executing tool: {tool_name}",
        status="pending",
        tool_name=tool_name,
        customer_id=customer_id,
        agent_id=agent_id,
        workflow_id=workflow_id,
        payload={"input": arguments}
    )
    
    try:
        # Execute with retry logic
        result = await with_retry(
            lambda: fn(**arguments),
            max_retries=max_retries,
            event_type="TOOL_RETRY"
        )
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        log_event(
            level=logging.INFO,
            event_type="TOOL_SUCCESS",
            message=f"Tool {tool_name} completed successfully",
            status="success",
            duration_ms=duration_ms,
            tool_name=tool_name,
            customer_id=customer_id,
            agent_id=agent_id,
            workflow_id=workflow_id,
            payload={"output": result}
        )
        
        return result
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        error_type = getattr(e, "error_type", ErrorType.SYSTEM_ERROR)
        
        log_event(
            level=logging.ERROR,
            event_type="TOOL_FAILURE",
            message=f"Tool {tool_name} failed: {str(e)}",
            status="failed",
            duration_ms=duration_ms,
            tool_name=tool_name,
            customer_id=customer_id,
            agent_id=agent_id,
            workflow_id=workflow_id,
            error_type=error_type,
            error_message=str(e),
            stack_trace=traceback.format_exc(),
            payload={"input": arguments}
        )
        
        # Push to Dead Letter Queue (DLQ) if it was a system/api error
        if error_type in [ErrorType.SYSTEM_ERROR, ErrorType.EXTERNAL_API_ERROR, ErrorType.TIMEOUT]:
            await push_to_dlq(
                event_type="TOOL_EXECUTION",
                payload={
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "customer_id": customer_id,
                    "agent_id": agent_id,
                    "workflow_id": workflow_id
                },
                error_message=str(e)
            )
            
        raise

async def push_to_dlq(event_type: str, payload: Dict[str, Any], error_message: str):
    """Persist failed event to the Dead Letter Queue."""
    from ..database import get_session_maker
    from ..models import FailedEvent
    
    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            dlq_event = FailedEvent(
                trace_id=get_trace_id(),
                event_type=event_type,
                payload=payload,
                error_message=error_message,
                status="failed"
            )
            session.add(dlq_event)
            await session.commit()
            
        logging.info(f"Pushed failed event {event_type} to DLQ")
    except Exception as e:
        logging.error(f"CRITICAL: Failed to push to DLQ: {e}")
