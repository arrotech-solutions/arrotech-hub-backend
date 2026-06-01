"""
Shared helpers for WhatsApp ordering agent UX, security, and catalog search.
"""

import hashlib
import hmac
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Reuse harness injection patterns for inbound user messages
try:
    from .harness.guardrails import INJECTION_PATTERNS
except ImportError:
    INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"disregard\s+(all\s+)?prior",
        r"you\s+are\s+now\s+(?:a|an|the)",
        r"system\s*:\s*",
        r"<\s*/?system\s*>",
        r"(?:admin|root|sudo)\s+override",
        r"IMPORTANT:\s*ignore",
        r"\[\[SYSTEM\]\]",
    ]

_CONFIRM_WORDS = frozenset({
    "yes", "y", "yeah", "yep", "confirm", "confirmed", "ok", "okay", "sure",
    "proceed", "go ahead", "place order", "place the order", "ndio", "sawa",
    "ndiyo", "haya", "sawa sawa",
})

# Common menu typos (Kenya / food ordering)
_TYPO_MAP = {
    "chiken": "chicken",
    "chikcen": "chicken",
    "beef stew": "beef stew",
    "pilau": "pilau",
    "chapati": "chapati",
    "ugali": "ugali",
    "nyama": "nyama",
    "delevery": "delivery",
    "deliver": "delivery",
    "picup": "pickup",
    "pick up": "pickup",
}


def verify_whatsapp_signature(raw_body: bytes, signature_header: str, app_secret: str) -> bool:
    """Verify Meta X-Hub-Signature-256 header."""
    if not app_secret or not signature_header:
        return False
    expected = hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature_header.strip())


def check_user_message_injection(message: str) -> bool:
    """Return True if message looks like a prompt-injection attempt."""
    if not message:
        return False
    lower = message.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, lower, re.IGNORECASE):
            return True
    return False


def injection_safe_reply(business_name: str) -> str:
    return (
        f"Hi! I'm the ordering assistant for {business_name}. "
        "I can help you browse the menu, place an order, or check your orders. "
        "What would you like today?"
    )


def is_order_confirmation_message(message: str) -> bool:
    if not message:
        return False
    normalized = re.sub(r"[^\w\s]", "", message.strip().lower())
    if normalized in _CONFIRM_WORDS:
        return True
    for word in _CONFIRM_WORDS:
        if normalized == word or normalized.startswith(word + " "):
            return True
    if "confirm" in normalized and len(normalized) < 40:
        return True
    return False


def normalize_search_query(query: str) -> str:
    """Lightweight typo normalization before RAG search."""
    if not query:
        return query
    q = query.strip()
    lower = q.lower()
    for typo, fix in _TYPO_MAP.items():
        if typo in lower:
            lower = lower.replace(typo, fix)
    return lower if lower != q.lower() else q


def expand_search_query_with_llm_hint(original: str, normalized: str) -> str:
    """Return the best query to use for catalog search."""
    return normalized if normalized != original else original


def sanitize_product_button_id(product_id: str) -> str:
    """Meta button id max 256 chars; keep alphanumeric + underscore."""
    pid = str(product_id or "item").strip()
    pid = re.sub(r"[^\w\-]", "_", pid)[:200]
    return pid or "item"


def parse_product_button_id(btn_id: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse cart/details button ids.
    New: cart:{product_id} or details:{product_id}
    Legacy: cart:{name}:{price}
    """
    if not btn_id:
        return None, None
    if btn_id.startswith("cart:"):
        rest = btn_id[5:]
        action = "cart"
    elif btn_id.startswith("details:"):
        rest = btn_id[8:]
        action = "details"
    else:
        return None, None

    # Legacy: contains second colon with numeric price tail
    parts = rest.split(":")
    if len(parts) >= 2 and parts[-1].replace(".", "", 1).isdigit():
        return action, None  # legacy name:price — caller uses cache by name
    return action, rest


def format_cart_summary(cart: List[Dict[str, Any]], currency: str = "KES") -> str:
    if not cart:
        return "Your cart is empty."
    lines = [f"🛒 *Your cart* ({len(cart)} item(s)):"]
    total = 0.0
    for item in cart:
        qty = float(item.get("quantity", 1))
        price = float(item.get("unit_price", 0) or item.get("price", 0))
        name = item.get("name", "Item")
        line_total = qty * price
        total += line_total
        lines.append(f"• {name} × {qty:g} — {currency} {line_total:,.0f}")
    lines.append(f"\n*Total:* {currency} {total:,.0f}")
    return "\n".join(lines)


def check_whatsapp_rate_limit(
    redis_client,
    owner_user_id: str,
    sender_phone: str,
    limit: int = 15,
    window_seconds: int = 60,
) -> Tuple[bool, int]:
    """
    Returns (is_allowed, current_count).
    If redis unavailable, allow.
    """
    if not redis_client:
        return True, 0
    key = f"wa:rate:{owner_user_id}:{sender_phone}"
    try:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, window_seconds)
        return count <= limit, int(count)
    except Exception as e:
        logger.warning(f"[WA_RATE] Redis error: {e}")
        return True, 0


def rate_limit_message(business_phone: str = "") -> str:
    phone_hint = f" Call {business_phone}." if business_phone else ""
    return (
        "You're sending messages very quickly 🙂 "
        f"I'll be ready to help in a moment.{phone_hint}"
    )
