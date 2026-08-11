# WhatsApp Support Agent v2 — Arrotech Rollout Guide

## Deploy updated template

1. Open **Library** → **WhatsApp Support Agent** → Deploy (or update existing workflow).
2. Configure:
   - **Knowledge Base** — Arrotech product docs, pricing, onboarding, SLA
   - **Business Name** — Arrotech Solutions
   - **Escalation Phone** — team lead WhatsApp number
   - **Auto-Escalation** — enabled
   - **Human Handoff TTL** — 24 hours
3. Activate the workflow and ensure WhatsApp connection is active.

## Team inbox training

- **Human handling** badge appears when AI is paused (agent replied or customer escalated).
- Use **Release agent** when AI should resume.
- Internal notes do not pause AI; only customer-facing replies do.

## Production test matrix

| Scenario | Expected |
|----------|----------|
| FAQ from KB | Accurate answer from knowledge base |
| Unknown question | Honest "I don't know" + offer human |
| "Talk to human" | Escalation + owner alert + AI paused |
| Agent replies from inbox | No bot race reply |
| Agent releases AI | Bot resumes politely |
| Outside business hours | OOO / no AI reply (if hours configured in profile) |
| STOP keyword | Opt-out, no further AI |
| After 24h silence | Free-form send blocked in inbox; use template |
| Webhook retry | Single reply (idempotency) |

## Workflow execution (RAG ingest)

Manual runs return **202 Accepted** immediately. Track status in **Workflows → Executions** (polls every 4s while running).

Ensure Celery workers are running for long RAG ingest jobs.
