## What
<!-- Brief description of the change -->

## Why
<!-- Problem being solved or feature being added -->

## Type
- [ ] :bug: Bug fix
- [ ] :sparkles: New feature
- [ ] :recycle: Refactor
- [ ] :memo: Documentation
- [ ] :wrench: Infrastructure

## Changes
<!-- List the key files modified and what changed -->

## Checklist

### Required
- [ ] Tests pass locally (`pytest tests/ -x -q`)
- [ ] Architecture verification passes (`python scripts/verify_architecture.py`)
- [ ] No new `print()` statements in `src/` (use `logger` instead)
- [ ] New/modified services have corresponding tests

### If Applicable
- [ ] Database migration generated (`alembic revision --autogenerate -m "..."`)
- [ ] `AGENTS.md` updated if adding new patterns/services
- [ ] Tool schemas added to `platform_registry.py`, `dynamic_tool_registry.py`, and `tool_executor.py`
- [ ] Router registered in `src/routers/__init__.py`

## Impact Analysis
<!-- Auto-populated by CI, or run: python scripts/analyze_impact.py --files <changed_files> -->

## Testing
<!-- Describe what you tested and how -->
