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

# Strict checkout confirmation only (exclude bare ok/sure — too ambiguous)
_CONFIRM_WORDS = frozenset({
    "yes", "y", "yeah", "yep", "confirm", "confirmed",
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


# ── Checkout detail parsing (name / phone / delivery method) ──────────────

_DELIVERY_WORDS = ("delivery", "deliver", "delivered", "delivary", "delevery", "letewa", "uletewe")
_PICKUP_WORDS = (
    "pickup", "pick up", "pick-up", "collect", "collection",
    "self pickup", "self-pickup", "i'll pick", "ill pick", "nitachukua", "kuchukua",
)
_DINE_WORDS = ("dine in", "dine-in", "dinein", "eat in", "eat-in", "kula hapa")

# Phone: optional +, then 9+ digits possibly separated by spaces/dashes
_PHONE_RE = re.compile(r"(\+?\d[\d\s\-]{7,}\d)")
_LABELLED_PHONE_RE = re.compile(
    r"(?:phone|tel|telephone|mobile|cell|number|no|simu|nambari|namba)\s*[:\-]?\s*(\+?[\d\s\-]{7,})",
    re.IGNORECASE,
)
_LABELLED_NAME_RE = re.compile(r"name\s*[:\-]\s*(.+)", re.IGNORECASE)
_NAME_IS_RE = re.compile(
    r"(?:here\s+is\s+)?(?:my\s+)?name\s*(?:is|:|,)\s*"
    r"([A-Za-z][A-Za-z\s'\-]{1,60}?)"
    r"(?:\s+and|\s*,|\s+my\s+(?:phone|number|mobile)|$)",
    re.IGNORECASE,
)
_PHONE_IS_RE = re.compile(
    r"(?:my\s+)?(?:phone\s*(?:number)?|mobile|number|simu|nambari)\s*(?:is|:)\s*"
    r"(\+?[\d\s\-]{7,})",
    re.IGNORECASE,
)

# Must not be treated as a person's name when parsing checkout replies
_NOT_A_NAME_PHRASES = (
    "checkout", "check out", "place order", "proceed with", "would like to",
    "want to", "complete order", "finish order", "ready to", "order now",
    "browse", "menu", "cart", "help", "hello", "hi", "hey", "thanks",
    "thank you", "no you", "that's what", "assist you",
)

_CHECKOUT_INTENT_SUBSTRINGS = (
    "checkout", "check out", "place order", "place my order", "place the order",
    "complete order", "complete my order", "complete the order",
    "finish order", "finish my order",
    "proceed with order", "proceed with the order", "proceed with my order",
    "would like to checkout", "want to checkout", "ready to checkout",
    "ready to order", "order now", "make the order", "submit order",
    "confirm order", "pay now", "lipa", "go ahead with the order",
    "go ahead with order", "just checkout", "lets checkout", "let's checkout",
)


def _looks_like_phrase_not_name(text: str) -> bool:
    lower = (text or "").lower().strip()
    if not lower:
        return True
    return any(p in lower for p in _NOT_A_NAME_PHRASES)


def is_checkout_intent_message(message: str) -> bool:
    """True when the customer wants to checkout / place their order."""
    if not message:
        return False
    normalized = message.strip().lower()
    # Complaints / clarifications — not a fresh checkout request
    if normalized.startswith(("no,", "no ", "nope")):
        return False
    if any(s in normalized for s in (
        "you asked", "i already gave", "that's what", "i gave you",
        "already gave", "already provided", "that's what i",
    )):
        return False
    if normalized in _CART_CHECKOUT_PHRASES:
        return True
    return any(s in normalized for s in _CHECKOUT_INTENT_SUBSTRINGS)


def assistant_requested_checkout_details(assistant_message: str) -> bool:
    """True when the bot's last reply asked the customer for checkout details."""
    if not assistant_message:
        return False
    lower = assistant_message.lower()
    patterns = (
        "name and phone",
        "your name",
        "phone number",
        "confirm your name",
        "complete the order",
        "complete your order",
        "provide your name",
        "put on the order",
        "confirm your details",
        "need to confirm your details",
        "could you please confirm",
        "could you please provide",
        "name should i put",
        "before we proceed with the order",
        "to complete the order",
    )
    return any(p in lower for p in patterns)


def session_assistant_requested_checkout(session: Any) -> bool:
    """Check recent assistant turns for a checkout-details prompt."""
    if not session:
        return False
    assistant_msgs = [m for m in session.messages if m.get("role") == "assistant"]
    for msg in reversed(assistant_msgs[-3:]):
        if assistant_requested_checkout_details(msg.get("content") or ""):
            return True
    return False


def parse_checkout_details(message: str) -> Dict[str, Optional[str]]:
    """
    Extract checkout details from a free-text customer reply.

    Handles formats like:
        "Name: Harun\nPhone: 254711371265\nDelivery"
        "Harun Gachanja\n254711371265\npickup"
        "Here is my name, Harun and my phone number is 254 711 371 265"

    Returns {"name": str|None, "phone": str|None, "delivery_method": str|None}.
    delivery_method is one of: delivery | pickup | dine_in.
    """
    result: Dict[str, Optional[str]] = {"name": None, "phone": None, "delivery_method": None}
    if not message:
        return result

    text = message.strip()
    lower = text.lower()

    # ── Delivery method ──
    if any(w in lower for w in _PICKUP_WORDS):
        result["delivery_method"] = "pickup"
    elif any(w in lower for w in _DINE_WORDS):
        result["delivery_method"] = "dine_in"
    elif any(w in lower for w in _DELIVERY_WORDS):
        result["delivery_method"] = "delivery"

    # ── Phone ── "phone number is …", labelled, or first long digit run
    raw_phone = None
    m_phone_is = _PHONE_IS_RE.search(text)
    if m_phone_is:
        raw_phone = m_phone_is.group(1)
    else:
        m_label = _LABELLED_PHONE_RE.search(text)
        if m_label:
            raw_phone = m_label.group(1)
        else:
            m_any = _PHONE_RE.search(text)
            if m_any:
                raw_phone = m_any.group(1)
    if raw_phone:
        digits = re.sub(r"[^\d]", "", raw_phone)
        if len(digits) >= 9:
            result["phone"] = digits

    # ── Name ── "my name is …", labelled, else a clean alphabetic line
    m_name_is = _NAME_IS_RE.search(text)
    if m_name_is:
        cand = m_name_is.group(1).strip(" ,.-")
        if cand and not _looks_like_phrase_not_name(cand):
            result["name"] = cand[:80]
    else:
        m_name = _LABELLED_NAME_RE.search(text)
        if m_name:
            cand = m_name.group(1).splitlines()[0].strip()
            cand = re.sub(r"\+?\d[\d\s\-]{6,}.*$", "", cand).strip(" ,;-")
            if cand and not _looks_like_phrase_not_name(cand):
                result["name"] = cand[:80]
        else:
            for line in text.splitlines():
                s = line.strip()
                if not s:
                    continue
                sl = s.lower()
                if any(w in sl for w in _DELIVERY_WORDS + _PICKUP_WORDS + _DINE_WORDS):
                    continue
                if re.search(r"\d", s):
                    continue
                if sl in ("name", "phone", "tel", "mobile"):
                    continue
                letters = re.sub(r"[^a-zA-Z\s']", "", s).strip()
                parts = letters.split()
                if (
                    letters
                    and 1 <= len(parts) <= 6
                    and len(letters) >= 2
                    and not _looks_like_phrase_not_name(letters)
                ):
                    result["name"] = letters[:80]
                    break

    return result


def format_checkout_confirmation(
    cart: List[Dict[str, Any]],
    currency: str,
    customer_name: str,
    customer_phone: str,
    delivery_method: str,
    delivery_address: str = "",
    lang: str = "en",
) -> str:
    """Deterministic order summary asking the customer to reply YES to confirm."""
    total = 0.0
    lines = []
    for i, item in enumerate(cart, 1):
        qty = float(item.get("quantity", 1))
        price = float(item.get("unit_price", 0) or item.get("price", 0))
        name = item.get("name", "Item")
        line_total = qty * price
        total += line_total
        lines.append(f"{i}. {name} × {qty:g} — {currency} {line_total:,.0f}")
    items_block = "\n".join(lines)

    method_label = (delivery_method or "pickup").replace("_", " ").title()
    method_icon = "🚚" if delivery_method == "delivery" else "🏬"

    if lang == "sw":
        body = (
            f"🧾 *Muhtasari wa oda yako:*\n{items_block}\n\n"
            f"*Jumla:* {currency} {total:,.0f}\n\n"
            f"👤 Jina: {customer_name}\n"
            f"📞 Simu: {customer_phone}\n"
            f"{method_icon} {method_label}\n"
        )
        if delivery_method == "delivery" and delivery_address:
            body += f"📍 Anwani: {delivery_address}\n"
        body += "\nJibu *NDIO* kuthibitisha na kuweka oda, au *Cancel* kubadilisha."
        return body

    body = (
        f"🧾 *Your order summary:*\n{items_block}\n\n"
        f"*Total:* {currency} {total:,.0f}\n\n"
        f"👤 Name: {customer_name}\n"
        f"📞 Phone: {customer_phone}\n"
        f"{method_icon} {method_label}\n"
    )
    if delivery_method == "delivery" and delivery_address:
        body += f"📍 Address: {delivery_address}\n"
    body += "\nReply *YES* to confirm and place your order, or *Cancel* to make changes."
    return body


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
    "cart",
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
    if is_checkout_intent_message(message):
        return "checkout"
    # "remove chicken" / "remove 1 chicken stew"
    if normalized.startswith("remove ") and "cart" not in normalized:
        return "remove"
    # "change chicken to 2" / "set chicken to 3" / "make it 2 chicken"
    if re.match(r"^(change|set|update)\s+.+\s+to\s+\d+", normalized):
        return "set_quantity"
    # NOTE: Removed bare `^\d+\s+.+` regex that matched "4 mutton biryani"
    # as set_quantity.  That pattern is too greedy — it hijacks new-item
    # requests (e.g. "4 mutton biryani and 4 red bulls") and fails on an
    # empty cart.  Let these flow to the LLM which can search the catalog
    # and add items via manage_cart(action="add").
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
