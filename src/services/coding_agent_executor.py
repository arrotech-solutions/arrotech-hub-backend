"""
Coding Agent — Main Tool Executor

Routes coding_* tool calls to the appropriate handler, wraps every call
in the standard {tool, success, output, error, duration_ms} envelope,
and integrates with the sandbox lifecycle.
"""
import logging
import time
from typing import Any, Dict, Optional

from .coding_agent_helpers import build_tool_envelope
from .coding_agent_sandbox import CodingAgentSandbox, coding_agent_sandbox

logger = logging.getLogger(__name__)

# Handler imports (deferred to avoid circular imports at module load)
_FS_HANDLERS = None
_OPS_HANDLERS = None


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


class CodingAgentToolExecutor:
    """
    Main executor for all 24 coding agent tools.

    Usage from ToolExecutor._execute_tool_logic():
        from .coding_agent_executor import coding_agent_executor
        return await coding_agent_executor.execute(tool_name, arguments, user, db)
    """

    def __init__(self, sandbox: CodingAgentSandbox = None):
        self.sandbox = sandbox or coding_agent_sandbox

    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user: Any = None,
        db: Any = None,
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

        # Validate session exists
        session = self.sandbox.get_session(session_id)
        if not session:
            return build_tool_envelope(tool_name, False, None, f"No active session: {session_id}", 0)

        workspace = session.workspace_path

        try:
            output = await self._dispatch(tool_name, arguments, session, workspace, user)
            duration_ms = int((time.time() - start) * 1000)
            return build_tool_envelope(tool_name, True, output, None, duration_ms)
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.warning(f"Coding tool {tool_name} failed: {e}", exc_info=True)
            return build_tool_envelope(tool_name, False, None, str(e), duration_ms)

    async def _dispatch(
        self, tool_name: str, args: Dict, session: Any, workspace: str, user: Any
    ) -> Dict:
        """Route tool_name to the correct handler."""

        # ── Filesystem & Search tools (take workspace path) ────────────
        if tool_name in _FS_HANDLERS:
            handler = _FS_HANDLERS[tool_name]
            # Scratchpad tools need the session object, not workspace
            if tool_name in ("coding_write_scratchpad", "coding_read_scratchpad"):
                return await handler(args, session)
            return await handler(args, workspace)

        # ── Command Execution tools (need sandbox) ─────────────────────
        if tool_name == "coding_run_command":
            return await _OPS_HANDLERS[tool_name](args, self.sandbox)

        if tool_name == "coding_run_tests":
            return await _OPS_HANDLERS[tool_name](args, self.sandbox, workspace)

        if tool_name == "coding_install_dependencies":
            return await _OPS_HANDLERS[tool_name](args, self.sandbox)

        # ── Git tools (need sandbox for git commands) ──────────────────
        if tool_name in ("coding_git_status", "coding_git_diff", "coding_git_commit",
                         "coding_git_create_branch", "coding_git_read_log"):
            return await _OPS_HANDLERS[tool_name](args, self.sandbox)

        if tool_name == "coding_git_push":
            token = self._get_github_token(user)
            return await _OPS_HANDLERS[tool_name](args, self.sandbox, token)

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
