#!/usr/bin/env python3
"""
Import Graph Analyzer — Development Harness

Detects circular imports in the src/ directory.

Usage:
    python scripts/verify_imports.py
    python scripts/verify_imports.py --verbose

Exit codes: 0 = clean, 1 = cycles found
"""

import ast
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set

SRC_DIR = Path(__file__).parent.parent / "src"


def module_name(filepath: Path, base: Path) -> str:
    rel = filepath.relative_to(base.parent)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].replace(".py", "")
    return ".".join(parts)


def resolve_relative(module: str, level: int, current: Path, base: Path) -> Optional[str]:
    if level == 0:
        return module
    cur = module_name(current, base).split(".")
    if level > len(cur):
        return None
    base_parts = cur[:-level]
    return ".".join(base_parts + ([module] if module else []))


def build_graph(base: Path) -> Dict[str, Set[str]]:
    graph: Dict[str, Set[str]] = defaultdict(set)
    modules: Set[str] = set()

    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(".py"):
                modules.add(module_name(Path(root) / f, base))

    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".py"):
                continue
            fp = Path(root) / f
            cur = module_name(fp, base)
            try:
                tree = ast.parse(open(fp, encoding="utf-8", errors="ignore").read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    resolved = resolve_relative(node.module or "", node.level or 0, fp, base)
                    if resolved:
                        for m in modules:
                            if resolved == m or resolved.startswith(m + ".") or m.startswith(resolved):
                                graph[cur].add(m)
                                break
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        for m in modules:
                            if alias.name == m or alias.name.startswith(m + "."):
                                graph[cur].add(m)
                                break
    return graph


def find_cycles(graph: Dict[str, Set[str]]) -> List[List[str]]:
    cycles = []
    visited: Set[str] = set()
    stack: Set[str] = set()
    path: List[str] = []

    def dfs(node: str):
        visited.add(node)
        stack.add(node)
        path.append(node)
        for nb in graph.get(node, set()):
            if nb not in visited:
                dfs(nb)
            elif nb in stack:
                idx = path.index(nb)
                cycles.append(path[idx:] + [nb])
        path.pop()
        stack.discard(node)

    for n in graph:
        if n not in visited:
            dfs(n)

    # Deduplicate
    seen = set()
    unique = []
    for c in cycles:
        core = c[:-1]
        if len(core) < 2:
            continue
        mi = core.index(min(core))
        norm = tuple(core[mi:] + core[:mi])
        if norm not in seen:
            seen.add(norm)
            unique.append(list(norm) + [norm[0]])
    return unique


def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    print("=" * 70)
    print("  🔄 Import Graph Analyzer — Development Harness")
    print("=" * 70)

    graph = build_graph(SRC_DIR)
    total_mods = len(graph)
    total_edges = sum(len(d) for d in graph.values())
    print(f"\n📊 {total_mods} modules, {total_edges} import edges")

    cycles = find_cycles(graph)

    if cycles:
        print(f"\n❌ Found {len(cycles)} circular import chain(s):\n")
        for i, c in enumerate(cycles, 1):
            short = [m.replace("src.", "") for m in c]
            print(f"  Cycle {i}: {' → '.join(short)}")
    else:
        print("\n✅ No circular imports detected")

    print(f"\n{'=' * 70}")
    if cycles:
        print(f"  ❌ FAILED — {len(cycles)} cycle(s)")
        print("  💡 Fix: Use lazy imports inside functions, or extract shared code")
    else:
        print("  ✅ PASSED")
    print(f"{'=' * 70}")

    sys.exit(0 if not cycles else 1)


if __name__ == "__main__":
    main()
