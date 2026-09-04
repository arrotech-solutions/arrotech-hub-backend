import uuid
import contextvars
import time
import logging
from typing import Optional, Dict, Any
from contextlib import contextmanager

# Context variables to store trace and span IDs across async tasks
trace_id_var = contextvars.ContextVar("trace_id", default=None)
span_stack_var = contextvars.ContextVar("span_stack", default=[])
customer_id_var = contextvars.ContextVar("customer_id", default=None)
phone_number_hash_var = contextvars.ContextVar("phone_number_hash", default=None)

def get_trace_id() -> str:
    """Get the current trace_id or generate a new one if not set."""
    tid = trace_id_var.get()
    if not tid:
        tid = str(uuid.uuid4())
        trace_id_var.set(tid)
    return tid

def set_trace_id(tid: str):
    """Explicitly set the trace_id (useful for incoming webhooks)."""
    trace_id_var.set(tid)

def get_span_id() -> Optional[str]:
    """Get the current span_id from the top of the stack."""
    stack = span_stack_var.get()
    if stack:
        return stack[-1].get("span_id")
    return None

def get_parent_span_id() -> Optional[str]:
    """Get the parent span_id of the current span."""
    stack = span_stack_var.get()
    if stack and len(stack) > 1:
        return stack[-2].get("span_id")
    return None

@contextmanager
def trace_span(name: str, payload: Optional[Dict[str, Any]] = None):
    """Context manager to handle span lifecycle, timing, and errors."""
    from .logger import log_event
    
    stack = list(span_stack_var.get())
    parent_id = get_span_id()
    span_id = str(uuid.uuid4())[:8]
    
    span_data = {
        "span_id": span_id,
        "name": name,
        "parent_span_id": parent_id,
        "payload": payload or {}
    }
    
    stack.append(span_data)
    token = span_stack_var.set(stack)
    
    start_time = time.time()
    
    try:
        log_event(
            level=logging.INFO,
            event_type="SPAN_START",
            message=f"Starting span: {name}",
            payload=payload,
            step_name=name
        )
        
        yield span_data
        
        duration_ms = int((time.time() - start_time) * 1000)
        log_event(
            level=logging.INFO,
            event_type="SPAN_END",
            message=f"Finished span: {name}",
            status="success",
            duration_ms=duration_ms,
            step_name=name
        )
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        error_type = getattr(e, "error_type", "SYSTEM_ERROR")
        log_event(
            level=logging.ERROR,
            event_type="SPAN_END",
            message=f"Failed span: {name} - {str(e)}",
            status="failed",
            duration_ms=duration_ms,
            error_type=error_type,
            error_message=str(e),
            step_name=name
        )
        raise
    finally:
        span_stack_var.reset(token)

def start_span() -> str:
    """Legacy compatibility - just sets a span_id at the top of the stack."""
    sid = str(uuid.uuid4())[:8]
    stack = list(span_stack_var.get())
    stack.append({"span_id": sid, "name": "legacy_span"})
    span_stack_var.set(stack)
    return sid

def get_customer_id() -> Optional[str]:
    """Get the current customer_id."""
    return customer_id_var.get()

def set_customer_id(cid: str):
    """Set the current customer_id."""
    customer_id_var.set(cid)

def get_phone_number_hash() -> Optional[str]:
    """Get the current phone_number_hash."""
    return phone_number_hash_var.get()

def set_phone_number_hash(pnh: str):
    """Set the current phone_number_hash."""
    phone_number_hash_var.set(pnh)

def get_full_context() -> dict:
    """Get all observability context variables as a dict (for passing to background tasks)."""
    return {
        "trace_id": trace_id_var.get(),
        "span_stack": span_stack_var.get(),
        "customer_id": customer_id_var.get(),
        "phone_number_hash": phone_number_hash_var.get(),
    }

def set_full_context(ctx: dict):
    """Restore context variables from a dict."""
    if ctx.get("trace_id"):
        trace_id_var.set(ctx["trace_id"])
    if ctx.get("span_stack"):
        span_stack_var.set(ctx["span_stack"])
    if ctx.get("customer_id"):
        customer_id_var.set(ctx["customer_id"])
    if ctx.get("phone_number_hash"):
        phone_number_hash_var.set(ctx["phone_number_hash"])

def clear_context():
    """Clear all context variables."""
    trace_id_var.set(None)
    span_stack_var.set([])
    customer_id_var.set(None)
    phone_number_hash_var.set(None)
