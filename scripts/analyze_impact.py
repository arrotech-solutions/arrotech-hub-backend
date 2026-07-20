#!/usr/bin/env python3
"""
Dependency Graph Builder & Change Impact Analyzer — Development Harness

Two tools in one:
1. dep_graph: Builds the import dependency graph for the codebase
2. analyze_impact: Given changed files, determines blast radius

Usage:
    python scripts/analyze_impact.py                    # Analyze uncommitted changes
    python scripts/analyze_impact.py --files src/services/slack_service.py
    python scripts/analyze_impact.py --diff HEAD~1      # Changes since last commit
    python scripts/analyze_impact.py --output markdown   # For PR comments

Exit codes: 0 = analysis complete (always succeeds)
"""

import os
import re
import subprocess
import sys
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

SRC_DIR = Path(__file__).parent.parent / "src"
PROJECT_ROOT = Path(__file__).parent.parent

# Risk classification for critical files
CRITICAL_FILES = {
    "src/models.py": "CRITICAL",
    "src/database.py": "CRITICAL",
    "src/config.py": "CRITICAL",
    "src/main.py": "CRITICAL",
    "src/services/execution_orchestrator.py": "HIGH",
    "src/services/tool_executor.py": "HIGH",
    "src/services/conversational_agent_service.py": "HIGH",
    "src/services/dynamic_tool_registry.py": "HIGH",
    "src/services/platform_registry.py": "HIGH",
    "src/services/llm_service.py": "HIGH",
}


def build_reverse_dep_graph(base_dir: Path) -> Dict[str, Set[str]]:
    """Build reverse dependency graph: module -> set of modules that import it."""
    forward: Dict[str, Set[str]] = defaultdict(set)
    reverse: Dict[str, Set[str]] = defaultdict(set)

    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".py"):
                continue
            filepath = Path(root) / f
            rel = str(filepath.relative_to(PROJECT_ROOT)).replace("\\", "/")

            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
            except OSError:
                continue

            # Extract imports via regex — only resolve absolute src.* imports
            for m in re.finditer(r"from\s+(src\.[\w.]+)\s+import", content):
                module = m.group(1)
                # Resolve src.X.Y to src/X/Y
                mod_path = module.replace(".", "/")
                for suffix in [".py", "/__init__.py"]:
                    candidate = mod_path + suffix
                    candidate_path = PROJECT_ROOT / candidate
                    try:
                        if candidate_path.exists():
                            forward[rel].add(candidate.replace("\\", "/"))
                            reverse[candidate.replace("\\", "/")].add(rel)
                            break
                    except OSError:
                        continue

    return reverse


def get_changed_files(diff_ref: str = None, explicit_files: List[str] = None) -> List[str]:
    """Get list of changed files."""
    if explicit_files:
        return explicit_files

    try:
        if diff_ref:
            cmd = ["git", "diff", "--name-only", diff_ref]
        else:
            # Uncommitted + staged changes
            cmd = ["git", "diff", "--name-only", "HEAD"]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(PROJECT_ROOT), timeout=10
        )
        files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]

        # Also get staged files
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True,
            cwd=str(PROJECT_ROOT), timeout=10
        )
        files += [f.strip() for f in staged.stdout.strip().split("\n") if f.strip()]

        return list(set(f for f in files if f.endswith(".py")))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def find_related_tests(changed_file: str, tests_dir: Path) -> List[str]:
    """Find test files that likely test the changed file."""
    stem = Path(changed_file).stem
    tests = []

    # Direct match: src/services/foo.py -> tests/test_foo.py
    test_file = tests_dir / f"test_{stem}.py"
    if test_file.exists():
        tests.append(str(test_file.relative_to(PROJECT_ROOT)))

    # Also check for partial name matches
    for tf in tests_dir.glob("test_*.py"):
        if stem.replace("_service", "") in tf.stem:
            rel = str(tf.relative_to(PROJECT_ROOT))
            if rel not in tests:
                tests.append(rel)

    return tests


def classify_risk(filepath: str) -> str:
    """Classify the risk level of changing a file."""
    normalized = filepath.replace("\\", "/")

    # Check critical files
    for pattern, level in CRITICAL_FILES.items():
        if pattern in normalized:
            return level

    # Heuristic based on path
    if "tests/" in normalized:
        return "LOW"
    if "scripts/" in normalized or "docs/" in normalized:
        return "LOW"
    if "routers/" in normalized:
        return "MEDIUM"
    if "services/" in normalized:
        return "MEDIUM"
    if "observability/" in normalized:
        return "MEDIUM"

    return "MEDIUM"


def analyze(changed_files: List[str], output_format: str = "console") -> dict:
    """Run full impact analysis."""
    reverse_deps = build_reverse_dep_graph(SRC_DIR)
    tests_dir = PROJECT_ROOT / "tests"

    results = {
        "changed_files": [],
        "total_blast_radius": 0,
        "max_risk": "LOW",
        "recommended_tests": [],
    }

    risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    all_affected = set()
    all_tests = set()

    for filepath in changed_files:
        normalized = filepath.replace("\\", "/")
        risk = classify_risk(normalized)

        # Find reverse dependencies (files that import this one)
        dependents = reverse_deps.get(normalized, set())
        all_affected.update(dependents)

        # Find related tests
        tests = find_related_tests(normalized, tests_dir)
        all_tests.update(tests)

        file_info = {
            "file": normalized,
            "risk": risk,
            "dependents": sorted(dependents),
            "related_tests": tests,
        }
        results["changed_files"].append(file_info)

        if risk_order.get(risk, 0) > risk_order.get(results["max_risk"], 0):
            results["max_risk"] = risk

    results["total_blast_radius"] = len(all_affected)
    results["recommended_tests"] = sorted(all_tests)

    return results


def format_console(results: dict):
    """Print results to console."""
    risk_icons = {"LOW": "o", "MEDIUM": "!", "HIGH": "!!", "CRITICAL": "!!!"}

    print("=" * 70)
    print("  Change Impact Analysis -- Development Harness")
    print("=" * 70)

    if not results["changed_files"]:
        print("\n  No changed Python files detected.")
        print("  Tip: Use --files path/to/file.py to analyze specific files")
        print("=" * 70)
        return

    print(f"\n  Overall Risk: [{results['max_risk']}]")
    print(f"  Blast Radius: {results['total_blast_radius']} dependent module(s)")
    print(f"  Changed Files: {len(results['changed_files'])}")

    for f in results["changed_files"]:
        icon = risk_icons.get(f["risk"], "?")
        print(f"\n  [{icon}] {f['file']} (Risk: {f['risk']})")
        if f["dependents"]:
            print(f"      Dependents ({len(f['dependents'])}):")
            for d in f["dependents"][:5]:
                print(f"        - {d}")
            if len(f["dependents"]) > 5:
                print(f"        ... and {len(f['dependents']) - 5} more")
        if f["related_tests"]:
            print(f"      Tests: {', '.join(f['related_tests'])}")

    if results["recommended_tests"]:
        print(f"\n  Recommended test command:")
        test_files = " ".join(results["recommended_tests"])
        print(f"    pytest {test_files} -v")

    # Risk-based recommendations
    if results["max_risk"] == "CRITICAL":
        print(f"\n  [!!!] CRITICAL changes detected -- run FULL test suite")
        print(f"    pytest tests/ -v")
    elif results["max_risk"] == "HIGH":
        print(f"\n  [!!] HIGH-risk changes -- run affected + integration tests")

    print(f"\n{'=' * 70}")


def format_markdown(results: dict) -> str:
    """Format results as markdown (for PR comments)."""
    risk_icons = {"LOW": ":white_circle:", "MEDIUM": ":yellow_circle:", "HIGH": ":orange_circle:", "CRITICAL": ":red_circle:"}

    lines = ["## Change Impact Analysis", ""]
    lines.append(f"**Overall Risk**: {risk_icons.get(results['max_risk'], '')} {results['max_risk']}")
    lines.append(f"**Blast Radius**: {results['total_blast_radius']} dependent module(s)")
    lines.append("")
    lines.append("| File | Risk | Dependents | Tests |")
    lines.append("|---|---|---|---|")

    for f in results["changed_files"]:
        deps = len(f["dependents"])
        tests = len(f["related_tests"])
        lines.append(f"| `{f['file']}` | {f['risk']} | {deps} | {tests} |")

    if results["recommended_tests"]:
        lines.append("")
        lines.append("**Recommended tests:**")
        lines.append(f"```bash\npytest {' '.join(results['recommended_tests'])} -v\n```")

    return "\n".join(lines)


def main():
    diff_ref = None
    explicit_files = None
    output_format = "console"

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--diff" and i + 1 < len(args):
            diff_ref = args[i + 1]
            i += 2
        elif args[i] == "--files":
            explicit_files = args[i + 1:]
            break
        elif args[i] == "--output" and i + 1 < len(args):
            output_format = args[i + 1]
            i += 2
        else:
            i += 1

    changed = get_changed_files(diff_ref, explicit_files)
    results = analyze(changed, output_format)

    if output_format == "markdown":
        print(format_markdown(results))
    elif output_format == "json":
        print(json.dumps(results, indent=2))
    else:
        format_console(results)


if __name__ == "__main__":
    main()
