"""
Coding Agent — Shared Helpers

Security utilities and common functions used across all coding agent tools.
These are the foundational building blocks that every tool calls before
performing any filesystem or execution operation.
"""

import os
import time
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Directories always excluded from filesystem walks and searches
IGNORED_DIRS = {
    "node_modules", ".git", "dist", "build", "__pycache__",
    ".next", ".venv", "venv", ".tox", ".mypy_cache",
    ".pytest_cache", "coverage", ".nyc_output", "target",
    ".terraform", ".serverless",
}

# File extensions considered binary (skip during search/read)
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".dat",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pyc", ".pyo", ".class", ".o", ".obj",
    ".sqlite", ".db", ".lock",
}


def safe_path(session_workspace: str, requested_path: str) -> str:
    """
    Resolve a requested path and verify it stays within the session workspace.

    This MUST be called at the top of every filesystem tool. If the resolved
    path escapes the workspace boundary, a ValueError is raised immediately.

    Args:
        session_workspace: Absolute path to the session workspace root.
        requested_path: The path requested by the agent (relative or absolute).

    Returns:
        The resolved absolute path, guaranteed to be within the workspace.

    Raises:
        ValueError: If the resolved path is outside the workspace (path traversal).
    """
    # Normalise workspace to remove trailing slashes for consistent comparison
    workspace_resolved = os.path.realpath(session_workspace)

    # Treat the requested path as relative to the workspace
    if os.path.isabs(requested_path):
        # Strip leading slash so it becomes relative
        requested_path = requested_path.lstrip("/").lstrip("\\")

    resolved = os.path.realpath(os.path.join(workspace_resolved, requested_path))

    # The resolved path must start with the workspace path
    if not resolved.startswith(workspace_resolved + os.sep) and resolved != workspace_resolved:
        raise ValueError(f"Path traversal attempt blocked: {requested_path}")

    return resolved


def truncate_output(text: str, max_chars: int = 16000) -> str:
    """
    Truncate long output, keeping the LAST max_chars characters.

    The tail is kept (not the head) because error messages, test failures,
    and build results typically appear at the end of command output.

    Args:
        text: The full output text.
        max_chars: Maximum characters to return. Default: 16000.

    Returns:
        The original text if short enough, or the truncated tail with a notice.
    """
    if not text or len(text) <= max_chars:
        return text

    kept = text[len(text) - max_chars:]
    return f"[OUTPUT TRUNCATED — showing last {max_chars} characters]\n\n{kept}"


def build_tool_envelope(
    tool_name: str,
    success: bool,
    output: Any,
    error: Optional[str],
    duration_ms: int,
) -> Dict[str, Any]:
    """
    Build the standard response envelope for every coding agent tool call.

    Every tool — success or failure — returns this exact structure so the
    agent can parse results consistently and self-correct on errors.

    Args:
        tool_name: Name of the tool that was called.
        success: Whether the tool completed successfully.
        output: The tool-specific output dict (None on failure).
        error: Error message string (None on success).
        duration_ms: Wall-clock execution time in milliseconds.

    Returns:
        Standard envelope dict: {tool, success, output, error, duration_ms}
    """
    return {
        "tool": tool_name,
        "success": success,
        "output": output,
        "error": error,
        "duration_ms": duration_ms,
    }


def is_binary_file(filepath: str) -> bool:
    """
    Quick check whether a file is likely binary based on its extension.

    Used by search tools to skip files that cannot be meaningfully
    searched as text.

    Args:
        filepath: Path to the file.

    Returns:
        True if the file extension is in the known binary set.
    """
    _, ext = os.path.splitext(filepath)
    return ext.lower() in BINARY_EXTENSIONS


def should_ignore_dir(dirname: str) -> bool:
    """
    Check whether a directory name should be skipped during filesystem walks.

    Args:
        dirname: The basename of the directory (not the full path).

    Returns:
        True if the directory should be ignored.
    """
    return dirname in IGNORED_DIRS


def strip_sensitive_token(text: str, token: Optional[str]) -> str:
    """
    Remove a sensitive token (e.g. GitHub PAT) from any text string.

    Must be called before returning git/GitHub error messages to the agent.

    Args:
        text: The string that may contain the token.
        token: The token value to strip. If None, text is returned as-is.

    Returns:
        The text with the token replaced by '[REDACTED]'.
    """
    if not token or not text:
        return text
    return text.replace(token, "[REDACTED]")
