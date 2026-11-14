# Arrotech Hub API — Bruno Workspace

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
