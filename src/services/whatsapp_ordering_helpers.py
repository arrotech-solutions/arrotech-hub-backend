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

# Common menu and catalog typos (Kenya / food / real estate)
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
    "aprtment": "apartment",
    "apartmant": "apartment",
    "bedster": "bedsitter",
    "bed sitta": "bedsitter",
    "bedsitta": "bedsitter",
    "maisonete": "maisonette",
    "kodi": "rent",
    "shamba": "plot",
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
        return "Your cart is empty. 🛒\nTap *Browse menu* to add items, or tell me what you'd like."
    lines = [f"🛒 *Your cart* ({len(cart)} item(s)):"]
    total = 0.0
    for i, item in enumerate(cart, 1):
        qty = float(item.get("quantity", 1))
        price = float(item.get("unit_price", 0) or item.get("price", 0))
        name = item.get("name", "Item")
        line_total = qty * price
        total += line_total
        lines.append(f"{i}. {name} × {qty:g} — {currency} {line_total:,.0f}")
    lines.append(f"\n*Total:* {currency} {total:,.0f}")
    lines.append(f"\n_{CART_BUTTONS_TEXT_MARKER} to checkout, add more, or clear your cart._")
    if len(cart) > 0:
        lines.append("_To remove one item, tap *Remove item* and pick from the list._")
    return "\n".join(lines)


def build_cart_remove_list_rows(
    cart: List[Dict[str, Any]],
    currency: str = "KES",
) -> List[Dict[str, str]]:
    """Rows for WhatsApp list message — remove one line item (max 10)."""
    rows = []
    for item in cart[:10]:
        item_id = sanitize_product_button_id(str(item.get("id") or item.get("name", "item")))
        name = (item.get("name") or "Item")[:24]
        qty = float(item.get("quantity", 1))
        price = float(item.get("unit_price", 0) or item.get("price", 0))
        line_total = qty * price
        desc = f"Qty {qty:g} · {currency} {line_total:,.0f}"[:72]
        rows.append({
            "id": f"cart_rm:{item_id}",
            "title": name,
            "description": desc,
        })
    return rows


_CART_CLEAR_PHRASES = (
    "clear cart",
    "clear my cart",
    "empty cart",
    "empty my cart",
    "delete cart",
    "remove all",
    "start over cart",
    "futa cart",
    "futa kikapu",
    "ondoa cart",
    "ondoa kikapu",
    "clear the cart",
)

_CART_VIEW_PHRASES = (
    "view cart",
    "view my cart",
    "my cart",
    "show cart",
    "show my cart",
    "what's in my cart",
    "whats in my cart",
    "cart summary",
    "see my cart",
    "onyesha cart",
    "kikapu changu",
)

_CART_CHECKOUT_PHRASES = (
    "checkout",
    "check out",
    "place order",
    "ready to order",
    "complete order",
    "finish order",
    "lipa",
    "order now",
)


def match_cart_command(message: str) -> Optional[str]:
    """
    Detect simple cart intents from customer text or menu button synthetic messages.
    Returns: 'clear' | 'view' | 'checkout' | 'reset' | None
    """
    if not message:
        return None
    normalized = message.strip().lower()
    if normalized in ("reset", "start over", "new conversation", "clear", "restart", "anza upya"):
        return "reset"
    if normalized in _CART_CLEAR_PHRASES or any(
        normalized == p or normalized.startswith(p + " ") for p in _CART_CLEAR_PHRASES
    ):
        return "clear"
    if normalized in _CART_VIEW_PHRASES or any(
        normalized == p or normalized.startswith(p) for p in _CART_VIEW_PHRASES
    ):
        return "view"
    if normalized in _CART_CHECKOUT_PHRASES or any(
        normalized == p or normalized.startswith(p) for p in _CART_CHECKOUT_PHRASES
    ):
        return "checkout"
    # "remove chicken" / "remove 1 chicken stew"
    if normalized.startswith("remove ") and "cart" not in normalized:
        return "remove"
    # "change chicken to 2" / "set chicken to 3" / "make it 2 chicken"
    if re.match(r"^(change|set|update)\s+.+\s+to\s+\d+", normalized):
        return "set_quantity"
    if re.match(r"^\d+\s+.+", normalized):  # "2 chicken stew"
        return "set_quantity"
    return None


def parse_remove_item_name(message: str) -> str:
    """Extract product name from 'remove X' messages."""
    m = message.strip()
    lower = m.lower()
    for prefix in ("remove ", "delete ", "cancel ", "ondoa "):
        if lower.startswith(prefix):
            return m[len(prefix):].strip()
    return m.strip()


def parse_set_quantity_message(message: str) -> Tuple[Optional[str], Optional[float]]:
    """
    Parse quantity updates from messages like:
    - 'change chicken stew to 2'
    - 'set pilau to 1'
    - '2 chicken stew'
    """
    m = message.strip()
    lower = m.lower()
    match = re.match(r"^(?:change|set|update)\s+(.+?)\s+to\s+(\d+(?:\.\d+)?)", lower, re.I)
    if match:
        return match.group(1).strip(), float(match.group(2))
    match = re.match(r"^(\d+(?:\.\d+)?)\s+(.+)$", lower)
    if match:
        return match.group(2).strip(), float(match.group(1))
    return None, None


def cart_cleared_message() -> str:
    return (
        "✅ Your cart is now empty.\n\n"
        "Tap *Browse menu* to add items, or tell me what you'd like. 🛒"
    )


def cart_item_removed_message(item_name: str) -> str:
    return f"✅ Removed *{item_name}* from your cart."


def cart_quantity_updated_message(item_name: str, quantity: float) -> str:
    if quantity <= 0:
        return cart_item_removed_message(item_name)
    qty_label = int(quantity) if quantity == int(quantity) else quantity
    return f"✅ Updated *{item_name}* to ×{qty_label} in your cart."


CART_BUTTONS_TEXT_MARKER = "Use the buttons below"


def message_requests_cart_buttons(message: str) -> bool:
    """True when agent cart summary expects follow-up interactive buttons."""
    return bool(message and CART_BUTTONS_TEXT_MARKER in message)


# ── Agent / human handoff reply buttons (WhatsApp max 3, title max 20 chars) ──

AGENT_BUTTON_TALK_TO_STAFF = "agent:human"
AGENT_BUTTON_ORDER_WITH_AI = "agent:ai"


def agent_mode_buttons(handoff_active: bool) -> List[Dict[str, str]]:
    """
    Reply buttons to switch between live staff and AI ordering assistant.

    handoff_active=True  → customer is with staff; offer return to AI.
    handoff_active=False → normal AI chat; offer escalation to staff.
    """
    if handoff_active:
        return [{"id": AGENT_BUTTON_ORDER_WITH_AI, "title": "Order with AI"}]
    return [
        {"id": "menu:browse", "title": "Browse menu"},
        {"id": AGENT_BUTTON_TALK_TO_STAFF, "title": "Talk to staff"},
        {"id": "menu:cart", "title": "My cart"},
    ]


def agent_mode_button_body(handoff_active: bool) -> str:
    if handoff_active:
        return "Tap below when you'd like to order with our AI assistant again."
    return "Quick options — tap below or just type your request."


def cart_action_buttons(cart_has_items: bool = True) -> List[Dict[str, str]]:
    """
    Cart screen actions (WhatsApp max 3 reply buttons).
    Mirrors a typical cart: checkout, keep shopping, or empty cart.
    """
    if cart_has_items:
        return [
            {"id": "menu:checkout", "title": "Checkout"},
            {"id": "menu:add_more", "title": "Add items"},
            {"id": "menu:clear_cart", "title": "Clear cart"},
        ]
    return [
        {"id": "menu:browse", "title": "Browse menu"},
        {"id": "menu:cart", "title": "View cart"},
    ]


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
