from enum import Enum

class GovernanceDecision(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    REJECTED = "rejected"
