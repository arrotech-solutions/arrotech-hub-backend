"""
Coding Agent — Main Tool Executor

Routes coding_* tool calls to the appropriate handler, wraps every call
in the standard {tool, success, output, error, duration_ms} envelope,
and integrates with the sandbox lifecycle.

All tool calls are validated through the GovernedCodingBridge before
dispatch, ensuring governance policy compliance and audit chain recording.

Session state is read from Redis (via session_store.py).
"""
import logging
import time
from typing import Any, Dict, Optional

from .coding_agent_helpers import build_tool_envelope
from .coding_agent_sandbox import CodingAgentSandbox, coding_agent_sandbox
from . import session_store

logger = logging.getLogger(__name__)

# Handler imports (deferred to avoid circular imports at module load)
_FS_HANDLERS = None
_OPS_HANDLERS = None

# Governance bridge (deferred import to avoid circular imports)
_BRIDGE = None


def _load_handlers():
    global _FS_HANDLERS, _OPS_HANDLERS
    if _FS_HANDLERS is None:
        from . import coding_agent_tools_fs as fs
        from . import coding_agent_tools_ops as ops
        _FS_HANDLERS = {
            "coding_file_read": fs.handle_file_read,
            "coding_file_write": fs.handle_file_write,
            "coding_file_edit": fs.handle_file_edit,
            "coding_file_delete": fs.handle_file_delete,
            "coding_directory_list": fs.handle_directory_list,
            "coding_file_search": fs.handle_file_search,
            "coding_grep_search": fs.handle_grep_search,
            "coding_get_definition": fs.handle_get_definition,
            "coding_read_file_summary": fs.handle_read_file_summary,
            "coding_get_project_structure": fs.handle_get_project_structure,
            "coding_write_scratchpad": fs.handle_write_scratchpad,
            "coding_read_scratchpad": fs.handle_read_scratchpad,
        }
        _OPS_HANDLERS = {
            "coding_run_command": ops.handle_run_command,
            "coding_run_tests": ops.handle_run_tests,
            "coding_install_dependencies": ops.handle_install_deps,
            "coding_git_status": ops.handle_git_status,
            "coding_git_diff": ops.handle_git_diff,
            "coding_git_commit": ops.handle_git_commit,
            "coding_git_push": ops.handle_git_push,
            "coding_git_create_branch": ops.handle_git_create_branch,
            "coding_git_read_log": ops.handle_git_read_log,
            "coding_github_create_pr": ops.handle_github_create_pr,
            "coding_github_get_pr_status": ops.handle_github_get_pr_status,
            "coding_github_get_check_logs": ops.handle_github_get_check_logs,
        }


def _get_bridge():
    """Lazy-load the governance bridge to avoid circular imports."""
    global _BRIDGE
    if _BRIDGE is None:
        from src.core.runtime.governed_bridge import GovernedCodingBridge
        from src.core.skills.contracts import CODING_AGENT_POLICY
        from src.core.skills.models import EnvironmentScope

        # Load and register all coding skill manifests
        _register_coding_skills()

        _BRIDGE = GovernedCodingBridge(
            policy=CODING_AGENT_POLICY,
            environment=EnvironmentScope.LOCAL,
            # LOW/MEDIUM tools auto-approve; HIGH/CRITICAL handled per-call
            approved_by_human=False,
        )
    return _BRIDGE


# ── TOOL → RISK LEVEL MAP (for auto-approval decisions) ──────────────
_TOOL_RISK_CACHE = None

def _get_tool_risk(tool_name: str) -> str:
    """Get cached risk level for a tool."""
    global _TOOL_RISK_CACHE
    if _TOOL_RISK_CACHE is None:
        from src.core.skills.contracts import RegisteredToolRegistry
        _TOOL_RISK_CACHE = {
            name: defn.risk_level.value
            for name, defn in RegisteredToolRegistry.all().items()
        }
    return _TOOL_RISK_CACHE.get(tool_name, "critical")


def _is_auto_approved(tool_name: str) -> bool:
    """LOW and MEDIUM risk tools are auto-approved. HIGH/CRITICAL need explicit approval."""
    risk = _get_tool_risk(tool_name)
    return risk in ("low", "medium")


# ── SKILL MANIFEST AUTO-LOADING ──────────────────────────────────────
_SKILLS_LOADED = False

def _register_coding_skills():
    """Load all coding skill manifests into the SkillRegistry at startup."""
    global _SKILLS_LOADED
    if _SKILLS_LOADED:
        return

    import os
    from pathlib import Path
    from src.core.skills.loader import load_skill
    from src.core.skills.registry import SkillRegistry
    from src.core.skills.exceptions import SkillLoadError, SkillValidationError

    registry = SkillRegistry()
    skills_dir = Path(__file__).resolve().parent.parent / "skills"

    if not skills_dir.exists():
        logger.warning(f"Skills directory not found: {skills_dir}")
        _SKILLS_LOADED = True
        return

    loaded = 0
    for skill_dir in sorted(skills_dir.iterdir()):
        manifest = skill_dir / "skill.yaml"
        if not manifest.exists():
            continue
        try:
            skill = load_skill(manifest)
            try:
                registry.register(skill)
            except SkillValidationError:
                pass  # Already registered (e.g. from a previous import)
            loaded += 1
        except (SkillLoadError, SkillValidationError) as e:
            logger.warning(f"Failed to load skill {skill_dir.name}: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error loading skill {skill_dir.name}: {e}")

    _SKILLS_LOADED = True
    logger.info(f"Loaded {loaded} coding skill manifests")


class CodingAgentToolExecutor:
    """
    Main executor for all 24 coding agent tools.

    Every tool call passes through the GovernedCodingBridge for:
    - Policy evaluation (risk level, capability constraints)
    - Environment authorization
    - Audit chain recording (immutable, tamper-evident)

    Usage from ToolExecutor._execute_tool_logic():
        from .coding_agent_executor import coding_agent_executor
        return await coding_agent_executor.execute(tool_name, arguments, user, db, redis)
    """

    def __init__(self, sandbox: CodingAgentSandbox = None):
        self.sandbox = sandbox or coding_agent_sandbox

    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: Any = None,
        db: Any = None,
        redis: Any = None,
        approved: bool = False,
    ) -> Dict[str, Any]:
        """
        Route and execute a coding agent tool.

        Returns the standard envelope: {tool, success, output, error, duration_ms}
        """
        _load_handlers()
        start = time.time()

        # Extract session_id (required for all tools)
        session_id = arguments.get("session_id")
        if not session_id:
            return build_tool_envelope(tool_name, False, None, "Missing required: session_id", 0)

        # Validate session exists in Redis
        if redis is None:
            return build_tool_envelope(tool_name, False, None, "Redis unavailable — cannot look up session", 0)

        session = await session_store.get_session(redis, session_id)
        if not session:
            return build_tool_envelope(tool_name, False, None, f"No active session: {session_id}", 0)

        workspace = session.workspace_path

        # ── GOVERNANCE GATE ────────────────────────────────────────────
        bridge = _get_bridge()
        auto_approved = _is_auto_approved(tool_name)
        is_approved = auto_approved or approved
        try:
            bridge.authorize(
                tool_name,
                approved_by_human=is_approved,
            )
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.warning(f"Governance rejected {tool_name}: {e}")
            bridge.record_failure(
                tool_name=tool_name,
                skill_name="coding_agent",
                execution_time_ms=duration_ms,
                error_message=str(e),
            )
            requires_approval = "requires human approval" in str(e).lower()
            return build_tool_envelope(
                tool_name, 
                False, 
                None, 
                f"Governance: {e}", 
                duration_ms, 
                requires_approval=requires_approval
            )

        # ── EXECUTION WITH TIMEOUT ─────────────────────────────────────
        try:
            from src.core.runtime.timeout import execute_with_timeout, get_timeout_for_risk
            risk = _get_tool_risk(tool_name)
            timeout_sec = get_timeout_for_risk(risk)

            output = await execute_with_timeout(
                self._dispatch(tool_name, arguments, session, workspace, user, redis),
                timeout_seconds=timeout_sec,
                tool_name=tool_name,
            )
            duration_ms = int((time.time() - start) * 1000)

            # Extend session TTL on successful execution
            await session_store.touch_session(redis, session_id)

            # Record success in audit chain
            bridge.record_success(
                tool_name=tool_name,
                skill_name="coding_agent",
                execution_time_ms=duration_ms,
                output=output if isinstance(output, dict) else {"result": str(output)},
            )

            return build_tool_envelope(tool_name, True, output, None, duration_ms)
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.warning(f"Coding tool {tool_name} failed: {e}", exc_info=True)

            # Record failure in audit chain
            bridge.record_failure(
                tool_name=tool_name,
                skill_name="coding_agent",
                execution_time_ms=duration_ms,
                error_message=str(e),
            )

            return build_tool_envelope(tool_name, False, None, str(e), duration_ms)

    async def _dispatch(
        self, tool_name: str, args: Dict, session: Any, workspace: str, user: Any, redis: Any
    ) -> Dict:
        """Route tool_name to the correct handler."""

        # ── Filesystem & Search tools (take workspace path) ────────────
        if tool_name in _FS_HANDLERS:
            handler = _FS_HANDLERS[tool_name]
            # Scratchpad tools need the session object, not workspace
            if tool_name in ("coding_write_scratchpad", "coding_read_scratchpad"):
                return await handler(args, session)
            return await handler(args, workspace)

        # ── Command Execution tools (need sandbox + redis) ─────────────
        if tool_name == "coding_run_command":
            return await _OPS_HANDLERS[tool_name](args, self.sandbox, redis)

        if tool_name == "coding_run_tests":
            return await _OPS_HANDLERS[tool_name](args, self.sandbox, workspace, redis)

        if tool_name == "coding_install_dependencies":
            return await _OPS_HANDLERS[tool_name](args, self.sandbox, redis)

        # ── Git tools (need sandbox + redis for git commands) ──────────
        if tool_name in ("coding_git_status", "coding_git_diff", "coding_git_commit",
                         "coding_git_create_branch", "coding_git_read_log"):
            return await _OPS_HANDLERS[tool_name](args, self.sandbox, redis)

        if tool_name == "coding_git_push":
            token = self._get_github_token(user)
            return await _OPS_HANDLERS[tool_name](args, self.sandbox, token, redis)

        # ── GitHub API tools (need token) ──────────────────────────────
        if tool_name in ("coding_github_create_pr", "coding_github_get_pr_status",
                         "coding_github_get_check_logs"):
            token = self._get_github_token(user)
            if not token:
                raise ValueError("GitHub token not configured. Set GITHUB_TOKEN in environment.")
            return await _OPS_HANDLERS[tool_name](args, token)

        raise ValueError(f"Unknown coding tool: {tool_name}")

    def _get_github_token(self, user: Any = None) -> Optional[str]:
        """Get GitHub token — first from user settings, then from env."""
        # Per-user token (future: stored in UserSettings/Connection)
        if user and hasattr(user, "github_token") and user.github_token:
            return user.github_token
        # Fall back to platform-level env var
        from ..config import settings
        return getattr(settings, "GITHUB_TOKEN", None)


# Global executor instance
coding_agent_executor = CodingAgentToolExecutor()
