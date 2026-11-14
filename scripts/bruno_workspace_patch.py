"""Scaffold Bruno workspace files and patch imported collections."""
from __future__ import annotations

import re
from pathlib import Path

LOCAL_BASE_URL = "http://localhost:8000"
PRODUCTION_BASE_URL = "https://prod.api.arrotechsolutions.com"
COLLECTION_REL = "collections/arrotech-hub-api"

_HOST_RE = re.compile(
    r"https?://(?:localhost:8000|127\.0\.0\.1:8000|prod\.api\.arrotechsolutions\.com)"
)

README_TEMPLATE = """# Arrotech Hub API — Bruno Workspace

Bruno **3.0+** workspace generated from the FastAPI OpenAPI schema
(classic `.bru` collection under `collections/arrotech-hub-api`).

## Open / import in Bruno

1. Install [Bruno](https://www.usebruno.com/) 3.0 or newer.
2. Open Bruno → workspace dropdown (top-left) → **Open workspace**.
3. Select this folder (`bruno/`) — the one that contains `workspace.yml`.
4. Confirm the **Arrotech Hub API** collection appears under Collections.

Alternatively: **Import workspace** from a zip of this folder if a teammate sent one.

## Environments

Use the workspace environments:

| Environment | `baseUrl` |
|---|---|
| **Local** | `http://localhost:8000` |
| **Production** | `https://prod.api.arrotechsolutions.com` |

Fill `email` and `password` in the active environment (placeholders only in Git — never commit secrets).

**Local-first:** develop and explore against Local. Use Production only for careful smoke checks with your own credentials.

**Production caution:** Prefer read-only calls (`GET`). Avoid write/delete endpoints against Production unless you intend to change real data. TLS on the API host must be valid.

## Auth (cookies)

The Hub API uses HttpOnly cookies (`auth_token`, `refresh_token`), same as the web app.

1. Select **Local** (or Production).
2. Set `email` / `password`.
3. Run **auth → login** (`POST {{baseUrl}}/auth/login`) with body:
   ```json
   { "email": "{{email}}", "password": "{{password}}" }
   ```
4. Bruno stores response cookies; later requests should send them (collection auth is cookie-oriented).

Internal/admin routes (for example under `/api/internal`) are included for completeness — treat them as sensitive.

## Regenerate

From the backend repo root:

```bash
python scripts/generate_bruno_workspace.py
```

This refreshes `openapi.json` and `collections/arrotech-hub-api/` from the current FastAPI app. This `README.md` is preserved if it already exists.
"""


def _env_yaml(name: str, base_url: str) -> str:
    return (
        f"name: {name}\n"
        f"variables:\n"
        f"  - name: baseUrl\n"
        f"    value: {base_url}\n"
        f"  - name: email\n"
        f"    value: \"\"\n"
        f"  - name: password\n"
        f"    value: \"\"\n"
    )


def write_workspace_scaffold(bruno_root: Path) -> None:
    """Create workspace.yml and Local/Production environment files."""
    root = Path(bruno_root)
    root.mkdir(parents=True, exist_ok=True)
    env_dir = root / "environments"
    env_dir.mkdir(parents=True, exist_ok=True)
    (root / "collections").mkdir(parents=True, exist_ok=True)

    workspace = (
        "opencollection: 1.0.0\n"
        "info:\n"
        "  name: Arrotech Hub API\n"
        "  type: workspace\n"
        "collections:\n"
        f"  - name: Arrotech Hub API\n"
        f"    path: {COLLECTION_REL}\n"
    )
    (root / "workspace.yml").write_text(workspace, encoding="utf-8")
    (env_dir / "Local.yml").write_text(_env_yaml("Local", LOCAL_BASE_URL), encoding="utf-8")
    (env_dir / "Production.yml").write_text(
        _env_yaml("Production", PRODUCTION_BASE_URL), encoding="utf-8"
    )


def patch_collection_base_url(collection_dir: Path) -> int:
    """Replace hard-coded API hosts with ``{{baseUrl}}``. Returns files changed."""
    root = Path(collection_dir)
    if not root.exists():
        return 0

    patched = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".yml", ".yaml", ".bru", ".json"}:
            continue
        text = path.read_text(encoding="utf-8")
        new_text = _HOST_RE.sub("{{baseUrl}}", text)
        # Also fix servers / url prefixes that omit scheme mismatch
        if "localhost:8000" in new_text or "prod.api.arrotechsolutions.com" in new_text:
            new_text = new_text.replace("http://localhost:8000", "{{baseUrl}}")
            new_text = new_text.replace("https://localhost:8000", "{{baseUrl}}")
            new_text = new_text.replace(
                "https://prod.api.arrotechsolutions.com", "{{baseUrl}}"
            )
            new_text = new_text.replace(
                "http://prod.api.arrotechsolutions.com", "{{baseUrl}}"
            )

        if path.name in {"opencollection.yml", "bruno.json", "collection.bru"}:
            new_text = _ensure_cookie_auth(new_text, path.suffix.lower())

        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            patched += 1
    return patched


def _ensure_cookie_auth(text: str, suffix: str) -> str:
    """Best-effort cookie auth hint in collection root config."""
    if "cookie" in text.lower() and "auth" in text.lower():
        return text
    if suffix in {".yml", ".yaml"}:
        if "auth:" in text:
            return text
        return text.rstrip() + "\n\nauth:\n  type: cookie\n"
    return text


def write_readme_if_missing(bruno_root: Path) -> None:
    """Write README.md only when absent (preserves hand edits on regenerate)."""
    path = Path(bruno_root) / "README.md"
    if path.exists():
        return
    path.write_text(README_TEMPLATE, encoding="utf-8")
