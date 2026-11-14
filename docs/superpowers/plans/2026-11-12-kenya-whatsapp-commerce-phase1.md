# Kenya WhatsApp Commerce Phase 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a complete Kenya sell loop on Arrotech DB — catalog in, smart WhatsApp product search, M-Pesa checkout, orders/reservations persisted and visible in Hub — with no Google, no `kb_id`, and no intelligence drop.

**Architecture:** Add first-class `CatalogProduct`, `CommerceOrder`, and `CommerceReservation` tables. Catalog Builder and CRUD/import write products to DB; library WhatsApp Ordering Agent defaults to `storage_provider=arrotech_db` and searches the merchant catalog via a new `CatalogSearchService` instead of RAG when no KB is configured. Conversational agent persist/read paths gain an `arrotech_db` branch. Hub gets an Orders ops page (list, payment, customer, status, reservations).

**Tech Stack:** FastAPI, SQLAlchemy/Postgres, Alembic, Celery (existing), React/TypeScript frontend, existing OpenAI embeddings path if used for search, existing `FileManagementService` for images.

**Spec:** `docs/superpowers/specs/2026-11-12-kenya-whatsapp-commerce-design.md`

**Out of this plan:** Phase 2 guided Go-live wizard; Phase 3 Sheets/Airtable sync (separate plans after Phase 1 ships).

## Global Constraints

- Default Kenya path requires only WhatsApp + M-Pesa + Arrotech DB (no Google).
- Product search quality must match or beat current RAG for messy/slang queries; LLM keeps conversation/intent.
- Library deploy remains the primary agent path (`whatsapp_ordering_agent`).
- Phase 1 must be end-to-end: Hub Orders ops essentials + reservations in Arrotech DB.
- Do not remove canvas `rag_*` tools or Sheets/Airtable code paths; add `arrotech_db` alongside them.
- Photos for the default path must not require Google Drive.

## Review Focus

- Empty catalog + deployed agent → `search_products` returns a clear “no products” result, never pretends items exist.
- `storage_provider=arrotech_db` with STK paid callback → order payment_status becomes `paid` in DB and Hub list.
- Reservation enabled + customer books table → row in `commerce_reservations` visible on Orders UI.
- Deploy without `kb_id` and without Google still activates the ordering workflow.
- Catalog image URLs returned to WhatsApp must be publicly fetchable by Meta (not localhost-only Drive links).

---

## File map

| File | Responsibility |
|------|----------------|
| `arrotech-hub-backend/src/models.py` | `CatalogProduct`, `CommerceOrder`, `CommerceReservation` |
| `arrotech-hub-backend/alembic/versions/*_commerce_catalog_orders.py` | Migration |
| `arrotech-hub-backend/src/services/catalog_service.py` | Product CRUD + CSV import |
| `arrotech-hub-backend/src/services/catalog_search_service.py` | Smart product search |
| `arrotech-hub-backend/src/services/commerce_storage_service.py` | Order/reservation/payment persistence |
| `arrotech-hub-backend/src/services/catalog_image_service.py` | Store image + public URL |
| `arrotech-hub-backend/src/routers/catalog_router.py` | Merchant catalog API |
| `arrotech-hub-backend/src/routers/commerce_orders_router.py` | Orders/reservations API |
| `arrotech-hub-backend/src/routers/catalog_builder_router.py` | Add DB save path; keep Sheets optional |
| `arrotech-hub-backend/src/services/catalog_builder_service.py` | Optional Sheets export only |
| `arrotech-hub-backend/src/services/conversational_agent_service.py` | Search + persist branches |
| `arrotech-hub-backend/src/services/whatsapp_ordering_helpers.py` | Normalize `arrotech_db` |
| `arrotech-hub-backend/src/routers/templates_router.py` | Template defaults / required_connections |
| `arrotech-hub-backend/src/main.py` | Mount new routers |
| `arrotech-hub-frontend/src/pages/CatalogBuilder.tsx` | Default save to Arrotech DB |
| `arrotech-hub-frontend/src/pages/CommerceOrders.tsx` | Orders ops UI |
| `arrotech-hub-frontend/src/App.tsx` + `Layout.tsx` | Route + nav |
| `arrotech-hub-frontend/src/components/WorkflowTemplates.tsx` | Deploy form: no required kb/Google for default |

---

### Task 1: Catalog + commerce models and migration

**Files:**
- Modify: `arrotech-hub-backend/src/models.py`
- Create: `arrotech-hub-backend/alembic/versions/<rev>_commerce_catalog_orders.py`
- Test: `arrotech-hub-backend/tests/test_commerce_models.py`

**Interfaces:**
- Produces: ORM classes `CatalogProduct`, `CommerceOrder`, `CommerceReservation` with fields below

**Model fields (pinned):**

`CatalogProduct`: `id` UUID PK, `user_id` FK users, `name` str, `price` Numeric(12,2), `cost_price` Numeric nullable, `description` Text, `category` str, `sku` str, `brand` str, `quantity` Numeric nullable, `unit` str, `condition` str, `image_url` str, `availability` str default `in_stock`, `search_text` Text (name+description+category+brand for lexical search), `embedding` JSON nullable (list[float] if used), `created_at`, `updated_at`. Index `(user_id, name)`.

`CommerceOrder`: `id` UUID PK, `user_id` FK, `external_order_id` str (agent order id), `customer_name`, `customer_phone`, `status` str (use existing `ORDER_STATUSES`), `payment_status` str (`pending`\|`paid`\|`failed`), `payment_method` str nullable, `currency` default `KES`, `total` Numeric, `line_items` JSON, `delivery_method` str, `delivery_address` Text nullable, `notes` Text nullable, `mpesa_receipt` str nullable, `raw_snapshot` JSON nullable, `created_at`, `updated_at`. Unique `(user_id, external_order_id)`.

`CommerceReservation`: `id` UUID PK, `user_id` FK, `external_reservation_id` str, `customer_name`, `customer_phone`, `reservation_date` str, `reservation_time` str, `party_size` int, `status` str default `confirmed`, `notes` Text nullable, `raw_snapshot` JSON nullable, `created_at`, `updated_at`. Unique `(user_id, external_reservation_id)`.

- [ ] **Step 1: Write failing test** that imports the three model classes and asserts `__tablename__` values `catalog_products`, `commerce_orders`, `commerce_reservations`

- [ ] **Step 2: Run test — expect FAIL** (classes missing)

```bash
cd arrotech-hub-backend && python -m pytest tests/test_commerce_models.py -v
```

- [ ] **Step 3: Add models + Alembic migration; run upgrade on dev DB**

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add arrotech-hub-backend/src/models.py arrotech-hub-backend/alembic/versions/ arrotech-hub-backend/tests/test_commerce_models.py
git commit -m "feat(commerce): add catalog and order models"
```

---

### Task 2: CatalogService CRUD + CSV import

**Files:**
- Create: `arrotech-hub-backend/src/services/catalog_service.py`
- Test: `arrotech-hub-backend/tests/test_catalog_service.py`

**Interfaces:**
- Consumes: `CatalogProduct`
- Produces:
  - `async def create_product(db, user_id, data: dict) -> CatalogProduct`
  - `async def update_product(db, user_id, product_id, data: dict) -> CatalogProduct`
  - `async def delete_product(db, user_id, product_id) -> None`
  - `async def list_products(db, user_id, *, q: str | None = None, limit: int = 100, offset: int = 0) -> list[CatalogProduct]`
  - `async def bulk_upsert_from_rows(db, user_id, rows: list[dict]) -> dict` with `{created, updated, errors}`
  - `def build_search_text(product_fields: dict) -> str`

CSV/row keys accepted (case-insensitive, match Catalog Builder headers): `name`, `Price`, `Cost Price`, `Description`, `Category`, `SKU`, `Brand`, `Quantity`, `Unit`, `Condition`, `image_url`, `Availability`.

- [ ] **Step 1: Write failing tests** `test_create_and_list_product`, `test_bulk_upsert_from_rows_creates_two`, `test_build_search_text_includes_name_and_category`

- [ ] **Step 2: Run — expect FAIL**

```bash
cd arrotech-hub-backend && python -m pytest tests/test_catalog_service.py -v
```

- [ ] **Step 3: Implement `CatalogService` in `catalog_service.py`**

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit** `feat(commerce): catalog CRUD and CSV upsert`

---

### Task 3: Catalog image public URLs

**Files:**
- Create: `arrotech-hub-backend/src/services/catalog_image_service.py`
- Modify: `arrotech-hub-backend/src/main.py` (static/public route if needed)
- Test: `arrotech-hub-backend/tests/test_catalog_image_service.py`

**Interfaces:**
- Produces: `async def store_catalog_image(user_id, filename: str, content: bytes, content_type: str) -> str` → absolute HTTPS (or configured `PUBLIC_API_BASE_URL`) URL Meta can fetch
- Builder call: reuse `FileManagementService` disk layout under `uploads/{user_id}/catalog/`; expose `GET /api/public/catalog-images/{user_id}/{filename}` **without auth** but path-hardened (no `..`)

- [ ] **Step 1: Write failing test** `test_store_catalog_image_returns_url_containing_public_path`

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement store + public GET route; pin `PUBLIC_API_BASE_URL` env for absolute URLs**

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit** `feat(commerce): public catalog image URLs`

---

### Task 4: CatalogSearchService (smart match)

**Files:**
- Create: `arrotech-hub-backend/src/services/catalog_search_service.py`
- Test: `arrotech-hub-backend/tests/test_catalog_search_service.py`

**Interfaces:**
- Consumes: `CatalogProduct`, optional embeddings via existing OpenAI helper used elsewhere in Hub
- Produces: `async def search_products(db, user_id, query: str, *, top_k: int = 10) -> list[dict]`  
  Each dict: `{name, price, description, category, image_url, availability, sku, score}`  
  Must rank lexical/`search_text` hits; if embeddings present, hybrid-rank. Empty catalog → `[]` with no throw.

**Pinned slang fixtures (must hit):**
- Product named `Simba Chips` → query `chips` returns it
- Product named `Coca-Cola 500ml` → query `soda` OR `coke` returns it (allow synonym map or embedding; document chosen approach in commit body)
- Query `xyzzy-no-match` → `[]`

- [ ] **Step 1: Write failing tests** for the three fixtures above (seed products in test DB/session)

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement search** (prefer hybrid: ILIKE/`search_text` + optional embedding cosine; synonym dict for common Kenyan drink/food terms as needed for fixtures)

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit** `feat(commerce): smart catalog search`

---

### Task 5: Catalog HTTP API + wire Catalog Builder save-to-DB

**Files:**
- Create: `arrotech-hub-backend/src/routers/catalog_router.py`
- Modify: `arrotech-hub-backend/src/routers/catalog_builder_router.py`
- Modify: `arrotech-hub-backend/src/main.py`
- Modify: `arrotech-hub-frontend/src/pages/CatalogBuilder.tsx`
- Test: `arrotech-hub-backend/tests/test_catalog_router.py`

**Interfaces:**
- `GET /api/catalog/products`, `POST /api/catalog/products`, `PATCH /api/catalog/products/{id}`, `DELETE /api/catalog/products/{id}`
- `POST /api/catalog/products/import` (CSV multipart)
- `POST /api/catalog/products/from-builder` body: `{products: [...]}` after extract/edit (stores images via Task 3 when bytes/urls provided)
- `POST /api/catalog-builder/export` gains `destination`: `arrotech_db` \| `google_sheets` (default `arrotech_db`). Sheets path keeps current Google requirement; DB path does **not** require Google.

- [ ] **Step 1: Write failing API tests** for create/list and `export` with `destination=arrotech_db` without Google connection

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement router + builder destination; update CatalogBuilder success UI** — primary CTA “Saved to Arrotech”; Sheets optional secondary; remove “Go to Workflows / ingest KB” as required next step

- [ ] **Step 4: Run API tests — expect PASS**

- [ ] **Step 5: Commit** `feat(commerce): catalog API and DB export default`

---

### Task 6: CommerceStorageService (orders + reservations + payment)

**Files:**
- Create: `arrotech-hub-backend/src/services/commerce_storage_service.py`
- Test: `arrotech-hub-backend/tests/test_commerce_storage_service.py`

**Interfaces:**
- Produces:
  - `async def upsert_order(db, user_id, order: dict) -> CommerceOrder`
  - `async def update_order_status(db, user_id, external_order_id, status: str) -> CommerceOrder`
  - `async def mark_order_paid(db, user_id, external_order_id, *, mpesa_receipt: str | None = None) -> CommerceOrder`
  - `async def list_orders(db, user_id, *, limit=50, offset=0) -> list[CommerceOrder]`
  - `async def get_order(db, user_id, external_order_id) -> CommerceOrder | None`
  - `async def upsert_reservation(db, user_id, reservation: dict) -> CommerceReservation`
  - `async def list_reservations(db, user_id, *, limit=50, offset=0) -> list[CommerceReservation]`

- [ ] **Step 1: Write failing tests** `test_upsert_order_and_mark_paid`, `test_upsert_reservation`

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement service**

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit** `feat(commerce): order and reservation storage service`

---

### Task 7: Wire conversational agent to Arrotech catalog + storage

**Files:**
- Modify: `arrotech-hub-backend/src/services/conversational_agent_service.py` (`_sub_search_products`, persist/update/reservation branches ~5080–9200)
- Modify: `arrotech-hub-backend/src/services/whatsapp_ordering_helpers.py` (`normalize_agent_storage_settings`)
- Modify: `arrotech-hub-backend/src/tasks/order_payment_tasks.py` (paid callback → `mark_order_paid` when provider `arrotech_db`)
- Test: `arrotech-hub-backend/tests/test_conversational_agent_arrotech_db.py`

**Interfaces:**
- Consumes: `CatalogSearchService.search_products`, `CommerceStorageService.*`
- `normalize_agent_storage_settings`: if provider empty/`none` and no sheet/airtable ids → default `arrotech_db` for new Kenya path (do not override explicit `google_sheets`/`airtable`)
- `_sub_search_products`: if `kb_id` blank/missing → search Arrotech catalog for `user.id`; if `kb_id` set → keep existing RAG path
- Persist branches: `elif provider == "arrotech_db":` mirror sheets/airtable success behavior via `CommerceStorageService`

- [ ] **Step 1: Write failing tests**  
  - `test_search_products_uses_catalog_when_kb_id_empty`  
  - `test_persist_order_arrotech_db`  
  - `test_persist_reservation_arrotech_db`

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement wiring** (shape search result text/chunks so existing `_parse_products_from_search_results` still works, or adapt parser with a dedicated structured path)

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit** `feat(commerce): agent uses Arrotech catalog and DB storage`

---

### Task 8: Library template defaults (no Google / no required kb_id)

**Files:**
- Modify: `arrotech-hub-backend/src/routers/templates_router.py` (`whatsapp_ordering_agent` block ~2164–2310)
- Modify: `arrotech-hub-frontend/src/components/WorkflowTemplates.tsx` (connection gate already treats `rag_pipeline` as connected)
- Test: `arrotech-hub-backend/tests/test_whatsapp_ordering_template_storage.py` (extend)

**Pinned template changes:**
- `required_connections`: `["whatsapp"]` only (remove `rag_pipeline`, `google_workspace` as required)
- `variables.kb_id.required`: `False`
- `variables.storage_provider` enum includes `arrotech_db`; **default `arrotech_db`**
- `business_config` still passes `kb_id` when provided (optional FAQ KB later)

- [ ] **Step 1: Extend tests** asserting defaults and required_connections

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Update template + any FE deploy copy that says Google/KB required**

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit** `feat(commerce): ordering agent defaults to Arrotech DB`

---

### Task 9: Commerce Orders API + Hub Orders UI

**Files:**
- Create: `arrotech-hub-backend/src/routers/commerce_orders_router.py`
- Create: `arrotech-hub-frontend/src/pages/CommerceOrders.tsx`
- Modify: `arrotech-hub-frontend/src/App.tsx`, `Layout.tsx`
- Test: `arrotech-hub-backend/tests/test_commerce_orders_router.py`

**Interfaces:**
- `GET /api/commerce/orders`, `GET /api/commerce/orders/{external_order_id}`, `PATCH /api/commerce/orders/{external_order_id}` body `{status}`
- `GET /api/commerce/reservations`
- UI: list orders with status + payment_status + total; detail with line items, customer phone (WhatsApp deep link `https://wa.me/<digits>`), status action buttons using allowed `STATUS_TRANSITIONS` from `order_service.py`; tab/section for reservations

- [ ] **Step 1: Write failing API tests** for list + patch status + list reservations

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement API + Orders page + nav item “Orders” near Catalog Builder**

- [ ] **Step 4: Run API tests — expect PASS**; smoke-check page renders against mock/API

- [ ] **Step 5: Commit** `feat(commerce): orders ops API and Hub page`

---

### Task 10: Phase 1 end-to-end verification

**Files:**
- Create: `arrotech-hub-backend/tests/test_commerce_phase1_e2e.py` (service-level e2e, mocked WhatsApp/STK where needed)

**Scenario pinned:**
1. Create two catalog products for user  
2. `search_products` via agent helper with empty `kb_id` returns both for query `chips` / named item  
3. `upsert_order` + `mark_order_paid` → `GET /api/commerce/orders` shows `payment_status=paid`  
4. `upsert_reservation` → list reservations non-empty  
5. Template `whatsapp_ordering_agent` required_connections == `["whatsapp"]` and storage default `arrotech_db`

- [ ] **Step 1: Write failing e2e test module**

- [ ] **Step 2: Run — expect FAIL until prior tasks done; then PASS**

```bash
cd arrotech-hub-backend && python -m pytest tests/test_commerce_phase1_e2e.py tests/test_catalog_search_service.py tests/test_whatsapp_ordering_template_storage.py -v
```

- [ ] **Step 3: Manual checklist** (record in PR): connect WhatsApp sandbox/test → add products via Catalog Builder DB → configure M-Pesa settings → deploy library agent with empty kb_id → place test order → confirm Orders page

- [ ] **Step 4: Commit** `test(commerce): phase1 end-to-end coverage`

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Products in Arrotech DB | 1–2, 5 |
| Photos without Google | 3, 5 |
| Manual + CSV + photo entry | 2, 5 |
| Smart search / no intelligence drop | 4, 7 |
| Library agent, no kb_id/Google required | 7–8 |
| Orders in Arrotech DB | 6–7 |
| Reservations in Arrotech DB | 6–7, 9 |
| Orders ops essentials UI | 9 |
| M-Pesa Settings (existing) + paid state visible | 6–7, 9–10 |
| Sheets/Airtable remain available, not default | 5, 8 |
| Phase 2 wizard / Phase 3 Sheets sync | **Deferred** (own plans) |
