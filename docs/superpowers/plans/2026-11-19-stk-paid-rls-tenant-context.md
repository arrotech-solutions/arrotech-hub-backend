# STK Paid Reconcile under RLS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** STK callback/poll set RLS tenant context so Hub marks `commerce_orders` paid and WhatsApp notify/receipt can run after Safaricom confirms payment.

**Architecture:** Mirror WhatsApp webhook: `set_tenant_context(db, owner_user_id)` on every DB session that calls `finalize_order_stk_payment`. On reconcile flush failure, `rollback()` before notify so a poisoned session does not drop customer messaging when payment was confirmed.

**Tech Stack:** FastAPI, SQLAlchemy async, Postgres RLS (`app.current_tenant_id`), pytest

**Spec:** `docs/superpowers/specs/2026-11-19-stk-paid-rls-tenant-context-design.md`

## Global Constraints

- Proven root cause: RLS on `commerce_orders` without tenant context — not callback URL, not M-Pesa≠WhatsApp
- Reuse `src.database.set_tenant_context` (same as WhatsApp webhook)
- No `bypass_rls` for this path (Approach B rejected)
- Receipts still go to `whatsapp_sender`
- No speculative callback-URL changes in this ship

## File map

| File | Role |
|------|------|
| `src/routers/mpesa_agent_router.py` | Callback background session → set tenant before finalize |
| `src/services/order_stk_payment_service.py` | Poll sessions → set tenant; reconcile error → rollback then notify |
| `tests/test_stk_hub_paid_receipt.py` (or new `tests/test_stk_rls_tenant_context.py`) | Prove tenant context + rollback behavior |

---

### Task 1: Poll + finalize set tenant context + rollback on reconcile failure

**Files:**
- Modify: `src/services/order_stk_payment_service.py` (`poll_stk_and_finalize_order_payment`, `_reconcile_commerce_payment` / `finalize_order_stk_payment`)
- Test: `tests/test_stk_rls_tenant_context.py`

**Interfaces:**
- Consumes: `set_tenant_context(session, user_id)` from `src.database`
- Produces: poll/finalize sessions always have tenant set before Hub order writes

- [ ] **Step 1: Failing test** — finalize/reconcile path mocks storage; assert `set_tenant_context` called with owner id when opening poll DB session for paid finalize (or unit-test helper that wraps session open)
- [ ] **Step 2: Run** — FAIL
- [ ] **Step 3: In every `async with session_maker() as db:` used for `finalize_order_stk_payment` in poll, call `await set_tenant_context(db, owner_user_id)` first**
- [ ] **Step 4: In `_reconcile_commerce_payment` except block (or finalize after reconcile fails): `await db.rollback()` before re-raise/return so caller can still notify**
- [ ] **Step 5: In `finalize_order_stk_payment`, if reconcile logs failure, ensure rollback then continue paid notify when `is_paid`**
- [ ] **Step 6: Run tests PASS**
- [ ] **Step 7: Commit** `fix(payments): set RLS tenant on STK poll finalize`

---

### Task 2: Daraja callback background session sets tenant context

**Files:**
- Modify: `src/routers/mpesa_agent_router.py` (`_handle_mpesa_callback_background`)
- Test: extend `tests/test_stk_rls_tenant_context.py` or router-level mock

**Interfaces:**
- After `config = ... MpesaAgentConfig`, `await set_tenant_context(db, config.user_id)` before STK finalize branch

- [ ] **Step 1: Failing test / assert** set_tenant_context called with config.user_id in background handler (mock)
- [ ] **Step 2–4: Implement + PASS**
- [ ] **Step 5: Commit** `fix(payments): set RLS tenant on Daraja STK callback session`

---

### Task 3: Regression + verify

**Files:**
- Modify: existing `tests/test_stk_hub_paid_receipt.py` if needed (still pass)
- Run: focused pytest

- [ ] **Step 1: Run** `pytest tests/test_stk_hub_paid_receipt.py tests/test_stk_rls_tenant_context.py -q`
- [ ] **Step 2: Commit if needed; push branch; PR to develop**
- [ ] **Step 3: After deploy — new STK pay: Hub `paid`, no RLS warning in logs, WhatsApp notify**
