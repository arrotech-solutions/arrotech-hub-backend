#!/usr/bin/env python3
"""
Dependency Diagram Generator — Development Harness

Generates Mermaid dependency diagrams for the codebase.
Output: docs/DEPENDENCY_MAP.md (auto-generated)

Usage:
    python scripts/generate_dep_diagram.py
    python scripts/generate_dep_diagram.py --output console
"""

import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Set

PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"
DOCS_DIR = PROJECT_ROOT / "docs"


def build_service_graph() -> Dict[str, Set[str]]:
    """Build a dependency graph of service -> services it imports."""
    graph: Dict[str, Set[str]] = defaultdict(set)
    services_dir = SRC_DIR / "services"

    for filepath in sorted(services_dir.glob("*.py")):
        if filepath.name == "__init__.py":
            continue

        name = filepath.stem
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        # Find imports from other services
        for m in re.finditer(r"from\s+\.(\w+_service)\s+import", content):
            dep = m.group(1)
            if dep != name:
                graph[name].add(dep)

        # Also find relative imports like from .tool_executor
        for m in re.finditer(r"from\s+\.(\w+)\s+import", content):
            dep = m.group(1)
            dep_path = services_dir / f"{dep}.py"
            if dep_path.exists() and dep != name:
                graph[name].add(dep)

    return graph


def build_router_to_service_map() -> Dict[str, Set[str]]:
    """Map routers to the services they depend on."""
    mapping: Dict[str, Set[str]] = defaultdict(set)
    routers_dir = SRC_DIR / "routers"

    for filepath in sorted(routers_dir.glob("*.py")):
        if filepath.name == "__init__.py":
            continue

        name = filepath.stem
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for m in re.finditer(r"from\s+\.\.services\.(\w+)\s+import", content):
            mapping[name].add(m.group(1))
        for m in re.finditer(r"from\s+\.\.services\s+import\s+(\w+)", content):
            mapping[name].add(m.group(1))

    return mapping


def generate_mermaid_service_graph(graph: Dict[str, Set[str]]) -> str:
    """Generate a Mermaid diagram for service dependencies."""
    lines = ["graph LR"]

    # Classify nodes
    core = {"execution_orchestrator", "tool_executor", "dynamic_tool_registry",
            "platform_registry", "intent_processor", "tool_selector"}
    harness = {"guardrails", "feedback_loops", "quality_gates", "agent_context"}

    all_nodes = set(graph.keys())
    for deps in graph.values():
        all_nodes.update(deps)

    # Style definitions
    lines.append("    classDef core fill:#3b82f6,color:#fff,stroke:#1d4ed8")
    lines.append("    classDef harness fill:#22c55e,color:#fff,stroke:#16a34a")
    lines.append("    classDef service fill:#6b7280,color:#fff,stroke:#4b5563")

    # Add edges (limit to keep readable)
    edge_count = 0
    for src, deps in sorted(graph.items()):
        for dep in sorted(deps):
            if edge_count > 80:
                break
            src_short = src.replace("_service", "").replace("_", " ").title()
            dep_short = dep.replace("_service", "").replace("_", " ").title()
            src_id = src.replace("_", "")
            dep_id = dep.replace("_", "")
            lines.append(f'    {src_id}["{src_short}"] --> {dep_id}["{dep_short}"]')
            edge_count += 1

    # Apply styles
    for node in all_nodes:
        node_id = node.replace("_", "")
        if node in core:
            lines.append(f"    class {node_id} core")
        elif node in harness:
            lines.append(f"    class {node_id} harness")
        else:
            lines.append(f"    class {node_id} service")

    return "\n".join(lines)


def generate_high_level_diagram() -> str:
    """Generate a high-level component overview."""
    return """graph TB
    subgraph "API Layer"
        R["Routers (64)"]
    end
    subgraph "Orchestration"
        EO["Execution Orchestrator"]
        IP["Intent Processor"]
        TR["Tool Router"]
    end
    subgraph "Harness Engineering"
        GR["Guardrails"]
        FL["Feedback Loops"]
        QG["Quality Gates"]
        AC["Agent Context"]
    end
    subgraph "Execution"
        TE["Tool Executor"]
        DTR["Dynamic Tool Registry"]
        PR["Platform Registry"]
        CM["Code Mode Sandbox"]
    end
    subgraph "Services (107)"
        SVC["Integration Services"]
    end
    subgraph "Data"
        DB["PostgreSQL"]
        RD["Redis Cache"]
    end

    R --> EO
    EO --> IP
    EO --> TR
    EO --> GR
    EO --> FL
    EO --> QG
    EO --> AC
    TR --> DTR
    EO --> TE
    EO --> CM
    TE --> PR
    TE --> SVC
    SVC --> DB
    SVC --> RD

    classDef router fill:#3b82f6,color:#fff
    classDef orchestration fill:#8b5cf6,color:#fff
    classDef harness fill:#22c55e,color:#fff
    classDef execution fill:#f59e0b,color:#000
    classDef data fill:#ef4444,color:#fff

    class R router
    class EO,IP,TR orchestration
    class GR,FL,QG,AC harness
    class TE,DTR,PR,CM execution
    class DB,RD data"""


def generate_document(graph: Dict[str, Set[str]], r2s: Dict[str, Set[str]]) -> str:
    """Generate the full dependency map document."""
    lines = [
        "# Dependency Map",
        "",
        f"> Auto-generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "> **Do not edit manually** — regenerate with: `python scripts/generate_dep_diagram.py`",
        "",
        "## High-Level Architecture",
        "",
        "```mermaid",
        generate_high_level_diagram(),
        "```",
        "",
        "## Service Dependencies",
        "",
        "```mermaid",
        generate_mermaid_service_graph(graph),
        "```",
        "",
        "## Statistics",
        "",
        f"| Metric | Count |",
        f"|---|---|",
        f"| Service files | {len(graph)} |",
        f"| Dependency edges | {sum(len(d) for d in graph.values())} |",
        f"| Router-to-service mappings | {sum(len(s) for s in r2s.values())} |",
        f"| Avg dependencies per service | {sum(len(d) for d in graph.values()) / max(len(graph), 1):.1f} |",
        "",
    ]

    return "\n".join(lines) + "\n"


def main():
    output_console = "--output" in sys.argv and "console" in sys.argv

    print("Building dependency graph...")
    graph = build_service_graph()
    r2s = build_router_to_service_map()
    print(f"  {len(graph)} services, {sum(len(d) for d in graph.values())} edges")

    doc = generate_document(graph, r2s)

    if output_console:
        print(doc)
    else:
        DOCS_DIR.mkdir(exist_ok=True)
        output_path = DOCS_DIR / "DEPENDENCY_MAP.md"
        output_path.write_text(doc, encoding="utf-8")
        print(f"Dependency map written to {output_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
