# WhatsApp Agent Reliability Hardening — Design

**Date:** 2026-11-15  
**Status:** Approved — partner approved to build (2026-11-15)  
**Size:** Project  
**Branch home:** `feat/whatsapp-ordering-commerce-rails` worktree (unify with main-checkout catalog browse/search fixes)

## Intent and why

Kenya merchants and buyers are hitting production-grade failures on the live WhatsApp ordering agent: Browse Catalog fails, semantic search misses obvious products (shoes → Jordan sneakers), typed YES confirmation greets then double-places, “My Orders” becomes the customer name, successful M-Pesa leaves Hub Orders on payment pending, and paid customers get no PDF receipt. Industry-standard commerce bots do not let an LLM invent catalog failures or invent names; they use hard conversation phases, deterministic mutations, reconciled payments, and adversarial journey tests that fail CI when those rails break.

## Observed failures → root causes

| Symptom | Primary cause |
|---------|----------------|
| Browse Catalog → “issue retrieving product catalog” | Rails worktree lacks main’s `is_browse_all_catalog_query` + `_browse_catalog_fast_path`; browse text goes to LLM/search with no name overlap → empty → model invents failure |
| “shoes” misses Jordan sneakers | Rails synonyms lack footwear group; optional embedding floor; model may filter rows after search |
| First YES → generic greeting; second YES → already placed | Summary often model prose without `pending_confirmation` / `awaiting_order_confirmation`; first YES falls through to LLM (place may still run via tool); second YES hits rails `already_placed` |
| “My Orders” as Name | `parse_checkout_details` treats 1–6 word alpha as name; `_NOT_A_NAME_PHRASES` omits orders/my orders; capture can run without awaiting-details gate |
| Paid but Hub pending | Must ensure STK success always `mark_order_paid` on `commerce_orders` (rails has reconcile; harden lookup misses + provider config) |
| No receipt after pay | Callback/registry miss skips finalize; or PDF fail sets `payment_notified` without successful document send — no retry |
| Weak CI | Journey harness stubs PDF, seeds YES metadata, never presses Browse button, never hostile LLM, never asserts receipt document |

## Goals

1. **Browse Catalog** always lists sellable Hub `catalog_products` (cards) without requiring LLM or name overlap; honest empty state if catalog empty.
2. **Intentful search** returns Jordan sneakers for “shoes” (synonyms + hybrid; never silently empty when synonym/category match exists); model cannot drop `READY_TO_DISPLAY_PRODUCTS`.
3. **Checkout phases** are explicit; YES only places in `awaiting_yes`; other YES re-sends summary or reports existing order id — never a fresh greeting.
4. **Slot hygiene:** button titles / intents (`My Orders`, Browse, Cart, Help, Cancel, …) never become customer name.
5. **Payment truth:** STK success → `commerce_orders.payment_status=paid` (Hub Orders) + receipt PDF (or text fallback) attempted; `payment_notified` only after successful WhatsApp send; failed sends retryable.
6. **Adversarial E2E gate:** mocked-LLM + webhook-style turns covering browse, shoes→sneakers, YES without pre-seeded metadata, double YES, My Orders as name trap, pay→paid+receipt attempt, return/cancel/handoff; CI fails on regressions.
7. **Real-world concurrency:** same customer can send consecutive messages while a turn is still running; the system must not corrupt phase/cart/order. CI must **prove** the policy with overlapping turns (not assume sequential chats).

## How we evaluate that a response is “expected”

We do **not** grade the agent by “sounds helpful.” Basics are failing because CI largely checked **tools/state** (or pre-seeded happy paths) and almost never asserted **customer-visible contracts**.

**Evaluation model for this ship (merge gate):**

Each turn produces an `TurnResult` the test inspects:

| Oracle | Pass condition (examples) |
|--------|---------------------------|
| **Forbidden text** | After confirm/place, reply MUST NOT match greeting/assist patterns (`how can i (assist\|help) you`, bare `hello!`, menu waffle with no order id) |
| **Required text** | Browse with stock → at least one known product name (or card-send spy); empty catalog → fixed honest empty copy |
| **Structured outcome** | `commerce_phase`, `order_id`, Hub `payment_status`, cart lines — exact values |
| **Side-effect spies** | `send_product_card` / `upload_and_send_document` / STK initiate called N times (0 or 1 as required) |
| **Invariants (property)** | No place unless phase was `awaiting_yes`; name ∉ button/intent denylist; paid ⇒ receipt attempt; same wamid ⇒ ≤1 process; burst ⇒ ≤1 place |

**How a test decides pass/fail:** deterministic predicates on that `TurnResult` — `assert_forbidden`, `assert_required_substring`, `assert_phase`, `assert_spy_calls`. If the model returns poetry that violates a predicate, **CI fails**. The scripted/hostile LLM is an input fixture; the oracle is the ground truth.

**What we deliberately do not use as the merge gate:** LLM-as-judge (“was this a good reply?”), BLEU, or vibe checks — they are flaky and would not have caught YES→greeting reliably.

**Why basics still fail in production today:** journeys often pre-seed `pending_confirmation`, stub receipts, never burst, and rarely assert forbidden customer text — so the agent can greet on YES and still “pass.”

## How we know what happens (testing philosophy — not assumed prompts)

Today’s `CommerceJourney.say()` is **sequential** and **pre-scripts** the model. That is necessary for a non-flaky merge gate, but it is **not** enough to claim real-world readiness. Merchants’ failures (YES → greeting, name = “My Orders”) are exactly what sequential happy scripts miss.

**Industry pattern (AWS WhatsApp assistants, Chatwoot, FIFO WA engines):**  
webhook ack fast → queue → **per-phone / per-session lock** so one customer is processed **FIFO**; different customers parallel; Meta `wamid` dedupe for retries. Parallel processing of two turns on the same session is an anti-pattern.

**What this ship adds — a Real-World Message Pump (merge-gate, still mocked LLM):**

| Layer | What it simulates | What it asserts |
|-------|-------------------|-----------------|
| Meta webhook shapes | `button_reply` (`menu:browse`), text, interactive | Same parsers production uses |
| Scripted + hostile LLM | Greeting, dropped products, extra `create_order` | Customer text never becomes greeting on YES; hits always displayed |
| **Burst / overlap** | `asyncio.gather` two `execute`/`process` calls on same `session_key` while turn A artificially holds a lock / sleeps mid-turn | **Defined policy** (below) holds; no double place; phase not torn |
| STK callback mid-chat | Payment webhook while customer types | Hub `paid` + receipt attempt; chat phase not reset to hello |
| Idempotency | Same `wamid` twice | Second is no-op |

**Decided concurrency policy (B1):** **Per-session FIFO lock + queue.** While turn A runs for phone X, message B for X waits (or is queued) and runs after A commits session metadata. Optional short “still working on your last message…” only if wait exceeds a threshold — not required for v1. Different phones still parallel.

Why not “process both in parallel”? That is how you get YES placed + greeting in one breath, or two STK pushes. Why not “drop B”? Silent drop is worse UX and hides bugs in CI.

**Required CI scenarios (must fail the build if broken):**

1. Burst: summary shown → customer sends `YES` then immediately `YES` again before first finishes → exactly one place; second sees `already_placed` (or queued confirm is harmless).
2. Burst: `YES` overlapping with `cancel` / `My Orders` → no name slot write; no greeting; phase remains coherent.
3. Burst: Browse + “shoes” overlapping → both complete under FIFO; final catalog state consistent; no invented “couldn’t retrieve catalog” from empty race.
4. STK success callback overlapping customer “where is my receipt?” → paid + receipt path still runs once.
5. Duplicate Meta webhook (`wamid`) → single process.

Live WABA/Daraja sandbox remains **optional nightly**, not the merge gate — same as the commerce-rails design. Merge gate proves policy with deterministic clocks/locks.

## Non-goals

- Meta Commerce Manager catalog sync / native `catalog_message` (follow-up ship).
- Live WABA/Daraja nightly as merge gate (optional later; merge gate stays mocked).
- Rewriting CommerceRuntime cart/stock CAS (keep; harden wiring around it).
- Hub Products polish (separate ship already in flight).

## Anti-goals

- “Just prompt the model harder” as the fix for YES/name/browse.
- Marking Hub paid without a verifiable STK success path.
- Setting `payment_notified` when the customer never received a document/text receipt.
- Journey tests that pre-seed the exact metadata the bug forgets to set.

## Approaches considered

### A — Conversation / intent

| # | Approach | Tradeoff |
|---|----------|----------|
| **A1 (chosen)** | Explicit phase enum in session metadata (`browsing`, `collecting_details`, `awaiting_yes`, `placed`, `paying`, `post_order`) gated before slot writes and `place_order` | Small surface; high reliability |
| A2 | Constrained intent classifier tool before every turn | More LLM dependency |
| A3 | Full dialog statechart (Rasa-style) | Overkill for this ship |

### B — Payment + receipt

| # | Approach | Tradeoff |
|---|----------|----------|
| **B1 (chosen)** | Single reconcile path: STK callback + poll → `mark_order_paid` + receipt send; `payment_notified` only after WhatsApp ACK; outbox/retry row on failure | Industry PSP pattern |
| B2 | Redis-only faster path | Already failing on key miss |
| B3 | Full outbox worker service | Heavier; can follow if B1 retry table insufficient |

### C — Catalog browse / search

| # | Approach | Tradeoff |
|---|----------|----------|
| **C1 (chosen)** | Port main browse fast path + footwear synonyms into rails; force display of search hits; Jordan sneakers fixture test | Fixes live bug; no Meta sync yet |
| C2 | Meta Commerce sync + catalog_message | Second catalog; later |
| C3 | Embeddings-only rewrite | Flaky without synonym floor |

### D — Testing

| # | Approach | Tradeoff |
|---|----------|----------|
| **D1 (chosen)** | Extend `CommerceJourney` → Real-World Message Pump: webhook shapes, hostile model, **overlapping turns**, Hub paid + receipt spy | Merge-safe; proves races |
| D2 | Golden production transcript replay only | Needs corpus first |
| D3 | Live sandbox nightly as merge gate | Flaky; keep optional |

### E — Concurrent messages (same customer)

| # | Approach | Tradeoff |
|---|----------|----------|
| **E1 (chosen)** | Per-session Redis/async lock + FIFO queue before `execute` | Industry standard; CI can hold lock and prove waiter order |
| E2 | Coalesce rapid texts into one prompt | Loses distinct YES vs cancel |
| E3 | Parallel turns on one session | Causes the reported corruption — reject |

**Chosen ship:** A1 + B1 + C1 + D1 + E1 on the commerce-rails branch (port catalog browse/search from main as needed).

## Decided behavior

1. `menu:browse` (and browse-all natural language) → deterministic list cards; no LLM required.
2. Search expands footwear (and existing food) synonyms; “shoes” matches name/category/brand/search_text containing sneaker/Jordan/footwear.
3. After `_present_checkout_confirmation`, phase=`awaiting_yes`. **Any confirm-intent utterance** places once (not only the literal string `YES`). Confirm when already `placed` → clear “Order {id} already placed” (not greeting). Confirm when not awaiting → re-present summary or ask to continue checkout — never generic hello.

## Intent vs rails (ChatGPT-like understanding without ChatGPT chaos)

We are **not** requiring customers to speak a script. Real people say `yea`, `yeah`, `ok`, `okay`, `sure`, `sawa`, `ndio`, typos, Swahili mix. ChatGPT feels smart because it maps many surface forms → one intent. We do the same for a **small intent set**, then run a **hard action**.

| Layer | Soft (understand humans) | Hard (don’t invent outcomes) |
|-------|--------------------------|------------------------------|
| Confirm | In phase `awaiting_yes`, treat `yes/yea/yeah/yep/y/ok/okay/sure/alright/fine/go ahead/proceed/confirm/sawa/ndio/ndiyo/haya` (+ light typo/fold) as **confirm** | Only then call `place_order`. Outside `awaiting_yes`, bare `ok` does **not** place |
| Search | Synonyms + typos (`shose`→shoes) + footwear group → Jordan sneakers | Always display hits; don’t invent “catalog down” |
| Name | Fuzzy reject intents/buttons | Never store “My Orders” as name |
| Browse | Many phrasings → browse-all | Deterministic card list |

Today `_CONFIRM_WORDS` already includes `yeah`/`yep`/`sawa`/`ndio` but **excludes** `ok`/`sure` as “too ambiguous” globally. That is wrong for real checkout: **phase supplies the disambiguation**. In `awaiting_yes`, `ok`/`okay`/`sure`/`yea` **must** confirm. Outside it, they must not.

Evaluation still uses oracles: after those soft forms in `awaiting_yes`, customer text must show placed/order id — not a greeting. CI must include `yea` / `ok` / `okay` / `sure` as first-class cases, not only `YES`.
4. Expand `_NOT_A_NAME_PHRASES` / intent denylist: my orders, orders, browse catalog, cancel, return, help, human, agent, pay, yes/ndio as sole message, etc. Name capture only in `collecting_details`.
5. STK success always reconciles Hub order paid when `commerce_orders` row exists (create/link if missing when registry has external id). Receipt PDF preferred; text fallback; retry if send fails; do not permanently swallow.
6. Journey CI: scripted turns for each bug above + return/cancel/handoff smoke already present stay green.
7. Same-session overlapping messages are serialized FIFO; CI burst tests prove single place / coherent phase.

## Builder calls

- Prefer porting proven main `catalog_search_service` browse + footwear group over re-inventing.
- Phase enum stored in session metadata; agent `execute` checks phase before LLM tool loop for mutations.
- Receipt: change `payment_notified` semantics carefully with tests for already_notified vs retry_needed.

## Left to the builder

- Exact phase string names; whether to add a small `receipt_delivery` table vs metadata flag `receipt_send_status`.
- How aggressive synonym expansion for brand tokens (Jordan) vs category only.
- Whether Hub Orders UI needs any change (should not if `payment_status` flips correctly).

## Approval

Approve this design to proceed to implementation plan execution (or request changes). Partner asked for a ready-made plan and approval-only gate to start build.
