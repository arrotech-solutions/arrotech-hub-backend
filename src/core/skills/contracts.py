from enum import Enum
from typing import List, Dict, Optional
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


# ==============================================================================
# ENVIRONMENTS
# ==============================================================================

_LOCAL_DEV = [EnvironmentScope.LOCAL, EnvironmentScope.DEVELOPMENT]
_LOCAL_DEV_STAGING = [EnvironmentScope.LOCAL, EnvironmentScope.DEVELOPMENT, EnvironmentScope.STAGING]
_ALL_ENVS = [EnvironmentScope.LOCAL, EnvironmentScope.DEVELOPMENT, EnvironmentScope.STAGING, EnvironmentScope.PRODUCTION]


class RegisteredToolRegistry:
    """
    Central runtime registry of known valid tools for governance enforcement.
    Uses immutable ToolDefinition models instead of simple strings.
    """
    _REGISTERED_TOOLS: Dict[str, ToolDefinition] = {

        # ==================================================================
        # ORIGINAL GOVERNED TOOLS
        # ==================================================================

        "test_runner": ToolDefinition(
            name="test_runner",
            description="Executes automated tests",
            risk_level=ToolRiskLevel.MEDIUM,
            capabilities=[ToolCapability(name="test_execution")],
            mutates_files=False,
            requires_network=False,
            requires_shell=True,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "file_editor": ToolDefinition(
            name="file_editor",
            description="Modifies repository files",
            risk_level=ToolRiskLevel.HIGH,
            capabilities=[ToolCapability(name="file_mutation")],
            mutates_files=True,
            requires_network=False,
            requires_shell=False,
            allowed_environments=_ALL_ENVS,
            deterministic=True,
        ),
        "route_inspector": ToolDefinition(
            name="route_inspector",
            description="Reads FastAPI route metadata",
            risk_level=ToolRiskLevel.LOW,
            capabilities=[ToolCapability(name="route_analysis")],
            mutates_files=False,
            requires_network=False,
            requires_shell=False,
            allowed_environments=_ALL_ENVS,
            deterministic=True,
        ),

        # ==================================================================
        # CODING AGENT — FILESYSTEM TOOLS (12)
        # ==================================================================

        "coding_file_read": ToolDefinition(
            name="coding_file_read",
            description="Reads file contents with optional line range",
            risk_level=ToolRiskLevel.LOW,
            capabilities=[ToolCapability(name="file_read")],
            mutates_files=False,
            requires_network=False,
            requires_shell=False,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "coding_file_write": ToolDefinition(
            name="coding_file_write",
            description="Creates or overwrites a file with new content",
            risk_level=ToolRiskLevel.MEDIUM,
            capabilities=[ToolCapability(name="file_mutation")],
            mutates_files=True,
            requires_network=False,
            requires_shell=False,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "coding_file_edit": ToolDefinition(
            name="coding_file_edit",
            description="Performs targeted string replacement in a file",
            risk_level=ToolRiskLevel.MEDIUM,
            capabilities=[ToolCapability(name="file_mutation")],
            mutates_files=True,
            requires_network=False,
            requires_shell=False,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "coding_file_delete": ToolDefinition(
            name="coding_file_delete",
            description="Deletes a file from the workspace",
            risk_level=ToolRiskLevel.HIGH,
            capabilities=[ToolCapability(name="file_mutation")],
            mutates_files=True,
            requires_network=False,
            requires_shell=False,
            allowed_environments=_LOCAL_DEV,
            deterministic=True,
        ),
        "coding_directory_list": ToolDefinition(
            name="coding_directory_list",
            description="Lists directory contents with optional recursion",
            risk_level=ToolRiskLevel.LOW,
            capabilities=[ToolCapability(name="file_read")],
            mutates_files=False,
            requires_network=False,
            requires_shell=False,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "coding_file_search": ToolDefinition(
            name="coding_file_search",
            description="Searches for files matching a pattern",
            risk_level=ToolRiskLevel.LOW,
            capabilities=[ToolCapability(name="file_read")],
            mutates_files=False,
            requires_network=False,
            requires_shell=False,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "coding_grep_search": ToolDefinition(
            name="coding_grep_search",
            description="Searches file contents for text patterns with context",
            risk_level=ToolRiskLevel.LOW,
            capabilities=[ToolCapability(name="file_read")],
            mutates_files=False,
            requires_network=False,
            requires_shell=False,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "coding_get_definition": ToolDefinition(
            name="coding_get_definition",
            description="Finds symbol definitions across the codebase",
            risk_level=ToolRiskLevel.LOW,
            capabilities=[ToolCapability(name="file_read"), ToolCapability(name="code_analysis")],
            mutates_files=False,
            requires_network=False,
            requires_shell=False,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "coding_read_file_summary": ToolDefinition(
            name="coding_read_file_summary",
            description="Reads file metadata: imports, exports, declarations",
            risk_level=ToolRiskLevel.LOW,
            capabilities=[ToolCapability(name="file_read"), ToolCapability(name="code_analysis")],
            mutates_files=False,
            requires_network=False,
            requires_shell=False,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "coding_get_project_structure": ToolDefinition(
            name="coding_get_project_structure",
            description="Detects project framework, language, and structure",
            risk_level=ToolRiskLevel.LOW,
            capabilities=[ToolCapability(name="file_read"), ToolCapability(name="code_analysis")],
            mutates_files=False,
            requires_network=False,
            requires_shell=False,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "coding_write_scratchpad": ToolDefinition(
            name="coding_write_scratchpad",
            description="Writes to the agent scratchpad for working notes",
            risk_level=ToolRiskLevel.LOW,
            capabilities=[ToolCapability(name="file_mutation")],
            mutates_files=True,
            requires_network=False,
            requires_shell=False,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "coding_read_scratchpad": ToolDefinition(
            name="coding_read_scratchpad",
            description="Reads the agent scratchpad contents",
            risk_level=ToolRiskLevel.LOW,
            capabilities=[ToolCapability(name="file_read")],
            mutates_files=False,
            requires_network=False,
            requires_shell=False,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),

        # ==================================================================
        # CODING AGENT — OPERATIONS TOOLS (12)
        # ==================================================================

        "coding_run_command": ToolDefinition(
            name="coding_run_command",
            description="Executes arbitrary shell commands in sandbox",
            risk_level=ToolRiskLevel.CRITICAL,
            capabilities=[
                ToolCapability(name="shell_execution"),
                ToolCapability(name="file_mutation"),
            ],
            mutates_files=True,
            requires_network=False,
            requires_shell=True,
            allowed_environments=_LOCAL_DEV,
            deterministic=False,
        ),
        "coding_run_tests": ToolDefinition(
            name="coding_run_tests",
            description="Auto-detects and runs test suite",
            risk_level=ToolRiskLevel.MEDIUM,
            capabilities=[ToolCapability(name="test_execution"), ToolCapability(name="shell_execution")],
            mutates_files=False,
            requires_network=False,
            requires_shell=True,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "coding_install_dependencies": ToolDefinition(
            name="coding_install_dependencies",
            description="Installs project dependencies via package manager",
            risk_level=ToolRiskLevel.HIGH,
            capabilities=[
                ToolCapability(name="shell_execution"),
                ToolCapability(name="network_access"),
                ToolCapability(name="file_mutation"),
            ],
            mutates_files=True,
            requires_network=True,
            requires_shell=True,
            allowed_environments=_LOCAL_DEV,
            deterministic=False,
        ),
        "coding_git_status": ToolDefinition(
            name="coding_git_status",
            description="Shows git working tree status",
            risk_level=ToolRiskLevel.LOW,
            capabilities=[ToolCapability(name="shell_execution"), ToolCapability(name="version_control")],
            mutates_files=False,
            requires_network=False,
            requires_shell=True,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "coding_git_diff": ToolDefinition(
            name="coding_git_diff",
            description="Shows git diff of changes",
            risk_level=ToolRiskLevel.LOW,
            capabilities=[ToolCapability(name="shell_execution"), ToolCapability(name="version_control")],
            mutates_files=False,
            requires_network=False,
            requires_shell=True,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "coding_git_commit": ToolDefinition(
            name="coding_git_commit",
            description="Stages and commits changes to git",
            risk_level=ToolRiskLevel.MEDIUM,
            capabilities=[ToolCapability(name="shell_execution"), ToolCapability(name="version_control")],
            mutates_files=True,
            requires_network=False,
            requires_shell=True,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "coding_git_push": ToolDefinition(
            name="coding_git_push",
            description="Pushes commits to remote repository",
            risk_level=ToolRiskLevel.HIGH,
            capabilities=[
                ToolCapability(name="shell_execution"),
                ToolCapability(name="version_control"),
                ToolCapability(name="network_access"),
            ],
            mutates_files=False,
            requires_network=True,
            requires_shell=True,
            allowed_environments=_LOCAL_DEV,
            deterministic=True,
        ),
        "coding_git_create_branch": ToolDefinition(
            name="coding_git_create_branch",
            description="Creates and checks out a new git branch",
            risk_level=ToolRiskLevel.MEDIUM,
            capabilities=[
                ToolCapability(name="shell_execution"),
                ToolCapability(name="version_control"),
                ToolCapability(name="network_access"),
            ],
            mutates_files=False,
            requires_network=True,
            requires_shell=True,
            allowed_environments=_LOCAL_DEV,
            deterministic=True,
        ),
        "coding_git_read_log": ToolDefinition(
            name="coding_git_read_log",
            description="Reads git commit history",
            risk_level=ToolRiskLevel.LOW,
            capabilities=[ToolCapability(name="shell_execution"), ToolCapability(name="version_control")],
            mutates_files=False,
            requires_network=False,
            requires_shell=True,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "coding_github_create_pr": ToolDefinition(
            name="coding_github_create_pr",
            description="Creates a GitHub pull request",
            risk_level=ToolRiskLevel.HIGH,
            capabilities=[ToolCapability(name="network_access"), ToolCapability(name="version_control")],
            mutates_files=False,
            requires_network=True,
            requires_shell=False,
            allowed_environments=_LOCAL_DEV,
            deterministic=True,
        ),
        "coding_github_get_pr_status": ToolDefinition(
            name="coding_github_get_pr_status",
            description="Gets PR status and check run results",
            risk_level=ToolRiskLevel.LOW,
            capabilities=[ToolCapability(name="network_access"), ToolCapability(name="version_control")],
            mutates_files=False,
            requires_network=True,
            requires_shell=False,
            allowed_environments=_LOCAL_DEV_STAGING,
            deterministic=True,
        ),
        "coding_github_get_check_logs": ToolDefinition(
            name="coding_github_get_check_logs",
            description="Gets CI/CD check run logs from GitHub",
            risk_level=ToolRiskLevel.LOW,
            capabilities=[ToolCapability(name="network_access"), ToolCapability(name="version_control")],
            mutates_files=False,
            requires_network=True,
            requires_shell=False,
            allowed_environments=_LOCAL_DEV_STAGING,
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

    @classmethod
    def by_risk_level(cls, risk_level: ToolRiskLevel) -> Dict[str, ToolDefinition]:
        """Return tools filtered by risk level."""
        return {
            name: tool for name, tool in cls._REGISTERED_TOOLS.items()
            if tool.risk_level == risk_level
        }


class GovernancePolicy(BaseModel):
    """
    Governance policy that controls which tools and capabilities
    are permitted in a given execution context.
    """
    name: str
    description: str
    allowed_risk_levels: List[ToolRiskLevel]
    allow_shell_execution: bool
    allow_network_access: bool
    allow_file_mutation: bool
    require_human_approval_for_high_risk: bool = True

    model_config = {
        "extra": "forbid",
        "frozen": True
    }

    def permits_tool(self, tool: ToolDefinition) -> bool:
        """Check whether this policy permits a given tool."""
        if tool.risk_level not in self.allowed_risk_levels:
            return False
        if tool.requires_shell and not self.allow_shell_execution:
            return False
        if tool.requires_network and not self.allow_network_access:
            return False
        if tool.mutates_files and not self.allow_file_mutation:
            return False
        return True


DEFAULT_POLICY = GovernancePolicy(
    name="default",
    description="Default governance baseline — permits low and medium risk tools",
    allowed_risk_levels=[
        ToolRiskLevel.LOW,
        ToolRiskLevel.MEDIUM,
    ],
    allow_shell_execution=True,
    allow_network_access=False,
    allow_file_mutation=True,
    require_human_approval_for_high_risk=True,
)

CODING_AGENT_POLICY = GovernancePolicy(
    name="coding_agent",
    description="Coding agent policy — permits all risk levels with governance gates",
    allowed_risk_levels=[
        ToolRiskLevel.LOW,
        ToolRiskLevel.MEDIUM,
        ToolRiskLevel.HIGH,
        ToolRiskLevel.CRITICAL,
    ],
    allow_shell_execution=True,
    allow_network_access=True,
    allow_file_mutation=True,
    require_human_approval_for_high_risk=True,
)

READ_ONLY_POLICY = GovernancePolicy(
    name="read_only",
    description="Read-only policy — no mutations, no shell, no network",
    allowed_risk_levels=[
        ToolRiskLevel.LOW,
    ],
    allow_shell_execution=False,
    allow_network_access=False,
    allow_file_mutation=False,
    require_human_approval_for_high_risk=True,
)
