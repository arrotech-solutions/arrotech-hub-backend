# AGENTS.md — Arrotech Hub Backend

> This file is the **operational context** for any AI coding agent or developer working
> on this codebase. It follows [OpenAI's Harness Engineering](https://openai.com/index/harness-engineering/)
> pattern: machine-readable, version-controlled, and the single source of truth for
> how to work in this repository.

---

## Build & Test Commands

```bash
# Environment setup
pip install -r requirements.txt

# Run full test suite
pytest tests/ -v

# Run single test file
pytest tests/test_<module>.py -v

# Run tests by marker
pytest tests/ -m "unit" -v
pytest tests/ -m "architecture" -v
pytest tests/ -m "harness" -v

# Quick smoke test (stop on first failure)
pytest tests/ -x -q

# Lint
flake8 src/ --max-line-length=120 --exclude=__pycache__

# Format
black src/ --line-length=120

# Type check
mypy src/ --ignore-missing-imports

# Start dev server
python -m src.main

# Database migrations
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1
```

---

## Architecture Rules (Enforced by CI)

These rules are **mechanically enforced** by `scripts/verify_architecture.py` and
`tests/test_architecture.py`. Violations will block merges.

### 1. Layer Dependency Direction

```
Models (src/models.py)
    ↓ (allowed)
Services (src/services/*.py)
    ↓ (allowed)
Routers (src/routers/*.py)
    ↓ (allowed)
Main (src/main.py)

❌ Routers → Services (reverse) is FORBIDDEN
❌ Services → Routers (reverse) is FORBIDDEN except lazy imports inside functions
```

### 2. Import Rules

- **No circular imports.** Use lazy imports (`from X import Y` inside function bodies)
  when cross-layer references are unavoidable.
- **Services must not import from routers.** The only exception is
  `execution_orchestrator.py` importing `get_optimized_context` from `chat_router.py`
  (documented legacy pattern, scheduled for refactor).
- **Routers must not import other routers** (use shared service methods instead).

### 3. Service Isolation

- Each service file owns one domain (e.g., `slack_service.py` owns all Slack logic).
- Cross-service calls go through explicit method calls, never through shared globals.
- Services receive `AsyncSession` via parameter injection, never create their own engines.

### 4. Tool Registration Consistency

Every tool in the system requires entries in **three** places:
1. `src/services/platform_registry.py` — Tool schema definition
2. `src/services/dynamic_tool_registry.py` — Tool availability rules
3. `src/services/tool_executor.py` — Dispatch mapping to service method

If any of the three is missing, `scripts/verify_tools.py` will flag it.

### 5. Observability Standards

- **All** service/router files must use `logger = logging.getLogger(__name__)`.
- **No `print()` statements** in production code (`src/`). Use `logger.info()`,
  `logger.warning()`, `logger.error()` instead.
- Tool executions must be wrapped with observability tracing (`observability_execute_tool()`).
- Harness events must be logged via `_harness_log_event()` or `log_event()`.

### 6. Security Rules

- **Never hardcode** API keys, tokens, or secrets. Use `src/config.py` settings
  or `UserSettings` BYOK resolution.
- **Encrypted storage** for sensitive fields — use `src/utils/encryption.py`.
- **Sandbox safety** for Code Mode — AST validation blocks dangerous imports
  (`os`, `sys`, `subprocess`, `socket`).

---

## Code Change Verification

Before marking any work complete, run this verification sequence:

```bash
# Step 1: All tests pass
pytest tests/ -x -q

# Step 2: Application compiles
python -c "from src.main import app; print('✅ App compiles')"

# Step 3: Architecture is clean
python scripts/verify_architecture.py

# Step 4: No circular imports
python scripts/verify_imports.py

# Step 5: Tool registry is consistent
python scripts/verify_tools.py
```

All five steps must pass. If any fails, fix the issue before committing.

---

## File Organization

```
arrotech-hub-backend/
├── AGENTS.md                    ← You are here (dev context)
├── src/
│   ├── main.py                  ← FastAPI app entry point
│   ├── config.py                ← Pydantic settings (env-based)
│   ├── database.py              ← Async SQLAlchemy engine + session
│   ├── models.py                ← All SQLAlchemy models (~86K)
│   ├── models/                  ← Model extensions
│   ├── observability/           ← Logging, tracing, middleware, DLQ
│   │   ├── logger.py            ← Structured JSON logging + DB persistence
│   │   ├── tracer.py            ← Distributed tracing (trace_id/span_id)
│   │   ├── middleware.py        ← Request lifecycle tracing
│   │   ├── tool_wrapper.py      ← Tool execution wrapping + auto-retry
│   │   └── errors.py            ← Error classification taxonomy
│   ├── routers/                 ← HTTP endpoints (64 routers)
│   │   ├── __init__.py          ← Router registration (MUST include all routers)
│   │   ├── harness_router.py    ← /_internal/harness/* monitoring API
│   │   └── ...
│   ├── services/                ← Business logic (107 service files)
│   │   ├── AGENTS.md            ← Services-specific agent context
│   │   ├── harness/             ← Harness Engineering framework
│   │   │   ├── guardrails.py    ← Pre-execution validation
│   │   │   ├── feedback_loops.py← Error classification + auto-correction
│   │   │   ├── quality_gates.py ← Post-execution response scoring
│   │   │   ├── agent_context.py ← Living documentation for runtime agents
│   │   │   └── mixin.py         ← HarnessedExecutionMixin
│   │   ├── execution_orchestrator.py ← Central AI chat coordinator (~95K)
│   │   ├── tool_executor.py     ← Tool dispatch layer (~330K)
│   │   ├── dynamic_tool_registry.py  ← Runtime tool manifest (~152K)
│   │   ├── platform_registry.py ← Tool schema definitions (~187K)
│   │   └── ...
│   └── utils/                   ← Shared utilities
├── tests/                       ← Pytest test suite (107 files)
│   ├── conftest.py              ← Fixtures (in-memory SQLite, test users)
│   ├── test_architecture.py     ← Structural invariant tests
│   ├── test_harness_components.py ← Harness framework tests
│   └── ...
├── scripts/                     ← Development harness scripts
│   ├── verify_architecture.py   ← Layer dependency enforcement
│   ├── verify_imports.py        ← Circular import detection
│   ├── verify_tools.py          ← Tool registration consistency
│   ├── analyze_impact.py        ← Change blast-radius detection
│   ├── dep_graph.py             ← Import dependency graph builder
│   ├── pre_commit_check.py      ← Fast pre-commit sanity checks
│   ├── new_service.py           ← Service scaffolding generator
│   ├── generate_service_catalog.py ← Auto-generated service docs
│   └── generate_dep_diagram.py  ← Auto-generated dependency diagrams
├── .github/
│   ├── workflows/ci.yml         ← CI/CD pipeline with harness gates
│   └── pull_request_template.md ← PR template with checklist
├── alembic/                     ← Database migrations
├── docs/                        ← Generated documentation
└── requirements.txt             ← Python dependencies
```

---

## Common Patterns

### Adding a New Integration/Service

```bash
# Use the scaffolding generator
python scripts/new_service.py <platform_name>
```

Manual steps if not using the generator:
1. Create `src/services/<platform>_service.py` — follow existing service patterns
2. Add tool schemas to `src/services/platform_registry.py`
3. Add tool availability to `src/services/dynamic_tool_registry.py`
4. Add dispatch entries to `src/services/tool_executor.py`
5. Create `src/routers/<platform>_router.py` — thin HTTP layer
6. Register router in `src/routers/__init__.py`
7. Create `tests/test_<platform>_service.py`
8. Run `python scripts/verify_tools.py` to verify consistency

### Adding a New Tool to Existing Service

1. Add tool schema to `platform_registry.py` (under the platform's section)
2. Add dispatch case to `tool_executor.py` (in the platform's executor method)
3. Add test for the new tool
4. Run `python scripts/verify_tools.py`

### Fixing a Bug

1. **Write a failing test first** that reproduces the bug
2. Fix the code
3. Verify the test passes
4. Run `python scripts/analyze_impact.py` to check blast radius
5. Run full test suite

### Refactoring

1. Run `python scripts/analyze_impact.py` on the files you plan to change
2. Ensure tests cover the code being refactored (check coverage)
3. Make changes incrementally
4. Run `python scripts/verify_architecture.py` after each change
5. Run full test suite

---

## Harness Engineering Integration

### Runtime Harness (for AI agents serving users)

The runtime harness lives in `src/services/harness/` and provides:

| Component | File | Purpose |
|---|---|---|
| Guardrails | `guardrails.py` | Pre-execution: tool ACL, injection detection, rate limiting |
| Feedback Loops | `feedback_loops.py` | Error classification + corrective instruction generation |
| Quality Gates | `quality_gates.py` | Post-execution: response scoring (completeness, accuracy, safety) |
| Agent Context | `agent_context.py` | Living docs injected into system prompts per session |
| Mixin | `mixin.py` | Composable harness for any agent class |

### Development Harness (for humans/agents modifying code)

The development harness lives in `scripts/` and enforces:

| Script | Purpose | When |
|---|---|---|
| `verify_architecture.py` | Layer dependency enforcement | CI + pre-commit |
| `verify_imports.py` | Circular import detection | CI + pre-commit |
| `verify_tools.py` | Tool registration consistency | CI + post-change |
| `analyze_impact.py` | Change blast-radius detection | CI (PR only) |
| `pre_commit_check.py` | Fast sanity checks | Pre-commit hook |
| `new_service.py` | Service scaffolding | When adding services |

---

## Known Legacy Patterns

> These are documented exceptions to the architecture rules. They should be
> refactored over time, but currently work and are not worth breaking.

1. **`execution_orchestrator.py` imports from `chat_router.py`**: The `get_optimized_context`
   function is used by the orchestrator but lives in the router layer. This is a reverse
   dependency. Future fix: move `get_optimized_context` to a service.

2. **`print()` statements in `execution_orchestrator.py`**: Debug prints exist throughout
   the orchestrator. These should be converted to `logger.info()` calls.

3. **`tool_executor.py` size (330K)**: This file is too large. Future refactor should split
   it into per-platform executor modules (e.g., `executors/slack_executor.py`).

4. **`models.py` size (86K)**: Single-file model definitions. Future refactor should split
   into `models/` package with per-domain modules.
