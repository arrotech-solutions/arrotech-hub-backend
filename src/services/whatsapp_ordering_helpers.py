"""
Shared helpers for WhatsApp ordering agent UX, security, and catalog search.
"""

import ast
import hashlib
import hmac
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

VALID_DELIVERY_METHODS = frozenset(
    {"pickup", "delivery", "dine_in", "shipping", "digital"}
)

FOOD_ORDER_TYPES = frozenset({"food", "restaurant", "restaurants"})


def is_food_business(order_type: str) -> bool:
    """True for restaurant / food verticals (dine-in + reservations apply)."""
    return (order_type or "").strip().lower() in FOOD_ORDER_TYPES


def coerce_delivery_methods(raw: Any, default: Optional[List[str]] = None) -> List[str]:
    """
    Normalize delivery_methods from workflow config.

    Jinja substitution often turns lists into strings like "['delivery', 'pickup']".
    Iterating that string character-by-character breaks checkout prompts.
    """
    fallback = list(default or ["delivery", "pickup"])
    if raw is None or raw == "":
        return fallback

    candidates: List[str] = []
    if isinstance(raw, list):
        candidates = [str(m).strip().lower() for m in raw if str(m).strip()]
    elif isinstance(raw, str):
        text = raw.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, list):
                    candidates = [str(m).strip().lower() for m in parsed if str(m).strip()]
            except (ValueError, SyntaxError):
                candidates = [
                    p.strip().lower().strip("'\"")
                    for p in text[1:-1].split(",")
                    if p.strip()
                ]
        elif "," in text:
            candidates = [p.strip().lower() for p in text.split(",") if p.strip()]
        else:
            candidates = [text.lower()]
    else:
        return fallback

    filtered = [m for m in candidates if m in VALID_DELIVERY_METHODS]
    return filtered or fallback


def apply_food_only_fulfillment(
    order_type: str,
    delivery_methods: List[str],
    reservations_enabled: bool,
) -> tuple[List[str], bool]:
    """Strip dine-in / reservations for non-food businesses (retail, health, general, etc.)."""
    if is_food_business(order_type):
        return delivery_methods, reservations_enabled
    methods = [m for m in delivery_methods if m != "dine_in"]
    if not methods:
        methods = ["delivery", "pickup"]
    return methods, False

# Internal marker the webhook uses when a customer taps the "Pay with Mpesa"
# interactive button. The agent detects this prefix and deterministically
# triggers an M-Pesa STK push (no reliance on the LLM choosing the tool).
PAY_MPESA_AGENT_PREFIX = "__PAY_MPESA__:"

# Customer tapped "Other number" — agent asks for M-Pesa line before STK push.
PAY_MPESA_OTHER_PREFIX = "__PAY_MPESA_OTHER__:"

# Internal marker for the "Pay with M-Pesa" button shown on the checkout
# confirmation screen. One tap confirms the order (creating it) AND triggers
# the STK push — so customers never have to type "YES" to proceed to payment.
CONFIRM_PAY_AGENT_MARKER = "__CONFIRM_PAY__"

# Manual payment fallback: customer taps "I've paid" after paying via
# Paybill/Till/Pochi/Send Money (no STK). The agent asks for / records the
# M-Pesa confirmation code and writes it to the merchant's Sheet/Airtable.
REPORTED_PAID_AGENT_PREFIX = "__REPORTED_PAID__:"

# Safaricom M-Pesa transaction codes look like 10-char alphanumerics (e.g. QGR7XXXX12).
MPESA_CODE_RE = re.compile(r"\b([A-Z0-9]{10})\b")


def extract_mpesa_code(message: str) -> Optional[str]:
    """Return an uppercase M-Pesa confirmation code if the text looks like one."""
    if not message:
        return None
    text = str(message).strip().upper()
    m = MPESA_CODE_RE.search(text)
    if not m:
        return None
    code = m.group(1)
    # Require at least one letter and one digit to avoid matching plain numbers/words.
    if not (any(c.isalpha() for c in code) and any(c.isdigit() for c in code)):
        return None
    return code

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

# Words that mean "I don't have / skip the table number" for dine-in
_TABLE_SKIP_WORDS = (
    "skip", "no", "none", "n/a", "na", "dont know", "don't know", "not sure",
    "no table", "later", "sina", "sijui", "hakuna", "bado",
)
# "table 12", "table no 12", "meza 5", or a bare number like "12"
_TABLE_NUMBER_RE = re.compile(
    r"(?:table|tbl|meza)\s*(?:no\.?|number|namba|#)?\s*[:\-]?\s*([A-Za-z]?\d{1,4}[A-Za-z]?)",
    re.IGNORECASE,
)
_BARE_TABLE_RE = re.compile(r"^\s*#?\s*([A-Za-z]?\d{1,4}[A-Za-z]?)\s*$")

# Phone: optional +, then 9+ digits possibly separated by spaces/dashes
_PHONE_RE = re.compile(r"(\+?\d[\d\s\-]{7,}\d)")
_LABELLED_PHONE_RE = re.compile(
    r"(?:phone|tel|telephone|mobile|cell|number|no|simu|nambari|namba)\s*[:\-]?\s*(\+?[\d\s\-]{7,})",
    re.IGNORECASE,
)
_LABELLED_NAME_RE = re.compile(r"name\s*[:\-]\s*([^\n\r]+)", re.IGNORECASE)
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


def _is_delivery_method_only(text: str) -> bool:
    """True when a line is only a delivery/pickup preference (not a person's name)."""
    compact = re.sub(r"[^a-z\s]", "", (text or "").lower()).strip()
    if not compact:
        return True
    if compact in (
        "pickup", "pick up", "delivery", "deliver", "delivered",
        "collect", "collection", "dine in", "dinein", "eat in",
        "letewa", "uletewe", "nitachukua", "kuchukua", "kula hapa",
    ):
        return True
    words = compact.split()
    if words and len(words) <= 3 and all(
        w in ("pick", "up", "pickup", "delivery", "deliver", "dine", "in", "collect", "collection")
        for w in words
    ):
        return True
    return False


def clean_checkout_customer_name(name: str) -> str:
    """
    Remove delivery/pickup lines or suffixes accidentally captured as the customer name.

    Examples:
        "Harun Gitundu\\nPickup" -> "Harun Gitundu"
        "Name: Harun Gitundu Pickup" -> "Harun Gitundu"
    """
    if not name:
        return ""

    text = (name or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    name_lines: List[str] = []
    for ln in text.split("\n"):
        s = ln.strip()
        if not s or _is_delivery_method_only(s):
            continue
        s = re.sub(r"^name\s*[:\-]\s*", "", s, flags=re.IGNORECASE).strip()
        if s and not _is_delivery_method_only(s):
            name_lines.append(s)

    if not name_lines:
        return ""

    cleaned = name_lines[0]
    lower = cleaned.lower()
    for phrases in (_PICKUP_WORDS, _DINE_WORDS, _DELIVERY_WORDS):
        for phrase in sorted(phrases, key=len, reverse=True):
            if lower.endswith(phrase):
                cleaned = cleaned[: -len(phrase)].strip(" ,;-:")
                lower = cleaned.lower()

    parts = cleaned.split()
    while parts and parts[-1].lower() in ("pickup", "delivery", "collect", "collection"):
        parts.pop()
    cleaned = " ".join(parts).strip()

    if not cleaned or _looks_like_phrase_not_name(cleaned):
        return ""
    return cleaned[:80]


def normalize_ke_mpesa_phone(raw: str) -> Optional[str]:
    """Normalize Kenyan mobile to 254XXXXXXXXX for M-Pesa STK."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw).strip())
    if not digits:
        return None
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in ("7", "1"):
        digits = "254" + digits
    elif digits.startswith("254") and len(digits) == 12:
        pass
    else:
        return None
    if len(digits) != 12 or not digits.startswith("254"):
        return None
    if digits[3] not in ("7", "1"):
        return None
    return digits


def extract_phone_from_text(text: str) -> Optional[str]:
    """Extract and normalize the first plausible KE mobile from free text."""
    if not text:
        return None
    stripped = text.strip()
    if stripped.lower() in ("cancel", "stop", "quit", "acha"):
        return None

    m_phone_is = _PHONE_IS_RE.search(stripped)
    if m_phone_is:
        normalized = normalize_ke_mpesa_phone(m_phone_is.group(1))
        if normalized:
            return normalized

    m_label = _LABELLED_PHONE_RE.search(stripped)
    if m_label:
        normalized = normalize_ke_mpesa_phone(m_label.group(1))
        if normalized:
            return normalized

    m_any = _PHONE_RE.search(stripped)
    if m_any:
        normalized = normalize_ke_mpesa_phone(m_any.group(1))
        if normalized:
            return normalized

    return normalize_ke_mpesa_phone(stripped)


def mask_mpesa_phone(phone: str) -> str:
    """Mask phone for customer-facing messages (254712***678)."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 6:
        return phone or ""
    return f"{digits[:5]}***{digits[-3:]}"


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
            cand = m_name.group(1).strip()
            cand = re.sub(r"\+?\d[\d\s\-]{6,}.*$", "", cand).strip(" ,;-")
            if cand and not _looks_like_phrase_not_name(cand):
                result["name"] = cand[:80]
        else:
            for line in text.splitlines():
                s = line.strip()
                if not s:
                    continue
                sl = s.lower()
                if _is_delivery_method_only(s):
                    continue
                if re.match(r"^name\s*[:\-]", sl):
                    s = re.sub(r"^name\s*[:\-]\s*", "", s, flags=re.IGNORECASE).strip()
                    sl = s.lower()
                    if not s or _is_delivery_method_only(s):
                        continue
                if re.search(r"\d", s):
                    continue
                if sl in ("name", "phone", "tel", "mobile"):
                    continue
                letters = re.sub(r"[^a-zA-Z\s']", "", s).strip()
                candidate = clean_checkout_customer_name(letters) or letters
                parts = candidate.split()
                if (
                    candidate
                    and 1 <= len(parts) <= 6
                    and len(candidate) >= 2
                    and not _looks_like_phrase_not_name(candidate)
                ):
                    result["name"] = candidate[:80]
                    break

    if result["name"]:
        result["name"] = clean_checkout_customer_name(result["name"])

    return result


def parse_table_number(message: str) -> str:
    """
    Extract a dine-in table number from a free-text reply.

    Returns the table number string (e.g. "12", "A3"), or "" when the customer
    skipped / doesn't have one. An empty string is a valid "no table" answer.
    """
    if not message:
        return ""
    text = message.strip()
    compact = re.sub(r"[^a-z\s]", "", text.lower()).strip()
    if compact in _TABLE_SKIP_WORDS:
        return ""

    m = _TABLE_NUMBER_RE.search(text)
    if m:
        return m.group(1).strip().upper()

    m2 = _BARE_TABLE_RE.match(text)
    if m2:
        return m2.group(1).strip().upper()

    return ""


# ── Reservation flow parsing (dine-in table bookings) ────────────────────

# Intent phrases that mean "I want to book a table". On a food business with
# reservations enabled, "book"/"booking" almost always means a table booking,
# so we match those verbs (incl. common typos) as well as explicit phrases.
_RESERVATION_INTENT_RE = re.compile(
    r"\b("
    r"reserv\w*"            # reserve, reserved, reservation(s), reserving
    r"|book\w*"             # book, booked, booking, bookings
    r"|bok|buk|buku\w*"     # common typos / Swahili "buku"
    r"|weka\s+meza|nafasi\s+ya\s+meza|kuweka\s+meza|hifadhi\s+meza"
    r")\b",
    re.IGNORECASE,
)

# Explicit "cancel my booking/reservation/table" — reservation-domain even when
# no booking is currently in progress (so it never routes to order cancellation).
_RESERVATION_CANCEL_EXPLICIT_RE = re.compile(
    r"\bcancel\b.*\b(reserv\w*|book(?:ing)?|bookings?|table|meza)\b",
    re.IGNORECASE,
)

_WORD_NUMBERS = {
    "one": 1, "two": 2, "couple": 2, "pair": 2,
    "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    # Swahili numerals
    "moja": 1, "mbili": 2, "tatu": 3, "nne": 4, "tano": 5, "sita": 6,
    "saba": 7, "nane": 8, "tisa": 9, "kumi": 10, "wawili": 2, "watu wawili": 2,
}

_PARTY_DIGIT_PATTERNS = (
    re.compile(r"(?:party|table|reservation|booking|group)\s+(?:of|for)\s+(\d{1,3})", re.IGNORECASE),
    re.compile(r"\bfor\s+(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"(\d{1,3})\s*(?:people|persons?|guests?|pax|adults?|diners?|of\s+us)", re.IGNORECASE),
)

_RESERVATION_CANCEL_RE = re.compile(
    r"^(cancel|stop|nevermind|never\s*mind|forget\s*it|no\s*thanks?|acha|"
    r"cancel\s+(?:reservation|booking))\b",
    re.IGNORECASE,
)


def detect_reservation_intent(message: str) -> bool:
    """True when the customer wants to book a table (not order food)."""
    if not message:
        return False
    # An explicit "cancel booking" is a reservation action, not a booking intent.
    if _RESERVATION_CANCEL_EXPLICIT_RE.search(message):
        return False
    return bool(_RESERVATION_INTENT_RE.search(message))


def is_reservation_cancel(message: str) -> bool:
    """True when the customer wants to abandon an in-progress reservation.

    Matches bare cancels ("cancel", "stop", "acha") used while the booking wizard
    is active, as well as explicit "cancel my booking/reservation/table" phrases.
    """
    if not message:
        return False
    if _RESERVATION_CANCEL_EXPLICIT_RE.search(message):
        return True
    return bool(_RESERVATION_CANCEL_RE.match(message.strip()))


def is_reservation_cancel_explicit(message: str) -> bool:
    """True only for explicit 'cancel booking/reservation/table' phrasing."""
    if not message:
        return False
    return bool(_RESERVATION_CANCEL_EXPLICIT_RE.search(message))


def parse_party_size(message: str, bare: bool = False) -> Optional[int]:
    """
    Extract a reservation party size (number of guests).

    When ``bare`` is True the caller has explicitly asked for the party size, so
    a lone number or number word ("2", "two") is accepted. Otherwise only
    explicit phrasings ("for two", "party of 4", "3 people") are matched so we
    never confuse a date/time number for a head count.
    """
    if not message:
        return None
    text = message.strip().lower()

    for pat in _PARTY_DIGIT_PATTERNS:
        m = pat.search(text)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 100:
                return n

    for word, val in _WORD_NUMBERS.items():
        w = re.escape(word)
        if (
            re.search(r"(?:party|table|group|reservation|booking)\s+(?:of|for)\s+" + w + r"\b", text)
            or re.search(r"\bfor\s+" + w + r"\b", text)
            or re.search(r"\b" + w + r"\s+(?:people|persons?|guests?|pax|of\s+us)\b", text)
        ):
            return val

    if bare:
        m = re.search(r"\b(\d{1,3})\b", text)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 100:
                return n
        for word, val in _WORD_NUMBERS.items():
            if re.search(r"\b" + re.escape(word) + r"\b", text):
                return val
    return None


def format_reservation_summary_line(
    *,
    customer_name: str,
    customer_phone: str,
    reservation_date: str,
    reservation_time: str,
    party_size: Any,
    business_name: str = "",
) -> str:
    """Human-readable reservation summary shown before the YES confirmation."""
    lines = ["🍽️ *Reservation summary:*"]
    if business_name:
        lines.append(f"🏬 {business_name}")
    lines.append(f"👤 Name: {customer_name}")
    if customer_phone:
        lines.append(f"📞 Phone: {customer_phone}")
    lines.append(f"📅 Date: {reservation_date}")
    lines.append(f"🕖 Time: {reservation_time}")
    lines.append(f"👥 Party size: {party_size}")
    lines.append("")
    lines.append(
        "Reply *YES* to send this booking request. "
        "We'll confirm once the restaurant approves it. 🙏"
    )
    return "\n".join(lines)


def format_checkout_confirmation(
    cart: List[Dict[str, Any]],
    currency: str,
    customer_name: str,
    customer_phone: str,
    delivery_method: str,
    delivery_address: str = "",
    lang: str = "en",
    table_number: str = "",
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
    if delivery_method == "delivery":
        method_icon = "🚚"
    elif delivery_method == "dine_in":
        method_icon = "🍽️"
    else:
        method_icon = "🏬"

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
        if delivery_method == "dine_in" and table_number:
            body += f"🪑 Meza: {table_number}\n"
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
    if delivery_method == "dine_in" and table_number:
        body += f"🪑 Table: {table_number}\n"
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


def sanitize_image_url_for_whatsapp(url: str) -> str:
    """
    Sanitize image URLs for WhatsApp Cloud API.
    WhatsApp interactive headers require direct links to images (JPEG/PNG).
    """
    if not url:
        return ""
    
    url = url.strip()
    
    # 1. Unsplash: Force JPEG format instead of WebP (which auto=format often returns)
    if "unsplash.com" in url:
        if "fm=jpg" not in url:
            if "?" in url:
                # Replace auto=format with fm=jpg
                if "auto=format" in url:
                    url = url.replace("auto=format", "fm=jpg")
                else:
                    url += "&fm=jpg"
            else:
                url += "?fm=jpg"
                
    # 2. Google Drive: Convert view/open links to direct download links
    elif "drive.google.com" in url:
        m = re.search(r'id=([a-zA-Z0-9_-]+)', url) or re.search(r'file/d/([a-zA-Z0-9_-]+)', url)
        if m:
            url = f"https://drive.google.com/uc?export=download&id={m.group(1)}"
            
    return url


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


def format_cart_summary(cart: List[Dict[str, Any]], currency: str = "KES", catalog_word: str = "catalog") -> str:
    if not cart:
        return f"Your cart is empty. 🛒\nTap *Browse {catalog_word}* to add items, or tell me what you'd like."
    lines = [f"🛒 *Your cart* ({len(cart)} item(s)):"]
    total = 0.0
    for i, item in enumerate(cart, 1):
        raw_qty = item.get("quantity", 1)
        try:
            if isinstance(raw_qty, str):
                import re
                cleaned = re.sub(r'[^\d.]', '', raw_qty)
                qty = float(cleaned) if cleaned else 1.0
            else:
                qty = float(raw_qty)
        except (ValueError, TypeError):
            qty = 1.0

        raw_price = item.get("unit_price", 0) or item.get("price", 0)
        try:
            if isinstance(raw_price, str):
                import re
                cleaned = re.sub(r'[^\d.]', '', raw_price)
                price = float(cleaned) if cleaned else 0.0
            else:
                price = float(raw_price)
        except (ValueError, TypeError):
            price = 0.0
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


def cart_cleared_message(catalog_word: str = "catalog") -> str:
    return (
        "✅ Your cart is now empty.\n\n"
        f"Tap *Browse {catalog_word}* to add items, or tell me what you'd like. 🛒"
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


def agent_mode_buttons(handoff_active: bool, catalog_word: str = "catalog") -> List[Dict[str, str]]:
    """
    Reply buttons to switch between live staff and AI ordering assistant.

    handoff_active=True  → customer is with staff; offer return to AI.
    handoff_active=False → normal AI chat; offer escalation to staff.
    """
    if handoff_active:
        return [{"id": AGENT_BUTTON_ORDER_WITH_AI, "title": "Order with AI"}]
    return [
        {"id": "menu:browse", "title": f"Browse {catalog_word}"},
        {"id": AGENT_BUTTON_TALK_TO_STAFF, "title": "Talk to us"},
        {"id": "menu:cart", "title": "View cart"},
        {"id": "menu:orders", "title": "My orders"},
        {"id": "menu:new_arrivals", "title": "New Arrivals"},
        {"id": "menu:offers", "title": "Special Offers"},
    ]


def agent_mode_button_body(handoff_active: bool) -> str:
    if handoff_active:
        return "Tap below when you'd like to order with our AI assistant again."
    return "Quick options — tap below or just type your request."


def cart_action_buttons(cart_has_items: bool = True, catalog_word: str = "catalog") -> List[Dict[str, str]]:
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
        {"id": "menu:browse", "title": f"Browse {catalog_word}"},
        {"id": "agent:human", "title": "Talk to us"},
        {"id": "menu:cart", "title": "View cart"},
        {"id": "menu:orders", "title": "My orders"},
        {"id": "menu:new_arrivals", "title": "New Arrivals"},
        {"id": "menu:offers", "title": "Special Offers"},
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
