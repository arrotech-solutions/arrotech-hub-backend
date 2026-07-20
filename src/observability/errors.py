from enum import Enum
from typing import Optional, Any, Dict

class ErrorType(str, Enum):
    USER_ERROR = "USER_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    EXTERNAL_API_ERROR = "EXTERNAL_API_ERROR"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    UNKNOWN = "UNKNOWN"

class AppError(Exception):
    """Base exception for all application errors."""
    def __init__(
        self, 
        message: str, 
        error_type: ErrorType = ErrorType.SYSTEM_ERROR,
        status_code: int = 500,
        payload: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.status_code = status_code
        self.payload = payload

class UserError(AppError):
    def __init__(self, message: str, payload: Optional[Dict[str, Any]] = None):
        super().__init__(message, ErrorType.USER_ERROR, 400, payload)

class ValidationError(AppError):
    def __init__(self, message: str, payload: Optional[Dict[str, Any]] = None):
        super().__init__(message, ErrorType.VALIDATION_ERROR, 422, payload)

class ExternalAPIError(AppError):
    def __init__(self, message: str, service_name: str, payload: Optional[Dict[str, Any]] = None):
        merged_payload = {"service": service_name, **(payload or {})}
        super().__init__(message, ErrorType.EXTERNAL_API_ERROR, 502, merged_payload)

class RateLimitError(AppError):
    def __init__(self, message: str = "Rate limit exceeded", payload: Optional[Dict[str, Any]] = None):
        super().__init__(message, ErrorType.RATE_LIMIT, 429, payload)

class TimeoutError(AppError):
    def __init__(self, message: str = "Request timed out", payload: Optional[Dict[str, Any]] = None):
        super().__init__(message, ErrorType.TIMEOUT, 504, payload)
