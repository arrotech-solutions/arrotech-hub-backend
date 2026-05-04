#!/usr/bin/env python3
"""
Change Navigator — Development Harness

Given a change intent (feature, bugfix, refactor), maps it to the exact files,
line numbers, and change patterns required.

This is the "declarative intent" layer from OpenAI's Harness Engineering:
the developer states the GOAL, the harness maps it to specific FILES.

Usage:
    python scripts/navigate_change.py "add xero invoice tool"
    python scripts/navigate_change.py "fix slack message sending"
    python scripts/navigate_change.py "refactor tool_executor"
    python scripts/navigate_change.py --list-services
    python scripts/navigate_change.py --find slack
    python scripts/navigate_change.py --trace web_search

Exit codes: 0 always (informational tool)
"""

import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"
SERVICES_DIR = SRC_DIR / "services"
ROUTERS_DIR = SRC_DIR / "routers"
TESTS_DIR = PROJECT_ROOT / "tests"


# ─── Service Index ───────────────────────────────────────────────────────────

def build_service_index() -> Dict[str, dict]:
    """Build an index of all services with metadata."""
    index = {}
    for filepath in sorted(SERVICES_DIR.glob("*.py")):
        if filepath.name == "__init__.py":
            continue
        name = filepath.stem
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        # Extract class names
        classes = re.findall(r"^class\s+(\w+)", content, re.MULTILINE)

        # Extract public methods
        methods = re.findall(r"^\s+(?:async\s+)?def\s+([a-z]\w+)", content, re.MULTILINE)
        public = [m for m in methods if not m.startswith("_")]

        # Extract keywords from docstrings and method names
        keywords = set()
        keywords.add(name.replace("_service", "").replace("_", " "))
        for m in public:
            keywords.update(m.replace("_", " ").split())
        # From docstring
        doc_match = re.search(r'"""(.+?)"""', content, re.DOTALL)
        if doc_match:
            doc_words = doc_match.group(1).lower().split()[:30]
            keywords.update(w for w in doc_words if len(w) > 3)

        index[name] = {
            "path": str(filepath.relative_to(PROJECT_ROOT)),
            "classes": classes,
            "methods": public,
            "keywords": keywords,
            "lines": len(content.split("\n")),
        }
    return index


def build_tool_index() -> Dict[str, dict]:
    """Build an index of all registered tools with their locations."""
    tools = {}
    registry_path = SERVICES_DIR / "platform_registry.py"
    executor_path = SERVICES_DIR / "tool_executor.py"

    # Scan platform_registry.py for tool definitions
    if registry_path.exists():
        try:
            content = registry_path.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")
            for i, line in enumerate(lines):
                match = re.search(r'"name"\s*:\s*"([^"]+)"', line)
                if match:
                    tool_name = match.group(1)
                    tools[tool_name] = {
                        "registry_line": i + 1,
                        "registry_file": str(registry_path.relative_to(PROJECT_ROOT)),
                    }
        except OSError:
            pass

    # Find dispatch locations in tool_executor.py
    if executor_path.exists():
        try:
            content = executor_path.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")
            for i, line in enumerate(lines):
                for tool_name in list(tools.keys()):
                    if f'"{tool_name}"' in line and ("tool_name" in line or "function_name" in line):
                        tools[tool_name]["executor_line"] = i + 1
                        tools[tool_name]["executor_file"] = str(executor_path.relative_to(PROJECT_ROOT))
        except OSError:
            pass

    return tools


def build_router_index() -> Dict[str, str]:
    """Map router names to their file paths."""
    routers = {}
    for filepath in sorted(ROUTERS_DIR.glob("*.py")):
        if filepath.name == "__init__.py":
            continue
        routers[filepath.stem] = str(filepath.relative_to(PROJECT_ROOT))
    return routers


# ─── Intent Matching ─────────────────────────────────────────────────────────

def match_services(query: str, service_index: Dict) -> List[Tuple[str, float, dict]]:
    """Match a query to relevant services using keyword scoring."""
    query_words = set(query.lower().replace("_", " ").split())
    results = []

    for name, info in service_index.items():
        score = 0
        name_words = set(name.replace("_", " ").split())

        # Direct name match (highest priority)
        for qw in query_words:
            if qw in name:
                score += 10
            for kw in info["keywords"]:
                if qw in kw or kw in qw:
                    score += 2

        # Method name matching
        for method in info["methods"]:
            for qw in query_words:
                if qw in method:
                    score += 3

        if score > 0:
            results.append((name, score, info))

    return sorted(results, key=lambda x: -x[1])


def determine_change_type(query: str) -> str:
    """Classify the type of change requested."""
    q = query.lower()

    if any(w in q for w in ["add", "new", "create", "implement", "integrate", "build"]):
        return "NEW_FEATURE"
    elif any(w in q for w in ["fix", "bug", "broken", "not working", "error", "fail", "issue"]):
        return "BUG_FIX"
    elif any(w in q for w in ["refactor", "split", "move", "rename", "reorganize", "clean"]):
        return "REFACTOR"
    elif any(w in q for w in ["update", "modify", "change", "enhance", "improve"]):
        return "ENHANCEMENT"
    elif any(w in q for w in ["remove", "delete", "deprecate", "disable"]):
        return "REMOVAL"
    else:
        return "UNKNOWN"


# ─── Change Recipes ──────────────────────────────────────────────────────────

CHANGE_RECIPES = {
    "NEW_FEATURE": {
        "title": "New Feature / Integration",
        "steps": [
            "1. Generate scaffolding: python scripts/new_service.py <name> --with-router --with-tools",
            "2. Implement service logic in src/services/<name>_service.py",
            "3. Add tool schemas to src/services/platform_registry.py",
            "4. Add tool availability to src/services/dynamic_tool_registry.py",
            "5. Add dispatch entries to src/services/tool_executor.py",
            "6. Add router endpoints in src/routers/<name>_router.py",
            "7. Register router in src/routers/__init__.py",
            "8. Write tests in tests/test_<name>_service.py",
            "9. Verify: python scripts/verify_architecture.py && python scripts/verify_tools.py",
        ],
    },
    "BUG_FIX": {
        "title": "Bug Fix",
        "steps": [
            "1. Identify the service file(s) listed below",
            "2. Write a failing test that reproduces the bug",
            "3. Fix the code",
            "4. Verify the test passes: pytest tests/test_<service>.py -v",
            "5. Check blast radius: python scripts/analyze_impact.py --files <changed_files>",
            "6. Run full verification: python scripts/verify_architecture.py",
        ],
    },
    "REFACTOR": {
        "title": "Refactoring",
        "steps": [
            "1. Run impact analysis FIRST: python scripts/analyze_impact.py --files <target_files>",
            "2. Ensure test coverage exists for the code being refactored",
            "3. Make changes incrementally",
            "4. After each change: python scripts/verify_architecture.py && python scripts/verify_imports.py",
            "5. Run affected tests after each change",
            "6. Run full test suite before pushing: pytest tests/ -x -q",
        ],
    },
    "ENHANCEMENT": {
        "title": "Enhancement / Modification",
        "steps": [
            "1. Locate the relevant service file(s) listed below",
            "2. Check existing tests for the service",
            "3. Add/modify the feature",
            "4. Update or add tests",
            "5. If modifying tool behavior: python scripts/verify_tools.py",
            "6. Verify: python scripts/verify_architecture.py",
        ],
    },
    "REMOVAL": {
        "title": "Removal / Deprecation",
        "steps": [
            "1. Run impact analysis: python scripts/analyze_impact.py --files <target_files>",
            "2. Check for dependents before removing anything",
            "3. Remove/deprecate incrementally",
            "4. Update tool registrations if removing tools",
            "5. Remove/update tests",
            "6. Full verification: python scripts/verify_architecture.py && python scripts/verify_imports.py",
        ],
    },
    "UNKNOWN": {
        "title": "General Change",
        "steps": [
            "1. See matched files below",
            "2. Run: python scripts/analyze_impact.py --files <files>",
            "3. Make changes",
            "4. Verify: python scripts/verify_architecture.py",
        ],
    },
}


# ─── Tool Tracing ────────────────────────────────────────────────────────────

def trace_tool(tool_name: str, tool_index: Dict, service_index: Dict):
    """Trace a tool through all its touchpoints."""
    print(f"\n  Tracing tool: {tool_name}")
    print(f"  {'─' * 50}")

    if tool_name not in tool_index:
        # Fuzzy search
        matches = [t for t in tool_index if tool_name in t]
        if matches:
            print(f"  Tool '{tool_name}' not found. Did you mean:")
            for m in matches[:10]:
                print(f"    - {m}")
        else:
            print(f"  Tool '{tool_name}' not found in registry.")
        return

    info = tool_index[tool_name]

    print(f"\n  1. Schema Definition:")
    print(f"     {info.get('registry_file', '?')} : line {info.get('registry_line', '?')}")

    print(f"\n  2. Dispatch Entry:")
    if "executor_line" in info:
        print(f"     {info['executor_file']} : line {info['executor_line']}")
    else:
        print(f"     Not found — may use prefix-based dispatch")

    # Find which service likely handles this tool
    platform = tool_name.split("_")[0]
    matching_services = [s for s in service_index if platform in s]
    if matching_services:
        print(f"\n  3. Service Implementation:")
        for s in matching_services:
            print(f"     {service_index[s]['path']}")

    # Find related test
    test_path = TESTS_DIR / f"test_{matching_services[0]}.py" if matching_services else None
    if test_path and test_path.exists():
        print(f"\n  4. Test File:")
        print(f"     tests/test_{matching_services[0]}.py")
    else:
        print(f"\n  4. Test File: NOT FOUND")

    # Find related router
    router_matches = [f for f in ROUTERS_DIR.glob("*.py") if platform in f.stem]
    if router_matches:
        print(f"\n  5. Router:")
        for r in router_matches:
            print(f"     {r.relative_to(PROJECT_ROOT)}")


# ─── Main Output ─────────────────────────────────────────────────────────────

def navigate(query: str):
    """Main navigation function."""
    service_index = build_service_index()
    tool_index = build_tool_index()

    # Classify change type
    change_type = determine_change_type(query)
    recipe = CHANGE_RECIPES[change_type]

    # Match relevant services
    matches = match_services(query, service_index)

    print("=" * 60)
    print(f"  Change Navigator — Development Harness")
    print("=" * 60)
    print(f"\n  Intent: \"{query}\"")
    print(f"  Type:   {recipe['title']}")

    # Show matched files
    if matches:
        print(f"\n  Relevant Files (ranked by relevance):")
        print(f"  {'─' * 50}")
        for name, score, info in matches[:8]:
            router_path = ROUTERS_DIR / f"{name.replace('_service', '')}_router.py"
            has_router = router_path.exists()
            test_path = TESTS_DIR / f"test_{name}.py"
            has_test = test_path.exists()

            print(f"\n  [{score:.0f}] {info['path']} ({info['lines']} lines)")
            print(f"       Classes: {', '.join(info['classes'][:3]) if info['classes'] else 'none'}")
            print(f"       Methods: {', '.join(info['methods'][:5])}")
            if has_router:
                print(f"       Router:  src/routers/{name.replace('_service', '')}_router.py")
            if has_test:
                print(f"       Test:    tests/test_{name}.py")

    # Show recipe
    print(f"\n  Change Recipe: {recipe['title']}")
    print(f"  {'─' * 50}")
    for step in recipe["steps"]:
        print(f"  {step}")

    # Show matched tools
    query_words = query.lower().split()
    matching_tools = [t for t in tool_index if any(w in t for w in query_words)]
    if matching_tools:
        print(f"\n  Related Tools ({len(matching_tools)}):")
        print(f"  {'─' * 50}")
        for t in matching_tools[:10]:
            info = tool_index[t]
            print(f"  - {t}")
            print(f"    Registry: {info.get('registry_file', '?')}:{info.get('registry_line', '?')}")
            if "executor_line" in info:
                print(f"    Dispatch: {info['executor_file']}:{info['executor_line']}")

    print(f"\n{'=' * 60}")


def list_services():
    """List all services with key info."""
    index = build_service_index()
    print("=" * 60)
    print("  Service Index")
    print("=" * 60)
    for name, info in sorted(index.items()):
        print(f"\n  {name} ({info['lines']} lines)")
        print(f"    Path: {info['path']}")
        if info['classes']:
            print(f"    Classes: {', '.join(info['classes'][:3])}")
        if info['methods']:
            print(f"    Methods: {', '.join(info['methods'][:8])}")
    print(f"\n  Total: {len(index)} services")
    print("=" * 60)


def find_keyword(keyword: str):
    """Find all files containing a keyword."""
    print(f"\n  Searching for: '{keyword}'")
    print(f"  {'─' * 50}")

    found = 0
    for root, dirs, files in os.walk(SRC_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".py"):
                continue
            filepath = Path(root) / f
            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            matches = []
            for i, line in enumerate(content.split("\n"), 1):
                if keyword.lower() in line.lower():
                    matches.append((i, line.strip()[:80]))

            if matches:
                rel = filepath.relative_to(PROJECT_ROOT)
                print(f"\n  {rel} ({len(matches)} match{'es' if len(matches) > 1 else ''})")
                for lineno, preview in matches[:3]:
                    print(f"    L{lineno}: {preview}")
                if len(matches) > 3:
                    print(f"    ... and {len(matches) - 3} more")
                found += len(matches)

    print(f"\n  Total: {found} matches across src/")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print('  python scripts/navigate_change.py "add xero invoice tool"')
        print('  python scripts/navigate_change.py "fix slack message sending"')
        print("  python scripts/navigate_change.py --list-services")
        print("  python scripts/navigate_change.py --find slack")
        print("  python scripts/navigate_change.py --trace web_search")
        sys.exit(0)

    if sys.argv[1] == "--list-services":
        list_services()
    elif sys.argv[1] == "--find" and len(sys.argv) > 2:
        find_keyword(sys.argv[2])
    elif sys.argv[1] == "--trace" and len(sys.argv) > 2:
        service_index = build_service_index()
        tool_index = build_tool_index()
        trace_tool(sys.argv[2], tool_index, service_index)
    else:
        query = " ".join(sys.argv[1:])
        navigate(query)


if __name__ == "__main__":
    main()
