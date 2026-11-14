# Bruno API Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a committed Bruno 3 workspace under `bruno/` covering all Hub FastAPI HTTP endpoints, with Local + Production environments and a regenerable generator script.

**Architecture:** Dump OpenAPI from the local FastAPI `app` offline, import it with Bruno CLI into one OpenCollection under `bruno/collections/arrotech-hub-api`, wrap that in `workspace.yml` + workspace environments, and patch URLs/auth to use `{{baseUrl}}` + cookies. A Python generator orchestrates dump → import → patch → preserve README.

**Tech Stack:** FastAPI OpenAPI, Python 3 generator, Bruno CLI (`bru` or `npx @usebruno/cli`), OpenCollection YAML, pytest

**Spec:** `docs/superpowers/specs/2026-11-11-bruno-api-workspace-design.md`

## Global Constraints

- Environments only: Local `http://localhost:8000`, Production `https://prod.api.arrotechsolutions.com`
- Auth: cookie jar (match HttpOnly `auth_token` / `refresh_token`); no Bearer-only default
- Coverage: `app.openapi()` from local import; include internal/admin routes
- Commit generated `bruno/`; no CI drift gate in v1
- Do not commit secrets; `email` / `password` env vars stay empty placeholders
- Preserve `bruno/README.md` across regenerations
- One collection; folders by OpenAPI tags

## Review Focus

- Generator run without live Postgres/Redis still produces OpenAPI — stub/TESTING env in dump path
- Regenerating does not delete or blank `bruno/README.md`
- Imported requests use `{{baseUrl}}`, not hard-coded hosts from OpenAPI servers
- Cookie credentials enabled so login cookies apply to later requests
- Spot-check paths from the spec exist after import (`/auth/login`, `/auth/me`, `/health`, one WhatsApp + one workflow route)

## File structure

| Path | Responsibility |
|---|---|
| `scripts/bruno_openapi.py` | Load app safely; return/write OpenAPI dict/JSON |
| `scripts/bruno_workspace_patch.py` | Write workspace.yml, env files; patch collection for `{{baseUrl}}` + cookie auth |
| `scripts/generate_bruno_workspace.py` | CLI: dump → bru import → patch; preserve README |
| `tests/test_bruno_workspace_generator.py` | Unit tests for dump helpers, patch helpers, README preserve |
| `bruno/` | Generated workspace (committed) |
| `bruno/README.md` | Import/open instructions + Local-first / Production / internal-route cautions |

---

### Task 1: OpenAPI dump helper

**Files:**
- Create: `scripts/bruno_openapi.py`
- Test: `tests/test_bruno_workspace_generator.py`

**Interfaces:**
- Consumes: FastAPI `app` from `src.main` (after env stubs)
- Produces: `ensure_generation_env() -> None`, `load_app()`, `dump_openapi(path: Path) -> dict` writing JSON to `path`

- [ ] **Step 1: Write failing tests**

```python
def test_ensure_generation_env_sets_testing_defaults(monkeypatch):
    monkeypatch.delenv("TESTING", raising=False)
    from scripts.bruno_openapi import ensure_generation_env
    ensure_generation_env()
    assert os.environ.get("TESTING") == "1"
    assert os.environ.get("ENVIRONMENT") in {"testing", "development"}

def test_dump_openapi_writes_paths(tmp_path, monkeypatch):
    # Prefer importing real app if feasible; else monkeypatch load_app to a tiny FastAPI with /health and /auth/login
    ...
    spec = dump_openapi(tmp_path / "openapi.json")
    assert (tmp_path / "openapi.json").is_file()
    assert "/health" in spec["paths"] or any("health" in p for p in spec["paths"])
```

- [ ] **Step 2: Run tests — expect FAIL (module missing)**

Run: `pytest tests/test_bruno_workspace_generator.py::test_ensure_generation_env_sets_testing_defaults tests/test_bruno_workspace_generator.py::test_dump_openapi_writes_paths -v`

- [ ] **Step 3: Implement `scripts/bruno_openapi.py`**

Signatures: `ensure_generation_env() -> None`, `load_app()`, `dump_openapi(path: Path) -> dict`. Set minimal env stubs (`TESTING=1`, dummy `SECRET_KEY` / DB URLs if required for import). Import `app` only after stubs. Write pretty JSON.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add scripts/bruno_openapi.py tests/test_bruno_workspace_generator.py
git commit -m "feat: add OpenAPI dump helper for Bruno workspace generation"
```

---

### Task 2: Workspace + collection patch helpers

**Files:**
- Create: `scripts/bruno_workspace_patch.py`
- Modify: `tests/test_bruno_workspace_generator.py`

**Interfaces:**
- Consumes: paths under `bruno/`
- Produces: `write_workspace_scaffold(bruno_root: Path) -> None`, `patch_collection_base_url(collection_dir: Path) -> int` (files patched), `write_readme_if_missing(bruno_root: Path) -> None`

- [ ] **Step 1: Write failing tests**

```python
def test_write_workspace_scaffold_envs(tmp_path):
    write_workspace_scaffold(tmp_path)
    assert (tmp_path / "workspace.yml").is_file()
    local = (tmp_path / "environments" / "Local.yml").read_text(encoding="utf-8")
    prod = (tmp_path / "environments" / "Production.yml").read_text(encoding="utf-8")
    assert "http://localhost:8000" in local
    assert "https://prod.api.arrotechsolutions.com" in prod
    assert "email" in local and "password" in local

def test_patch_collection_rewrites_hardcoded_host(tmp_path):
    # create a fake request yml with http://localhost:8000/auth/me
    n = patch_collection_base_url(tmp_path / "collections" / "arrotech-hub-api")
    assert n >= 1
    text = (tmp_path / "collections" / "arrotech-hub-api" / "auth" / "me.yml").read_text(encoding="utf-8")
    assert "{{baseUrl}}" in text
    assert "http://localhost:8000" not in text

def test_write_readme_if_missing_preserves_existing(tmp_path):
    (tmp_path / "README.md").write_text("KEEP\n", encoding="utf-8")
    write_readme_if_missing(tmp_path)
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "KEEP\n"
```

Also assert scaffold `workspace.yml` lists collection path `collections/arrotech-hub-api` and cookie/auth guidance lands in collection config or README (collection-level cookie: implement via `opencollection.yml` / collection auth fields Bruno expects — verify against a sample import if unsure).

- [ ] **Step 2: Run new tests — expect FAIL**

- [ ] **Step 3: Implement `scripts/bruno_workspace_patch.py`**

Exact env values from spec. README content must include: Open workspace steps, select Local/Production, set email/password, run login first, Local-first warning, Production write caution, internal routes warning, regenerate command.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add scripts/bruno_workspace_patch.py tests/test_bruno_workspace_generator.py
git commit -m "feat: add Bruno workspace scaffold and collection URL patching"
```

---

### Task 3: Generator CLI + Bruno import

**Files:**
- Create: `scripts/generate_bruno_workspace.py`
- Modify: `tests/test_bruno_workspace_generator.py`

**Interfaces:**
- Consumes: `dump_openapi`, `write_workspace_scaffold`, `patch_collection_base_url`, `write_readme_if_missing`
- Produces: `run_bruno_import(openapi_path: Path, output_dir: Path, collection_name: str = "Arrotech Hub API") -> None`, `generate(bruno_root: Path) -> None`, CLI `main()`

- [ ] **Step 1: Write failing tests**

```python
def test_generate_invokes_import_and_patch(tmp_path, monkeypatch):
    calls = {}
    monkeypatch.setattr("scripts.generate_bruno_workspace.dump_openapi", lambda p: {"openapi":"3.0.0","paths":{}})
    monkeypatch.setattr("scripts.generate_bruno_workspace.run_bruno_import", lambda *a, **k: calls.setdefault("import", True))
    monkeypatch.setattr("scripts.generate_bruno_workspace.patch_collection_base_url", lambda d: calls.setdefault("patch", 1) or 1)
    monkeypatch.setattr("scripts.generate_bruno_workspace.write_workspace_scaffold", lambda r: calls.setdefault("scaffold", True))
    monkeypatch.setattr("scripts.generate_bruno_workspace.write_readme_if_missing", lambda r: calls.setdefault("readme", True))
    from scripts.generate_bruno_workspace import generate
    generate(tmp_path)
    assert calls["import"] and calls["patch"] and calls["scaffold"] and calls["readme"]

def test_run_bruno_import_builds_expected_argv(monkeypatch, tmp_path):
    # capture subprocess.run argv; accept either bru or npx @usebruno/cli
    ...
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement generator**

`run_bruno_import` should try `bru` on PATH, else `npx --yes @usebruno/cli`. Flags: `import openapi --source <openapi.json> --output <collections/> --collection-name "Arrotech Hub API" --collection-format=opencollection`. Clear/replace `collections/arrotech-hub-api` before import so regeneration is clean (do not delete README at bruno root).

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_bruno_workspace.py tests/test_bruno_workspace_generator.py
git commit -m "feat: add generate_bruno_workspace CLI orchestration"
```

---

### Task 4: Generate committed workspace + spot-check

**Files:**
- Create/overwrite: `bruno/**` (except preserve README once written)
- Create: `bruno/README.md` (via generator)
- Create: `bruno/openapi.json`

**Interfaces:**
- Consumes: `python scripts/generate_bruno_workspace.py`
- Produces: committed workspace ready to open in Bruno 3+

- [ ] **Step 1: Run generator against real repo**

Run from backend root: `python scripts/generate_bruno_workspace.py`  
Expected: `bruno/workspace.yml`, `bruno/environments/Local.yml`, `bruno/environments/Production.yml`, `bruno/collections/arrotech-hub-api/opencollection.yml`, `bruno/openapi.json`, `bruno/README.md`

- [ ] **Step 2: Spot-check paths exist in openapi + collection**

Assert (script or one-off pytest) that OpenAPI and/or collection contain routes for:
- `/auth/login`
- `/auth/me`
- `/health`
- at least one path containing `whatsapp` (case-insensitive)
- at least one path containing `workflow`

- [ ] **Step 3: Manual sanity — Bruno CLI import succeeded**

Confirm collection directory has many request YAML files (not empty). If `bru`/`npx` fails, fix install/flags and re-run; do not commit a half-empty collection.

- [ ] **Step 4: Commit workspace**

```bash
git add bruno scripts/generate_bruno_workspace.py scripts/bruno_openapi.py scripts/bruno_workspace_patch.py tests/test_bruno_workspace_generator.py
git commit -m "feat: commit Bruno API workspace generated from OpenAPI"
```

---

## Execution notes

- Prefer running generator inside the backend venv that can `import src.main`.
- If full app import is too heavy, keep dump behind `TESTING=1` stubs; only as last resort document fetching OpenAPI from a running local server — still not from Production as source of truth.
- After implementation, user opens Bruno → workspace dropdown → **Open workspace** → select `arrotech-hub-backend/bruno` (folder containing `workspace.yml`). Details belong in `bruno/README.md`.
