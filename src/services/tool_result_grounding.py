"""
Format tool results for the LLM and ground final answers on successful tool data.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


REFUSAL_PATTERNS = [
    r"can'?t access",
    r"cannot access",
    r"don'?t have access",
    r"unable to access",
    r"i currently can'?t",
    r"i don'?t have (direct )?access",
    r"check them in your whatsapp",
    r"open .+ in your whatsapp business app",
    r"would you like to take any action",
    r"let me know how i can assist",
    r"if you need help with anything else",
    r"couldn'?t get any data",
    r"could not get any data",
    r"issue retrieving",
    r"there was an issue",
    r"unfortunately,? i couldn'?t",
    r"try again later",
]

# Model narrates future work instead of calling a tool this turn
DEFER_PATTERNS = [
    r"one moment",
    r"let me check",
    r"let'?s check",
    r"i('?ll| will) check",
    r"checking (your|the)",
    r"please wait",
    r"hang on",
    r"give me a (moment|second)",
    r"looking (that|it) up",
    r"let'?s start by",
    r"i('?ll| will) first\b",
    r"i('?ll| will) (now )?(gather|retrieve|fetch|look(?:\s+up)?|pull|find)\b",
    r"i('?ll| will) (now )?(send|email)\b",
    r"(gathering|retrieving|fetching)\b",
    r"i('?ll| will) retrieve .+ now",
]

# Trailing soft offers after a real answer should not force another tool loop
_SOFT_OFFER = re.compile(
    r"(if you (want|need|like)|let me know|would you like|want me to|shall i)\b",
    re.I,
)


def _payload_collections(tool_result: Dict[str, Any]) -> Dict[str, Any]:
    """Unify WhatsApp-style `data` and Google Workspace top-level collections."""
    data = dict(tool_result.get("data") or {}) if isinstance(tool_result.get("data"), dict) else {}
    for key in (
        "emails", "events", "files", "documents", "availability",
        "conversations", "messages", "contact", "total_unread",
        "traffic_data", "conversion_data", "behavior_data", "ecommerce_data",
        "custom_report", "busy", "calendars",
    ):
        if key in tool_result and key not in data:
            data[key] = tool_result[key]
    if "total" in tool_result and "total" not in data:
        data["total"] = tool_result["total"]
    if "count" in tool_result and "count" not in data:
        data["count"] = tool_result["count"]
    return data


def format_tool_result_for_llm(tool_name: str, tool_result: Any) -> str:
    """
    Produce a clear, model-facing string so the LLM answers from tool data
    instead of hallucinating lack of access.
    """
    if not isinstance(tool_result, dict):
        return str(tool_result)

    if tool_result.get("pending_confirmation"):
        return json.dumps(tool_result, default=str)

    success = tool_result.get("success", True)
    parts: List[str] = []

    if not success:
        err = tool_result.get("error") or tool_result.get("message") or "Tool failed"
        parts.append(f"TOOL FAILED ({tool_name}): {err}")
        data = _payload_collections(tool_result)
        if data:
            parts.append("Partial data: " + json.dumps(data, default=str)[:2000])
        return "\n".join(parts)

    parts.append(
        f"TOOL SUCCEEDED ({tool_name}). Use this data to answer the user. "
        "Do NOT say you lack access or that retrieval failed."
    )

    result_text = tool_result.get("result") or tool_result.get("message")
    if result_text and not isinstance(result_text, (dict, list)):
        parts.append(str(result_text))

    data = _payload_collections(tool_result)

    conversations = data.get("conversations")
    if isinstance(conversations, list):
        total_unread = data.get("total_unread")
        if total_unread is not None:
            parts.append(f"Total unread messages: {total_unread}")
        parts.append(f"Conversations ({len(conversations)}):")
        for c in conversations[:25]:
            if not isinstance(c, dict):
                continue
            name = c.get("name") or "Unknown"
            phone = c.get("phone_number") or ""
            unread = c.get("unread_count", 0)
            preview = c.get("last_message_preview") or c.get("preview") or ""
            line = f"- {name} ({phone}): {unread} unread"
            if preview:
                line += f' — last: "{str(preview)[:160]}"'
            url = c.get("inbox_url")
            if url:
                line += f" [{url}]"
            parts.append(line)

    messages = data.get("messages")
    contact = data.get("contact")
    if isinstance(messages, list):
        label = "Thread"
        if isinstance(contact, dict):
            label = f"Thread with {contact.get('name') or contact.get('phone_number')}"
        parts.append(f"{label} ({len(messages)} messages):")
        for m in messages[-20:]:
            if not isinstance(m, dict):
                continue
            direction = m.get("direction") or ("out" if m.get("is_agent") else "in")
            body = (m.get("content") or "")[:400]
            parts.append(f"  [{direction}] {body}")

    emails = data.get("emails")
    if isinstance(emails, list):
        parts.append(f"Emails ({len(emails)}):")
        if not emails:
            parts.append("- (none)")
        for e in emails[:15]:
            if not isinstance(e, dict):
                continue
            parts.append(
                f"- From: {e.get('from') or '?'} | Subject: {e.get('subject') or '(no subject)'} "
                f"| Date: {e.get('date') or ''} | Snippet: {(e.get('snippet') or '')[:160]}"
            )

    events = data.get("events")
    if isinstance(events, list):
        parts.append(f"Calendar events ({len(events)}):")
        if not events:
            parts.append("- (none in range)")
        for ev in events[:15]:
            if not isinstance(ev, dict):
                continue
            start = ev.get("start") or {}
            when = start.get("dateTime") or start.get("date") or ""
            parts.append(
                f"- {ev.get('summary') or '(no title)'} @ {when}"
                + (f" | {ev.get('location')}" if ev.get("location") else "")
            )

    files = data.get("files")
    if isinstance(files, list):
        parts.append(f"Drive files ({len(files)}):")
        if not files:
            parts.append("- (none)")
        for f in files[:20]:
            if not isinstance(f, dict):
                continue
            parts.append(
                f"- {f.get('name') or '?'} ({f.get('mime_type') or f.get('mimeType') or 'file'}) "
                f"modified {f.get('modified_time') or f.get('modifiedTime') or ''}"
                + (f" {f.get('web_view_link') or f.get('webViewLink') or ''}" )
            )

    documents = data.get("documents")
    if isinstance(documents, list):
        parts.append(f"Google Docs ({len(documents)}):")
        if not documents:
            parts.append("- (none)")
        for d in documents[:15]:
            if not isinstance(d, dict):
                continue
            title = d.get("title") or d.get("name") or "?"
            content_preview = (d.get("content") or "")[:200]
            parts.append(f"- {title}" + (f" — {content_preview}" if content_preview else ""))

    availability = data.get("availability")
    if isinstance(availability, dict):
        parts.append("Availability:")
        for email, info in availability.items():
            if isinstance(info, dict):
                free = info.get("available")
                busy = info.get("busy") or []
                parts.append(
                    f"- {email}: {'FREE' if free else 'BUSY'} "
                    f"({len(busy)} busy block(s))"
                )
            else:
                parts.append(f"- {email}: {info}")

    # Analytics / leftover structured fields
    handled = {
        "conversations", "messages", "contact", "total_unread", "emails", "events",
        "files", "documents", "availability", "total", "count", "widget",
    }
    leftover = {k: v for k, v in data.items() if k not in handled and v is not None}
    if leftover and not any(
        isinstance(data.get(k), list) for k in ("emails", "events", "files", "documents", "conversations", "messages")
    ) and "availability" not in data:
        parts.append("Data: " + json.dumps(leftover, default=str)[:3500])

    trailer = {
        "success": True,
        "tool": tool_name,
        "result": result_text if not isinstance(result_text, (dict, list)) else None,
        "data": data,
    }
    parts.append("JSON: " + json.dumps(trailer, default=str)[:5000])
    return "\n".join(parts)


def looks_like_tool_deferral(answer: str, tools_called: Optional[List[Dict[str, Any]]] = None) -> bool:
    """
    True when this turn's answer promises future work instead of finishing the ask.

    Caller must only invoke this when the current assistant turn had no tool_calls.
    Prior tools in `tools_called` do not suppress detection — multi-step flows often
    stall after a successful first tool with "I'll email that now…".
    """
    _ = tools_called  # kept for call-site compatibility
    text = (answer or "").strip().lower()
    if not text:
        return False
    if not any(re.search(p, text) for p in DEFER_PATTERNS):
        return False

    # "You're free 10–12. I'll send an invite if you want." — answered; soft offer OK
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    if len(sentences) >= 2 and _SOFT_OFFER.search(text):
        first = sentences[0]
        if not any(re.search(p, first) for p in DEFER_PATTERNS):
            return False
    return True


def looks_ungrounded(answer: str, tools_called: List[Dict[str, Any]]) -> bool:
    """True when the model refused / hedged despite successful tool data."""
    if not tools_called:
        return False
    successful = [
        t for t in tools_called
        if isinstance(t.get("result"), dict)
        and t["result"].get("success")
        and not t["result"].get("pending_confirmation")
    ]
    if not successful:
        return False

    text = (answer or "").strip()
    if len(text) < 8:
        return True

    lower = text.lower()
    if not any(re.search(p, lower) for p in REFUSAL_PATTERNS):
        # Also ungrounded if tool returned list items but answer never mentions any concrete field
        for t in successful:
            data = _payload_collections(t.get("result") or {})
            emails = data.get("emails") or []
            events = data.get("events") or []
            files = data.get("files") or []
            if emails and not any(
                (e.get("subject") or "")[:20].lower() in lower or (e.get("from") or "").split("<")[0].strip().lower()[:12] in lower
                for e in emails[:5] if isinstance(e, dict)
            ):
                # Soft: only if also claims empty/problem
                if any(x in lower for x in ("no email", "none found", "couldn't", "could not", "issue", "unable")):
                    return True
            if events and any(x in lower for x in ("no upcoming", "no events", "couldn't", "issue")):
                # If events list non-empty, claiming none is wrong
                if len(events) > 0:
                    return True
            if files and any(x in lower for x in ("issue retrieving", "couldn't", "could not", "error")):
                if len(files) > 0:
                    return True
        return False

    for t in successful:
        data = _payload_collections(t.get("result") or {})
        if any(
            data.get(k) is not None
            for k in (
                "conversations", "messages", "emails", "events", "files",
                "documents", "availability", "total_unread",
            )
        ):
            return True
        name = t.get("name") or ""
        if name.startswith("whatsapp_") or name.startswith("google_workspace_"):
            return True
    return False


def synthesize_answer_from_tools(user_query: str, tools_called: List[Dict[str, Any]]) -> Optional[str]:
    """Deterministic answer from successful tool payloads when the LLM hedges."""
    lines: List[str] = []
    q = (user_query or "").lower()

    for t in tools_called:
        result = t.get("result")
        if not isinstance(result, dict) or not result.get("success"):
            if isinstance(result, dict) and result.get("error"):
                lines.append(f"⚠️ {t.get('name')}: {result.get('error')}")
            continue
        name = t.get("name") or ""
        data = _payload_collections(result)

        if name == "whatsapp_inbox" or data.get("widget") in ("whatsapp_inbox", "whatsapp_thread", "whatsapp_search"):
            conversations = data.get("conversations") or []
            messages = data.get("messages")
            total_unread = data.get("total_unread")

            if messages is not None:
                contact = data.get("contact") or {}
                who = contact.get("name") or contact.get("phone_number") or "contact"
                lines.append(f"**Thread with {who}** ({len(messages)} messages):")
                for m in messages[-15:]:
                    direction = m.get("direction") or ("out" if m.get("is_agent") else "in")
                    body = (m.get("content") or "").strip()
                    if body:
                        lines.append(f"- [{direction}] {body[:300]}")
                url = data.get("inbox_url")
                if url:
                    lines.append(f"\nOpen in Inbox: {url}")
                continue

            if conversations:
                if total_unread is not None:
                    lines.append(f"You have **{total_unread} unread** message(s) across **{len(conversations)}** chat(s):")
                elif "unread" in q:
                    unread_only = [c for c in conversations if (c.get("unread_count") or 0) > 0]
                    lines.append(f"**{len(unread_only)} unread** WhatsApp conversation(s):")
                    conversations = unread_only or conversations
                else:
                    lines.append(f"**{len(conversations)}** WhatsApp conversation(s):")

                for c in conversations[:20]:
                    cname = c.get("name") or "Unknown"
                    phone = c.get("phone_number") or ""
                    unread = c.get("unread_count") or 0
                    preview = c.get("last_message_preview") or ""
                    bullet = f"- **{cname}** (`{phone}`) — {unread} unread"
                    if preview:
                        bullet += f' — "{preview[:120]}"'
                    url = c.get("inbox_url")
                    if url:
                        bullet += f" — [Open]({url})"
                    lines.append(bullet)
                continue

            if result.get("result"):
                lines.append(str(result["result"]))

        elif name == "whatsapp_account_info":
            d = data or {}
            lines.append(
                f"WhatsApp connection is **{'healthy' if d.get('healthy') else 'not healthy'}**.\n"
                f"- Phone number ID: `{d.get('phone_number_id') or 'n/a'}`\n"
                f"- Status: {d.get('status')}\n"
                f"- Has access token: {d.get('has_access_token')}"
            )
            if not d.get("healthy"):
                lines.append(f"Reconnect at {d.get('reconnect_url') or '/connections'}.")

        elif name == "google_workspace_gmail" or "emails" in data:
            emails = data.get("emails") or []
            if not emails:
                lines.append("Your Gmail query returned **0 messages**.")
            else:
                lines.append(f"**{len(emails)} Gmail message(s):**")
                for e in emails[:10]:
                    lines.append(
                        f"- **{e.get('subject') or '(no subject)'}** — from {e.get('from') or '?'} "
                        f"({e.get('date') or ''})\n  {(e.get('snippet') or '')[:180]}"
                    )

        elif name == "google_workspace_calendar" or "events" in data or "availability" in data:
            if "availability" in data and isinstance(data["availability"], dict):
                lines.append("**Availability:**")
                for email, info in data["availability"].items():
                    if isinstance(info, dict):
                        free = info.get("available")
                        lines.append(f"- {email}: **{'free' if free else 'busy'}**")
                        for b in (info.get("busy") or [])[:5]:
                            lines.append(f"  - busy {b.get('start')} → {b.get('end')}")
                    else:
                        lines.append(f"- {email}: {info}")
            events = data.get("events") or []
            if "events" in data or name.endswith("calendar"):
                if not events and "availability" not in data:
                    lines.append("No upcoming Google Calendar events in the requested range.")
                elif events:
                    lines.append(f"**Next {len(events)} calendar event(s):**")
                    for ev in events[:10]:
                        start = ev.get("start") or {}
                        when = start.get("dateTime") or start.get("date") or "?"
                        lines.append(f"- **{ev.get('summary') or '(no title)'}** — {when}")

        elif name == "google_workspace_drive" or "files" in data:
            files = data.get("files") or []
            if not files:
                lines.append("No Google Drive files matched.")
            else:
                lines.append(f"**{len(files)} Drive file(s):**")
                for f in files[:15]:
                    link = f.get("web_view_link") or f.get("webViewLink") or ""
                    lines.append(
                        f"- **{f.get('name') or '?'}** ({f.get('mime_type') or 'file'})"
                        + (f" — [Open]({link})" if link else "")
                    )

        elif name == "google_workspace_docs" or "documents" in data:
            docs = data.get("documents") or []
            if not docs:
                lines.append("No Google Docs matched that search.")
            else:
                lines.append(f"**{len(docs)} Google Doc(s):**")
                for d in docs[:10]:
                    lines.append(f"- **{d.get('title') or d.get('name') or '?'}**")

        elif result.get("result") and not lines:
            lines.append(str(result["result"]))

    if not lines:
        return None
    return "\n".join(lines)


def chunk_text_for_stream(text: str, chunk_size: int = 24) -> List[str]:
    """Split text into small deltas for SSE streaming UX."""
    if not text:
        return []
    chunks: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + chunk_size, n)
        if end < n:
            space = text.rfind(" ", i, end + 12)
            if space > i:
                end = space + 1
        chunks.append(text[i:end])
        i = end
    return chunks


def normalize_drive_search_query(query: Optional[str]) -> Optional[str]:
    """Turn plain text like 'Hub' into a valid Drive API q parameter."""
    if query is None:
        return None
    q = str(query).strip()
    if not q:
        return None
    # Already looks like Drive query syntax
    lower = q.lower()
    if any(tok in lower for tok in (" contains ", " in parents", "mimetype", "trashed", "name =", "fulltext")):
        if "trashed" not in lower:
            return f"({q}) and trashed = false"
        return q
    # Escape single quotes in name
    safe = q.replace("'", "\\'")
    return f"name contains '{safe}' and trashed = false"
