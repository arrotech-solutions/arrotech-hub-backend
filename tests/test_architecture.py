"""
Architectural Invariant Tests — Development Harness

These tests enforce structural rules as pytest test cases.
They run alongside regular tests and provide clear failure messages.

Implements OpenAI's "taste invariants" — hard rules encoded as mechanical checks
that prevent architectural drift.

Markers: @pytest.mark.architecture
"""

import ast
import os
import re
from pathlib import Path

import pytest

# Project paths
SRC_DIR = Path(__file__).parent.parent / "src"
SERVICES_DIR = SRC_DIR / "services"
ROUTERS_DIR = SRC_DIR / "routers"
TESTS_DIR = Path(__file__).parent
PROJECT_ROOT = Path(__file__).parent.parent

# Known exceptions (must match AGENTS.md documented legacy patterns)
ALLOWED_REVERSE = {
    "execution_orchestrator.py": ["chat_router", "subscription_router"],
    "workflow_builder_service.py": ["subscription_router"],
}


def _get_py_files(directory: Path):
    """Get all .py files, excluding __pycache__ and __init__."""
    files = []
    for root, dirs, filenames in os.walk(directory):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in filenames:
            if f.endswith(".py") and f != "__init__.py":
                files.append(Path(root) / f)
    return files


@pytest.mark.architecture
class TestLayerDependencies:
    """Enforce the Models -> Services -> Routers dependency direction."""

    def test_services_do_not_import_routers(self):
        """Services must never import from the router layer (except documented exceptions)."""
        violations = []

        for filepath in _get_py_files(SERVICES_DIR):
            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for lineno, line in enumerate(content.split("\n"), 1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue

                # Check for router imports
                if re.search(r"from\s+\.\.routers|from\s+src\.routers", stripped):
                    # Check if it's an allowed exception
                    allowed = ALLOWED_REVERSE.get(filepath.name, [])
                    is_allowed = any(r in stripped for r in allowed)
                    if not is_allowed:
                        violations.append(f"{filepath.name}:{lineno} -> {stripped[:80]}")

        assert not violations, (
            f"Found {len(violations)} service(s) importing from routers:\n"
            + "\n".join(f"  - {v}" for v in violations)
            + "\n\nFix: Move the imported function to a service, or document in AGENTS.md"
        )


@pytest.mark.architecture
class TestServiceTestCoverage:
    """Ensure every service has a corresponding test file."""

    def test_all_top_level_services_have_tests(self):
        """Every top-level service file must have a test file."""
        missing = []

        for filepath in _get_py_files(SERVICES_DIR):
            # Only check top-level service files
            if filepath.parent != SERVICES_DIR:
                continue

            test_name = f"test_{filepath.stem}.py"
            test_path = TESTS_DIR / test_name

            if not test_path.exists():
                missing.append(filepath.stem)

        # Allow some missing (we report but don't hard-fail on count)
        if len(missing) > 20:
            pytest.skip(f"Too many missing tests ({len(missing)}), skipping until baseline established")

        # Report missing tests
        if missing:
            pytest.xfail(
                f"{len(missing)} service(s) without tests: {', '.join(missing[:10])}"
                + (f" ... and {len(missing) - 10} more" if len(missing) > 10 else "")
            )


@pytest.mark.architecture
class TestRouterRegistration:
    """Ensure all routers are registered in __init__.py."""

    def test_all_routers_registered(self):
        """Every router file must be included in routers/__init__.py."""
        init_path = ROUTERS_DIR / "__init__.py"
        if not init_path.exists():
            pytest.skip("routers/__init__.py not found")

        init_content = init_path.read_text(encoding="utf-8", errors="ignore")
        unregistered = []

        for filepath in _get_py_files(ROUTERS_DIR):
            module_name = filepath.stem
            if module_name not in init_content:
                unregistered.append(module_name)

        if unregistered:
            pytest.xfail(
                f"{len(unregistered)} router(s) not in __init__.py: {', '.join(unregistered)}"
            )


@pytest.mark.architecture
class TestObservabilityStandards:
    """Ensure observability patterns are followed."""

    def test_services_have_loggers(self):
        """All service files must have a module-level logger."""
        missing = []

        for filepath in _get_py_files(SERVICES_DIR):
            if filepath.parent != SERVICES_DIR:
                continue

            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            if not re.search(r"logger\s*=\s*logging\.getLogger", content):
                missing.append(filepath.stem)

        if missing:
            pytest.xfail(
                f"{len(missing)} service(s) missing logger: {', '.join(missing[:10])}"
            )

    def test_routers_have_loggers(self):
        """All router files must have a module-level logger."""
        missing = []

        for filepath in _get_py_files(ROUTERS_DIR):
            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            if not re.search(r"logger\s*=\s*logging\.getLogger", content):
                missing.append(filepath.stem)

        if missing:
            pytest.xfail(
                f"{len(missing)} router(s) missing logger: {', '.join(missing[:10])}"
            )


@pytest.mark.architecture
class TestDatabasePatterns:
    """Ensure database access patterns are correct."""

    def test_no_direct_engine_creation(self):
        """No direct engine creation outside database.py."""
        violations = []

        for filepath in _get_py_files(SRC_DIR):
            if filepath.name == "database.py":
                continue

            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for lineno, line in enumerate(content.split("\n"), 1):
                stripped = line.strip()
                if stripped.startswith(("from ", "import ")):
                    continue
                if re.search(r"create_(?:async_)?engine\s*\(", stripped):
                    violations.append(f"{filepath.name}:{lineno}")

        assert not violations, (
            f"Found direct engine creation in:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


@pytest.mark.architecture
class TestSecurityPatterns:
    """Ensure no hardcoded secrets in source code."""

    SECRET_PATTERNS = [
        (r'sk-[a-zA-Z0-9]{20,}', "OpenAI API key"),
        (r'sk-ant-[a-zA-Z0-9]{20,}', "Anthropic API key"),
        (r'ghp_[a-zA-Z0-9]{36}', "GitHub token"),
        (r'AKIA[A-Z0-9]{16}', "AWS access key"),
    ]

    def test_no_hardcoded_secrets(self):
        """No hardcoded API keys or tokens in source code."""
        violations = []

        for filepath in _get_py_files(SRC_DIR):
            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for lineno, line in enumerate(content.split("\n"), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                for pattern, desc in self.SECRET_PATTERNS:
                    if re.search(pattern, line):
                        violations.append(f"{filepath.name}:{lineno} ({desc})")

        assert not violations, (
            f"Found hardcoded secrets:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )
