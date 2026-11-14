# WhatsApp Ordering Commerce Rails — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the library WhatsApp ordering agent into a deterministic commerce-rails system (buy → pay → track/cancel → returns/complaints → handoff) on the existing webhook/Celery spine, with Hub policy, returns queue, status pushes, and a CI release gate.

**Architecture:** Keep Meta webhook → Celery → workflow → `ConversationalAgentService` → WhatsApp. Extract `CommerceRuntime` for money/cart/order/return/handoff mutations; agent does NLU and WhatsApp copy only. Persist policy, returns, and refund attempts in Arrotech DB. Extend Hub Orders/Conversations and add Policy + Returns UI. Feature-flag rails on `whatsapp_ordering_agent`.

**Tech Stack:** FastAPI, SQLAlchemy/Postgres, Alembic, Celery, existing `DarajaService` / STK path, React/TypeScript Hub, pytest, Vitest/RTL where frontend tests exist.

**Spec:** `docs/superpowers/specs/2026-11-14-whatsapp-ordering-commerce-rails-design.md`

**Out of this plan:** Rent / support / real-estate parity; loyalty; broadcasts; full accounting ledger; greenfield agent rewrite.

## Global Constraints

- Hard rails for money, cart, order, returns eligibility, handoff; LLM only in language/search gaps.
- One ordering agent; sell modes from Hub policy — no per-business code.
- Refunds: Hub-gated by default; optional auto-approve; on approve attempt M-Pesa payout when configured, else record + honest WhatsApp + offline settle; never claim `refunded` until payout success or merchant marks settled.
- No silent dropped chats after webhook ack; inbound processing idempotent on WhatsApp message id.
- Languages: EN + SW / mixed first-class.
- Hub UI: preserve existing design system; new surfaces aesthetic, responsive (phone→desktop), excellent ops UX.
- Other `order_type` templates: must-not-break smoke only.
- Do not remove canvas/RAG or Sheets/Airtable paths.

## Review Focus

- Duplicate Meta webhook delivery with same `wamid` → single customer-visible side effect (no double order/STK).
- Approve return without Daraja payout configured → status is pending-offline (not `refunded`); customer WhatsApp copy is honest.
- Auto-approve over max amount or outside window → stays Hub-pending; no payout.
- Hub marks order `ready` → customer receives WhatsApp status push.
- `commerce_rails_enabled=false` (or non-ordering template) → existing agent path unchanged (smoke).

---

## File map

| File | Responsibility |
|------|----------------|
| `src/models.py` | `CommercePolicy`, `CommerceReturn`, `CommerceComplaint`, `CommerceRefundAttempt`; CatalogProduct unchanged fields |
| `alembic/versions/*_commerce_rails.py` | Migration |
| `src/services/commerce_policy.py` | Load/save/normalize merchant commerce policy |
| `src/services/commerce_runtime/state.py` | Cart/checkout/session commerce state types |
| `src/services/commerce_runtime/runtime.py` | Deterministic transitions + policy checks |
| `src/services/commerce_runtime/inventory.py` | Availability + quantity reserve/restock |
| `src/services/commerce_returns_service.py` | Return/complaint CRUD + auto-approve eval |
| `src/services/commerce_refund_service.py` | Payout or offline settle; never false `refunded` |
| `src/services/daraja_service.py` | Add B2C (or documented payout) method |
| `src/services/commerce_status_notify.py` | Hub status change → WhatsApp customer message |
| `src/services/conversational_agent_service.py` | Route rails-enabled ordering mutations through runtime |
| `src/routers/commerce_policy_router.py` | GET/PUT policy |
| `src/routers/commerce_returns_router.py` | List/detail/approve/deny/settle |
| `src/routers/commerce_orders_router.py` | Status PATCH triggers notify |
| `src/main.py` | Mount routers |
| `src/services/idempotency_service.py` | Ensure claim/finalize covers full WhatsApp turn path gaps found in audit |
| `tests/test_commerce_runtime_*.py` | Runtime + inventory + returns + refund |
| `tests/test_commerce_rails_journeys.py` | Mocked-LLM golden journeys (CI gate) |
| `tests/test_commerce_spine_idempotency.py` | Duplicate wamid |
| `frontend/src/pages/CommercePolicy.tsx` | Policy editor |
| `frontend/src/pages/CommerceReturns.tsx` | Returns/complaints queue |
| `frontend/src/pages/CommerceOrders.tsx` | Mobile polish + link to returns |
| `frontend/src/components/whatsapp/ConversationsTab.tsx` | Handoff filter + richer packet |
| `frontend/src/App.tsx` + `Layout.tsx` | Routes/nav |
| `frontend/src/services/api.ts` | API clients |

---

### Task 1: Policy + returns/complaints models

**Files:**
- Modify: `arrotech-hub-backend/src/models.py`
- Create: `arrotech-hub-backend/alembic/versions/<rev>_commerce_rails.py`
- Test: `arrotech-hub-backend/tests/test_commerce_rails_models.py`

**Interfaces:**
- Produces: ORM `CommercePolicy` (`user_id` PK/unique, `config` JSON, timestamps); `CommerceReturn` (id, user_id, external_return_id, order_external_id, customer_phone, reason_code, amount, currency, status ∈ `requested|pending_approval|approved|denied|refund_pending|refunded|settled_offline|failed`, auto_approved bool, raw_snapshot JSON); `CommerceComplaint` (id, user_id, external_complaint_id, order_external_id nullable, customer_phone, category, status ∈ `open|resolved_self_serve|handed_off|closed`, raw_snapshot); `CommerceRefundAttempt` (id, return_id FK, method ∈ `mpesa_b2c|offline`, status ∈ `pending|success|failed`, amount, mpesa_receipt nullable, error nullable, created_at)

- [ ] **Step 1: Write failing test** importing models and asserting tablenames `commerce_policies`, `commerce_returns`, `commerce_complaints`, `commerce_refund_attempts`

- [ ] **Step 2: Run** `pytest tests/test_commerce_rails_models.py -v` — expect FAIL (classes missing)

- [ ] **Step 3: Add models + Alembic migration** matching Interfaces; indexes on `(user_id, status)` for returns/complaints; unique `(user_id, external_return_id)` and `(user_id, external_complaint_id)`

- [ ] **Step 4: Run test** — expect PASS

- [ ] **Step 5: Commit** `feat(commerce): add policy returns complaints refund models`

---

### Task 2: Commerce policy service + API

**Files:**
- Create: `arrotech-hub-backend/src/services/commerce_policy.py`
- Create: `arrotech-hub-backend/src/routers/commerce_policy_router.py`
- Modify: `arrotech-hub-backend/src/main.py`
- Test: `arrotech-hub-backend/tests/test_commerce_policy.py`

**Interfaces:**
- Produces: `DEFAULT_COMMERCE_POLICY: dict` with keys: `sell_modes` (list), `delivery_methods`, `reservations_enabled`, `business_hours`, `away_message`, `return_window_days`, `return_reason_codes`, `auto_approve_enabled`, `auto_approve_max_amount_kes`, `cancel_until_status` (default `preparing`), `human_handoff_ttl_hours`, `commerce_rails_enabled` (default true for new policy rows)
- `async def get_policy(db, user_id) -> dict` — merge DB over defaults
- `async def upsert_policy(db, user_id, patch: dict) -> dict` — validate enums/amounts
- Router: `GET/PUT /api/commerce/policy` (auth)

- [ ] **Step 1: Write failing tests** for default merge, reject negative `auto_approve_max_amount_kes`, PUT round-trip

- [ ] **Step 2: Run** — expect FAIL

- [ ] **Step 3: Implement service + router + mount**

- [ ] **Step 4: Run** — expect PASS

- [ ] **Step 5: Commit** `feat(commerce): merchant commerce policy API`

---

### Task 3: CommerceRuntime core (cart → place → cancel)

**Files:**
- Create: `arrotech-hub-backend/src/services/commerce_runtime/__init__.py`
- Create: `arrotech-hub-backend/src/services/commerce_runtime/state.py`
- Create: `arrotech-hub-backend/src/services/commerce_runtime/runtime.py`
- Create: `arrotech-hub-backend/src/services/commerce_runtime/inventory.py`
- Test: `arrotech-hub-backend/tests/test_commerce_runtime_core.py`

**Interfaces:**
- Produces: `CommerceState` dataclass/TypedDict: `cart_lines`, `fulfillment_method`, `checkout_fields`, `order_id`, `payment_status`, `phase`
- `class CommerceRuntime:`
  - `def __init__(self, policy: dict, catalog_port, order_port)`
  - `async def apply(self, state: CommerceState, command: dict) -> tuple[CommerceState, dict]` where `command["type"]` ∈ `add_line|update_line|remove_line|set_fulfillment|set_checkout_field|place_order|cancel_order`
  - Result dict always includes `ok: bool`, `error_code` optional, `effects` list (persist order, reserve inventory, etc.)
- Inventory: `async def assert_sellable(product_id, qty)`; `async def reserve(...)`; `async def restock(...)` — block if `availability` not sellable; if `quantity` is not null, decrement/increment; never soft-allow oversell
- Cancel: allowed only while order status is before policy `cancel_until_status` (default until entering `preparing`)

- [ ] **Step 1: Write failing tests** — add line; block out_of_stock; place creates effect; cancel after preparing rejected; quantity decrement on place + restock on cancel

- [ ] **Step 2: Run** — expect FAIL

- [ ] **Step 3: Implement runtime + inventory** with in-memory/fakes in unit tests; ports are callables/protocols, not HTTP

- [ ] **Step 4: Run** — expect PASS

- [ ] **Step 5: Commit** `feat(commerce): CommerceRuntime cart place cancel rails`

---

### Task 4: Returns, complaints, refund service

**Files:**
- Create: `arrotech-hub-backend/src/services/commerce_returns_service.py`
- Create: `arrotech-hub-backend/src/services/commerce_refund_service.py`
- Modify: `arrotech-hub-backend/src/services/daraja_service.py` — add `async def b2c_payment(...)` (or equivalent payout API the team standardizes on)
- Create: `arrotech-hub-backend/src/routers/commerce_returns_router.py`
- Modify: `arrotech-hub-backend/src/main.py`
- Test: `arrotech-hub-backend/tests/test_commerce_returns_refunds.py`

**Interfaces:**
- `async def request_return(db, user_id, *, order_external_id, phone, reason_code, amount) -> CommerceReturn`
- `def evaluate_auto_approve(policy, return_row, order) -> bool`
- `async def approve_return(db, user_id, return_id, actor_user_id) -> CommerceReturn` — creates refund attempt
- `async def deny_return(...)`
- `async def mark_settled_offline(...)` — sets return `settled_offline` / order payment notes; only path to terminal success without M-Pesa when payout missing
- `async def execute_refund(db, return_row) -> CommerceRefundAttempt` — if payout creds present → B2C; on success return status `refunded`; if no creds → status `refund_pending` (not `refunded`) + attempt method `offline` pending merchant
- Runtime commands: `request_return`, `request_complaint` (self-serve categories resolve without Hub; disputes → handoff effect)
- Router: `GET /api/commerce/returns`, `GET /api/commerce/returns/{id}`, `POST .../approve`, `POST .../deny`, `POST .../settle-offline`

- [ ] **Step 1: Write failing tests** covering Review Focus lines 2–3 (no false refunded; auto-approve over cap stays pending) plus approve with mocked B2C success → `refunded`

- [ ] **Step 2: Run** — expect FAIL

- [ ] **Step 3: Implement services + Daraja payout method + router**

- [ ] **Step 4: Run** — expect PASS

- [ ] **Step 5: Commit** `feat(commerce): returns complaints and refund payout rails`

---

### Task 5: Hub order status → WhatsApp notify

**Files:**
- Create: `arrotech-hub-backend/src/services/commerce_status_notify.py`
- Modify: `arrotech-hub-backend/src/routers/commerce_orders_router.py`
- Test: `arrotech-hub-backend/tests/test_commerce_status_notify.py`

**Interfaces:**
- `async def notify_order_status_change(db, user_id, order, previous_status: str) -> None` — sends WhatsApp text (EN/SW from customer lang if known else EN) with order id + new status; failures logged, do not roll back status update
- PATCH order status calls notify after successful persist

- [ ] **Step 1: Write failing test** — PATCH ready invokes notify once (mock WhatsApp send)

- [ ] **Step 2: Run** — expect FAIL

- [ ] **Step 3: Implement notify + wire router**

- [ ] **Step 4: Run** — expect PASS

- [ ] **Step 5: Commit** `feat(commerce): WhatsApp notify on Hub order status`

---

### Task 6: Wire agent to rails + spine idempotency audit

**Files:**
- Modify: `arrotech-hub-backend/src/services/conversational_agent_service.py` (mutation paths only; keep file split deferred unless required)
- Modify: `arrotech-hub-backend/src/services/whatsapp_ordering_helpers.py` — normalize `commerce_rails_enabled` from policy/template
- Modify: `arrotech-hub-backend/src/services/idempotency_service.py` and/or `src/routers/whatsapp_webhook.py` / task entry if claim gaps remain
- Test: `arrotech-hub-backend/tests/test_commerce_spine_idempotency.py`
- Test: `arrotech-hub-backend/tests/test_commerce_rails_agent_wiring.py`

**Interfaces:**
- When `get_policy(...).commerce_rails_enabled` and library ordering path: cart/checkout/place/cancel/return/complaint/handoff tools call `CommerceRuntime.apply` / returns service — LLM cannot bypass
- Safe failure: tool/runtime error → customer message + optional handoff effect; never empty response
- Duplicate `wamid`: second process is no-op after successful finalize (Review Focus #1)
- Non-rails / other `order_type`: existing behavior (Review Focus #5 smoke)

- [ ] **Step 1: Write failing tests** for rails place_order goes through runtime; duplicate wamid; rails flag off smoke

- [ ] **Step 2: Run** — expect FAIL

- [ ] **Step 3: Wire agent + close idempotency gaps**

- [ ] **Step 4: Run** — expect PASS

- [ ] **Step 5: Commit** `feat(commerce): wire ordering agent to CommerceRuntime rails`

---

### Task 7: Mocked-LLM journey CI gate

**Files:**
- Create: `arrotech-hub-backend/tests/test_commerce_rails_journeys.py`
- Modify: CI config if present (e.g. GitHub workflow / pytest marker `commerce_rails_gate`) so these tests must pass on PRs touching commerce/agent

**Interfaces:**
- Scripted multi-turn fixtures with mocked LLM intent → runtime tools: (1) browse→pay paid, (2) pay-fail recovery, (3) return auto-approve under cap, (4) return over cap → Hub pending, (5) complaint dispute → handoff, (6) hours-away, (7) EN/SW mixed search add-to-cart
- No live OpenAI in gate

- [ ] **Step 1: Write failing journey tests** (empty stubs failing on missing helpers OK)

- [ ] **Step 2: Run** `pytest tests/test_commerce_rails_journeys.py -v` — expect FAIL

- [ ] **Step 3: Add journey harness helpers + implement until PASS**

- [ ] **Step 4: Ensure CI invokes this file/marker**

- [ ] **Step 5: Commit** `test(commerce): mocked LLM rails journey release gate`

---

### Task 8: Hub Commerce Policy + Returns UI

**Files:**
- Create: `arrotech-hub-frontend/src/pages/CommercePolicy.tsx`
- Create: `arrotech-hub-frontend/src/pages/CommerceReturns.tsx`
- Modify: `arrotech-hub-frontend/src/pages/CommerceOrders.tsx` — responsive polish; link to return for an order
- Modify: `arrotech-hub-frontend/src/App.tsx`, `Layout.tsx`, `services/api.ts`
- Test: `arrotech-hub-frontend/src/__tests__/pages/CommercePolicy.test.tsx` (and Returns) following existing page test patterns

**Interfaces:**
- Routes under existing commerce nav: Policy (sell modes, hours/away linked copy, return rules, auto-approve, cancel cutoff, rails toggle), Returns queue (filter by status; detail approve/deny/settle-offline; WhatsApp deep link)
- Mobile-first list → detail; desktop table denser; reuse Hub components/tokens — no new brand system
- Hours: UI states that Commerce policy is source of truth for ordering; show link/sync note to WhatsApp profile hours

- [ ] **Step 1: Write failing RTL tests** for policy save calling PUT; returns approve calling API

- [ ] **Step 2: Run frontend tests** — expect FAIL

- [ ] **Step 3: Implement pages + api + nav**

- [ ] **Step 4: Run** — expect PASS

- [ ] **Step 5: Commit** `feat(hub): commerce policy and returns ops UI`

---

### Task 9: Conversations handoff packet

**Files:**
- Modify: backend commerce-context endpoint used by `apiService.getWhatsAppCommerceContext` (locate existing router; extend payload)
- Modify: `arrotech-hub-frontend/src/components/whatsapp/ConversationsTab.tsx`
- Test: backend context test + light frontend filter test if patterns exist

**Interfaces:**
- Context payload adds `return_ids`, `complaint_ids`, `commerce_phase`, `policy_sell_modes`
- Conversations: filter/tab for `human_handoff`; show commerce snapshot in side panel; takeover/release unchanged

- [ ] **Step 1: Write failing API test** for extended commerce-context keys

- [ ] **Step 2: Run** — expect FAIL

- [ ] **Step 3: Extend API + Conversations UI**

- [ ] **Step 4: Run** — expect PASS

- [ ] **Step 5: Commit** `feat(hub): richer commerce handoff context in Conversations`

---

## Self-review notes (author)

- Spec coverage: rails, spine idempotency, returns/complaints/refund, Hub policy/returns/orders notify, Conversations handoff, eval gate, UI quality constraints, Wave 2 out of scope — each mapped to a task.
- Refund payout without B2C today → Task 4 adds Daraja method; offline honesty covered in Review Focus + tests.
- Hours single source → Task 2 + Task 8; WhatsApp profile sync mechanism left to builder within “link or migrate.”
- Agent file size: Task 6 wires without mandatory split; split only if required to land the change safely.
