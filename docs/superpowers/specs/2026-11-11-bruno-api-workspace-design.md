# Bruno API Workspace — Design

**Date:** 2026-11-11  
**Status:** Ready for approval  
**Repo:** `arrotech-hub-backend`

## Intent

Give the team a Bruno **workspace** they can open/import that covers **all** Hub backend HTTP endpoints, with **Local** and **Production** environments, matching how the real app authenticates (cookie session).

## Goals

- Complete coverage of routes registered on the FastAPI app (same surface as `/openapi.json`).
- Bruno 3+ workspace layout (`workspace.yml`, `collections/`, `environments/`).
- Environments: `Local` (`http://localhost:8000`) and `Production` (`https://prod.api.arrotechsolutions.com`).
- Collection-level auth: cookie / credentials so login sets cookies used by later requests.
- Documented import steps for Bruno Desktop.
- Regenerable: a small script so the workspace can be refreshed when routes change.
- Commit generated `bruno/` artifacts in Git (no CI drift check in v1).

## Non-goals

- Staging environment (add later).
- Hand-polishing every request body/example.
- WebSocket-only flows beyond whatever OpenAPI exposes.
- Committing secrets (emails/passwords); env vars are placeholders only.
- Changing production API behavior.
- CI that fails when Bruno output is stale (v1).

## Anti-goals

- Incomplete “happy path only” collections sold as complete.
- Bearer-token-only setup that diverges from the app’s HttpOnly cookie auth without documenting it.

## Constraints

- Auth today: `auth_token` / `refresh_token` HttpOnly cookies; frontend uses `withCredentials: true`.
- Production TLS must be valid for Production env requests to succeed from Bruno.
- Bruno Free/OSS may limit concurrent open workspaces; files on disk are still shareable via Git.
- Generating OpenAPI may require importing `src.main:app` with env stubs so DB/Redis are not required at dump time (or use a documented fallback).

## Approaches considered

| Approach | Tradeoff | Decision |
|---|---|---|
| **1. FastAPI OpenAPI → Bruno import** | Complete + regenerable; names may be raw | **Chosen** |
| 2. Custom router scraper → YAML/Bru | Cleaner folders; easy to miss routes | Rejected for v1 |
| 3. Hand-curated subset | Best DX; not complete | Rejected |

## Decisions (partner + builder)

| Topic | Decision | Source |
|---|---|---|
| Environments | Local + Production only | Partner |
| Generation source | Offline: `app.openapi()` from local FastAPI app (stub env as needed) | Default (partner deferred) |
| Internal/admin routes | Include in shared collection; README warns they are sensitive | Default (partner deferred) |
| Production usage | Local-first; Production for careful smoke checks with personal credentials | Default (partner deferred) |
| Git | Commit generated `bruno/` workspace; no CI drift gate in v1 | Default (partner deferred) |
| Collection shape | One collection; folders by OpenAPI tags | Builder call |
| Auth mode | Cookie jar at collection level; `email`/`password` env placeholders | Builder call |

## How it will be built

### Output location

```
arrotech-hub-backend/bruno/
├── workspace.yml
├── environments/
│   ├── Local.yml          # baseUrl=http://localhost:8000
│   └── Production.yml     # baseUrl=https://prod.api.arrotechsolutions.com
├── collections/
│   └── arrotech-hub-api/  # single collection from OpenAPI (tag folders)
│       ├── opencollection.yml
│       └── …              # requests grouped by OpenAPI tags
├── openapi.json           # generated snapshot used for import
└── README.md              # how to open/import + regenerate + login + cautions
```

### Generation pipeline

1. Script `scripts/generate_bruno_workspace.py` (optional `.ps1` wrapper) that:
   - Loads FastAPI `app` with safe env defaults where needed.
   - Writes `bruno/openapi.json` from `app.openapi()`.
   - Invokes Bruno CLI (`bru import openapi` / `npx @usebruno/cli`) into `bruno/collections/arrotech-hub-api` with OpenCollection format.
   - Writes/patches `workspace.yml` and workspace `environments/`.
   - Patches collection auth for cookies + `{{baseUrl}}`.
2. Auth helper: ensure `POST {{baseUrl}}/auth/login` is easy to find; document run-login-first.
3. `README.md`: open workspace in Bruno, select env, set email/password, login, then call APIs; caution on Production writes and internal routes.

### Coverage definition

“Complete” = every path+method in the OpenAPI schema produced by importing the local FastAPI app with generation stubs. Optional routers only mounted under special flags are included when those flags can be enabled safely at dump time; otherwise noted in README.

## What’s left to the builder

- Exact Bruno CLI flags and post-import patches for `{{baseUrl}}` / cookie auth.
- Env stub details so `import src.main` works without live DB/Redis.
- Handling bru CLI install via `npx @usebruno/cli` if global `bru` is missing.
- Preserve `README.md` across regenerations.

## Success criteria

- Opening `bruno/` in Bruno (Open workspace → folder with `workspace.yml`) shows Local + Production and the Hub API collection.
- Spot-check Local: `/auth/login`, `/auth/me`, `/health`, one WhatsApp route, one workflow route exist.
- Production spot-checks are optional and cautioned; not required for “done.”
- Regenerating refreshes OpenAPI + collection without wiping README.
