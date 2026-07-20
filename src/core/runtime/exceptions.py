class RuntimeExecutionError(Exception):
    """Base class for all runtime execution errors."""
    pass

class RuntimeAuthorizationError(RuntimeExecutionError):
    """Raised when a tool is not authorized for execution."""
    pass

class RuntimeGovernanceError(RuntimeExecutionError):
    """Raised when execution violates sandbox governance rules."""
    pass

class RuntimeEnvironmentError(RuntimeGovernanceError):
    """Raised when the execution environment does not match allowed tool environments."""
    pass

class RuntimeSandboxViolationError(RuntimeGovernanceError):
    """Raised when a tool attempts to use a capability forbidden by the sandbox."""
    pass

class RuntimeTimeoutError(RuntimeGovernanceError):
    """Raised when tool execution exceeds the maximum allowed time limit."""
    pass
