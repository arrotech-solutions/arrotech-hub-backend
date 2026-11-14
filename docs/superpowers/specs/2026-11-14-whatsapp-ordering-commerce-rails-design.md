# WhatsApp Ordering — Commerce Rails + Shared Spine

**Date:** 2026-11-14  
**Status:** Approved  
**Scope:** Production-ready WhatsApp **ordering agent** + shared spine; Hub UX for merchant ops and policy. Wave 2 verticals (rent, support, real estate) consume the spine later — not in this ship.

**Related:** Builds on `2026-11-12-kenya-whatsapp-commerce-design.md` (catalog/orders/M-Pesa sell loop). This design does not reopen that default path; it hardens it into industry-grade automation.

---

## Intent and why

Ship an ordering experience that a real Kenya merchant can run in ~one week: customers buy, pay, track, return/complain, and reach a human on WhatsApp without dead ends; merchants run catalog, orders, returns approvals, hours/policy, and handoff from Hub. Rejection criteria are **industry standard, quality, intelligence, and automation** — not a thin happy-path demo.

Today the stack is: Meta webhook → Celery → workflow → `ConversationalAgentService` → WhatsApp. Catalog/search/orders/M-Pesa exist on the Arrotech DB path, but commerce logic is entangled in a large agent service (`order_type` branches, prompts, tools). Reliability gaps (ack-before-process, timeouts vs tool loops, inconsistent handoff) and missing first-class after-sale flows block a “perfect/complete” go-live. Hub ops exist for orders/catalog but lack a clear **policy + returns + handoff** surface that matches the automation bar.

---

## Goals

- **Complete customer journey on WhatsApp (ordering):** discover/browse/search → cart → checkout (delivery / pickup / dine-in where configured) → M-Pesa (STK + manual fallback) → order status / cancel-or-change within policy → returns request → complaints intake → talk-to-person with full context.
- **Hard rails, smart gaps:** money, cart, order, returns eligibility, and handoff are deterministic. LLM handles language, intent, search phrasing, and messy conversation — it does not invent prices, invent stock, invent refunds, or skip policy.
- **One agent, many sell modes via Hub config:** retail delivery, food delivery/pickup/dine-in (and related reservation where enabled) — no per-business code change. First merchant may enable one mode; others must already work when toggled.
- **Refunds:** Hub-gated by default; optional merchant-configured auto-approve for low-risk returns (amount cap, window, reason codes).
- **Shared spine:** idempotent inbound processing, retries without duplicate side effects, no silent dropped chats after HTTP 200, latency budget compatible with WhatsApp UX (target: p95 reply in a few seconds for normal turns), secure handling of tokens/PII, clean Hub handoff.
- **Hub UX:** aesthetic, responsive (phone → desktop), clear day-to-day ops — policy, orders, returns queue, handoff — without feeling like a generic toolkit. Preserve existing Hub visual language; raise quality on new/extended surfaces.
- **Ship gate:** harness/evals must block release when core journeys regress (not advisory-only heuristics).
- **Wave 2-ready spine:** rent/support/real estate later plug into the same reliability and handoff patterns — **not** built to parity in this project.

## Non-goals

- Rewriting into a new multi-agent product or greenfield ordering microservice.
- Tenant MCP / sandbox playground / eval theater as a Wave 1 deliverable.
- Full returns/refunds accounting, WMS, loyalty, marketing broadcasts.
- Wave 1 feature parity for rent collection, real estate, or dual support templates.
- Replacing Meta WhatsApp or M-Pesa with other channels/payments in this ship.
- Redesigning the entire Hub chrome/design system from scratch.

## Anti-goals

- Technically “works” but fails industry bar on intelligence, automation, or reliability (lost turns, brittle scripts, humans for routine buys).
- Happy path only; after-sale and escape-to-human treated as afterthoughts.
- Hardcoding merchant policy in code or prompts so every business needs an engineer.
- Dual paths that diverge (old free-form agent vs new rails) without a clear cutover.
- Hub screens that are unusable on mobile or feel bolted-on / low-trust for ops that move money.

---

## Constraints

- Build on existing: webhook, Celery tasks, library `whatsapp_ordering_agent`, `ConversationalAgentService`, `CatalogSearchService`, commerce storage, M-Pesa settings, Hub Catalog/Orders.
- Kenya default remains WhatsApp + M-Pesa + Arrotech DB (per 2026-11-12 design).
- Languages: English + Swahili (including mixed/messy customer phrasing) as first-class UX — not bolted translation.
- Frontend: extend existing React Hub; follow established layout/nav patterns; new surfaces must be responsive and meet a high aesthetic/UX bar (clear hierarchy, one job per view, fast ops for orders/returns/handoff).
- Security: no secrets in client; Hub actions for refunds/approvals require authenticated merchant user; audit who approved what.
- Do not remove canvas/RAG power-user paths; default ordering path stays Arrotech DB.

---

## Approaches considered

| Approach | Summary | Tradeoff |
|----------|---------|----------|
| 1. Patch-in-place | Keep stuffing flows into `ConversationalAgentService` + templates | Fastest demos; rails stay scattered; quality/automation bar hard to lock |
| **2. Commerce rails under existing agent (chosen)** | Deterministic commerce runtime under the current agent shell; harden shared spine; Hub policy/ops UX | More structure upfront; matches hard-rails decision; no greenfield rewrite |
| 3. New ordering runtime beside the old | Parallel engine + migrate traffic | Clean isolation; dual-path cost; slow/risky before first live merchant |

**Chosen:** Approach 2 — partner confirmed; Hub UI quality (aesthetic, responsive, excellent UX) is in scope for merchant-facing ops/policy surfaces.

---

## Architecture (how — decided shape)

```
Meta Webhook (fast ack)
  → durable queue (Celery) with idempotency key per inbound message
  → Ordering workflow
  → ConversationalAgentService (NLU, language, tool selection, WhatsApp copy)
       ⇄ CommerceRuntime (deterministic state + policy)
            → Catalog / Cart / Checkout / Payment / Order / Return / Complaint / Handoff
  → WhatsApp send (+ Hub realtime for handoff/ops)
```

### CommerceRuntime responsibilities

Owned as **code + Hub policy**, not free LLM invention:

- Session commerce state (cart, fulfillment mode, checkout fields, pending payment, open return/complaint).
- Transitions: add/update/remove line → checkout → pay → placed → status updates; cancel/change within policy; return request; complaint ticket; handoff latch.
- Policy evaluation: sell modes enabled, hours/away, delivery methods, return window/eligibility, auto-approve rules, when to force human.
- Side effects: inventory checks via catalog services, `CommerceOrder` / return records, M-Pesa STK trigger, Hub notifications.
- Idempotent application of tool results and payment callbacks.

### ConversationalAgentService responsibilities

- Understand user message (EN/SW/mixed); map to commerce intents or clarification.
- Present catalog results, carts, buttons/lists, receipts, status — WhatsApp-native UX.
- Call CommerceRuntime for any money/state mutation; never mutate those privately.
- Browse/search remain high quality (existing hybrid catalog search); empty catalog honest UX retained.
- Escape hatch: “talk to person” always available → handoff with transcript, cart, order ids, complaint/return ids.

### Shared spine

- Webhook returns quickly; processing is async and **at-least-once with idempotency** (no double-charge / double-order from retries).
- Timeouts and tool-loop budgets that fail loudly into a safe customer message + optional handoff — never silent drop.
- Structured logging/metrics for turn latency, queue lag, payment success, handoff rate, return auto-approve rate.
- Payment callbacks (M-Pesa) reconcile into CommerceRuntime / order payment_status the same way Hub expects today, extended for return refunds when approved.

### Hub surfaces (UI in scope)

Preserve Hub design system (nav, tokens, component patterns). New or extended screens must be:

- **Responsive:** usable on phone and desktop (ops often on mobile).
- **Aesthetic / clear:** one primary job per view; strong hierarchy; no cluttered “dashboard soup” on policy/ops pages.
- **Great UX:** few taps to approve a return, open WhatsApp to customer, see handoff queue, edit policy without engineer language.

Required Hub capabilities for this ship:

1. **Commerce policy** (merchant-editable): sell modes, fulfillment options, business hours/away message, return window + reason codes, auto-approve toggle + caps, handoff TTL / when bot pauses.
2. **Orders ops** (extend existing): status, payment, customer contact — already Phase 1; ensure mobile-friendly polish where gaps remain.
3. **Returns / complaints queue:** list, detail, approve/deny refund (with audit), notes; deep link to order + WhatsApp thread context.
4. **Handoff inbox:** who is waiting for a human, context snapshot, resume-bot control.

**Builder call on visuals:** Do not invent a new brand system; refine within existing Hub look. Prefer clarity and speed for money-moving actions over decorative chrome.

---

## Decided product behavior

| Topic | Decision |
|-------|----------|
| Wave | Ordering agent + shared spine first; other verticals later on same spine |
| Completeness | Buy + pay + track/change + returns + complaints + talk-to-person |
| Intelligence model | Hard rails for commerce; LLM in the gaps |
| Sell modes | Config-driven in one agent; no per-business code |
| Refunds | Hub approve default; optional auto-approve under merchant rules; **on approve → automated M-Pesa payout** when payout is configured; else record + WhatsApp status + merchant offline settle (no silent “approved” without a clear next step) |
| Languages | EN + SW / mixed as first-class |
| Reliability | No lost chats; p95 few seconds normal turns; payments stick |
| Success bar | Real merchant ~1 week; clean Hub handoff; industry quality/automation |
| Hub UI | Aesthetic, responsive, excellent ops UX on policy/orders/returns/handoff |
| Eval/harness | Release gate for core journeys |
| Out of ship | Broadcasts, loyalty, WMS, full accounting, Wave 2 vertical parity, MCP playground |

### Customer journey (ordering) — must work

1. Greet / hours-away aware.
2. Browse or search (slang OK); add to cart; edit cart.
3. Choose fulfillment allowed by policy; collect required fields only.
4. Confirm total; STK push or manual pay instructions; reconcile payment.
5. Confirm order; later: status, cancel/change if policy allows.
6. Return: start → eligibility → create request → auto-approve or “pending merchant” → status updates on WhatsApp.
7. Complaint: capture → classify → self-serve if possible → else handoff with packet.
8. Human anytime; bot stays quiet until released; context preserved.

### Merchant journey (Hub) — must work

1. Configure policy (modes, hours, returns, auto-approve).
2. Maintain catalog (existing).
3. See orders and payment state; update fulfillment status.
4. Process returns/complaints; approve/deny refunds.
5. Pick up handoff conversations and return to bot.

---

## Builder calls (defaults settled here)

- **Runtime shape:** New focused module(s) (e.g. `commerce_runtime` / state + policy) called from `ConversationalAgentService`; avoid a second WhatsApp entrypoint.
- **Cutover:** Feature-flag or library-template flag to force rails path for `whatsapp_ordering_agent`; no permanent dual brain.
- **Idempotency key:** inbound WhatsApp message id (wamid) + tenant; payment callback ids similarly.
- **Returns data:** first-class persistence (table or equivalent) linked to `CommerceOrder`, not only chat transcript.
- **Auto-approve:** evaluated only against Hub policy fields; default off for new merchants.
- **Hub IA:** Policy as its own settings area or Commerce sub-nav; Returns queue adjacent to Orders. **Handoff:** extend existing WhatsApp Conversations (queue filter + richer commerce packet: cart, order, return/complaint ids) — not a separate inbox product.
- **UI:** Mobile-first layouts for queues (Orders/Returns/Handoff); desktop gets denser tables. Use existing components where they fit; do not introduce a second design language.
- **Inventory rails:** Block sale when availability is not sellable. If `quantity` is tracked, decrement on place and restock on cancel/return-approve; no silent oversell. Soft “warn but allow” is not acceptable on the rails path.
- **Cancel / change:** Before paid/confirmed — customer may edit cart/fulfillment freely. After place — **cancel within configurable status cutoff** (default: until `preparing`). **Change after place** = cancel eligible lines or full cancel + new order, not a full amend engine in this ship. Paid cancel enters the **same refund/approval pipeline** as returns (execution of money move = partner decision below).
- **Status pushes:** Merchant Hub fulfillment status changes **do** proactively notify the customer on WhatsApp (in addition to on-demand track-in-chat).
- **Hours / away:** Single source of truth for ordering — Commerce policy. Existing WhatsApp profile hours/away are linked or migrated so merchants do not maintain two conflicting clocks.
- **Complaints self-serve (Wave 1):** Auto-resolve where tools already answer: where-is-my-order, hours/away, payment pending/failed recovery, start return/cancel. Product quality, wrong item, payment disputes, abuse → ticket + handoff. No separate SLA product beyond handoff TTL.
- **Evals / release gate:** CI blocks on (1) deterministic CommerceRuntime transition tests and (2) scripted multi-turn journeys with **mocked LLM**. Live-LLM journeys optional/nightly, not flake-prone merge blockers. Gate applies to ordering/rails releases; other `order_type` templates are **must-not-break** smoke only (Wave 2 owns their depth).
- **Wave 2:** Spine contracts (idempotent consume, handoff packet shape, hours/away) documented for later agents; no rent/RE feature work in this project.
- **Refund money movement (partner deferred → industry call):** On Hub or auto-approve, attempt **automated M-Pesa payout** to the customer phone (idempotent; Hub audit of initiator/amount/receipt). If payout credentials/capability are not configured, approval still **records** the refund, notifies the customer on WhatsApp with honest status, and prompts the merchant to settle offline — never claim “refunded” until payout succeeds or merchant marks settled. Full ledger/accounting remains out of scope; STK pay-in path stays as today.

---

## Left to the builder

- Exact module boundaries, state schema, and migration details for returns/complaints/policy JSON.
- Precise webhook/Celery idempotency and retry semantics implementation.
- WhatsApp interactive patterns (buttons/lists) per step — must stay Meta-compliant and fast.
- How policy is stored (business_config vs dedicated tables) as long as Hub-editable and agent-readable.
- Exact auto-approve rule fields and validation.
- Frontend component choices within the existing design system; visual polish pass on touched pages.
- Metrics/alert hooks (where they emit) without requiring a new observability product.
- Load/latency tactics (caching catalog, parallel tool IO) within the p95 goal.
- Test plan covering unit (runtime transitions), integration (webhook→order→Hub), and journey evals.

---

## Out of scope reminders

- Rent collection notify/buttons/reminders, real-estate lead flows, support-template consolidation — track for Wave 2 on the hardened spine.
- Multi-warehouse, loyalty, broadcasts — separate products.

---

## Approval

Partner chose Approach 2 and required Hub UI standards (aesthetic, responsive, great UX). This document is the contract for planning and implementation.

**Approve / request changes** before any implementation plan or code.
