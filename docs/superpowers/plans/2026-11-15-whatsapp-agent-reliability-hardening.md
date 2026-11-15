# WhatsApp Agent Reliability Hardening — Implementation Plan

> **Status (2026-11-15):** Tasks 1–4 shipped on this branch. Tasks 5–7 (FIFO lock, adversarial burst pump, sweep) **deferred** — partner stop before Task 5.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the WhatsApp ordering agent production-reliable for browse, semantic search, YES confirmation, name slot hygiene, M-Pesa→Hub paid + receipt, with adversarial mocked journeys that fail CI on the bugs merchants reported.

**Architecture:** Port main-checkout catalog browse/search into the commerce-rails worktree; add explicit session phase gates around checkout mutations; harden STK reconcile so Hub `mark_order_paid` + receipt send are atomic in outcome (retry on send fail); extend `CommerceJourney` with webhook/button turns and a hostile LLM fixture.

**Tech Stack:** FastAPI backend, `CommerceRuntime`, `CatalogSearchService`, `OrderTrackingService` / STK payment services, pytest journey harness, WhatsApp interactive buttons.

**Spec:** `docs/superpowers/specs/2026-11-15-whatsapp-agent-reliability-hardening-design.md`

## Global Constraints

- Ship on `feat/whatsapp-ordering-commerce-rails` worktree; unify catalog browse/search with main rather than diverging further.
- Mutations (place/cancel/pay) stay on CommerceRuntime / existing STK services — LLM never invents place success.
- YES places only in phase `awaiting_yes`; button titles never become names.
- `payment_notified` only after successful customer receipt send (document or text fallback).
- Merge gate stays mocked-LLM (no live WABA/Daraja in CI) but **must** include overlapping same-session turns.
- Same customer: per-session FIFO lock (E1) — never parallel `execute` on one `session_key`.
- Do not start Meta Commerce sync in this ship.

## Review Focus

- Browse button with empty catalog → honest empty, not invented Meta/catalog error prose.
- “shoes” → product named like Jordan sneakers (or Footwear category) appears in search hits and is displayed.
- Typed YES without pre-seeded metadata after a real confirmation present → places once; second YES → already placed (not greeting).
- Message “My Orders” with non-empty cart → not written as Name on summary.
- STK success with valid registry → Hub `payment_status=paid` and receipt send attempted.
- Receipt send failure → retryable (not permanent `payment_notified` swallow).
- Two overlapping YES (or YES + noise) on one session → exactly one place; no greeting corruption.
- Same `wamid` twice → single process.

---

## File map

| File | Responsibility |
|------|----------------|
| `src/services/catalog_search_service.py` | Browse-all query + footwear synonyms (+ any main ports) |
| `src/services/conversational_agent_service.py` | Browse fast path; phase gates; YES deterministic place; force display of search hits |
| `src/services/whatsapp_ordering_helpers.py` | Expand not-a-name / intent denylist; phase helpers if colocated |
| `src/services/order_stk_payment_service.py` | Reconcile Hub paid; receipt notify semantics |
| `src/services/order_tracking_service.py` | Receipt send success vs fail flags; retry |
| `tests/test_catalog_search_service.py` / browse tests (port) | shoes→sneakers, browse-all |
| `tests/test_commerce_rails_agent_wiring.py` | YES/phase/name |
| `tests/test_commerce_rails_journeys.py` + harness | Adversarial journeys |
| `tests/test_order_tracking_receipts.py` / STK tests | paid + receipt retry |

---

### Task 1: Port browse-all + footwear search into rails

**Files:**
- Modify: `src/services/catalog_search_service.py`
- Port/adapt: `_browse_catalog_fast_path` wiring from main `conversational_agent_service.py` into rails agent `execute`
- Create/extend: `tests/test_catalog_browse_fast_path.py`, `tests/test_whatsapp_browse_catalog_query.py`, `tests/test_catalog_search_service.py`

**Interfaces:**
- `is_browse_all_catalog_query(query: str) -> bool` — true for webhook browse paraphrase and browse intents
- Footwear synonym group includes shoe/shoes/sneaker/sneakers/footwear/trainer(s)/boot(s)
- `search_products`: browse-all lists sellable products without name overlap
- Agent: on browse-all, call browse fast path before LLM; send product cards

- [ ] **Step 1: Write failing tests** — browse query lists products; `shoes` matches a product named “Jordan sneakers” (or category Footwear + sneakers in name); webhook browse sentence is browse-all

- [ ] **Step 2: Run pytest** — expect FAIL on rails tree

- [ ] **Step 3: Port browse + synonyms + fast path from main**

- [ ] **Step 4: Run pytest** — PASS

- [ ] **Step 5: Commit** `feat(catalog): browse-all and footwear search on rails`

---

### Task 2: Checkout phase rails + YES / name hygiene

**Files:**
- Modify: `src/services/conversational_agent_service.py` (`execute`, `_present_checkout_confirmation`, create_order paths)
- Modify: `src/services/whatsapp_ordering_helpers.py` (`_NOT_A_NAME_PHRASES`, parse helpers)
- Modify: `tests/test_commerce_rails_agent_wiring.py` (+ new focused tests)

**Interfaces:**
- Session metadata `commerce_phase`: `browsing` | `collecting_details` | `awaiting_yes` | `placed` | `paying` | `post_order`
- `_present_checkout_confirmation` sets `commerce_phase=awaiting_yes` + existing pending flags
- Confirm message + `awaiting_yes` → deterministic place once → `placed`
- **Confirm lexicon (phase-gated):** in `awaiting_yes`, `yea` / `yeah` / `yep` / `ok` / `okay` / `sure` / `alright` / `fine` / `go ahead` / `sawa` / `ndio` / etc. all place; outside `awaiting_yes`, bare `ok`/`sure` do **not** place
- Confirm + `placed` → `already_placed` text (no LLM greeting)
- Confirm without awaiting/placed → re-present summary or short “reply YES to confirm” — no generic hello
- Name capture only when `commerce_phase=collecting_details` (or explicit awaiting checkout details)
- Denylist includes: `my orders`, `orders`, `browse catalog`, `cancel`, `return`, `help`, `human`, `agent`

- [ ] **Step 1: Write failing tests** — after present, `yea` and `ok` and `okay` place; second confirm already_placed not greeting; bare `ok` outside awaiting_yes does not place; “My Orders” not stored as name on summary

- [ ] **Step 2: Run** — FAIL

- [ ] **Step 3: Implement phase gates + denylist**

- [ ] **Step 4: Run** — PASS

- [ ] **Step 5: Commit** `fix(agent): checkout phase rails for YES and name slots`

---

### Task 3: Force display of catalog search hits

**Files:**
- Modify: `conversational_agent_service.py` (`_search_arrotech_catalog_products` / `_sub_display_product_cards` path)
- Test: extend catalog/agent wiring tests

**Interfaces:**
- When search returns `READY_TO_DISPLAY_PRODUCTS` (or equivalent list), agent sends cards deterministically in the same turn (or immediately after tool) — model cannot drop Jordan sneakers after a hit

- [ ] **Step 1: Failing test** — search returns sneakers product; assert display/cards path invoked with that id even if model would omit

- [ ] **Step 2–4: Implement + pass**

- [ ] **Step 5: Commit** `fix(agent): always display catalog search hits`

---

### Task 4: STK success → Hub paid + receipt delivery truth

**Files:**
- Modify: `src/services/order_stk_payment_service.py`
- Modify: `src/services/order_tracking_service.py` (notify/receipt flags)
- Tests: `tests/test_order_tracking_receipts.py`, STK/journey payment tests

**Interfaces:**
- On STK success: resolve order via Redis **or** `StkOrderMapping` **or** registry; call `mark_order_paid` for Hub `commerce_orders`
- `notify_payment_received` / PDF send: set `payment_notified` only after WhatsApp document or text receipt succeeds
- On send failure: record `receipt_send_status=failed` (or equivalent), allow retry on poll/next callback; do not claim notified
- Journey/unit assert: after simulated STK success, `payment_status=paid` and receipt send attempted (spy `upload_and_send_document` or text fallback)

- [ ] **Step 1: Write failing tests** for paid Hub row + notified-only-on-success + retry after fail

- [ ] **Step 2: Run** — FAIL

- [ ] **Step 3: Implement reconcile + receipt flag semantics**

- [ ] **Step 4: Run** — PASS

- [ ] **Step 5: Commit** `fix(payments): Hub paid + receipt notify truth`

---

### Task 5: Per-session FIFO lock (real-world consecutive messages)

**Files:**
- Create or modify: session lock helper (e.g. `src/services/whatsapp_session_lock.py` or extend context manager / webhook BG entry)
- Wire: `whatsapp_webhook` background processing **before** `ConversationalAgentService.execute` for a given `session_key`
- Tests: `tests/test_whatsapp_session_fifo.py`

**Interfaces:**
- `async with session_turn_lock(session_key):` — only one turn runs; waiters FIFO
- Lock TTL / release-on-error so a crashed turn cannot dead-lock the phone
- Dual overlapping `execute`/`process_message` on same key: second starts only after first exits; order of completion matches enqueue order

- [ ] **Step 1: Write failing concurrency test** — start turn A with artificial mid-turn delay; start turn B; assert B’s side effects happen after A; assert not both mutate place

- [ ] **Step 2: Run** — FAIL (today: no session lock → races possible)

- [ ] **Step 3: Implement FIFO lock + wire webhook/agent entry**

- [ ] **Step 4: Run** — PASS

- [ ] **Step 5: Commit** `fix(whatsapp): per-session FIFO turn lock`

---

### Task 6: Adversarial Real-World Message Pump

**Files:**
- Modify: `tests/commerce_rails_journey_harness.py` (evolve to pump: buttons, burst, spies)
- Modify: `tests/test_commerce_rails_journeys.py`
- Create: `tests/test_commerce_rails_burst_journeys.py` if clearer

**Interfaces:**
- Harness injects Meta-like button/text turns (not only free-typed happy paths)
- Hostile LLM: greeting / omit products / extra `create_order`
- `burst(messages)` runs overlapping turns under the real lock
- Every journey asserts a **TurnResult oracle**: forbidden customer text, required substrings/spies, phase/order/payment invariants (see spec “How we evaluate”) — not “LLM sounded ok”
- Journeys that **must** pass:
  1. Browse button → cards or honest empty
  2. “shoes” → Jordan sneakers shown
  3. Present → YES (no metadata pre-seed cheat) → placed; sequential second YES → already_placed, never assist-greeting
  4. Burst double-YES → exactly one place
  5. Burst YES + “My Orders” → not name; coherent phase
  6. Place → STK success → Hub `paid` + receipt send attempted
  7. Duplicate wamid → single process
  8. Existing return / cancel / handoff stay green

- [ ] **Step 1: Add failing journey/burst tests** for 1–7

- [ ] **Step 2: Run** — FAIL until Tasks 1–5 land

- [ ] **Step 3: Extend harness + close gaps**

- [ ] **Step 4: Full journey + burst files PASS**

- [ ] **Step 5: Commit** `test(agent): real-world adversarial and burst journeys`

---

### Task 7: Regression sweep + docs pointer

**Files:**
- Run full rails commerce test subset; fix stragglers only
- Optional: note in design that sequential `say()` alone is insufficient — burst pump is the gate

- [ ] **Step 1: Run** catalog + wiring + journeys + burst + receipt tests

- [ ] **Step 2: Fix only failures caused by this ship**

- [ ] **Step 3: Commit** if needed `fix(agent): reliability sweep`

---

## Self-review notes (author)

- Spec symptoms + concurrency map to Tasks 1–7.
- Review Focus pinned in task tests (including burst YES / wamid).
- Non-goals respected (no Meta sync; live sandbox not merge gate).
- Main vs rails divergence closed in Task 1; FIFO lock is Task 5.
