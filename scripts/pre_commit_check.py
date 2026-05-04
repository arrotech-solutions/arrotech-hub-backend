#!/usr/bin/env python3
"""
Pre-Commit Check — Development Harness

Fast sanity checks before commit (< 5 seconds):
1. No hardcoded API keys/secrets in staged files
2. Staged .py files have valid syntax
3. No reverse imports in staged service files

Usage:
    python scripts/pre_commit_check.py          # Check staged files
    python scripts/pre_commit_check.py --all    # Check all src/ files

Can be installed as a git hook:
    # .git/hooks/pre-commit
    #!/bin/sh
    python scripts/pre_commit_check.py
"""

import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"

# Secret patterns to detect
SECRET_PATTERNS = [
    (r'sk-[a-zA-Z0-9]{20,}', "OpenAI API key"),
    (r'sk-ant-[a-zA-Z0-9]{20,}', "Anthropic API key"),
    (r'AIza[a-zA-Z0-9_-]{35}', "Google API key"),
    (r'ghp_[a-zA-Z0-9]{36}', "GitHub personal access token"),
    (r'xoxb-[a-zA-Z0-9-]+', "Slack bot token"),
    (r'AKIA[A-Z0-9]{16}', "AWS access key"),
    (r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----', "Private key"),
    (r'password\s*=\s*["\'][^"\']{8,}["\']', "Hardcoded password"),
]

# Import direction violations
ROUTER_IMPORT_PATTERN = re.compile(
    r'from\s+\.\.routers|from\s+src\.routers|import\s+src\.routers'
)


def get_staged_files() -> list:
    """Get list of staged Python files."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True, text=True,
            cwd=str(PROJECT_ROOT), timeout=5,
        )
        return [f.strip() for f in result.stdout.strip().split("\n")
                if f.strip() and f.strip().endswith(".py")]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def check_secrets(filepath: Path) -> list:
    """Check for hardcoded secrets."""
    issues = []
    try:
        content = filepath.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return issues

    for lineno, line in enumerate(content.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        # Skip env example files and test files
        if "example" in filepath.name or "test" in filepath.name:
            continue
        for pattern, desc in SECRET_PATTERNS:
            if re.search(pattern, line):
                issues.append((lineno, desc, stripped[:60]))
    return issues


def check_syntax(filepath: Path) -> str:
    """Check Python syntax validity."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(filepath)],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return result.stderr.strip()[:200]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def check_reverse_imports(filepath: Path) -> list:
    """Check for service -> router imports."""
    issues = []
    if "services" not in str(filepath):
        return issues

    try:
        content = filepath.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return issues

    for lineno, line in enumerate(content.split("\n"), 1):
        if ROUTER_IMPORT_PATTERN.search(line.strip()):
            issues.append((lineno, line.strip()[:80]))
    return issues


def main():
    check_all = "--all" in sys.argv

    print("Pre-Commit Check -- Development Harness")
    print("-" * 50)

    if check_all:
        files = [str(f.relative_to(PROJECT_ROOT))
                 for f in SRC_DIR.rglob("*.py")
                 if "__pycache__" not in str(f)]
    else:
        files = get_staged_files()

    if not files:
        print("  No staged Python files to check.")
        sys.exit(0)

    print(f"  Checking {len(files)} file(s)...")
    total_issues = 0

    for filepath_str in files:
        filepath = PROJECT_ROOT / filepath_str

        if not filepath.exists():
            continue

        # Check secrets
        secrets = check_secrets(filepath)
        for lineno, desc, preview in secrets:
            print(f"  [SECRET] {filepath_str}:{lineno} - {desc}")
            print(f"           {preview}")
            total_issues += 1

        # Check syntax
        syntax_err = check_syntax(filepath)
        if syntax_err:
            print(f"  [SYNTAX] {filepath_str} - {syntax_err}")
            total_issues += 1

        # Check reverse imports (services only)
        reverse = check_reverse_imports(filepath)
        for lineno, line in reverse:
            print(f"  [IMPORT] {filepath_str}:{lineno} - Router import in service")
            total_issues += 1

    print(f"\n{'-' * 50}")
    if total_issues:
        print(f"  BLOCKED: {total_issues} issue(s) found. Fix before committing.")
        sys.exit(1)
    else:
        print(f"  PASSED: All {len(files)} files clean.")
        sys.exit(0)


if __name__ == "__main__":
    main()
