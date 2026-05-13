from enum import Enum
from typing import List, Dict
from pydantic import BaseModel
from src.core.skills.models import EnvironmentScope

class ToolRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class ToolCapability(BaseModel):
    name: str

    model_config = {
        "extra": "forbid",
        "frozen": True
    }

class ToolDefinition(BaseModel):
    name: str
    description: str
    risk_level: ToolRiskLevel
    capabilities: List[ToolCapability]
    mutates_files: bool = False
    requires_network: bool = False
    requires_shell: bool = False
    allowed_environments: List[EnvironmentScope]
    deterministic: bool = True

    model_config = {
        "extra": "forbid",
        "frozen": True
    }

class RegisteredToolRegistry:
    """
    Central runtime registry of known valid tools for governance enforcement.
    Uses immutable ToolDefinition models instead of simple strings.
    """
    _REGISTERED_TOOLS: Dict[str, ToolDefinition] = {
        "test_runner": ToolDefinition(
            name="test_runner",
            description="Executes automated tests",
            risk_level=ToolRiskLevel.MEDIUM,
            capabilities=[
                ToolCapability(name="test_execution")
            ],
            mutates_files=False,
            requires_network=False,
            requires_shell=True,
            allowed_environments=[EnvironmentScope.DEVELOPMENT, EnvironmentScope.STAGING],
            deterministic=True,
        ),
        "file_editor": ToolDefinition(
            name="file_editor",
            description="Modifies repository files",
            risk_level=ToolRiskLevel.HIGH,
            capabilities=[
                ToolCapability(name="file_mutation")
            ],
            mutates_files=True,
            requires_network=False,
            requires_shell=False,
            allowed_environments=[EnvironmentScope.DEVELOPMENT, EnvironmentScope.STAGING, EnvironmentScope.PRODUCTION],
            deterministic=True,
        ),
        "route_inspector": ToolDefinition(
            name="route_inspector",
            description="Reads FastAPI route metadata",
            risk_level=ToolRiskLevel.LOW,
            capabilities=[
                ToolCapability(name="route_analysis")
            ],
            mutates_files=False,
            requires_network=False,
            requires_shell=False,
            allowed_environments=[EnvironmentScope.DEVELOPMENT, EnvironmentScope.STAGING, EnvironmentScope.PRODUCTION],
            deterministic=True,
        ),
    }

    @classmethod
    def exists(cls, tool_name: str) -> bool:
        """Check if a tool is registered in the governance registry."""
        return tool_name in cls._REGISTERED_TOOLS

    @classmethod
    def get(cls, tool_name: str) -> ToolDefinition:
        """Get a tool definition by name. Raises KeyError if missing."""
        if tool_name not in cls._REGISTERED_TOOLS:
            raise KeyError(f"Tool not found: {tool_name}")
        return cls._REGISTERED_TOOLS[tool_name]

    @classmethod
    def all(cls) -> Dict[str, ToolDefinition]:
        """Return all registered tool definitions."""
        return cls._REGISTERED_TOOLS.copy()

class GovernancePolicy(BaseModel):
    """
    Metadata model for defining governance policies.
    This is for architecture preparation, not active enforcement yet.
    """
    name: str
    description: str
    allowed_risk_levels: List[ToolRiskLevel]
    allow_shell_execution: bool
    allow_network_access: bool
    allow_file_mutation: bool

    model_config = {
        "extra": "forbid",
        "frozen": True
    }

DEFAULT_POLICY = GovernancePolicy(
    name="default",
    description="Default governance baseline",
    allowed_risk_levels=[
        ToolRiskLevel.LOW,
        ToolRiskLevel.MEDIUM,
    ],
    allow_shell_execution=True,
    allow_network_access=False,
    allow_file_mutation=True,
)
