# WhatsApp Order Confirmation Follow-up Implementation Plan

> **For agentic workers:** REQUIRED AGENT WORKFLOW: Read and follow `subagent-driven-development.agent.md` (recommended) or `executing-plans.agent.md` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure a customer's clear typed-Yes confirmation in the active checkout reaches the existing pending-receipt and payment-choice follow-up exactly once.

**Architecture:** First pin the real inbound WhatsApp path, including its Meta message ID and checkout state, then test the typed-Yes path through `ConversationalAgentService.execute()` and its existing `_sub_create_order()` → `_bg_notify_order_placed()` handoff. Keep receipt generation, payment prompts, and payment actions in their existing services; limit any intent adjustment to the active checkout handoff.

**Tech Stack:** Python, FastAPI, WhatsApp workflow runner, `ConversationContextManager`, existing order-tracking and payment services, pytest, `AsyncMock`.

**Spec:** `docs/superpowers/specs/2026-11-16-whatsapp-order-confirmation-follow-up-design.md`

## Global Constraints

- “Do not change order creation, payment rules, or the choice of payment method.”
- “Do not start M-Pesa STK automatically on “Yes.””
- “Do not generate or send a paid receipt before payment is confirmed.”
- “Do not duplicate or replace existing receipt and payment-prompt logic.”
- “Do not treat a keyword match alone as sufficient evidence of customer intent.”
- “Reproduce/trace the reported path before wiring it, since another order path may be producing the “placed / pending” text.”
- “Reuse the existing order-tracking notification and pending-receipt behavior.”
- “Preserve single-send behavior if webhook retries or background notifications are involved.”
- “Keep intent-handling changes limited to this checkout handoff; reuse the existing conversation context and intent mechanisms.”

## Review Focus

- A bare “Yes” when there is only a cart, stale checkout data, a reservation confirmation, or a human handoff must not place an order; test in Task 2.
- “Yes, change …” or a cancellation while the checkout summary is pending must not place the old order; test in Task 2.
- Ambiguous acknowledgements such as “ok” and “sure” must leave the customer in checkout confirmation rather than create an order; test in Task 2.
- A webhook retry or repeated follow-up for the same order must not send another order confirmation, pending PDF, or payment prompt; test in Task 3.
- Typed “Yes” must not start STK or produce a paid receipt; selecting a payment choice afterward must use its existing action; test in Tasks 1 and 3.

---

## File Map

| File | Responsibility |
|---|---|
| `src/routers/whatsapp_webhook.py` | Inbound message claim and handoff to workflow; trace only unless Task 1 proves the active path breaks here |
| `src/services/whatsapp_workflow_trigger.py` | Adds `session_key` and Meta `meta_message_id` to workflow input; trace only unless Task 1 proves the active path breaks here |
| `src/services/tool_executor.py` | Routes the workflow's conversational-agent step into `ConversationalAgentService.execute()`; trace only unless Task 1 proves the active path breaks here |
| `src/services/conversational_agent_service.py` | Typed-confirmation checkout state, single follow-up handoff, and checkout-local precedence for corrections/cancellation |
| `src/services/order_tracking_service.py` | Existing pending PDF, configured payment prompt, and notification idempotency; preserve behavior |
| `tests/test_whatsapp_order_confirmation_follow_up.py` | Active typed-Yes journey and checkout-intent regressions |
| `tests/test_order_tracking_receipts.py` | Pending-vs-paid receipt and duplicate follow-up contract |
| `tests/test_mpesa_payment_phone.py` | Existing payment-choice actions; add the missing typed-choice regression if needed |

### Task 1: Reproduce the active typed-Yes path

**Files:**
- Create: `tests/test_whatsapp_order_confirmation_follow_up.py`
- Verify only: `src/routers/whatsapp_webhook.py:735-780`
- Verify only: `src/services/whatsapp_workflow_trigger.py:359-445`
- Verify only: `src/services/tool_executor.py:8288-8345`
- Verify only: `src/services/conversational_agent_service.py:2120-2205, 6598-6860`

**Interfaces:**
- Consumes: `ConversationalAgentService.execute(user_message, session_key, business_config, user, db, background_tasks=None, meta_message_id="")`; checkout metadata keys `pending_confirmation`, `checkout_customer`, and `awaiting_order_confirmation`.
- Produces: a test that follows the current service path and observes the single existing order-follow-up call. The typed-Yes deterministic path returns `order_created=True` and keeps the assistant response empty so the notification remains the sole customer-facing follow-up.

- [x] **Step 1: Trace the test's entry and handoff**

  Confirm the actual path is webhook `background_process_message` → `WhatsAppWorkflowTrigger.on_message_received` → `WorkflowBuilderService` / `ToolExecutor._execute_conversational_agent_tool` → `ConversationalAgentService.execute()` → `_sub_create_order()` → `_bg_notify_order_placed()` → `OrderTrackingService.notify_order_placed()`. Confirm the Meta `wamid` is passed as `meta_message_id`, and that the workflow execution path calls the agent without a `BackgroundTasks` collector (so the existing code awaits the follow-up inline). Do not substitute the separate `checkout_confirm_pay` button path.

- [x] **Step 2: Write `test_typed_yes_dispatches_order_follow_up_once`**

  Seed a WhatsApp `ConversationSession` with a cart, matching `pending_confirmation["items"]`, a complete `checkout_customer`, and `awaiting_order_confirmation=True`. Call `agent.execute(user_message="Yes", ..., meta_message_id="wamid.test-yes")`. Exercise the deterministic branch and real `_sub_create_order()` while stubbing order persistence; spy on `_bg_notify_order_placed()`. Assert one order is created, the follow-up is invoked once with that order and the same Meta ID, `response_text == ""`, and no STK initiation occurs.

- [x] **Step 3: Run the path test before changing the dispatch**

  Run: `pytest tests/test_whatsapp_order_confirmation_follow_up.py::test_typed_yes_dispatches_order_follow_up_once -v`

  Expected: PASS if the existing post-create hook already serves the active path; otherwise FAIL at the missing or duplicate follow-up assertion. Use this result to identify the exact gap before editing production code.

- [x] **Step 4: Keep or repair only the existing post-create hook**

  If Step 3 passes, make no production dispatch change. If it fails, make the smallest correction at `_sub_create_order()`'s existing successful-order notification hook: preserve `background_tasks.add_task(...)` when a collector is supplied, otherwise await `_bg_notify_order_placed(...)`, and forward the same `meta_message_id`. Do not add another notification call in `execute()`, the webhook, or the workflow.

- [x] **Step 5: Re-run the path test**

  Run: `pytest tests/test_whatsapp_order_confirmation_follow_up.py::test_typed_yes_dispatches_order_follow_up_once -v`

  Expected: PASS with one order and one follow-up invocation.

### Task 2: Make confirmation depend on current checkout state

**Files:**
- Modify: `src/services/conversational_agent_service.py:1100-1122, 1140-1260, 2120-2205`
- Test: `tests/test_whatsapp_order_confirmation_follow_up.py`

**Interfaces:**
- Consumes: existing `is_order_confirmation_message()`, `match_cart_command()`, CCM metadata, and the typed-Yes path from Task 1.
- Produces: an active-checkout-only gate; no new global intent API. An order may be created from typed confirmation only when the current session is awaiting its order summary confirmation, has pending items and checkout details, and is not in reservation confirmation or human handoff.

- [x] **Step 1: Write the failing checkout-state tests**

  Add these cases and assertions:
  - `test_bare_yes_without_active_checkout_summary_does_not_create_order`: parameterize a cart-only session and one with stale `checkout_customer` data but no active pending confirmation; even a mocked LLM `create_order` proposal must not create an order from the bare “Yes”.
  - `test_yes_during_reservation_or_handoff_does_not_create_checkout_order`: reservation confirmation and human handoff each retain control; the cart order tool is not called.
  - `test_ambiguous_ack_does_not_create_order`: “ok” and “sure” leave the pending checkout intact and do not call `_sub_create_order()`.
  - `test_cancel_during_checkout_confirmation_does_not_create_order`: “cancel” clears `pending_confirmation`, `order_confirmed`, and `awaiting_order_confirmation`, preserves the cart for editing, and returns an unplaced/edit prompt; it does not call `_sub_create_order()`.
  - `test_correction_after_summary_requires_new_confirmation`: “change pilau to 2” updates the cart through the existing cart action, clears stale confirmation and `awaiting_order_confirmation`, and does not create an order until a new summary is confirmed.
  - `test_leading_yes_with_correction_does_not_create_order`: “Yes, change pilau to 2” routes the correction before confirmation, updates the cart, clears stale confirmation state, and does not approve the old summary.

- [x] **Step 2: Run the new state tests to reproduce failures**

  Run: `pytest tests/test_whatsapp_order_confirmation_follow_up.py -k "bare_yes or reservation_confirmation or ambiguous_ack or cancel_during or correction_after or leading_yes" -v`

  Expected: FAIL where current checkout-state handling treats a keyword as approval or lets the old summary reach order creation; no order/payment service should be involved for rejected confirmation.

- [x] **Step 3: Implement checkout-local state and correction precedence**

  In `ConversationalAgentService.execute()`, require the active checkout metadata before entering deterministic creation. While that checkout is pending, route cancellation or an existing cart-edit command—even when preceded by “Yes”—through the existing checkout/cart handling before setting `order_confirmed`. Use `clear_pending_confirmation()` for cancellation and keep cart items available for editing; after a correction, require a fresh checkout summary before another confirmation. Preserve reservation and human-handoff ownership. Leave the global confirmation matcher and general conversation intent behavior unchanged.

- [x] **Step 4: Re-run checkout-state tests and the clear-Yes journey**

  Run: `pytest tests/test_whatsapp_order_confirmation_follow_up.py tests/test_order_confirmation_gate.py -q`

  Expected: PASS; only a clear confirmation in active checkout creates an order, while cancellation, correction, reservation state, missing checkout state, and ambiguous replies do not.

**Decision gate:** The existing helper accepts a leading confirmation word (for example, “yes …”) as confirmation, and the service can synthesize pending confirmation from a cart. Keep this plan limited to precedence inside the active checkout handoff. If making these cases safe requires changing global intent classification or adding a new general-purpose cancellation/NLU system, stop and get a scope decision rather than expanding this task.

The current deterministic cart command set has no explicit checkout-cancel command. For this plan, “cancel” means cancel the unplaced confirmation attempt while retaining the cart for editing. If the product instead expects cancellation to discard the cart or use a broader free-text cancellation intent, get that behavior approved before implementation.

### Task 3: Pin the pending-receipt, payment-choice, and retry contract

**Files:**
- Modify: `tests/test_order_tracking_receipts.py`
- Modify: `tests/test_mpesa_payment_phone.py`
- Test: `tests/test_whatsapp_order_confirmation_follow_up.py`
- Production behavior: `src/services/order_tracking_service.py` is reused, not replaced

**Interfaces:**
- Consumes: Task 1's one-call handoff and `OrderTrackingService.notify_order_placed(user, db, customer_phone, order_data, business_name, ..., meta_message_id)`.
- Produces: regression coverage for one pending (not paid) receipt, the already-configured payment action, and single-send behavior under a repeated follow-up/retry.

- [x] **Step 1: Strengthen the pending-receipt test**

  In `tests/test_order_tracking_receipts.py`, assert `notify_order_placed()` generates the PDF with `payment_status="pending"` and does not call the paid-receipt path. Assert it sends the order confirmation and exactly one payment prompt selected by the configured mode; do not assert or add an STK request on typed “Yes”.

- [x] **Step 2: Pin payment-choice actions to the created order**

  In `tests/test_mpesa_payment_phone.py`, preserve the existing assertions for the “Other number” path. Add or extend a test for the “Pay on this number” action to assert it calls the existing payment initiation for the existing order ID, does not call order creation again, and does not produce a paid receipt before payment confirmation. Keep manual-payment and “I’ve paid” behavior on their existing paths.

- [x] **Step 3: Pin duplicate follow-up behavior**

  Extend `test_notify_order_placed_idempotent` to call the notifier twice for the same registered order and assert that the second call sends no second customer confirmation, PDF, or payment prompt. In the typed-Yes path test, assert the same `meta_message_id` reaches the follow-up guard. Add `test_duplicate_meta_wamid_skips_order_workflow` using `background_process_message()` with `claim_message()` returning `ClaimResult.ALREADY_COMPLETED`; assert the conversational workflow is not invoked again.

- [x] **Step 4: Run the focused regression set**

  Run: `pytest tests/test_whatsapp_order_confirmation_follow_up.py tests/test_order_confirmation_gate.py tests/test_order_tracking_receipts.py tests/test_mpesa_payment_phone.py -q`

  Expected: PASS; typed “Yes” creates one order and one pending follow-up; configured payment choices remain actionable; duplicate delivery does not duplicate customer-visible sends; no paid receipt or automatic STK is produced before the corresponding existing payment action/confirmation.
