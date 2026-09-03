import uuid
import contextvars
from typing import Optional

# Context variables to store trace and span IDs across async tasks
trace_id_var = contextvars.ContextVar("trace_id", default=None)
span_id_var = contextvars.ContextVar("span_id", default=None)
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
    """Get the current span_id."""
    return span_id_var.get()

def start_span() -> str:
    """Start a new span and return its ID."""
    sid = str(uuid.uuid4())[:8] # Shorter IDs for spans
    span_id_var.set(sid)
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
        "span_id": span_id_var.get(),
        "customer_id": customer_id_var.get(),
        "phone_number_hash": phone_number_hash_var.get(),
    }

def set_full_context(ctx: dict):
    """Restore context variables from a dict."""
    if ctx.get("trace_id"):
        trace_id_var.set(ctx["trace_id"])
    if ctx.get("span_id"):
        span_id_var.set(ctx["span_id"])
    if ctx.get("customer_id"):
        customer_id_var.set(ctx["customer_id"])
    if ctx.get("phone_number_hash"):
        phone_number_hash_var.set(ctx["phone_number_hash"])

def clear_context():
    """Clear all context variables."""
    trace_id_var.set(None)
    span_id_var.set(None)
    customer_id_var.set(None)
    phone_number_hash_var.set(None)
