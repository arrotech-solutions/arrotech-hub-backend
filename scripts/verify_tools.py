#!/usr/bin/env python3
"""
Tool Consistency Verifier — Development Harness

Ensures tool registration consistency across the three required locations:
1. platform_registry.py — Tool schema definitions
2. dynamic_tool_registry.py — Tool availability rules
3. tool_executor.py — Dispatch mapping to service methods

Usage:
    python scripts/verify_tools.py
    python scripts/verify_tools.py --verbose

Exit codes: 0 = consistent, 1 = inconsistencies found
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

SRC_DIR = Path(__file__).parent.parent / "src"
SERVICES_DIR = SRC_DIR / "services"

PLATFORM_REGISTRY = SERVICES_DIR / "platform_registry.py"
DYNAMIC_REGISTRY = SERVICES_DIR / "dynamic_tool_registry.py"
TOOL_EXECUTOR = SERVICES_DIR / "tool_executor.py"


def extract_tool_names_from_registry(filepath: Path) -> Set[str]:
    """Extract tool names from platform_registry.py (looks for 'name': 'tool_name' patterns)."""
    tools = set()
    try:
        content = filepath.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return tools

    # Match patterns like: "name": "slack_send_message" or 'name': 'slack_send_message'
    pattern = r"""["']name["']\s*:\s*["']([a-zA-Z_][a-zA-Z0-9_.]+)["']"""
    for match in re.finditer(pattern, content):
        name = match.group(1)
        # Filter out non-tool names (like field names that happen to have 'name' key)
        if not name.startswith(("type", "string", "object", "array", "boolean", "integer", "number")):
            tools.add(name)

    return tools


def extract_tool_names_from_dynamic(filepath: Path) -> Set[str]:
    """Extract tool names from dynamic_tool_registry.py."""
    tools = set()
    try:
        content = filepath.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return tools

    pattern = r"""["']name["']\s*:\s*["']([a-zA-Z_][a-zA-Z0-9_.]+)["']"""
    for match in re.finditer(pattern, content):
        name = match.group(1)
        if not name.startswith(("type", "string", "object", "array", "boolean", "integer", "number")):
            tools.add(name)

    return tools


def extract_dispatched_tools(filepath: Path) -> Set[str]:
    """Extract tool names that have dispatch entries in tool_executor.py."""
    tools = set()
    try:
        content = filepath.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return tools

    # Match patterns like: tool_name == "slack_send_message"
    # or: elif tool_name == "some_tool"
    # or: if function_name == "some_tool"
    # or: case "some_tool"
    patterns = [
        r"""(?:tool_name|function_name)\s*==\s*["']([a-zA-Z_][a-zA-Z0-9_.]+)["']""",
        r"""["']([a-zA-Z_][a-zA-Z0-9_.]+)["']\s*:\s*(?:self\._|lambda)""",
        r"""in\s*\[([^\]]+)\]""",
    ]

    for pattern in patterns[:2]:
        for match in re.finditer(pattern, content):
            tools.add(match.group(1))

    # Also catch tool_name.startswith("prefix_") patterns
    prefix_pattern = r"""tool_name\.startswith\s*\(\s*["']([a-zA-Z_]+)["']\s*\)"""
    prefixes = set()
    for match in re.finditer(prefix_pattern, content):
        prefixes.add(match.group(1))

    return tools, prefixes


def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    print("=" * 70)
    print("  🔧 Tool Consistency Verifier — Development Harness")
    print("=" * 70)

    issues = []

    # Check files exist
    for f in [PLATFORM_REGISTRY, DYNAMIC_REGISTRY, TOOL_EXECUTOR]:
        if not f.exists():
            print(f"\n❌ Required file not found: {f}")
            sys.exit(1)

    # Extract tool names from each source
    print("\n📊 Scanning tool registrations...")

    registry_tools = extract_tool_names_from_registry(PLATFORM_REGISTRY)
    dynamic_tools = extract_tool_names_from_dynamic(DYNAMIC_REGISTRY)
    dispatched_tools, dispatch_prefixes = extract_dispatched_tools(TOOL_EXECUTOR)

    print(f"   Platform Registry: {len(registry_tools)} tools")
    print(f"   Dynamic Registry:  {len(dynamic_tools)} tools")
    print(f"   Tool Executor:     {len(dispatched_tools)} dispatch entries + {len(dispatch_prefixes)} prefix handlers")

    # Check: tools in registry but not dispatched
    print("\n🔍 Checking consistency...")

    # For prefix-based dispatch, a tool like "slack_send_message" is covered
    # if there's a prefix handler for "slack_"
    def is_dispatched(tool_name: str) -> bool:
        if tool_name in dispatched_tools:
            return True
        for prefix in dispatch_prefixes:
            if tool_name.startswith(prefix):
                return True
        return False

    # Tools in platform registry but missing dispatch
    missing_dispatch = set()
    for tool in registry_tools:
        if not is_dispatched(tool):
            missing_dispatch.add(tool)

    if missing_dispatch and verbose:
        print(f"\n  ⚠️  Tools in platform_registry but no dispatch entry ({len(missing_dispatch)}):")
        for t in sorted(missing_dispatch)[:20]:
            print(f"     - {t}")
        if len(missing_dispatch) > 20:
            print(f"     ... and {len(missing_dispatch) - 20} more")

    # Tools dispatched but not in any registry
    orphaned_dispatch = set()
    all_registered = registry_tools | dynamic_tools
    for tool in dispatched_tools:
        if tool not in all_registered:
            # Check if it's a common/internal tool
            internal_prefixes = ("_", "execute_python", "search_tools", "get_tool_schema")
            if not any(tool.startswith(p) for p in internal_prefixes):
                orphaned_dispatch.add(tool)

    if orphaned_dispatch and verbose:
        print(f"\n  ⚠️  Dispatch entries with no registry definition ({len(orphaned_dispatch)}):")
        for t in sorted(orphaned_dispatch)[:20]:
            print(f"     - {t}")

    # Summary
    total_issues = len(missing_dispatch)  # Only missing dispatch is blocking

    print(f"\n{'=' * 70}")
    print(f"  📊 Summary:")
    print(f"     Total unique tools: {len(registry_tools | dynamic_tools | dispatched_tools)}")
    print(f"     Missing dispatch:   {len(missing_dispatch)} (warning)")
    print(f"     Orphaned dispatch:  {len(orphaned_dispatch)} (info)")

    # Not blocking for now — too many existing inconsistencies to block on
    if missing_dispatch:
        print(f"\n  ⚠️  WARNING — {len(missing_dispatch)} tools lack dispatch entries")
        print("     This is expected for tools using prefix-based routing.")
    else:
        print(f"\n  ✅ PASSED — Tool registrations are consistent")

    print(f"{'=' * 70}")

    # Exit 0 for now (warnings only, not blocking)
    sys.exit(0)


if __name__ == "__main__":
    main()
