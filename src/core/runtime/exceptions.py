class RuntimeExecutionError(Exception):
    """Base class for all runtime execution errors."""
    pass

class RuntimeAuthorizationError(RuntimeExecutionError):
    """Raised when a tool is not authorized for execution."""
    pass

class RuntimeGovernanceError(RuntimeExecutionError):
    """Raised when execution violates sandbox governance rules."""
    pass
