import time
import logging
import uuid
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .tracer import set_trace_id, clear_context, set_customer_id
from .logger import log_event
from .errors import AppError, ErrorType

class ObservabilityMiddleware(BaseHTTPMiddleware):
    """
    Middleware for trace injection, request logging, and global error handling.
    """
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        # 1. Trace ID Injection
        # Use existing X-Trace-ID header if present (for propagation), else generate new
        trace_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())
        set_trace_id(trace_id)
        
        # 2. Extract context if available (e.g. from JWT in later steps)
        # For now, we'll just prepare the context
        
        start_time = time.time()
        
        log_event(
            level=logging.INFO,
            event_type="HTTP_REQUEST",
            message=f"Incoming {request.method} {request.url.path}",
            status="pending",
            payload={
                "method": request.method,
                "path": request.url.path,
                "query_params": dict(request.query_params),
                "client_ip": request.client.host if request.client else None
            }
        )
        
        try:
            response = await call_next(request)
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Add trace ID to response headers
            response.headers["X-Trace-ID"] = trace_id
            
            log_event(
                level=logging.INFO,
                event_type="HTTP_RESPONSE",
                message=f"Finished {request.method} {request.url.path} with {response.status_code}",
                status="success",
                duration_ms=duration_ms,
                payload={
                    "status_code": response.status_code
                }
            )
            
            return response
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Identify error type
            error_type = getattr(e, "error_type", ErrorType.SYSTEM_ERROR)
            status_code = getattr(e, "status_code", 500)
            
            log_event(
                level=logging.ERROR,
                event_type="HTTP_ERROR",
                message=f"Request failed: {str(e)}",
                status="failed",
                duration_ms=duration_ms,
                error_type=error_type,
                error_message=str(e),
                payload={
                    "method": request.method,
                    "path": request.url.path
                }
            )
            
            # Clear context at the end of request
            clear_context()
            raise
        finally:
            # Always clear context to prevent leak between requests in same thread
            clear_context()
