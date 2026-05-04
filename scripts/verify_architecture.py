#!/usr/bin/env python3
"""
Architectural Constraint Verification — Development Harness

Enforces the layered architecture rules defined in AGENTS.md:
  Models → Services → Routers (forward-only dependencies)

This script is run in CI and as a pre-commit check.
Violations are BLOCKING — they prevent merges.

Usage:
    python scripts/verify_architecture.py
    python scripts/verify_architecture.py --verbose
    python scripts/verify_architecture.py --fix-suggestions

Exit codes:
    0 — All checks passed
    1 — Violations found

Reference: OpenAI Harness Engineering — "taste invariants" encoded as mechanical checks.
"""

import ast
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ─── Configuration ───────────────────────────────────────────────────────────

SRC_DIR = Path(__file__).parent.parent / "src"
SERVICES_DIR = SRC_DIR / "services"
ROUTERS_DIR = SRC_DIR / "routers"

# Known exceptions (documented legacy patterns from AGENTS.md)
ALLOWED_REVERSE_IMPORTS = {
    # execution_orchestrator.py is allowed to import from chat_router and subscription_router
    ("execution_orchestrator.py", "chat_router"): (
        "Legacy pattern: get_optimized_context should be moved to a service."
    ),
    ("execution_orchestrator.py", "subscription_router"): (
        "Legacy pattern: get_or_create_usage_record lazy import."
    ),
    # workflow_builder_service.py uses subscription_router
    ("workflow_builder_service.py", "subscription_router"): (
        "Legacy pattern: subscription usage tracking."
    ),
}

# Files to skip entirely (non-production, generated, etc.)
SKIP_FILES = {"__pycache__", ".pyc", "__init__.py"}

# Directories that are allowed to use print() (scripts, tests)
PRINT_ALLOWED_DIRS = {"scripts", "tests", "scratch"}


# ─── Data Classes ────────────────────────────────────────────────────────────

@dataclass
class Violation:
    """A single architecture violation."""
    rule: str
    file: str
    line: int
    message: str
    severity: str = "ERROR"  # ERROR (blocking) or WARNING (informational)
    suggestion: str = ""

    def __str__(self):
        icon = "❌" if self.severity == "ERROR" else "⚠️"
        s = f"{icon} [{self.rule}] {self.file}:{self.line} — {self.message}"
        if self.suggestion:
            s += f"\n   💡 {self.suggestion}"
        return s


@dataclass
class VerificationResult:
    """Result of the full verification run."""
    violations: List[Violation] = field(default_factory=list)
    files_checked: int = 0
    rules_checked: int = 0

    @property
    def passed(self) -> bool:
        return not any(v.severity == "ERROR" for v in self.violations)

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "ERROR")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "WARNING")


# ─── Helpers (regex-based for speed on large files) ──────────────────────────

# Max file size for AST analysis (skip print detection on huge files)
MAX_AST_SIZE = 200_000  # 200KB

def get_python_files(directory: Path) -> List[Path]:
    """Get all .py files in a directory, recursively."""
    files = []
    for root, dirs, filenames in os.walk(directory):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in filenames:
            if f.endswith(".py") and f not in SKIP_FILES:
                files.append(Path(root) / f)
    return files


def parse_imports(filepath: Path) -> List[Tuple[str, int, bool]]:
    """
    Parse imports using regex (fast, works on any file size).
    Returns: List of (imported_module, line_number, is_lazy_guess)
    """
    imports = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError:
        return imports

    indent_stack = 0  # rough heuristic: indented imports are likely lazy
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        leading_spaces = len(line) - len(line.lstrip())
        is_lazy = leading_spaces >= 8  # inside a function (2+ indent levels)

        # Match: from X import Y
        m = re.match(r"from\s+([\w.]+)\s+import", stripped)
        if m:
            imports.append((m.group(1), lineno, is_lazy))
            continue

        # Match: from ..module import Y (relative)
        m = re.match(r"from\s+(\.+[\w.]*)\s+import", stripped)
        if m:
            imports.append((m.group(1), lineno, is_lazy))
            continue

        # Match: import X
        m = re.match(r"import\s+([\w.]+)", stripped)
        if m:
            imports.append((m.group(1), lineno, is_lazy))

    return imports


def find_print_calls(filepath: Path) -> List[Tuple[int, str]]:
    """Find print() calls using regex (fast, skips huge files)."""
    results = []
    try:
        size = filepath.stat().st_size
        if size > MAX_AST_SIZE:
            return results  # Skip huge files for print detection
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError:
        return results

    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if re.search(r'\bprint\s*\(', stripped):
            results.append((lineno, stripped[:80]))

    return results


def check_logger_exists(filepath: Path) -> bool:
    """Check if a file has a module-level logger definition."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
    except (UnicodeDecodeError, OSError):
        return True  # Skip files we can't read

    # Look for: logger = logging.getLogger(__name__)
    return bool(re.search(r"logger\s*=\s*logging\.getLogger\s*\(", source))


# ─── Verification Rules ─────────────────────────────────────────────────────

def check_reverse_imports(result: VerificationResult, verbose: bool = False):
    """
    Rule: Services must not import from Routers.

    This is the most critical architectural invariant.
    """
    rule_name = "NO_REVERSE_IMPORT"
    service_files = get_python_files(SERVICES_DIR)

    for filepath in service_files:
        rel_path = filepath.relative_to(SRC_DIR)
        imports = parse_imports(filepath)

        for module, lineno, is_lazy in imports:
            # Check for router imports
            is_router_import = any([
                "routers" in module and "src" in str(filepath),
                module.startswith("..routers"),
                module.startswith("src.routers"),
            ])

            if not is_router_import:
                continue

            # Check if this is an allowed exception
            source_file = filepath.name
            exception_key = None
            for (svc_pattern, router_pattern), reason in ALLOWED_REVERSE_IMPORTS.items():
                if svc_pattern in source_file and router_pattern in module:
                    exception_key = (svc_pattern, router_pattern)
                    break

            if exception_key:
                if is_lazy:
                    if verbose:
                        print(f"  ℹ️  Allowed exception: {rel_path}:{lineno} → {module} (lazy, documented)")
                    continue
                else:
                    result.violations.append(Violation(
                        rule=rule_name,
                        file=str(rel_path),
                        line=lineno,
                        message=f"Allowed exception imports router at module level (should be lazy): {module}",
                        severity="WARNING",
                        suggestion="Move this import inside the function that uses it.",
                    ))
            else:
                result.violations.append(Violation(
                    rule=rule_name,
                    file=str(rel_path),
                    line=lineno,
                    message=f"Service imports from router layer: {module}",
                    severity="ERROR",
                    suggestion=(
                        "Move the imported function to a service, or use a lazy import "
                        "inside the function body AND document it in AGENTS.md."
                    ),
                ))


def check_print_statements(result: VerificationResult, verbose: bool = False):
    """
    Rule: No print() in production code — use logger instead.
    """
    rule_name = "NO_PRINT"
    all_files = get_python_files(SRC_DIR)

    for filepath in all_files:
        # Skip non-production directories
        rel_path = filepath.relative_to(SRC_DIR.parent)
        if any(skip_dir in str(rel_path) for skip_dir in PRINT_ALLOWED_DIRS):
            continue

        prints = find_print_calls(filepath)
        for lineno, line_content in prints:
            result.violations.append(Violation(
                rule=rule_name,
                file=str(filepath.relative_to(SRC_DIR)),
                line=lineno,
                message=f"print() found: `{line_content[:80]}`",
                severity="WARNING",  # WARNING for now (legacy code has many prints)
                suggestion="Replace with logger.info(), logger.warning(), or logger.error()",
            ))


def check_logger_presence(result: VerificationResult, verbose: bool = False):
    """
    Rule: All service and router files must have a module-level logger.
    """
    rule_name = "LOGGER_REQUIRED"

    for directory in [SERVICES_DIR, ROUTERS_DIR]:
        for filepath in get_python_files(directory):
            if filepath.name == "__init__.py":
                continue
            if filepath.suffix != ".py":
                continue
            # Skip AGENTS.md and non-python
            if not filepath.name.endswith(".py"):
                continue

            if not check_logger_exists(filepath):
                result.violations.append(Violation(
                    rule=rule_name,
                    file=str(filepath.relative_to(SRC_DIR)),
                    line=1,
                    message="Missing module-level logger definition",
                    severity="WARNING",
                    suggestion="Add: logger = logging.getLogger(__name__)",
                ))


def check_service_test_coverage(result: VerificationResult, verbose: bool = False):
    """
    Rule: Every service file should have a corresponding test file.
    """
    rule_name = "TEST_COVERAGE"
    tests_dir = SRC_DIR.parent / "tests"

    service_files = get_python_files(SERVICES_DIR)
    for filepath in service_files:
        if filepath.name == "__init__.py":
            continue
        # Skip subdirectories like harness/, agents/, google_workspace/
        if filepath.parent != SERVICES_DIR:
            continue

        # Expected test file
        test_name = f"test_{filepath.stem}.py"
        test_path = tests_dir / test_name

        if not test_path.exists():
            result.violations.append(Violation(
                rule=rule_name,
                file=str(filepath.relative_to(SRC_DIR)),
                line=0,
                message=f"No corresponding test file found (expected: tests/{test_name})",
                severity="WARNING",
                suggestion=f"Create tests/{test_name} with at least a basic import test.",
            ))


def check_router_registration(result: VerificationResult, verbose: bool = False):
    """
    Rule: Every router file should be registered in routers/__init__.py.
    """
    rule_name = "ROUTER_REGISTERED"
    init_path = ROUTERS_DIR / "__init__.py"

    if not init_path.exists():
        return

    try:
        with open(init_path, "r", encoding="utf-8") as f:
            init_content = f.read()
    except (UnicodeDecodeError, OSError):
        return

    router_files = get_python_files(ROUTERS_DIR)
    for filepath in router_files:
        if filepath.name == "__init__.py":
            continue

        module_name = filepath.stem
        # Check if the module is imported in __init__.py
        if module_name not in init_content:
            result.violations.append(Violation(
                rule=rule_name,
                file=str(filepath.relative_to(SRC_DIR)),
                line=0,
                message=f"Router '{module_name}' not found in routers/__init__.py",
                severity="WARNING",
                suggestion=f"Add import and include_router() call for {module_name} in routers/__init__.py",
            ))


def check_direct_engine_creation(result: VerificationResult, verbose: bool = False):
    """
    Rule: No direct database engine creation outside database.py.
    """
    rule_name = "NO_DIRECT_ENGINE"
    all_files = get_python_files(SRC_DIR)

    for filepath in all_files:
        if filepath.name == "database.py":
            continue

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()
        except (UnicodeDecodeError, OSError):
            continue

        # Look for create_engine or create_async_engine calls
        for i, line in enumerate(source.split("\n"), 1):
            if re.search(r"create_(?:async_)?engine\s*\(", line):
                # Skip imports
                if line.strip().startswith(("from ", "import ")):
                    continue
                result.violations.append(Violation(
                    rule=rule_name,
                    file=str(filepath.relative_to(SRC_DIR)),
                    line=i,
                    message="Direct engine creation outside database.py",
                    severity="ERROR",
                    suggestion="Use dependency injection via get_db() instead.",
                ))


# ─── Main ────────────────────────────────────────────────────────────────────

def run_verification(verbose: bool = False) -> VerificationResult:
    """Run all architectural verification checks."""
    result = VerificationResult()

    checks = [
        ("Reverse Import Detection", check_reverse_imports),
        ("Print Statement Detection", check_print_statements),
        ("Logger Presence Check", check_logger_presence),
        ("Service Test Coverage", check_service_test_coverage),
        ("Router Registration Check", check_router_registration),
        ("Direct Engine Creation", check_direct_engine_creation),
    ]

    for name, check_fn in checks:
        if verbose:
            print(f"\n🔍 Running: {name}")
        before = len(result.violations)
        check_fn(result, verbose)
        found = len(result.violations) - before
        if verbose:
            print(f"   Found {found} issue(s)")
        result.rules_checked += 1

    # Count files
    result.files_checked = len(get_python_files(SRC_DIR))

    return result


def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    print("=" * 70)
    print("  🏗️  Architectural Constraint Verification — Development Harness")
    print("=" * 70)
    print()

    result = run_verification(verbose)

    # Print results
    if result.violations:
        errors = [v for v in result.violations if v.severity == "ERROR"]
        warnings = [v for v in result.violations if v.severity == "WARNING"]

        if errors:
            print(f"\n{'─' * 70}")
            print(f"  ERRORS ({len(errors)}) — These MUST be fixed before merging")
            print(f"{'─' * 70}")
            for v in errors:
                print(f"\n{v}")

        if warnings:
            print(f"\n{'─' * 70}")
            print(f"  WARNINGS ({len(warnings)}) — Should be fixed, not blocking")
            print(f"{'─' * 70}")
            for v in warnings:
                print(f"\n{v}")

    # Summary
    print(f"\n{'=' * 70}")
    print(f"  📊 Summary: {result.files_checked} files, {result.rules_checked} rules checked")
    print(f"     Errors: {result.error_count} | Warnings: {result.warning_count}")

    if result.passed:
        print(f"  ✅ PASSED — Architecture is clean")
    else:
        print(f"  ❌ FAILED — {result.error_count} blocking violation(s) found")

    print(f"{'=' * 70}")

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
