# STK Paid Reconcile under RLS — Design

**Date:** 2026-11-19  
**Status:** Approved (partner)  
**Size:** Small backend fix  
**Approach:** A — set tenant RLS context on STK finalize sessions (same pattern as WhatsApp webhook)

## Intent and why

Customers pay successfully (M-Pesa SMS). Hub Orders stay `pending` and WhatsApp never gets paid text/receipt.

**Proven from production app logs (2026-11-19):**

1. STK ResultURL was correct: `https://prod.api.arrotechsolutions.com/api/agents/daraja/callback/{secret}`
2. Daraja callback POST hit Hub; poll also confirmed payment
3. Reconcile failed with:  
   `new row violates row-level security policy for table "commerce_orders"`
4. Session then rolled back → payment WhatsApp text and receipt failed with *transaction has been rolled back*

WhatsApp message handling calls `set_tenant_context(db, owner_user_id)`. STK callback background sessions and STK poll finalize sessions do **not**. Without `app.current_tenant_id`, RLS on `commerce_orders` blocks SELECT/INSERT/UPDATE; Hub never reaches `paid`.

M-Pesa MSISDN ≠ WhatsApp sender is **not** the failure mode here (logs show both numbers; failure is RLS before notify).

## Goals

1. After STK success (callback or poll), Hub `commerce_orders.payment_status` becomes `paid` (and receipt fields as today).
2. Customer WhatsApp sender receives paid confirmation / receipt attempt.
3. A reconcile DB failure must not leave the session poisoned so notify is skipped for a recoverable path (rollback, then notify when paid was confirmed).

## Non-goals

- Speculative callback-URL / override PRs that were not proven by these logs
- Backfill/heal already-charged pending orders (ops/one-off follow-up)
- Changing RLS policies globally or using `bypass_rls` for all payment traffic (Approach B rejected)
- Redesigning receipt PDF content

## Architecture

| Path | Change |
|------|--------|
| Daraja STK callback (`mpesa_agent_router` background DB session) | After owner `MpesaAgentConfig` is resolved, `await set_tenant_context(db, config.user_id)` before `finalize_order_stk_payment` |
| STK poll (`poll_stk_and_finalize_order_payment`) | On each session used for finalize, `await set_tenant_context(db, owner_user_id)` before finalize |
| `finalize_order_stk_payment` / `_reconcile_commerce_payment` | On reconcile exception: log, `await db.rollback()`, then continue to paid notify/receipt when `is_paid` (so RLS poison does not drop customer messaging if paid was already confirmed by Daraja) |

Reuse existing `src.database.set_tenant_context` (same as WhatsApp webhook).

## Data flow

```
Safaricom STK success
  → callback and/or poll
  → set_tenant_context(owner)
  → mark_order_paid on commerce_orders
  → WhatsApp text + notify_payment_received to whatsapp_sender
```

## Error handling

- Missing owner / order: unchanged (no false paid)
- RLS/flush error during reconcile: rollback; if payment confirmed (`is_paid`), still attempt customer notify; log clearly
- Underpayment fraud check: unchanged

## Testing

| Scenario | Oracle |
|----------|--------|
| Finalize with tenant context set | Hub order `paid`; no RLS error |
| Poll finalize sets tenant context | Same |
| Reconcile flush error then rollback | Session usable; paid notify attempted when `is_paid` |
| Regression | Alternate M-Pesa phone still notifies WhatsApp sender |

## Out of scope follow-ups

Manual mark-paid / refund for duplicate charges already taken; close or park unproven callback-URL PR if still open.
