"""
Coding Agent — Docker Sandbox Manager
Manages Docker container lifecycle for coding agent sessions.
"""
import asyncio
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .coding_agent_helpers import strip_sensitive_token

logger = logging.getLogger(__name__)


@dataclass
class CodingAgentSession:
    """Represents an active coding agent session."""
    session_id: str
    workspace_path: str
    scratchpad_path: str
    container_id: Optional[str] = None
    repo_url: Optional[str] = None
    status: str = "creating"
    created_at: float = field(default_factory=time.time)
    last_activity_at: float = field(default_factory=time.time)
    user_id: Optional[str] = None


class CodingAgentSandbox:
    """Manages Docker containers and workspace directories for coding agent sessions."""

    def __init__(self):
        from ..config import settings
        self.sessions: Dict[str, CodingAgentSession] = {}
        self.docker_image = getattr(settings, "CODING_AGENT_DOCKER_IMAGE", "node:20-alpine")
        self.session_timeout = getattr(settings, "CODING_AGENT_SESSION_TIMEOUT", 1800)
        self.max_sessions = getattr(settings, "CODING_AGENT_MAX_SESSIONS_PER_USER", 1)
        self.cpu_limit = getattr(settings, "CODING_AGENT_CPU_LIMIT", "2")
        self.memory_limit = getattr(settings, "CODING_AGENT_MEMORY_LIMIT", "2g")
        self.sessions_dir = getattr(settings, "CODING_AGENT_SESSIONS_DIR", "/tmp/agent-sessions")
        self._docker_available: Optional[bool] = None

    async def create_session(self, session_id: str, repo_url: Optional[str] = None,
                             github_token: Optional[str] = None, user_id: Optional[str] = None) -> CodingAgentSession:
        """Create a new coding agent session with workspace and Docker container."""
        if user_id:
            active = [s for s in self.sessions.values() if s.user_id == user_id and s.status == "active"]
            if len(active) >= self.max_sessions:
                # Auto-destroy stale sessions instead of rejecting the new one
                logger.info(f"Auto-destroying {len(active)} existing session(s) for user {user_id}")
                for stale in active:
                    try:
                        await self.destroy_session(stale.session_id)
                    except Exception as e:
                        logger.warning(f"Failed to auto-destroy session {stale.session_id}: {e}")

        session_base = os.path.join(self.sessions_dir, session_id)
        workspace_path = os.path.join(session_base, "workspace")
        scratchpad_path = os.path.join(session_base, "scratchpad.md")
        os.makedirs(workspace_path, exist_ok=True)

        with open(scratchpad_path, "w", encoding="utf-8") as f:
            f.write(f"# Agent Scratchpad — Session {session_id}\n\n")

        session = CodingAgentSession(
            session_id=session_id, workspace_path=workspace_path,
            scratchpad_path=scratchpad_path, repo_url=repo_url, user_id=user_id,
        )

        if repo_url:
            await self._clone_repo(repo_url, workspace_path, github_token)

        if await self._is_docker_available():
            session.container_id = await self._create_container(session_id, workspace_path)
        else:
            logger.warning("Docker not available — sandboxed tools will run on host (DEV ONLY)")

        session.status = "active"
        self.sessions[session_id] = session
        logger.info(f"Coding agent session created: {session_id}")
        return session

    async def destroy_session(self, session_id: str) -> bool:
        """Stop container and delete workspace for a session."""
        session = self.sessions.get(session_id)
        if not session:
            return False
        session.status = "destroying"

        if session.container_id:
            try:
                await self._run_proc(["docker", "rm", "-f", session.container_id], 15)
            except Exception as e:
                logger.warning(f"Failed to remove container: {e}")

        session_base = os.path.dirname(session.workspace_path)
        shutil.rmtree(session_base, ignore_errors=True)
        session.status = "destroyed"
        del self.sessions[session_id]
        logger.info(f"Coding agent session destroyed: {session_id}")
        return True

    def get_session(self, session_id: str) -> Optional[CodingAgentSession]:
        """Get session metadata. Returns None if not found."""
        session = self.sessions.get(session_id)
        if session:
            session.last_activity_at = time.time()
        return session

    async def execute_in_sandbox(self, session_id: str, command: str,
                                  timeout: int = 60, env: Optional[Dict[str, str]] = None,
                                  working_directory: str = ".") -> Dict[str, Any]:
        """Execute a command inside the session's Docker container (or subprocess fallback)."""
        session = self.sessions.get(session_id)
        if not session or session.status != "active":
            return {"stdout": "", "stderr": "No active session", "exit_code": -1, "timed_out": False, "duration_ms": 0}

        timeout = min(timeout, 300)
        start = time.time()

        if session.container_id:
            result = await self._exec_docker(session.container_id, command, timeout, env)
        else:
            work_dir = os.path.join(session.workspace_path, working_directory)
            result = await self._exec_subprocess(command, work_dir, timeout, env)

        result["duration_ms"] = int((time.time() - start) * 1000)
        session.last_activity_at = time.time()
        return result

    async def run_git_command(self, session_id: str, git_args: str,
                              env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Run a git command against the session workspace clone."""
        session = self.sessions.get(session_id)
        if not session or session.status != "active":
            return {"stdout": "", "stderr": "No active session", "exit_code": -1}
        return await self._exec_subprocess(f"git {git_args}", session.workspace_path, 30, env)

    # ── Internal ───────────────────────────────────────────────────────

    async def _is_docker_available(self) -> bool:
        if self._docker_available is not None:
            return self._docker_available
        try:
            r = await self._run_proc(["docker", "info"], 10)
            self._docker_available = r.returncode == 0
        except Exception:
            self._docker_available = False
        return self._docker_available

    async def _create_container(self, session_id: str, workspace_path: str) -> str:
        name = f"coding-agent-{session_id[:12]}"
        cmd = [
            "docker", "run", "-d", "--name", name,
            "--cpus", self.cpu_limit, "--memory", self.memory_limit,
            "-v", f"{os.path.realpath(workspace_path)}:/workspace", "-w", "/workspace",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=512m",
            self.docker_image, "tail", "-f", "/dev/null",
        ]
        r = await self._run_proc(cmd, 60)
        if r.returncode != 0:
            stderr = r.stderr.decode("utf-8", errors="replace") if r.stderr else ""
            raise RuntimeError(f"Failed to create container: {stderr}")
        return r.stdout.decode("utf-8").strip()

    async def _clone_repo(self, repo_url: str, workspace_path: str, token: Optional[str] = None):
        """Clone a repository into the workspace.

        Tries `git clone` first.  If the `git` binary is not installed,
        falls back to downloading the GitHub tarball via the REST API.
        """
        clone_url = repo_url
        if token and "github.com" in repo_url:
            clone_url = repo_url.replace("https://github.com", f"https://{token}@github.com")

        # git clone fails if target dir exists — remove the empty pre-created one
        if os.path.isdir(workspace_path) and not os.listdir(workspace_path):
            os.rmdir(workspace_path)

        try:
            r = await self._run_proc(["git", "clone", "--depth", "1", clone_url, workspace_path], 120)
            if r.returncode != 0:
                err = strip_sensitive_token(r.stderr.decode("utf-8", errors="replace") if r.stderr else "", token)
                raise RuntimeError(f"Git clone failed: {err}")
        except FileNotFoundError:
            # git binary not installed — try GitHub tarball fallback
            logger.warning("git binary not found — falling back to GitHub tarball download")
            await self._clone_via_tarball(repo_url, workspace_path, token)
        except Exception as e:
            raise RuntimeError(strip_sensitive_token(str(e), token)) from None

    async def _clone_via_tarball(self, repo_url: str, workspace_path: str, token: Optional[str] = None):
        """Download and extract a GitHub repo as a tarball (fallback when git is unavailable)."""
        import tarfile
        import tempfile
        import io

        try:
            import httpx
        except ImportError:
            raise RuntimeError(
                "Neither git nor httpx is available. Install git in the container "
                "or add httpx to requirements.txt for tarball fallback."
            )

        # Parse owner/repo from URL
        # e.g. https://github.com/owner/repo.git → owner/repo
        parts = repo_url.rstrip("/").removesuffix(".git").split("github.com/")
        if len(parts) < 2:
            raise RuntimeError(f"Cannot parse GitHub owner/repo from URL: {repo_url}")
        owner_repo = parts[1]

        tarball_url = f"https://api.github.com/repos/{owner_repo}/tarball"
        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"token {token}"

        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.get(tarball_url, headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(f"GitHub tarball download failed ({resp.status_code})")

            os.makedirs(workspace_path, exist_ok=True)

            with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
                # GitHub tarballs have a top-level directory — strip it
                members = tar.getmembers()
                if not members:
                    raise RuntimeError("Empty tarball received from GitHub")
                prefix = members[0].name.split("/")[0] + "/"
                for member in members:
                    if member.name.startswith(prefix):
                        member.name = member.name[len(prefix):]
                        if member.name:  # skip the root dir itself
                            tar.extract(member, workspace_path)

        logger.info(f"Repo extracted via tarball to {workspace_path}")

    async def _exec_docker(self, container_id: str, command: str,
                            timeout: int, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        cmd = ["docker", "exec"]
        if env:
            for k, v in env.items():
                cmd.extend(["-e", f"{k}={v}"])
        cmd.extend(["-w", "/workspace", container_id, "sh", "-c", command])
        try:
            r = await self._run_proc(cmd, timeout)
            return {
                "stdout": r.stdout.decode("utf-8", errors="replace") if r.stdout else "",
                "stderr": r.stderr.decode("utf-8", errors="replace") if r.stderr else "",
                "exit_code": r.returncode, "timed_out": False,
            }
        except asyncio.TimeoutError:
            return {"stdout": "", "stderr": f"Timed out after {timeout}s", "exit_code": -1, "timed_out": True}

    async def _exec_subprocess(self, command: str, cwd: str,
                                timeout: int = 60, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        full_env = os.environ.copy()
        if env:
            full_env.update(env)
        try:
            proc = await asyncio.create_subprocess_shell(
                command, cwd=cwd, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=full_env,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
                "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
                "exit_code": proc.returncode or 0, "timed_out": False,
            }
        except asyncio.TimeoutError:
            try: proc.kill()
            except Exception: pass
            return {"stdout": "", "stderr": f"Timed out after {timeout}s", "exit_code": -1, "timed_out": True}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "exit_code": -1, "timed_out": False}

    async def _run_proc(self, cmd: list, timeout: int = 30) -> subprocess.CompletedProcess:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return subprocess.CompletedProcess(args=cmd, returncode=proc.returncode or 0, stdout=stdout, stderr=stderr)

    async def cleanup_expired_sessions(self) -> int:
        """Destroy sessions that exceeded idle timeout."""
        now = time.time()
        expired = [sid for sid, s in self.sessions.items()
                    if (now - s.last_activity_at) > self.session_timeout and s.status == "active"]
        for sid in expired:
            await self.destroy_session(sid)
        return len(expired)


# Global sandbox instance
coding_agent_sandbox = CodingAgentSandbox()
