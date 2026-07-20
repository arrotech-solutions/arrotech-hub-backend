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
    
    # In Python, an __init__.py file acts as its parent directory for relative imports.
    # So `from . import foo` inside `pkg/__init__.py` means `pkg.foo`.
    if current.name == "__init__.py":
        level -= 1

    if level > len(cur):
        return None
    base_parts = cur[:-level] if level > 0 else cur
    return ".".join(base_parts + ([module] if module else []))


def _top_level_imports(tree: ast.Module):
    """Yield only top-level import nodes (not those inside functions/methods).

    Lazy imports inside functions are an intentional pattern to break
    runtime circular dependencies and must not be treated as static edges.
    """
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        # Also check inside class bodies (class-level imports)
        elif isinstance(node, ast.ClassDef):
            for class_node in node.body:
                if isinstance(class_node, (ast.Import, ast.ImportFrom)):
                    yield class_node


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
            for node in _top_level_imports(tree):
                if isinstance(node, ast.ImportFrom):
                    resolved = resolve_relative(node.module or "", node.level or 0, fp, base)
                    if resolved:
                        for alias in node.names:
                            # Try the specific symbol first (might be a module)
                            full_name = f"{resolved}.{alias.name}" if resolved else alias.name
                            if full_name in modules:
                                graph[cur].add(full_name)
                            elif resolved in modules:
                                # It's just a variable/function from the resolved module
                                graph[cur].add(resolved)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        # Check if the exact module exists
                        if alias.name in modules:
                            graph[cur].add(alias.name)
                        else:
                            # It might be importing a parent package where only submodules exist,
                            # but usually we only track explicit file-to-file dependencies.
                            # If they do `import foo` and `foo/__init__.py` exists, `foo` is in modules.
                            pass
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
