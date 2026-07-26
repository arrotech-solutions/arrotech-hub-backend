# Ask AI — WhatsApp + Google Workspace (operator copilot)

Feature flag: `ASK_AI_WA_GW_V1` (default true). HITL: `ASK_AI_REQUIRE_CONFIRM` (default true).

## Who it’s for

Hub operators in `/chat` (Ask AI). Customer-facing WhatsApp ordering agent is separate.

## Capabilities

### WhatsApp tools (when connected)

| Tool | Ops | Free | Notes |
|------|-----|------|-------|
| `whatsapp_inbox` | list_conversations, get_thread, search, unread_summary | Read OK | Deep links to `/inbox?contact=` |
| `whatsapp_agent_control` | pause_ai, resume_ai, handoff_status | OK | CCM handoff |
| `whatsapp_account_info` | check_connection, get_phone_info | OK | Reconnect CTA |
| `whatsapp_send_message` / `whatsapp_messaging` | send_* | Starter+ + confirm | |
| `whatsapp_templates` | list_templates (free), send_template (Starter+ + confirm) | | |

### Google Workspace

`google_workspace_gmail|calendar|drive|sheets|docs|analytics` — Free can **read**; sends/mutates need Starter+ and confirmation.

## Confirmation flow

1. Model calls outbound tool → server creates `tool_proposals` row  
2. SSE `tool.propose` + pending `tool_result`  
3. UI Approve/Cancel → `POST /chat/proposals/{id}/confirm`  
4. Execution audited in `tool_audit_log`

## Test matrix (smoke)

1. Connect WhatsApp → “Show unread WhatsApp chats”  
2. “Pause AI for +2547…” → handoff_status ACTIVE  
3. Free user: send WA → upgrade message  
4. Starter: send WA → Approve chip → message sent  
5. Connect Google → “List my next 5 calendar events”  
6. “Email me a digest…” → Gmail send proposal → Approve  
7. Disconnect Google → clear reconnect error with `/connections`

## Meta sandbox checklist

- Test number + Cloud API app  
- Template approved for outbound outside 24h window  
- Webhook signature (`WHATSAPP_WEBHOOK_REQUIRE_SIGNATURE=true` in prod)

## Alembic

`k5f6g7h8i9d1_tool_audit_proposals` — `tool_audit_log`, `tool_proposals`.
