"""
Coding Agent — Tool Executor (Part 2: Commands, Git, GitHub)
Handles: run_command, run_tests, install_dependencies,
git_status, git_diff, git_commit, git_push, git_create_branch, git_read_log,
github_create_pr, github_get_pr_status, github_get_check_logs
"""
import json
import logging
import os
import re
from typing import Any, Dict, Optional

from .coding_agent_helpers import strip_sensitive_token, truncate_output

logger = logging.getLogger(__name__)


# ── Command Execution ──────────────────────────────────────────────────

async def handle_run_command(args: Dict, sandbox, redis) -> Dict:
    result = await sandbox.execute_in_sandbox(
        redis, args["session_id"], args["command"],
        timeout=min(int(args.get("timeout_seconds", 60)), 300),
        env=args.get("env"), working_directory=args.get("working_directory", "."),
    )
    result["stdout"] = truncate_output(result.get("stdout", ""))
    result["stderr"] = truncate_output(result.get("stderr", ""), 8000)
    return result


async def handle_run_tests(args: Dict, sandbox, workspace: str, redis) -> Dict:
    # Auto-detect test framework
    cmd = None
    if os.path.isfile(os.path.join(workspace, "package.json")):
        try:
            with open(os.path.join(workspace, "package.json")) as f:
                pkg = json.load(f)
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "vitest" in deps:
                cmd = "npx vitest run"
            elif "jest" in deps:
                cmd = "npx jest"
            else:
                cmd = "npm test"
        except Exception:
            cmd = "npm test"
    elif os.path.isfile(os.path.join(workspace, "pytest.ini")) or os.path.isfile(os.path.join(workspace, "conftest.py")):
        cmd = "python -m pytest"
    elif os.path.isfile(os.path.join(workspace, "pyproject.toml")):
        cmd = "python -m pytest"
    elif os.path.isfile(os.path.join(workspace, "Cargo.toml")):
        cmd = "cargo test"
    else:
        cmd = "npm test"

    # Apply filters
    test_path = args.get("test_path", "")
    test_filter = args.get("test_filter", "")
    if test_path:
        cmd += f" {test_path}"
    if test_filter:
        if "pytest" in cmd:
            cmd += f" -k '{test_filter}'"
        elif "jest" in cmd or "vitest" in cmd:
            cmd += f" -t '{test_filter}'"

    result = await sandbox.execute_in_sandbox(
        redis, args["session_id"], cmd,
        timeout=min(int(args.get("timeout_seconds", 120)), 300),
        working_directory=args.get("working_directory", "."),
    )
    stdout = result.get("stdout", "")
    # Parse pass/fail counts from common patterns
    parsed = {"passed": 0, "failed": 0, "skipped": 0}
    # Jest/Vitest: Tests: 5 passed, 1 failed
    m = re.search(r"(\d+)\s+passed", stdout)
    if m: parsed["passed"] = int(m.group(1))
    m = re.search(r"(\d+)\s+failed", stdout)
    if m: parsed["failed"] = int(m.group(1))
    m = re.search(r"(\d+)\s+skipped", stdout)
    if m: parsed["skipped"] = int(m.group(1))
    # Pytest: 5 passed, 1 failed
    m = re.search(r"(\d+) passed", stdout)
    if m: parsed["passed"] = int(m.group(1))
    m = re.search(r"(\d+) failed", stdout)
    if m: parsed["failed"] = int(m.group(1))

    result["stdout"] = truncate_output(stdout)
    result["stderr"] = truncate_output(result.get("stderr", ""), 8000)
    result["test_results"] = parsed
    result["all_passed"] = parsed["failed"] == 0 and parsed["passed"] > 0
    return result


async def handle_install_deps(args: Dict, sandbox, redis) -> Dict:
    pm = args["package_manager"]
    packages = args.get("packages", [])
    dev = args.get("dev", False)

    if packages:
        pkg_str = " ".join(packages)
        cmds = {
            "npm": f"npm install {'--save-dev' if dev else ''} {pkg_str}",
            "yarn": f"yarn add {'--dev' if dev else ''} {pkg_str}",
            "pnpm": f"pnpm add {'--save-dev' if dev else ''} {pkg_str}",
            "pip": f"pip install {pkg_str}",
            "cargo": f"cargo add {pkg_str}",
        }
    else:
        cmds = {
            "npm": "npm ci || npm install",
            "yarn": "yarn install --frozen-lockfile || yarn install",
            "pnpm": "pnpm install --frozen-lockfile || pnpm install",
            "pip": "pip install -r requirements.txt",
            "cargo": "cargo build",
        }
    cmd = cmds.get(pm, f"{pm} install")
    result = await sandbox.execute_in_sandbox(
        redis, args["session_id"], cmd, timeout=180,
        working_directory=args.get("working_directory", "."),
    )
    result["stdout"] = truncate_output(result.get("stdout", ""))
    result["stderr"] = truncate_output(result.get("stderr", ""), 8000)
    return result


# ── Git Tools ──────────────────────────────────────────────────────────

async def handle_git_status(args: Dict, sandbox, redis) -> Dict:
    sid = args["session_id"]
    status = await sandbox.run_git_command(redis, sid, "status --porcelain")
    branch = await sandbox.run_git_command(redis, sid, "branch --show-current")
    ahead = await sandbox.run_git_command(redis, sid, "rev-list @{u}..HEAD --count 2>/dev/null || echo 0")
    behind = await sandbox.run_git_command(redis, sid, "rev-list HEAD..@{u} --count 2>/dev/null || echo 0")
    files = []
    for line in status.get("stdout", "").strip().splitlines():
        if len(line) >= 4:
            files.append({"status": line[:2].strip(), "path": line[3:]})
    return {
        "branch": branch.get("stdout", "").strip(),
        "files": files,
        "clean": len(files) == 0,
        "ahead": int(ahead.get("stdout", "0").strip() or "0"),
        "behind": int(behind.get("stdout", "0").strip() or "0"),
    }


async def handle_git_diff(args: Dict, sandbox, redis) -> Dict:
    sid = args["session_id"]
    cmd = "diff"
    if args.get("staged"):
        cmd += " --cached"
    if args.get("base_ref"):
        cmd += f" {args['base_ref']}..HEAD"
    if args.get("file_path"):
        cmd += f" -- {args['file_path']}"
    result = await sandbox.run_git_command(redis, sid, cmd)
    result["stdout"] = truncate_output(result.get("stdout", ""))
    return {"diff": result.get("stdout", ""), "exit_code": result.get("exit_code", 0)}


async def handle_git_commit(args: Dict, sandbox, redis) -> Dict:
    sid = args["session_id"]
    name = args.get("author_name", "Arrotech Coding Agent")
    email = args.get("author_email", "agent@arrotechsolutions.com")
    env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}
    if args.get("add_all", True):
        add_r = await sandbox.run_git_command(redis, sid, "add -A", env=env)
        if add_r.get("exit_code", 0) != 0:
            return {"error": f"git add failed: {add_r.get('stderr', '')}"}
    msg = args["message"].replace('"', '\\"')
    commit_r = await sandbox.run_git_command(redis, sid, f'commit -m "{msg}"', env=env)
    if commit_r.get("exit_code", 0) != 0:
        return {"error": f"git commit failed: {commit_r.get('stderr', '')}"}
    hash_r = await sandbox.run_git_command(redis, sid, "rev-parse HEAD")
    return {
        "commit_hash": hash_r.get("stdout", "").strip(),
        "message": args["message"],
        "output": commit_r.get("stdout", ""),
    }


async def handle_git_push(args: Dict, sandbox, github_token: Optional[str] = None, redis=None) -> Dict:
    sid = args["session_id"]
    remote = args.get("remote", "origin")
    branch = args.get("branch", "")
    if not branch:
        br = await sandbox.run_git_command(redis, sid, "branch --show-current")
        branch = br.get("stdout", "").strip()

    # Get current remote URL
    url_r = await sandbox.run_git_command(redis, sid, f"remote get-url {remote}")
    original_url = url_r.get("stdout", "").strip()

    if not github_token:
        return {
            "error": "GitHub authentication required. Please connect your GitHub account in the Connections page, or reconnect if your token has expired.",
            "exit_code": 128, "branch": branch, "remote": remote, "output": "", "stderr": "",
        }

    if "github.com" not in original_url:
        return {
            "error": f"Remote '{remote}' does not point to github.com: {original_url}",
            "exit_code": 128, "branch": branch, "remote": remote, "output": "", "stderr": "",
        }

    # Always strip any existing credentials from the URL before injecting fresh ones.
    # This prevents stale tokens from lingering after a failed push.
    import re
    clean_url = re.sub(r'https://[^@]+@github\.com', 'https://github.com', original_url)

    # Inject the fresh token using oauth2:<token> format
    auth_url = clean_url.replace("https://github.com", f"https://oauth2:{github_token}@github.com")
    await sandbox.run_git_command(redis, sid, f"remote set-url {remote} {auth_url}")

    try:
        cmd = f"push {remote} {branch}"
        if args.get("force"):
            cmd += " --force"
        result = await sandbox.run_git_command(redis, sid, cmd)
    finally:
        # ALWAYS restore the clean URL (no credentials) regardless of success or failure
        await sandbox.run_git_command(redis, sid, f"remote set-url {remote} {clean_url}")

    stdout = strip_sensitive_token(result.get("stdout", ""), github_token)
    stderr = strip_sensitive_token(result.get("stderr", ""), github_token)
    return {"branch": branch, "remote": remote, "exit_code": result.get("exit_code", 0),
            "output": stdout, "stderr": stderr}


async def handle_git_create_branch(args: Dict, sandbox, redis) -> Dict:
    sid = args["session_id"]
    await sandbox.run_git_command(redis, sid, "fetch origin")
    name = args["branch_name"]
    from_ref = args.get("from_ref", "main")
    result = await sandbox.run_git_command(redis, sid, f"checkout -b {name} {from_ref}")
    if result.get("exit_code", 0) != 0:
        return {"error": f"Failed: {result.get('stderr', '')}"}
    return {"branch": name, "from_ref": from_ref, "output": result.get("stdout", "")}


async def handle_git_read_log(args: Dict, sandbox, redis) -> Dict:
    sid = args["session_id"]
    n = min(int(args.get("max_commits", 20)), 100)
    fmt = "--pretty=format:%H|%an|%ae|%aI|%s"
    cmd = f"log -{n} {fmt}"
    if args.get("file_path"):
        cmd += f" -- {args['file_path']}"
    result = await sandbox.run_git_command(redis, sid, cmd)
    commits = []
    for line in result.get("stdout", "").strip().splitlines():
        parts = line.split("|", 4)
        if len(parts) == 5:
            commits.append({"hash": parts[0], "author": parts[1], "email": parts[2],
                            "date": parts[3], "message": parts[4]})
    return {"commits": commits, "count": len(commits)}


# ── GitHub / PR Tools ──────────────────────────────────────────────────

async def _github_request(method: str, url: str, token: str, json_data: Dict = None) -> Dict:
    import httpx
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(method, url, headers=headers, json=json_data)
        if resp.status_code >= 400:
            raise RuntimeError(f"GitHub API {resp.status_code}: {resp.text[:500]}")
        return resp.json() if resp.text else {}


async def handle_github_create_pr(args: Dict, token: str) -> Dict:
    repo = args["repo"]
    url = f"https://api.github.com/repos/{repo}/pulls"
    data = {
        "title": args["title"], "body": args["body"],
        "head": args["head_branch"], "base": args.get("base_branch", "main"),
        "draft": args.get("draft", False),
    }
    result = await _github_request("POST", url, token, data)
    return {"pr_number": result.get("number"), "url": result.get("html_url"),
            "state": result.get("state"), "title": result.get("title")}


async def handle_github_get_pr_status(args: Dict, token: str) -> Dict:
    repo = args["repo"]
    pr_num = int(args["pr_number"])
    pr = await _github_request("GET", f"https://api.github.com/repos/{repo}/pulls/{pr_num}", token)
    sha = pr.get("head", {}).get("sha", "")
    checks = await _github_request("GET", f"https://api.github.com/repos/{repo}/commits/{sha}/check-runs", token)
    runs = []
    for cr in checks.get("check_runs", []):
        runs.append({"id": cr["id"], "name": cr["name"], "status": cr["status"],
                      "conclusion": cr.get("conclusion"), "url": cr.get("html_url")})
    all_passed = all(r.get("conclusion") == "success" for r in runs if r.get("status") == "completed")
    return {"pr_number": pr_num, "state": pr.get("state"), "mergeable": pr.get("mergeable"),
            "check_runs": runs, "all_checks_passed": all_passed and len(runs) > 0}


async def handle_github_get_check_logs(args: Dict, token: str) -> Dict:
    repo = args["repo"]
    check_id = int(args["check_run_id"])
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    # Get check run details
    cr = await _github_request("GET", f"https://api.github.com/repos/{repo}/check-runs/{check_id}", token)
    # Attempt to get job logs if it's an Actions check
    log_text = cr.get("output", {}).get("text", "") or cr.get("output", {}).get("summary", "")
    log_text = truncate_output(log_text, 20000)
    return {"check_run_id": check_id, "name": cr.get("name"), "status": cr.get("status"),
            "conclusion": cr.get("conclusion"), "logs": log_text}
