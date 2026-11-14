# Kenya WhatsApp Commerce — Arrotech DB Default

**Date:** 2026-11-12  
**Status:** Ready for approval  
**Scope:** Product + backend + frontend for the Kenya WhatsApp + M-Pesa selling wedge

## Intent and why

Make Arrotech the best WhatsApp selling app for non-technical Kenya merchants: go live with **WhatsApp + M-Pesa + Arrotech’s database only** — no Google Sheets, Airtable, Knowledge Base IDs, or Pinecone homework required.

Today Catalog Builder stops at a Google Sheet; product search depends on RAG/Pinecone and a free-text `kb_id` on the library **WhatsApp Ordering Agent**; order storage is Sheets/Airtable/`none`; M-Pesa lives on Settings. Power users can ingest via canvas/templates, but that is not a merchant go-live path. There are **no live merchants yet**, so we can make Arrotech DB the default without a Sheets migration.

## Goals

- A merchant can take a real WhatsApp order paid via M-Pesa with only: WhatsApp connected, products in Arrotech DB, M-Pesa configured, Ordering Agent deployed from the **library**.
- Products and orders are first-class data in Arrotech’s database.
- Conversational intelligence stays excellent: slang, partial names, messy intent (“naomba chips na soda”) still resolve to the right catalog items.
- Product entry is flexible: photos (default), manual add/edit, file upload (CSV/Excel).
- Day-to-day ops: Orders screen with list, payment state, customer contact, status actions (“ops essentials”) — **required in Phase 1** so the loop is complete end-to-end (WhatsApp order → M-Pesa → merchant sees and manages it in Hub).
- Table reservations on the library Ordering Agent persist in Arrotech DB on the default path (not Sheets-only, not silently broken).
- First-time UX polish (Phase 2): guided Go live checklist; after that Catalog / Orders / Settings / Library for ongoing use.
- Sheets/Airtable remain optional later (Phase 3), not required.

## Non-goals

- Replacing the whole Hub with a single-purpose POS.
- Full shop desk in v1 (receipts/print, deep CRM, accounting exports).
- Forcing every Hub workflow onto Arrotech DB.
- Removing canvas/RAG tools for power users who want Knowledge Bases.
- Building Sheets/Airtable sync in Phase 1–2.

## Anti-goals

- Shipping a path that “works” but feels dumber on WhatsApp than today’s RAG agent.
- Requiring merchants to understand `kb_id`, Pinecone, or Workflows to sell.
- Leaving Catalog export as “success” when the agent still cannot find products.
- A wizard that traps merchants forever (day-to-day must leave the checklist).

## Constraints

- Build on existing Hub: library templates (`whatsapp_ordering_agent`), conversational agent, M-Pesa settings, Catalog Builder UX patterns.
- Default Kenya path: **no Google connection required**.
- Product photos need Arrotech-hosted storage (not Google Drive) for the default path. **Builder call:** use existing cloud object storage already available to the backend if present; otherwise introduce a single bucket/prefix for catalog images.
- M-Pesa configuration can remain on Settings in Phase 1; wizard surfaces it in Phase 2.
- Platform still needs OpenAI (and whatever powers embeddings/fuzzy match) configured server-side.

## Approaches considered

| Approach | Summary | Tradeoff |
|----------|---------|----------|
| 1. Plumbing-only | DB tables + search swap + thin checklist on existing screens | Fastest; still feels like a toolkit |
| 2. Big-bang Kenya product | Wizard + catalog modes + Orders + search in one ship | Full vision; high stall risk |
| **3. Phased vertical (chosen)** | Complete DB sell loop first (including Orders ops); guided Go-live polish next; Sheets later | End-to-end selling without a half product; wizard is polish not a gap filler |

**Chosen:** Phased vertical (3), refined by partner: Phase 1 must be **complete end-to-end** (not plumbing-only). Guided wizard can wait; seeing/managing orders cannot.

## Phases

### Phase 1 — Complete Arrotech DB sell loop (must ship first)

1. **Catalog data model** in Arrotech DB (per-user/per-business products: name, price, description, category, images, stock/availability, etc., aligned with what the ordering agent already understands).
2. **Catalog UX** writes to DB: photo flow (default), manual CRUD, CSV/Excel import. Stop pointing “success” at Sheets + Workflows ingest.
3. **Image hosting** on Arrotech storage for the default path.
4. **Smart product search** used by the WhatsApp ordering agent against that catalog — quality bar equal to (or better than) current RAG matching for messy customer language. Merchant never sees Pinecone/KB for this path.
5. **Library WhatsApp Ordering Agent** auto-binds to the merchant’s Arrotech catalog (no required `kb_id`, no required Google). Deploy remains the primary agent path.
6. **Orders + reservations persistence** in Arrotech DB (default for new Kenya deploys). Food table reservations that the library agent already supports must save and be manageable on this path — not Sheets-only and not disabled.
7. **Orders ops essentials UI** in Hub: order list; detail with line items and total; payment state (STK paid/pending/manual); customer phone + open WhatsApp; status actions (e.g. new → preparing → ready → delivered / cancelled). Include a clear place for reservations tied to the same merchant.
8. **M-Pesa** on Settings (required for paid checkout); agent uses existing STK/manual behavior.
9. Optional RAG/Pinecone KB remains available for power users / extra knowledge — not on the default go-live path.

**Phase 1 done means:** WhatsApp customer can order (and reserve a table where enabled) → pay via M-Pesa → merchant sees payment + order/reservation in Hub and can update status — with no Google and no KB setup.

### Phase 2 — Guided first-sale polish

1. **Go live** guided path: Connect WhatsApp → Add products → M-Pesa → Deploy Ordering Agent from library.
2. After completion, merchants stay on Catalog / Orders / Settings / Library for day-to-day (not stuck in the wizard).
3. Does not add new core commerce capabilities beyond Phase 1 — it makes first-time setup harder to get wrong.

### Phase 3 — Optional external storage

- Optional sync/export or storage provider for Google Sheets and Airtable for merchants who want it.
- Does not block Phases 1–2.

## Decided product behavior

| Topic | Decision |
|-------|----------|
| Who | Non-technical Kenya merchants selling on WhatsApp |
| Required connections (default) | WhatsApp + M-Pesa + Arrotech DB |
| Google | Not required for default path |
| Product + order storage default | Arrotech database |
| Product search | Query Arrotech catalog with smart matching; LLM keeps conversation/intent |
| Pinecone / KB | Optional later / power users; not default go-live |
| Agent discovery | Library deploy (not canvas-built) |
| Catalog entry | Photos (default) + manual + file upload |
| Go-live UX | Hybrid: separate screens work end-to-end in Phase 1; guided first sale polish in Phase 2 |
| Orders UI | Ops essentials **in Phase 1** (complete loop) |
| Reservations | Persist in Arrotech DB on default path (Phase 1) |
| Existing Sheets merchants | None today → no migration requirement; DB-only default OK |
| Sheets/Airtable | Phase 3 add-on |
| Completeness bar | No half loops — merchant-visible orders/payments (and reservations) required with first ship |

## Builder calls (defaults I settled)

- Photo storage: reuse existing backend object storage if present; else one catalog image bucket/prefix.
- Phase 2 stays wizard-only polish; core completeness is Phase 1 (per “complete, end to end”).
- Reservation management in Phase 1 can be a section/filter on Orders (or sibling list) rather than a full bookings product.

## Left to the builder

- Exact Postgres/SQLAlchemy schema and migrations for products, orders, reservations, payment/status fields.
- Exact smart-search implementation (e.g. hybrid lexical + embeddings stored with products vs query-time ranking) as long as the quality bar is met and merchants never configure RAG for the default path.
- How library deploy passes “use Arrotech catalog” into `conversational_agent` / `business_config` (replace or deprecate required `kb_id` for this template).
- Photo upload API and CDN/public URL strategy.
- CSV/Excel column mapping and validation rules.
- Order/reservation status enums and transitions.
- Phase 2 wizard placement in the app (route, onboarding hook for messaging goal).
- Keeping canvas `rag_*` tools working for unrelated KB use cases.
- Test plan: catalog CRUD; search quality fixtures (Kenyan slang); STK + order write; reservation write/read; library deploy without Google; merchant can open Hub Orders and see payment state.

## Success criteria

- New merchant can go from empty account to a test WhatsApp order that appears in Hub Orders with payment state, without connecting Google or creating a Knowledge Base.
- Where reservations are enabled, a test reservation also lands in Arrotech and is visible to the merchant.
- Customer messages with partial/slang product names still resolve correctly in representative test dialogues.
- Library Ordering Agent deploy does not require `kb_id` or Google for the default Kenya path.
- Phase 2: first-time merchant can complete guided Go live without visiting Workflows.

## Out of scope until later

- Receipts/print, full customer CRM, analytics dashboards.
- Multi-branch inventory, staff roles beyond current Hub auth.
- Telegram/other channels parity (may follow same patterns later).
