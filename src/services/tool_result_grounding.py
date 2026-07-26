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
]


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
        if tool_result.get("data"):
            parts.append("Partial data: " + json.dumps(tool_result["data"], default=str)[:2000])
        return "\n".join(parts)

    parts.append(f"TOOL SUCCEEDED ({tool_name}). Use this data to answer the user. Do NOT say you lack access.")

    result_text = tool_result.get("result") or tool_result.get("message")
    if result_text and not isinstance(result_text, (dict, list)):
        parts.append(str(result_text))

    data = tool_result.get("data")
    if isinstance(data, dict):
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

        # Generic key dump for other successful tools (gmail, calendar, etc.)
        if not conversations and not messages:
            compact = {k: v for k, v in data.items() if k != "widget"}
            if compact:
                parts.append("Data: " + json.dumps(compact, default=str)[:3500])

    # Keep a compact JSON trailer for structured needs
    trailer = {
        "success": True,
        "tool": tool_name,
        "result": result_text if not isinstance(result_text, (dict, list)) else None,
        "data": data,
    }
    parts.append("JSON: " + json.dumps(trailer, default=str)[:4000])
    return "\n".join(parts)


def looks_ungrounded(answer: str, tools_called: List[Dict[str, Any]]) -> bool:
    """True when the model refused / hedged despite successful tool data."""
    if not tools_called:
        return False
    successful = [
        t for t in tools_called
        if isinstance(t.get("result"), dict) and t["result"].get("success") and not t["result"].get("pending_confirmation")
    ]
    if not successful:
        return False

    text = (answer or "").strip()
    if len(text) < 8:
        return True

    lower = text.lower()
    if any(re.search(p, lower) for p in REFUSAL_PATTERNS):
        # Refusal is only "ungrounded" if we actually returned usable data
        for t in successful:
            data = (t.get("result") or {}).get("data") or {}
            if data.get("conversations") or data.get("messages") or data.get("total_unread") is not None:
                return True
            if (t.get("result") or {}).get("result"):
                # Generic success with a result string — still ungrounded if refusal
                if t.get("name", "").startswith("whatsapp_") or t.get("name", "").startswith("google_workspace_"):
                    return True
    return False


def synthesize_answer_from_tools(user_query: str, tools_called: List[Dict[str, Any]]) -> Optional[str]:
    """Deterministic answer from successful tool payloads when the LLM hedges."""
    lines: List[str] = []
    q = (user_query or "").lower()

    for t in tools_called:
        result = t.get("result")
        if not isinstance(result, dict) or not result.get("success"):
            continue
        name = t.get("name") or ""
        data = result.get("data") or {}

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

            # Fall back to result string
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
        # Prefer breaking on whitespace near chunk_size
        end = min(i + chunk_size, n)
        if end < n:
            space = text.rfind(" ", i, end + 12)
            if space > i:
                end = space + 1
        chunks.append(text[i:end])
        i = end
    return chunks
