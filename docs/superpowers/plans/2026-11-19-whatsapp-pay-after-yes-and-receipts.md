# WhatsApp Pay-After-YES + Receipts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After typed YES places an order, offer Pay on this number / Other number before STK; harden STK success → Hub paid → WhatsApp receipt; re-offer pay buttons if unpaid customer messages again.

**Architecture:** On deterministic place success, set `commerce_phase=paying` and call existing `order_tracking_service.send_payment_retry_buttons` with placed confirmation as body (no STK until button). Reuse pay_mpesa / pay_mpesa_other webhook markers. Verify/fix receipt notify path so paid ⇒ receipt attempt with retryable send failures.

**Tech Stack:** FastAPI agent, order_tracking_service, order_stk_payment_service, pytest

**Spec:** `docs/superpowers/specs/2026-11-19-whatsapp-pay-after-yes-and-receipts-design.md`

## Global Constraints

- No STK on YES alone — ask this WhatsApp number vs other M-Pesa number first
- Unpaid abandon: leave pending; re-offer buttons; no second place
- Receipt only after successful pay; `payment_notified` only after WhatsApp send success
- Reuse existing button ids `pay_mpesa:{order_id}` / `pay_mpesa_other:{order_id}`
- No TTL cancel / reminder cron in this ship

## Review Focus

- YES → place text + buttons sent; STK not called in that turn
- Other-number path still works unchanged
- Unpaid follow-up → buttons again, no new order_id
- STK success → Hub paid + receipt send attempted
- Forbidden: YES reply is only “Payment is still pending.” with no buttons

---

### Task 1: YES/place → pay-choice buttons

**Files:**
- Modify: `src/services/conversational_agent_service.py` (deterministic place success ~2280–2335)
- Test: `tests/test_commerce_rails_agent_wiring.py` or new `tests/test_pay_after_yes.py`

**Interfaces:**
- After place: metadata `commerce_phase=paying`, `placed_order_id=…`
- Call `_offer_payment_retry_buttons` / `send_payment_retry_buttons` with `customer_phone` = WhatsApp sender, `body_text` = placed confirmation (order id + total + short “choose how to pay”)
- Return still includes `response_text`; buttons are outbound via tracking service (same as retry path)
- Do **not** call `_sub_initiate_mpesa_payment` in this turn

- [ ] **Step 1: Failing test** — YES place success offers payment buttons; STK initiate not called
- [ ] **Step 2: Run** — FAIL
- [ ] **Step 3: Wire buttons + phase=paying on place success**
- [ ] **Step 4: Run** — PASS
- [ ] **Step 5: Commit** `fix(agent): offer pay number choice after YES place`

---

### Task 2: Unpaid re-offer

**Files:**
- Modify: `conversational_agent_service.py` (`execute` early path when phase paying / placed unpaid)
- Test: same test file

**Interfaces:**
- If session has unpaid `placed_order_id` / phase `paying` and message is not a pay marker / not confirm-place: re-send pay buttons; do not create_order
- Already-placed confirm while unpaid → re-offer pay (not greeting)

- [ ] **Step 1–4: TDD unpaid re-offer**
- [ ] **Step 5: Commit** `fix(agent): re-offer pay buttons while unpaid`

---

### Task 3: Receipt wiring verification + gaps

**Files:**
- Review/fix: `order_stk_payment_service.py`, `order_tracking_service.py` (`notify_payment_received`)
- Test: extend STK/receipt tests — spy `upload_and_send_document` or `notify_payment_received` after paid finalize

**Interfaces:**
- STK success → `mark_order_paid` + receipt notify; `payment_notified` only on send success; failed send retryable
- Fix any gap found where paid skips receipt or notified without send

- [ ] **Step 1: Failing/regression test** paid ⇒ receipt attempt
- [ ] **Step 2–4: Fix gaps if any**
- [ ] **Step 5: Commit** `fix(payments): ensure receipt after STK paid`

---

### Task 4: Journey smoke

**Files:**
- Modify: `tests/test_commerce_rails_journeys.py` if harness available on branch; else unit path is enough

- [ ] **Step 1: Journey or wiring test** YES → buttons → this-number STK → paid → receipt spy
- [ ] **Step 2: Run focused suite PASS**
- [ ] **Step 3: Commit** if needed
