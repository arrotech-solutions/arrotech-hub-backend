# WhatsApp Order Confirmation Follow-up — Design

## Intent and why

When a customer replies “Yes” to the order summary, the order is placed but the
customer must also receive the already-supported pending PDF receipt and clear
payment choices. The current confirmation path appears to rely on a separate
follow-up notification, and the reported response does not give the customer a
next step.

## Goals

- Ensure the exact typed-“Yes” order-confirmation path reaches the existing
  post-order follow-up.
- Verify the pending receipt and payment choices are sent once.
- Add regression coverage for the customer-visible confirmation journey.
- Verify replies are interpreted in the current checkout state: confirmation,
  cancellation, correction, ambiguity, and payment selection must take the
  appropriate existing action.

## Non-goals and anti-goals

- Do not change order creation, payment rules, or the choice of payment method.
- Do not start M-Pesa STK automatically on “Yes.”
- Do not generate or send a paid receipt before payment is confirmed.
- Do not duplicate or replace existing receipt and payment-prompt logic.
- Do not treat a keyword match alone as sufficient evidence of customer intent.

## Constraints

- Reproduce/trace the reported path before wiring it, since another order path
  may be producing the “placed / pending” text.
- Reuse the existing order-tracking notification and pending-receipt behavior.
- Preserve single-send behavior if webhook retries or background notifications
  are involved.
- Keep intent-handling changes limited to this checkout handoff; reuse the
  existing conversation context and intent mechanisms.

## Approaches considered

1. Wire the typed-“Yes” path to the existing follow-up and add an end-to-end
   regression test. **Chosen:** smallest change, consistent with the reported
   wiring gap.
2. Centralize follow-up across every order-creation path. Broader consistency,
   but expands scope beyond this reported path.
3. Send follow-up inline from the webhook. Avoids a background handoff, but may
   increase webhook latency and risk duplicate messages.

## Left to the builder

Identify the exact active confirmation path and the narrowest reliable hook
for one follow-up invocation. Test that a clear confirmation leads to a pending
PDF receipt and actionable payment choices, while cancellation, correction, or
ambiguous replies do not place an unintended order; payment choices should
continue through their existing actions. Do not change payment or receipt
semantics.
