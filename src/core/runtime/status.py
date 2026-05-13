from enum import Enum

class ExecutionStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    DENIED = "denied"
    GOVERNANCE_REJECTED = "governance_rejected"
    TIMEOUT = "timeout"
