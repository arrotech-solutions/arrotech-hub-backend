# WhatsApp Pay-After-YES + Receipts — Design

**Date:** 2026-11-19  
**Status:** Approved (partner)  
**Size:** Small–medium backend ship  
**Approach:** Reuse existing pay-button / other-number / STK / receipt paths; wire them into typed YES place success and harden paid→receipt

## Intent and why

After the customer confirms checkout with YES (or equivalent), the agent places the order and stops on “Payment is still pending” with no next step. Merchants also report missing receipts after a successful M-Pesa pay. Kenya WhatsApp commerce requires: place → choose who pays (WhatsApp MSISDN vs other M-Pesa number) → STK → Hub paid → receipt on WhatsApp.

## Goals

1. After successful confirm/place: short placed confirmation + interactive **Pay on this WhatsApp number** / **Use a different M-Pesa number** — **no STK until they choose**.
2. Set `commerce_phase=paying`; keep `order_id` on session.
3. This-number → existing STK to WhatsApp MSISDN; other-number → existing collect-number → STK; retries on **same** order.
4. If they abandon or chat again while unpaid: leave Hub `payment_status=pending`; re-offer the same two buttons; **do not** place again.
5. On STK success: `mark_order_paid` on Hub + generate/send receipt (PDF preferred, text fallback); `payment_notified` only after successful WhatsApp send; failed send retryable without “pay again.”
6. Tests/oracles cover YES→buttons (no STK), both pay paths, unpaid re-offer, paid→receipt attempt; forbid dead-end pending-only reply after YES.

## Non-goals

- Unpaid TTL auto-cancel / reminder cron  
- Receipt visual redesign / email receipts  
- New payment provider or Meta catalog sync  
- FIFO burst pump (deferred elsewhere)

## Anti-goals

- Auto-STK on YES without offering another M-Pesa number  
- LLM-owned payment handoff after place  
- Claiming paid/receipted when WhatsApp send failed  
- Duplicate orders to retry payment  

## Decided behavior

| Topic | Decision |
|-------|----------|
| Post-YES payment UX | Ask first (this WhatsApp number vs other M-Pesa number) before STK |
| Unpaid abandon | Leave pending; re-offer buttons on next message |
| Implementation approach | Wire existing pay-button fast paths into YES/place success (Approach 1) |
| Receipt timing | After successful pay only — never on place alone |

## Architecture

- **Place path:** On confirm + `awaiting_yes` place success, transition to `paying`, send placed copy + existing pay-choice buttons (reuse markers / helpers already used for post-checkout pay UI).
- **Pay paths:** Unchanged fast paths for this-number STK and other-number collection → `initiate_mpesa` / `_sub_initiate_mpesa_payment`.
- **Reconcile + receipt:** STK callback and poll share resolve → `mark_order_paid` → `notify_payment_received` (PDF via `_generate_receipt_pdf_bytes` / `upload_and_send_document`, else text). Separate **paid** from **receipt delivered**; retry receipt if send failed.
- **Idempotency:** Double YES while placed/unpaid → already placed or re-offer pay; never second place. Same STK success → single paid + single successful receipt notify.

## Error handling

- STK fail/cancel/timeout → customer message + retry on same `order_id`  
- Invalid other-number → re-ask  
- Receipt send fail → `receipt_send_status=failed`; poll/callback may retry; do not treat as unpaid  

## Testing

| Scenario | Oracle |
|----------|--------|
| YES after summary | Order placed; two pay buttons; STK **not** called yet |
| Tap this number | STK once for session order |
| Other number + MSISDN | STK to that MSISDN |
| Unpaid text follow-up | Buttons again; no new place |
| STK success | Hub `paid` + receipt send attempted |
| Forbidden after YES | Lone “Payment is still pending.” with no pay affordance |

## Out of scope follow-ups

TTL cancel/restock; proactive unpaid reminder; adversarial burst FIFO (prior deferred tasks).
