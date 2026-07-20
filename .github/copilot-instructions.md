# Copilot Instructions — Arrotech Hub Backend

Read `AGENTS.md` in the repo root for full operational context.

## Architecture Rules (ENFORCED BY CI — violations block merges)
1. Layer direction: Models → Services → Routers. Services NEVER import from routers.
2. All service/router files must use `logger = logging.getLogger(__name__)`, not `print()`.
3. Never hardcode API keys. Use `src/config.py` settings.
4. Tools must be registered in 3 files: `platform_registry.py`, `dynamic_tool_registry.py`, `tool_executor.py`.

## Patterns
- Services: receive `AsyncSession` via constructor, return `{"success": True/False, "data"/"error": ...}`
- New services: use `python scripts/new_service.py <name> --with-router --with-tools`
- Bug fixes: write a failing test first, then fix

## Verification (run before completing work)
```bash
python scripts/verify_architecture.py
python scripts/verify_imports.py
python scripts/verify_tools.py
pytest tests/ -x -q
```
