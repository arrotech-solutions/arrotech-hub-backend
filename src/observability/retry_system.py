import asyncio
import logging
import random
import functools
from typing import Callable, Any, Optional, Type, Tuple

from .logger import log_event
from .errors import AppError, ErrorType

async def with_retry(
    fn: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    event_type: str = "RETRY_ATTEMPT"
) -> Any:
    """
    Execute a function with exponential backoff and jitter.
    """
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except retryable_exceptions as e:
            last_error = e
            if attempt == max_retries:
                break
                
            # Calculate delay: base_delay * 2^attempt + jitter
            delay = min(base_delay * (2 ** attempt), max_delay)
            jitter = delay * 0.1 * random.uniform(-1, 1)
            sleep_time = delay + jitter
            
            log_event(
                level=logging.WARNING,
                event_type=event_type,
                message=f"Attempt {attempt + 1} failed. Retrying in {sleep_time:.2f}s...",
                status="failed",
                retry_count=attempt + 1,
                error_type=type(e).__name__,
                error_message=str(e)
            )
            
            await asyncio.sleep(sleep_time)
            
    # If we got here, all retries failed
    raise last_error

def retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """Decorator version of with_retry."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await with_retry(
                lambda: func(*args, **kwargs),
                max_retries=max_retries,
                base_delay=base_delay,
                retryable_exceptions=retryable_exceptions,
                event_type=f"{func.__name__.upper()}_RETRY"
            )
        return wrapper
    return decorator
