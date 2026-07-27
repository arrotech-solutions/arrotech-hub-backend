"""
Ask AI product-ready operator checklist

Feature flags: `ASK_AI_WA_GW_V1` (default true), `ASK_AI_REQUIRE_CONFIRM` (default true).

## Product guarantees

Every Ask AI turn ends with one of:
1. A grounded answer (from tool data or synthesis)
2. An Approve/Cancel proposal (HITL)
3. A visible typed error

Never: empty `done`, “I’ll retrieve…” as final, or `success: true` when the upstream API failed.

## Core loop

- Soft intent (email/calendar/WhatsApp/check/list/…) always takes the tool path
- Stream and non-stream share system prompt, tool-result formatting, deferral retry, HITL early exit
- Write-tier gate runs **before** creating a proposal
- Failed confirms mark proposal `failed` (not `executed`)

## WhatsApp + Google Workspace

| Surface | Notes |
|---------|--------|
| Inbox / account / agent | No HITL; free can read |
| WA send / media / template / create_template | Starter+ + HITL in Ask AI only; Meta success propagated |
| Gmail / Calendar / Drive / Sheets / Docs | Reads free; mutates Starter+ + HITL |
| Calendar availability | Accepts `start_time`/`end_time` as `time_min`/`time_max` |
| Gmail drafts | `list_drafts` / `get_draft` / `update_draft` wired |

**Ordering agent / workflows:** use `skip_confirmation=True` so customer WhatsApp replies are not blocked by Ask AI Approve.

## Other integrations (name-aligned)

Registry tool names resolve via `tool_name_aliases.resolve_tool_name` to executor handlers:

Outlook, Notion, Trello, Jira, Power BI, Xero (`xero_accounting`), QuickBooks (`quickbooks_accounting`), HubSpot contact ops, Salesforce CRUD names, Airtable, Telegram.

**Not exposed in Ask AI until wired:** Facebook, Twitter/X, TikTok, GitHub platform tools (coding agent GitHub tools remain separate).

**Zoho Mail:** clear “not available” error (CRM/Finance/Desk remain).

## Smoke matrix

1. Unread WhatsApp → grounded list  
2. “Am I free tomorrow 10–12 Africa/Nairobi?” → calendar availability  
3. Email unread WA summary → inbox then Gmail propose  
4. Free user send WA → upgrade (no Approve card)  
5. Starter send WA → Approve → Meta success/failure reflected  
6. Outlook / Notion / Trello / Jira list tools when connected  
7. Xero / QuickBooks company info when connected  
8. Disconnect → reconnect CTA  

## Tests

`tests/test_ask_ai_wa_workspace.py` — confirmation, gates, deferral, aliases, operator ensure.
