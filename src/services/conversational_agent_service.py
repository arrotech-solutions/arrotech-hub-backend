"""
Conversational Agent Service — Agentic AI with inner tool-calling.

This service powers dynamic, multi-business WhatsApp/Telegram ordering agents.
Instead of requiring 5+ manually-wired workflow steps, this single tool wraps
the AI + sub-tools (RAG search, order creation, customer capture, notifications)
into an inner tool-calling loop.

Each incoming message triggers one execution. The AI uses CCM conversation
history for multi-turn context, and decides which sub-tools to call based
on the customer's intent.

Design decisions:
- Option B: Single-turn per message, CCM provides multi-turn memory
- Option X: Business config comes from workflow variables (no new DB model)
- Stateless orders: OrderService returns structured JSON, no DB persistence
- Notifications: Both WhatsApp message + email to business owner
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from .llm_service import LLMService, LLMResponse
from .order_service import OrderService
from .conversation_context_manager import context_manager
from .cache_service import cache_service
from .agent_intelligence_service import agent_intelligence, LANGUAGE_PROFILES, DEFAULT_LANGUAGE
from ..config import settings

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# IMAGE URL EXTRACTION UTILITIES
# ═══════════════════════════════════════════════════════════════

# 1) Markdown image syntax: ![alt text](url)
_MARKDOWN_IMAGE_PATTERN = re.compile(
    r'!\[([^\]]*)\]\((https?://[^\s\)]+)\)',
    re.IGNORECASE
)

# 2) URLs ending in common image extensions
_IMAGE_EXT_PATTERN = re.compile(
    r'https?://\S+\.(?:jpg|jpeg|png|webp|gif|bmp|svg|tiff)'
    r'(?:\?\S*)?',
    re.IGNORECASE
)

# 3) Known image hosting domains (URLs that serve images without extensions)
_IMAGE_HOST_DOMAINS = [
    'images.unsplash.com',
    'unsplash.com/photos',
    'i.imgur.com',
    'imgur.com',
    'res.cloudinary.com',
    'cloudinary.com',
    'lh3.googleusercontent.com',
    'drive.google.com/uc',
    'pbs.twimg.com',
    'scontent.cdninstagram.com',
    'img.freepik.com',
    'media.istockphoto.com',
    'cdn.pixabay.com',
    'images.pexels.com',
    'storage.googleapis.com',
    'firebasestorage.googleapis.com',
    's3.amazonaws.com',
    'maps.googleapis.com',
]

# Build a regex that matches URLs from known image hosts
_IMAGE_HOST_PATTERN = re.compile(
    r'https?://(?:' +
    '|'.join(re.escape(d) for d in _IMAGE_HOST_DOMAINS) +
    r')[^\s\)\]]*',
    re.IGNORECASE
)


def extract_image_urls(text: str) -> List[str]:
    """
    Extract image URLs from text, returning unique URLs in order.

    Handles three source patterns:
    1. Markdown image syntax: ![Men's Shirt](https://images.unsplash.com/photo-xxx)
    2. URLs with image file extensions: https://cdn.store.com/shirt.jpg
    3. URLs from known image hosting domains (no extension needed)
    """
    if not text:
        return []

    seen = set()
    urls = []

    def _add(url: str):
        # Clean trailing punctuation that may stick to URLs
        url = url.rstrip('.,;:!?)"\'>]')
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    # Priority 1: Markdown images — most reliable signal
    for match in _MARKDOWN_IMAGE_PATTERN.finditer(text):
        _add(match.group(2))

    # Priority 2: URLs with image file extensions
    for match in _IMAGE_EXT_PATTERN.finditer(text):
        _add(match.group(0))

    # Priority 3: Known image host domains
    for match in _IMAGE_HOST_PATTERN.finditer(text):
        _add(match.group(0))

    return urls


def extract_markdown_image_map(text: str) -> Dict[str, str]:
    """
    Build a map of normalized image alt-text → URL from markdown images.

    Product catalogs are rendered as ``![Product Name](https://image)`` where the
    alt-text is the product name. Matching a product to the image whose alt-text
    equals its name is the most reliable product↔image binding — far better than
    guessing by position inside a blob chunk.
    """
    out: Dict[str, str] = {}
    if not text:
        return out
    for m in _MARKDOWN_IMAGE_PATTERN.finditer(text):
        alt = (m.group(1) or "").strip()
        url = (m.group(2) or "").strip().rstrip('.,;:!?)"\'>]')
        if alt and url:
            key = re.sub(r"\s+", " ", alt.lower())
            out.setdefault(key, url)
    return out


def strip_image_urls(text: str, image_urls: List[str]) -> str:
    """
    Remove image URLs and Markdown image tags from text.
    Cleans up leftover blank lines and orphaned bullet points.
    """
    if not image_urls:
        return text

    # Safety guard: image_urls MUST be a list of strings.  If Jinja2
    # stringified a Python list, iterating over the resulting string
    # would iterate character-by-character and destroy the message text.
    if not isinstance(image_urls, list):
        logger.warning(
            "[strip_image_urls] image_urls is %s, not list — skipping strip "
            "to prevent garbled text. Value: %s",
            type(image_urls).__name__,
            str(image_urls)[:120],
        )
        return text

    # First: strip full Markdown image syntax ![alt](url)
    text = _MARKDOWN_IMAGE_PATTERN.sub('', text)

    # Then: strip any remaining bare image URLs
    for url in image_urls:
        if not isinstance(url, str) or len(url) < 10:
            continue  # skip non-URL items
        text = text.replace(url, '')

    # Clean up orphaned list markers (e.g. "- " on a now-empty line)
    text = re.sub(r'^[\s]*[-*•]\s*$', '', text, flags=re.MULTILINE)

    # Collapse multiple blank lines into at most two
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def _dedupe_keep_order(values: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out

def _col_idx_to_a1(idx0: int) -> str:
    """0-based column index → A1 column letters."""
    if idx0 < 0:
        return "A"
    n = idx0 + 1
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters

def _normalize_header(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v)

def _phones_match(p1: str, p2: str) -> bool:
    """Robustly compare phone numbers by checking the last 9 digits."""
    if not p1 or not p2:
        return False
    n1 = re.sub(r"\D", "", str(p1))
    n2 = re.sub(r"\D", "", str(p2))
    if not n1 or not n2:
        return False
    length = min(9, len(n1), len(n2))
    return n1[-length:] == n2[-length:]



# ═══════════════════════════════════════════════════════════════
# SUB-TOOL DEFINITIONS (OpenAI function-calling format)
# ═══════════════════════════════════════════════════════════════

AGENT_SUB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": (
                "Search the business knowledge base for products, menu items, "
                "services, or any catalog information. Use this whenever the "
                "customer asks about what's available, prices, categories, or "
                "specific items."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query for the knowledge base"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_order",
            "description": (
                "Create a new order after collecting all required details from "
                "the customer. Only call this when you have: customer name, phone, "
                "at least one item with quantity, and delivery method."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string", "description": "Customer's full name"},
                    "customer_phone": {"type": "string", "description": "Customer's phone number"},
                    "customer_email": {"type": "string", "description": "Customer's email (optional)"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "quantity": {"type": "number"},
                                "unit": {"type": "string", "description": "e.g. kg, pcs, plates"},
                                "unit_price": {"type": "number"},
                                "notes": {"type": "string"}
                            },
                            "required": ["name", "quantity"]
                        },
                        "description": "List of items being ordered"
                    },
                    "delivery_method": {
                        "type": "string",
                        "enum": ["delivery", "pickup", "dine_in"],
                        "description": "How the customer wants to receive the order"
                    },
                    "delivery_address": {"type": "string", "description": "Delivery address if delivery"},
                    "notes": {"type": "string", "description": "Special instructions or notes"}
                },
                "required": ["customer_name", "customer_phone", "items", "delivery_method"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "initiate_mpesa_payment",
            "description": (
                "Initiate an M-Pesa STK push so the customer can pay for their order. "
                "Only call this AFTER an order has been created (you must have an order_id and amount). "
                "Use the customer's phone number for the STK prompt. "
                "If the customer hasn't confirmed they want to pay now, ask first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "Order ID to use as AccountReference"},
                    "phone_number": {"type": "string", "description": "Customer phone number to prompt via STK"},
                    "amount": {"type": "number", "description": "Amount in KES to charge (usually order subtotal)"},
                    "description": {"type": "string", "description": "Payment description shown on STK prompt"}
                },
                "required": ["order_id", "phone_number", "amount"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_total",
            "description": (
                "Calculate the total cost for a list of items before confirming "
                "the order. Use this to show the customer a summary with prices."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "quantity": {"type": "number"},
                                "unit_price": {"type": "number"}
                            },
                            "required": ["name", "quantity", "unit_price"]
                        }
                    }
                },
                "required": ["items"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_order",
            "description": (
                "Validate order details before asking the customer to confirm. "
                "Call this after collecting items and customer info, and BEFORE create_order. "
                "Then show a clear summary and ask the customer to reply YES to confirm."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string"},
                    "customer_phone": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "quantity": {"type": "number"},
                                "unit_price": {"type": "number"}
                            },
                            "required": ["name", "quantity"]
                        }
                    },
                    "delivery_method": {"type": "string"},
                    "delivery_address": {"type": "string"}
                },
                "required": ["customer_name", "customer_phone", "items"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_cart",
            "description": (
                "Add items to, view, or update the customer's persisted shopping cart. "
                "Actions: 'add' (add a new item — ALWAYS search_products first to get the correct price), "
                "'view' (show cart), 'clear' (empty cart), 'remove' (drop one item), "
                "'set_quantity' (change qty; use quantity 0 to remove). "
                "For add: provide product_name, unit_price (from catalog), and quantity. "
                "For remove/set_quantity: provide product_name (or product_id from catalog)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "view", "clear", "remove", "set_quantity"],
                        "description": "Cart operation to perform"
                    },
                    "product_id": {
                        "type": "string",
                        "description": "Catalog product id (optional if product_name given)"
                    },
                    "product_name": {
                        "type": "string",
                        "description": "Product name to match in cart (partial match OK)"
                    },
                    "quantity": {
                        "type": "number",
                        "description": "Quantity to add, or new quantity for set_quantity (0 = remove item)"
                    },
                    "unit_price": {
                        "type": "number",
                        "description": "Unit price from the catalog (required for 'add' action)"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_order",
            "description": (
                "Cancel an existing order. ONLY call this tool if you already have the EXACT order_id "
                "from a button click or explicitly provided by the user. "
                "If the customer just says 'cancel my order' without specifying which order, "
                "you MUST call `get_user_orders` first so they can see their orders and pick one to cancel. "
                "Do NOT guess the order ID. Do NOT call this tool just to check if they have orders. "
                "NEVER ask the customer for their phone number — it is taken automatically and securely "
                "from the WhatsApp number they are messaging from."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "The ID of the order to cancel (may come from button click)"},
                    "reason": {"type": "string", "description": "Reason for cancellation provided by customer"}
                },
                "required": ["order_id", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_orders",
            "description": (
                "Search and retrieve the customer's order history and details. Use this when a customer asks to see their past orders, "
                "check an order status, track an order, or wants to cancel an order but hasn't provided the exact order ID yet. "
                "NEVER ask the customer for their phone number — orders are looked up automatically and securely using the "
                "WhatsApp number they are messaging from. Asking for or accepting a typed phone number is forbidden, because it "
                "would expose another person's orders. Just call this tool with no arguments. "
                "IMPORTANT: After getting results, ALWAYS call `display_order_cards` to show orders as interactive cards with action buttons. "
                "Never list orders as plain text."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "display_product_cards",
            "description": (
                "REQUIRED: Send products to the customer as interactive WhatsApp/Telegram cards. "
                "Each card shows the product image, name, price, description, and 'Add to Cart' / 'View Details' buttons. "
                "You MUST call this tool whenever you have products to show. "
                "NEVER list products as numbered text — always send them as cards. "
                "After this tool succeeds, respond with a brief message like 'Here are our options! Tap to add to cart.' "
                "Do NOT repeat product details in your text response."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "products": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "Unique product identifier from the catalog"},
                                "name": {"type": "string", "description": "Product name exactly as shown in catalog"},
                                "price": {"type": "number", "description": "Product price as a number (no currency symbol)"},
                                "description": {"type": "string", "description": "Short product description (1-2 sentences)"},
                                "image_url": {"type": "string", "description": "Full image URL from the catalog. Pass empty string if no image."}
                            },
                            "required": ["id", "name", "price", "description", "image_url"]
                        }
                    }
                },
                "required": ["products"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "display_order_cards",
            "description": (
                "REQUIRED: Send order history to the customer as interactive cards with action buttons. "
                "Each card shows the order ID, status, date, total, items, and contextual buttons like 'Cancel Order' and 'Order Details'. "
                "You MUST call this tool after `get_user_orders` returns results. "
                "NEVER list orders as plain text — always send them as interactive cards so the customer can take actions directly. "
                "After this tool succeeds, respond with a brief message like 'Here are your orders! Tap any button to take action.' "
                "CRITICAL: Do NOT repeat the order details or list the orders in your text response."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "orders": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "order_id": {"type": "string", "description": "The order ID (e.g. ORD-20260601-A1B2C3)"},
                                "status": {"type": "string", "description": "Current order status (e.g. pending, confirmed, delivered)"},
                                "date": {"type": "string", "description": "Order creation date"},
                                "total": {"type": "string", "description": "Order total with currency (e.g. 1,500 KES)"},
                                "items": {"type": "string", "description": "Brief summary of items ordered"}
                            },
                            "required": ["order_id", "status", "total", "items"]
                        }
                    }
                },
                "required": ["orders"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": (
                "Transfer the conversation to a live human agent. Use when: the customer explicitly "
                "asks for a person/manager; you cannot resolve their issue after trying; the request is "
                "too complex (bulk orders, special contracts, complaints); or the customer is clearly "
                "frustrated or upset. After calling this, reassure the customer briefly — do not continue "
                "trying to solve the issue yourself."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": (
                            "Why escalation is needed: customer_requested, frustrated, "
                            "complex_request, cannot_help, complaint"
                        ),
                    },
                    "summary": {
                        "type": "string",
                        "description": "One-sentence summary of the issue for the human agent",
                    },
                },
                "required": ["reason", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_options_menu",
            "description": (
                "Show the main options menu (Browse, Talk to Us, View Cart, Orders, Offers) to the customer. "
                "Call this ONLY when: "
                "1. The customer explicitly asks for 'menu', 'help', 'options', or 'home'. "
                "2. You have reached a dead end (e.g. cart cleared, order completed, nothing left to do). "
                "3. You are confused or cannot understand the customer's request. "
                "DO NOT call this automatically after every message."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


class ConversationalAgentService:
    """
    Agentic AI that can call sub-tools within a single workflow step.

    Integrates Harness Engineering via HarnessedExecutionMixin for:
    - Pre-execution guardrails on every tool call
    - Automated error feedback loops with corrective instructions
    - Post-execution quality gates with safety-critical blocking
    - Living agent context injected into system prompts

    Sub-tools available to the AI:
    - search_products(query) → RAG search against business KB
    - create_order(...) → OrderService.create_order
    - calculate_total(items) → OrderService.calculate_order_total
    - initiate_mpesa_payment(...) → M-Pesa STK push
    - display_product_cards(products) → WhatsApp interactive cards
    """

    def __init__(self):
        self.llm_service = LLMService()
        self.order_service = OrderService()
        # Initialize harness components
        self._init_harness_components()

    def _init_harness_components(self):
        """Initialize harness engineering components."""
        try:
            from .harness.mixin import HarnessedExecutionMixin
            # Dynamically bind mixin methods to this instance
            mixin = HarnessedExecutionMixin()
            mixin._init_harness("conversational_agent")
            self._harness_guardrails = mixin._harness_guardrails
            self._harness_feedback = mixin._harness_feedback
            self._harness_quality = mixin._harness_quality
            self._harness_context = mixin._harness_context
            self._harness_agent_type = mixin._harness_agent_type
            self._harness_turn_start = 0.0
            self._harness_tools_used = []
            # Bind methods
            self._harness_validate_tool_call = mixin._harness_validate_tool_call.__func__.__get__(self)
            self._harness_handle_tool_error = mixin._harness_handle_tool_error.__func__.__get__(self)
            self._harness_handle_guardrail_failure = mixin._harness_handle_guardrail_failure.__func__.__get__(self)
            self._harness_evaluate_response = mixin._harness_evaluate_response.__func__.__get__(self)
            self._harness_build_context = mixin._harness_build_context.__func__.__get__(self)
            self._harness_track_tool_call = mixin._harness_track_tool_call.__func__.__get__(self)
            self._harness_should_block_response = mixin._harness_should_block_response.__func__.__get__(self)
            self._harness_get_safe_fallback = mixin._harness_get_safe_fallback.__func__.__get__(self)
            self._harness_reset_turn = mixin._harness_reset_turn.__func__.__get__(self)
            self._harness_log_event = mixin._harness_log_event.__func__.__get__(self)
            self._harness_enabled = True
            logger.info("[CONV_AGENT] Harness Engineering initialized")
        except Exception as e:
            logger.warning(f"[CONV_AGENT] Harness init failed (running without): {e}")
            self._harness_enabled = False

    async def execute(
        self,
        user_message: str,
        session_key: str,
        business_config: Dict[str, Any],
        user: User,
        db: AsyncSession,
        background_tasks: Optional['BackgroundTasks'] = None
    ) -> Dict[str, Any]:
        """
        Run the conversational agent for one turn.

        Args:
            user_message: The incoming customer message
            session_key: CCM session key for conversation history
            business_config: Business-specific settings from workflow variables
            user: The business owner's User record
            db: Database session

        Returns:
            {
                "response_text": str,       # Message to send back to customer
                "order_created": bool,      # Whether an order was created
                "order_data": dict|None,    # Full order data if created
                "order_notification": str,  # Formatted notification for business
                "actions_taken": list       # Log of sub-tool calls made
            }
        """
        try:
            # Extract business config
            kb_id = business_config.get("kb_id", "")
            business_name = business_config.get("business_name", "Our Business")
            business_phone = business_config.get("business_phone", "")
            business_email = business_config.get("business_email", "")
            order_type = business_config.get("order_type", "general")
            currency = business_config.get("currency", "KES")
            delivery_methods = business_config.get("delivery_methods", ["delivery", "pickup"])
            custom_system_prompt = business_config.get("system_prompt", "")

            if order_type == "food":
                catalog_word = "menu"
            elif order_type in ("clothing", "apparel"):
                catalog_word = "collection"
            elif order_type == "real_estate":
                catalog_word = "properties"
            elif order_type == "services":
                catalog_word = "services"
            else:
                catalog_word = "catalog"
            reset_intro = "what would you like today?"
            if order_type in ("retail", "clothing"):
                reset_intro = "what are you looking for today?"
            elif order_type != "food":
                reset_intro = "how can we help you today?"

            if session_key:
                try:
                    await context_manager.update_session_metadata(
                        session_key, {"catalog_word": catalog_word}
                    )
                except Exception:
                    pass
            customer_phone = business_config.get("customer_phone", "")
            customer_name = business_config.get("customer_name", "")
            business_phone = business_config.get("business_phone", "")

            # The WhatsApp sender's phone is always encoded in the session key
            # (ccm:{platform}:{owner_user_id}:{sender}). Treat it as the
            # authoritative, trusted number so order/payment tools always have
            # the correct phone even when business_config doesn't carry it.
            if session_key and session_key.startswith("ccm:"):
                _sk_parts = session_key.split(":")
                if len(_sk_parts) >= 4 and _sk_parts[3].strip():
                    customer_phone = _sk_parts[3].strip()

            from .whatsapp_ordering_helpers import (
                check_user_message_injection,
                injection_safe_reply,
                is_order_confirmation_message,
                match_cart_command,
                format_cart_summary,
                format_checkout_confirmation,
                parse_checkout_details,
                session_assistant_requested_checkout,
                cart_cleared_message,
                cart_item_removed_message,
                cart_quantity_updated_message,
                parse_remove_item_name,
                parse_set_quantity_message,
                PAY_MPESA_AGENT_PREFIX,
                CONFIRM_PAY_AGENT_MARKER,
            )

            from .whatsapp_location_service import (
                LOCATION_AGENT_PREFIX,
                format_location_saved_reply,
            )

            if (
                business_config.get("whatsapp_is_location")
                or (user_message or "").startswith(LOCATION_AGENT_PREFIX)
            ) and session_key:
                try:
                    session = await context_manager.get_session_by_key(session_key)
                    loc = context_manager.get_delivery_location(session)
                    if loc:
                        reply = format_location_saved_reply(loc, business_name)
                        return await self._cart_fast_path_result(
                            session_key,
                            reply,
                            actions_taken=[
                                {
                                    "tool": "delivery_location",
                                    "result_summary": "location_saved",
                                }
                            ],
                            send_cart_buttons=True,
                        )
                except Exception as loc_err:
                    logger.warning(f"[CONV_AGENT] Location fast path failed: {loc_err}")

            if check_user_message_injection(user_message):
                logger.warning("[CONV_AGENT] Blocked suspected prompt injection in user message")
                return {
                    "response_text": injection_safe_reply(business_name),
                    "image_urls": [],
                    "cards": [],
                    "order_created": False,
                    "order_cancelled": False,
                    "order_data": None,
                    "order_notification": "",
                    "escalation_triggered": False,
                    "escalation_notification": "",
                    "human_handoff": False,
                    "actions_taken": [{"tool": "guard", "result_summary": "injection_blocked"}],
                }

            supported_languages = self._parse_supported_languages(
                business_config.get("supported_languages")
            )
            auto_escalation_enabled = self._config_bool(
                business_config.get("auto_escalation_enabled"),
                getattr(settings, "AGENT_AUTO_ESCALATION_ENABLED", True),
            )
            frustration_threshold = self._safe_float_config(
                business_config.get("frustration_threshold"),
                getattr(settings, "AGENT_FRUSTRATION_ESCALATION_THRESHOLD", 0.65),
            )
            handoff_ttl_seconds = self._safe_int_config(
                business_config.get("human_handoff_ttl_hours"),
                getattr(settings, "AGENT_HUMAN_HANDOFF_TTL_HOURS", 24),
            ) * 3600

            preferred_language = DEFAULT_LANGUAGE
            session = None
            if session_key:
                if handoff_ttl_seconds:
                    await context_manager.maybe_expire_human_handoff(
                        session_key, handoff_ttl_seconds
                    )
                session = await context_manager.get_session_by_key(session_key)

                if context_manager.is_reset_command(user_message):
                    await context_manager.clear_human_handoff(session_key)

                if agent_intelligence.is_release_bot_command(user_message):
                    lang = context_manager.get_preferred_language(session) if session else "en"
                    await context_manager.clear_human_handoff(session_key)
                    reply = agent_intelligence.get_release_bot_message(lang)
                    return {
                        "response_text": reply,
                        "image_urls": [],
                        "cards": [],
                        "order_created": False,
                        "order_cancelled": False,
                        "order_data": None,
                        "order_notification": "",
                        "escalation_triggered": False,
                        "escalation_notification": "",
                        "human_handoff": False,
                        "send_agent_mode_buttons": "assistant",
                        "actions_taken": [{"tool": "handoff", "result_summary": "released_to_bot"}],
                    }

                lang_detection = agent_intelligence.detect_language(
                    user_message, supported=supported_languages
                )
                detected_language = lang_detection["language_code"]
                detected_confidence = lang_detection["confidence"]
                # When the keyword heuristic is unsure on a substantial message,
                # refine with a cheap LLM classification (catches Sheng/code-mix).
                if (
                    detected_confidence < 0.6
                    and len((user_message or "").split()) >= 2
                    and not user_message.startswith(PAY_MPESA_AGENT_PREFIX)
                ):
                    llm_lang = await self._detect_language_llm(
                        user_message, supported_languages
                    )
                    if llm_lang:
                        detected_language = llm_lang
                        detected_confidence = 0.85
                preferred_language = detected_language
                if session:
                    existing_lang = session.metadata.get("preferred_language")
                    if not existing_lang:
                        # First detection — adopt it
                        await context_manager.set_preferred_language(
                            session_key, detected_language
                        )
                    elif detected_language == existing_lang:
                        # Same language — keep it (no flip-flop)
                        preferred_language = existing_lang
                    elif detected_confidence >= 0.7:
                        # Switch to a different language only on a strong signal,
                        # so a single foreign word (or a Kenyan name/phone) doesn't
                        # keep flipping the conversation language.
                        await context_manager.set_preferred_language(
                            session_key, detected_language
                        )
                    else:
                        preferred_language = existing_lang
                    streak = agent_intelligence.update_sentiment_streak(
                        session.metadata, user_message
                    )
                    await context_manager.update_session_metadata(
                        session_key, {"negative_sentiment_streak": streak}
                    )
                    session = await context_manager.get_session_by_key(session_key)

            if session_key and is_order_confirmation_message(user_message):
                try:
                    # If cart has items but pending_confirmation is missing,
                    # auto-create it so create_order isn't blocked
                    session = await context_manager.get_session_by_key(session_key)
                    if session and not session.metadata.get("pending_confirmation"):
                        cart = context_manager.get_cart(session)
                        if cart:
                            await context_manager.set_pending_confirmation(
                                session_key, cart, {"source": "auto_from_cart"}
                            )
                    await context_manager.mark_order_confirmed(session_key)
                except Exception as e:
                    logger.warning(f"[CONV_AGENT] mark_order_confirmed failed: {e}")

            # ── Fast path: cart commands (no LLM) — reply sent via workflow step 2 ──
            if session_key:
                cart_cmd = match_cart_command(user_message)
                # YES / "proceed with the order" confirms an existing summary — don't restart checkout
                if cart_cmd == "checkout":
                    try:
                        _sess = await context_manager.get_session_by_key(session_key)
                        if (
                            _sess
                            and _sess.metadata.get("awaiting_order_confirmation")
                            and is_order_confirmation_message(user_message)
                        ):
                            cart_cmd = None
                    except Exception:
                        pass
                if cart_cmd == "reset":
                    try:
                        session = await context_manager.get_session_by_key(session_key)
                        if session:
                            await context_manager.clear_session(session)
                            session.metadata["welcome_sent"] = True
                            await context_manager.save_session(session)
                    except Exception as e:
                        logger.warning(f"[CONV_AGENT] reset failed: {e}")
                    reply = (
                        f"🔄 Fresh start! Your cart and chat history are cleared.\n\n"
                        f"Welcome back to *{business_name}* — {reset_intro}"
                    )
                    return await self._cart_fast_path_result(
                        session_key, reply,
                        actions_taken=[{"tool": "manage_cart", "result_summary": "reset"}],
                        send_cart_buttons=True,
                    )
                if cart_cmd == "clear":
                    await context_manager.clear_cart(session_key)
                    reply = cart_cleared_message(catalog_word)
                    return await self._cart_fast_path_result(
                        session_key, reply,
                        actions_taken=[{"tool": "manage_cart", "result_summary": "clear"}],
                        send_cart_buttons=True,
                    )
                if cart_cmd == "view":
                    session = await context_manager.get_session_by_key(session_key)
                    cart = context_manager.get_cart(session) if session else []
                    reply = format_cart_summary(cart, currency, catalog_word)
                    return await self._cart_fast_path_result(
                        session_key, reply,
                        actions_taken=[{"tool": "manage_cart", "result_summary": "view"}],
                        send_cart_buttons=True,
                    )
                if cart_cmd == "checkout":
                    session = await context_manager.get_session_by_key(session_key)
                    cart = context_manager.get_cart(session) if session else []
                    if not cart:
                        reply = (
                            "Your cart is empty right now. 🛒\n"
                            f"Browse the {catalog_word} and tap *Add to Cart* on something you like!"
                        )
                        return await self._cart_fast_path_result(
                            session_key, reply,
                            actions_taken=[{"tool": "manage_cart", "result_summary": "checkout"}],
                            send_cart_buttons=True,
                        )
                    try:
                        return await self._start_checkout_flow(
                            session_key=session_key,
                            cart=cart,
                            currency=currency,
                            customer_name=customer_name,
                            customer_phone=customer_phone,
                            delivery_methods=delivery_methods,
                            preferred_language=preferred_language,
                            catalog_word=catalog_word,
                            user=user,
                            db=db,
                        )
                    except Exception as checkout_err:
                        # Degrade gracefully to the LLM path instead of returning the
                        # scary generic "experiencing a brief issue" fallback.
                        logger.error(
                            f"[CONV_AGENT] checkout fast-path failed, falling back to LLM: {checkout_err}",
                            exc_info=True,
                        )
                if cart_cmd == "remove":
                    name = parse_remove_item_name(user_message)
                    cart, removed, removed_name = await context_manager.remove_cart_item(
                        session_key, product_name=name
                    )
                    if removed:
                        reply = f"{cart_item_removed_message(removed_name)}\n\n{format_cart_summary(cart, currency, catalog_word)}"
                    else:
                        reply = (
                            f"I couldn't find *{name}* in your cart.\n\n"
                            f"{format_cart_summary(cart, currency, catalog_word)}"
                        )
                    return await self._cart_fast_path_result(
                        session_key, reply,
                        actions_taken=[{"tool": "manage_cart", "result_summary": "remove"}],
                        send_cart_buttons=True,
                    )
                if cart_cmd == "set_quantity":
                    name, qty = parse_set_quantity_message(user_message)
                    if name is not None and qty is not None:
                        cart, ok, item_name, _key = await context_manager.set_cart_item_quantity(
                            session_key, qty, product_name=name
                        )
                        if ok:
                            reply = (
                                f"{cart_quantity_updated_message(item_name, qty)}\n\n"
                                f"{format_cart_summary(cart, currency, catalog_word)}"
                            )
                        else:
                            reply = (
                                f"I couldn't find *{name}* in your cart.\n\n"
                                f"{format_cart_summary(cart, currency, catalog_word)}"
                            )
                        return await self._cart_fast_path_result(
                            session_key, reply,
                            actions_taken=[{"tool": "manage_cart", "result_summary": "set_quantity"}],
                            send_cart_buttons=True,
                        )

            # Human handoff — after self-serve cart/location paths
            if session_key:
                try:
                    session = await context_manager.get_session_by_key(session_key)
                except Exception:
                    session = None
                if session and context_manager.is_human_handoff(session):
                    lang = context_manager.get_preferred_language(session)
                    waiting_msg = agent_intelligence.get_handoff_waiting_message(lang)
                    await self._save_to_ccm(session_key, "assistant", waiting_msg)
                    return {
                        "response_text": waiting_msg,
                        "image_urls": [],
                        "cards": [],
                        "order_created": False,
                        "order_cancelled": False,
                        "order_data": None,
                        "order_notification": "",
                        "escalation_triggered": False,
                        "escalation_notification": "",
                        "human_handoff": True,
                        "skip_customer_reply": False,
                        "send_agent_mode_buttons": "staff",
                        "actions_taken": [{"tool": "handoff", "result_summary": "human_active"}],
                    }

            # ── Deterministic checkout (Phase 1): capture name/phone/delivery ──
            if session_key:
                try:
                    session = await context_manager.get_session_by_key(session_key)
                except Exception:
                    session = None
                cart = context_manager.get_cart(session) if session else []
                if (
                    session
                    and cart
                    and not context_manager.is_human_handoff(session)
                    and not is_order_confirmation_message(user_message)
                ):
                    parsed = parse_checkout_details(user_message)
                    draft = session.metadata.get("checkout_draft") or {}
                    awaiting = bool(session.metadata.get("awaiting_checkout_details"))
                    bot_asked = session_assistant_requested_checkout(session)

                    eff_phone = parsed.get("phone") or draft.get("phone") or customer_phone
                    eff_name = parsed.get("name") or draft.get("name") or customer_name
                    eff_delivery = parsed.get("delivery_method") or draft.get("delivery_method")

                    has_name_and_phone = bool(eff_phone and eff_name)
                    bot_expecting_reply = awaiting or bot_asked
                    customer_sent_details = bool(
                        parsed.get("phone") or parsed.get("name") or parsed.get("delivery_method")
                    )
                    
                    user_text = user_message.strip()
                    is_providing_address = draft.get("stage") == "need_delivery_address" and bool(user_text)

                    should_capture = customer_sent_details and (
                        has_name_and_phone
                        or (bot_expecting_reply and parsed.get("phone"))
                        or (bot_expecting_reply and parsed.get("name") and eff_phone)
                    ) or is_providing_address

                    if should_capture:
                        eff_delivery, saved_addr = await self._resolve_checkout_delivery(
                            session_key, eff_delivery, delivery_methods
                        )
                        if is_providing_address and not saved_addr:
                            saved_addr = user_text

                        if not eff_phone:
                            await context_manager.update_session_metadata(
                                session_key,
                                {
                                    "awaiting_checkout_details": True,
                                    "checkout_draft": {
                                        "name": eff_name or "",
                                        "phone": "",
                                        "delivery_method": eff_delivery or "",
                                        "stage": "need_phone",
                                    },
                                },
                            )
                            return await self._cart_fast_path_result(
                                session_key,
                                self._t(
                                    preferred_language,
                                    "Almost there! What's the best phone number to reach you on? 📞",
                                    "Karibu tumalize! Nipe namba yako ya simu ya kukupigia. 📞",
                                ),
                                actions_taken=[{"tool": "checkout", "result_summary": "need_phone"}],
                                send_cart_buttons=False,
                            )
                        if not eff_name:
                            await context_manager.update_session_metadata(
                                session_key,
                                {
                                    "awaiting_checkout_details": True,
                                    "checkout_draft": {
                                        "name": "",
                                        "phone": eff_phone or "",
                                        "delivery_method": eff_delivery or "",
                                        "stage": "need_name",
                                    },
                                },
                            )
                            return await self._cart_fast_path_result(
                                session_key,
                                self._t(
                                    preferred_language,
                                    "Thanks! And what name should I put on the order? 🙂",
                                    "Asante! Niweke jina gani kwenye oda? 🙂",
                                ),
                                actions_taken=[{"tool": "checkout", "result_summary": "need_name"}],
                                send_cart_buttons=False,
                            )

                        return await self._present_checkout_confirmation(
                            session_key=session_key,
                            cart=cart,
                            currency=currency,
                            customer_name=eff_name,
                            customer_phone=eff_phone,
                            delivery_method=eff_delivery,
                            delivery_methods=delivery_methods,
                            preferred_language=preferred_language,
                            delivery_address=saved_addr,
                            user=user,
                            db=db,
                        )

                    # Customer is correcting us after the bot (LLM) asked for details
                    msg_lower = (user_message or "").lower()
                    if bot_asked and any(
                        s in msg_lower
                        for s in ("you asked", "already gave", "that's what", "i gave")
                    ):
                        await context_manager.update_session_metadata(
                            session_key, {"awaiting_checkout_details": True}
                        )
                        return await self._cart_fast_path_result(
                            session_key,
                            self._t(
                                preferred_language,
                                "You're right — let's finish your order. 🛒\n\n"
                                "Please reply with your *name* and *phone number* "
                                "(one message is fine), e.g.:\n"
                                "Harun Gachanja\n254711371265",
                                "Uko sahihi — tumalize oda yako. 🛒\n\n"
                                "Tafadhali jibu na *jina* na *namba ya simu* "
                                "(ujumbe mmoja unatosha), mfano:\n"
                                "Harun Gachanja\n254711371265",
                            ),
                            actions_taken=[{"tool": "checkout", "result_summary": "reprompt_details"}],
                            send_cart_buttons=False,
                        )

            enabled_mcp_tool_names = business_config.get("enabled_mcp_tools", [])
            if isinstance(enabled_mcp_tool_names, str):
                try:
                    import ast
                    parsed = ast.literal_eval(enabled_mcp_tool_names)
                    if isinstance(parsed, list):
                        enabled_mcp_tool_names = parsed
                    else:
                        enabled_mcp_tool_names = [t.strip() for t in enabled_mcp_tool_names.split(",") if t.strip()]
                except Exception:
                    enabled_mcp_tool_names = [t.strip() for t in enabled_mcp_tool_names.split(",") if t.strip()]
            elif not isinstance(enabled_mcp_tool_names, list):
                enabled_mcp_tool_names = []
                
            if enabled_mcp_tool_names:
                custom_system_prompt += f"\n\n[HARNESS INSTRUCTIONS]\nYou have access to external enterprise tools: {', '.join(enabled_mcp_tool_names)}. Use them autonomously when the customer's request requires them."

            platform = self._detect_channel_platform(
                explicit_platform=business_config.get("platform"),
                session_key=session_key
            )

            # Extract storage config
            storage_config = {
                "provider": business_config.get("storage_provider", "none"),
                "spreadsheet_id": business_config.get("storage_spreadsheet_id", ""),
                "orders_sheet_name": business_config.get("storage_orders_sheet_name", "Orders"),
                "customers_sheet_name": business_config.get("storage_customers_sheet_name", "Customers"),
                "transactions_sheet_name": business_config.get("storage_transactions_sheet_name", "Transactions"),
                "airtable_base_id": business_config.get("storage_airtable_base_id", ""),
                "airtable_orders_table": business_config.get("storage_airtable_orders_table", "Orders"),
                "airtable_customers_table": business_config.get("storage_airtable_customers_table", "Customers"),
                "airtable_transactions_table": business_config.get("storage_airtable_transactions_table", "Transactions"),
            }

            # ── Fast path: "Pay with Mpesa" button → deterministic STK push ──
            # The webhook converts a pay_mpesa:{order_id} button tap into a marker
            # message. Trigger the STK push directly instead of depending on the LLM.
            if (user_message or "").startswith(PAY_MPESA_AGENT_PREFIX):
                pay_order_id = user_message[len(PAY_MPESA_AGENT_PREFIX):].strip()
                pay_phone = customer_phone
                if not pay_phone and session_key and session_key.startswith("ccm:"):
                    _parts = session_key.split(":")
                    if len(_parts) >= 4:
                        pay_phone = _parts[3]
                lang = (
                    context_manager.get_preferred_language(session)
                    if session else preferred_language
                )
                if not pay_order_id:
                    reply = self._t(
                        lang,
                        "I couldn't find which order to pay for. Please try again or type the order number.",
                        "Sikuweza kupata oda ya kulipia. Tafadhali jaribu tena au andika nambari ya oda.",
                    )
                    return await self._cart_fast_path_result(
                        session_key, reply,
                        actions_taken=[{"tool": "initiate_mpesa_payment", "result_summary": "missing_order_id"}],
                        send_cart_buttons=False,
                    )
                try:
                    pay_res = await self._sub_initiate_mpesa_payment(
                        order_id=pay_order_id,
                        phone_number=pay_phone,
                        amount=0,  # _sub_initiate looks up the real amount from the registered order
                        description=f"Order {pay_order_id}",
                        session_key=session_key,
                        storage_config=storage_config,
                        business_name=business_name,
                        user=user,
                        db=db,
                    )
                except Exception as pay_err:
                    logger.error(f"[CONV_AGENT] pay_mpesa fast-path failed: {pay_err}", exc_info=True)
                    pay_res = {"success": False, "error": str(pay_err)}

                if pay_res.get("success"):
                    reply = self._t(
                        lang,
                        (
                            f"📲 I've sent an M-Pesa payment request to {pay_phone or 'your phone'}.\n"
                            "Please check your phone and enter your M-Pesa PIN to complete the payment. "
                            "You'll get a receipt here once it's confirmed. 🙏"
                        ),
                        (
                            f"📲 Nimetuma ombi la malipo ya M-Pesa kwa {pay_phone or 'simu yako'}.\n"
                            "Tafadhali angalia simu yako na uweke PIN yako ya M-Pesa kukamilisha malipo. "
                            "Utapokea risiti hapa mara malipo yatakapothibitishwa. 🙏"
                        ),
                    )
                    summary = "stk_initiated"
                else:
                    err = pay_res.get("error", "")
                    reply = self._t(
                        lang,
                        (
                            "Sorry, I couldn't start the M-Pesa payment right now. "
                            + (f"({err}) " if err else "")
                            + "Please try again shortly or contact us for help."
                        ),
                        (
                            "Samahani, sikuweza kuanzisha malipo ya M-Pesa kwa sasa. "
                            + (f"({err}) " if err else "")
                            + "Tafadhali jaribu tena baadaye au wasiliana nasi kwa usaidizi."
                        ),
                    )
                    summary = "stk_failed"
                return await self._cart_fast_path_result(
                    session_key, reply,
                    actions_taken=[{"tool": "initiate_mpesa_payment", "result_summary": summary}],
                    send_cart_buttons=False,
                )

            # ── Fast path: "Pay with M-Pesa" tapped on the checkout screen ──
            # One tap: create the order (it's already confirmed by tapping) AND
            # trigger the STK push immediately. No reliance on typed "YES".
            if (user_message or "").strip() == CONFIRM_PAY_AGENT_MARKER:
                try:
                    session = await context_manager.get_session_by_key(session_key)
                except Exception:
                    session = None
                lang = (
                    context_manager.get_preferred_language(session)
                    if session else preferred_language
                )
                checkout_customer = session.metadata.get("checkout_customer") if session else None
                pending = session.metadata.get("pending_confirmation") if session else None
                cart_items = (pending or {}).get("items") if pending else None
                if not cart_items and session:
                    cart_items = context_manager.get_cart(session)

                if not checkout_customer or not cart_items:
                    reply = self._t(
                        lang,
                        "I couldn't find your order details. Please type *checkout* to start again.",
                        "Sikuweza kupata maelezo ya oda yako. Tafadhali andika *checkout* kuanza upya.",
                    )
                    return await self._cart_fast_path_result(
                        session_key, reply,
                        actions_taken=[{"tool": "checkout", "result_summary": "confirm_pay_no_details"}],
                        send_cart_buttons=False,
                    )

                create_args = {
                    "customer_name": checkout_customer.get("name", "") or customer_name,
                    "customer_phone": checkout_customer.get("phone", "") or customer_phone,
                    "items": cart_items,
                    "delivery_method": checkout_customer.get("delivery_method", "") or "pickup",
                    "delivery_address": checkout_customer.get("delivery_address", ""),
                }
                try:
                    await context_manager.mark_order_confirmed(session_key)
                except Exception:
                    pass

                tool_result = await self._sub_create_order(
                    arguments=create_args,
                    order_type=order_type,
                    currency=currency,
                    business_name=business_name,
                    storage_config=storage_config,
                    user=user,
                    db=db,
                    background_tasks=background_tasks,
                    session_key=session_key,
                    user_message="yes",
                    business_phone=business_phone,
                )

                if not tool_result.get("success"):
                    logger.warning(
                        "[CONV_AGENT] confirm_pay: order creation failed: %s",
                        tool_result.get("result"),
                    )
                    reply = self._t(
                        lang,
                        "Sorry, I couldn't place your order just now. Please try again shortly.",
                        "Samahani, sikuweza kuweka oda yako kwa sasa. Tafadhali jaribu tena baadaye.",
                    )
                    return await self._cart_fast_path_result(
                        session_key, reply,
                        actions_taken=[{"tool": "create_order", "result_summary": "confirm_pay_failed"}],
                        send_cart_buttons=False,
                    )

                order_data = tool_result.get("order_data", tool_result)
                _order = order_data.get("order") if isinstance(order_data.get("order"), dict) else order_data
                new_order_id = _order.get("order_id") or order_data.get("order_id", "")
                pay_amount = (
                    _order.get("total_amount") or _order.get("grand_total")
                    or _order.get("total") or _order.get("subtotal") or 0
                )
                pay_phone = create_args["customer_phone"]

                try:
                    await context_manager.clear_cart(session_key)
                    await context_manager.clear_pending_confirmation(session_key)
                    await context_manager.update_session_metadata(
                        session_key,
                        {
                            "checkout_customer": None,
                            "checkout_draft": {},
                            "awaiting_checkout_details": False,
                            "awaiting_order_confirmation": False,
                        },
                    )
                except Exception as e:
                    logger.warning(f"[CONV_AGENT] confirm_pay cleanup failed: {e}")

                try:
                    pay_res = await self._sub_initiate_mpesa_payment(
                        order_id=new_order_id,
                        phone_number=pay_phone,
                        amount=pay_amount,
                        description=f"Order {new_order_id}",
                        session_key=session_key,
                        storage_config=storage_config,
                        business_name=business_name,
                        user=user,
                        db=db,
                    )
                except Exception as pay_err:
                    logger.error(f"[CONV_AGENT] confirm_pay STK failed: {pay_err}", exc_info=True)
                    pay_res = {"success": False, "error": str(pay_err)}

                order_notification = self._format_business_notification(
                    order_data, business_name, currency
                )

                if pay_res.get("success"):
                    reply = self._t(
                        lang,
                        (
                            f"✅ Order *{new_order_id}* placed!\n\n"
                            f"📲 I've sent an M-Pesa request to {pay_phone}. "
                            "Enter your M-Pesa PIN to complete payment. "
                            "You'll get a receipt here once it's confirmed. 🙏"
                        ),
                        (
                            f"✅ Oda *{new_order_id}* imewekwa!\n\n"
                            f"📲 Nimetuma ombi la M-Pesa kwa {pay_phone}. "
                            "Weka PIN yako ya M-Pesa kukamilisha malipo. "
                            "Utapokea risiti hapa mara itakapothibitishwa. 🙏"
                        ),
                    )
                    summary = "confirm_pay_stk_initiated"
                else:
                    err = pay_res.get("error", "")
                    reply = self._t(
                        lang,
                        (
                            f"✅ Order *{new_order_id}* placed!\n\n"
                            "But I couldn't start the M-Pesa payment automatically"
                            + (f" ({err})" if err else "")
                            + ". Please tap *Pay with Mpesa* below to try again."
                        ),
                        (
                            f"✅ Oda *{new_order_id}* imewekwa!\n\n"
                            "Lakini sikuweza kuanzisha malipo ya M-Pesa kiotomatiki"
                            + (f" ({err})" if err else "")
                            + ". Tafadhali bonyeza *Pay with Mpesa* hapa chini kujaribu tena."
                        ),
                    )
                    summary = "confirm_pay_stk_failed"

                await self._save_to_ccm(session_key, "assistant", reply)
                return {
                    "response_text": reply,
                    "image_urls": [],
                    "cards": [],
                    "order_created": True,
                    "order_cancelled": False,
                    "order_data": order_data,
                    "order_notification": order_notification,
                    "escalation_triggered": False,
                    "escalation_notification": "",
                    "human_handoff": False,
                    "actions_taken": [{"tool": "initiate_mpesa_payment", "result_summary": summary}],
                    "send_cart_buttons": False,
                    "send_agent_mode_buttons": None,
                }

            # ── Deterministic checkout (Phase 2): create the order on YES ──
            # If we previously captured checkout details (Phase 1) and the customer
            # now confirms, create the order directly instead of hoping the LLM does.
            if session_key:
                try:
                    session = await context_manager.get_session_by_key(session_key)
                except Exception:
                    session = None
                if session and not context_manager.is_human_handoff(session):
                    checkout_customer = session.metadata.get("checkout_customer")
                    pending = session.metadata.get("pending_confirmation")
                    confirmed = (
                        is_order_confirmation_message(user_message)
                        or bool(session.metadata.get("order_confirmed"))
                    )
                    if checkout_customer and pending and confirmed:
                        items = pending.get("items") or context_manager.get_cart(session)
                        create_args = {
                            "customer_name": checkout_customer.get("name", "") or customer_name,
                            "customer_phone": checkout_customer.get("phone", "") or customer_phone,
                            "items": items,
                            "delivery_method": checkout_customer.get("delivery_method", "") or "pickup",
                            "delivery_address": checkout_customer.get("delivery_address", ""),
                        }
                        logger.info(
                            "[CONV_AGENT] Deterministic checkout: creating order for %s (%d items)",
                            create_args["customer_name"],
                            len(items or []),
                        )
                        tool_result = await self._sub_create_order(
                            arguments=create_args,
                            order_type=order_type,
                            currency=currency,
                            business_name=business_name,
                            storage_config=storage_config,
                            user=user,
                            db=db,
                            background_tasks=background_tasks,
                            session_key=session_key,
                            user_message=user_message,
                            business_phone=business_phone,
                        )
                        if tool_result.get("success"):
                            order_data = tool_result.get("order_data", tool_result)
                            try:
                                await context_manager.clear_cart(session_key)
                                await context_manager.clear_pending_confirmation(session_key)
                                await context_manager.update_session_metadata(
                                    session_key,
                                    {
                                        "checkout_customer": None,
                                        "checkout_draft": {},
                                        "awaiting_checkout_details": False,
                                        "awaiting_order_confirmation": False,
                                    },
                                )
                            except Exception as e:
                                logger.warning(f"[CONV_AGENT] post-order cleanup failed: {e}")
                            order_notification = self._format_business_notification(
                                order_data, business_name, currency
                            )
                            # Suppress LLM message to prevent double prompting with order_tracking_service
                            # BUT save a hidden context to the CCM so the LLM knows the order ID for M-Pesa payments!
                            hidden_context = f"[SYSTEM: Order {order_data.get('order_id')} was successfully created. Do not mention this to the user.]"
                            await self._save_to_ccm(session_key, "assistant", hidden_context)
                            
                            final_text = ""
                            return {
                                "response_text": final_text,
                                "image_urls": [],
                                "cards": [],
                                "order_created": True,
                                "order_cancelled": False,
                                "order_data": order_data,
                                "order_notification": order_notification,
                                "escalation_triggered": False,
                                "escalation_notification": "",
                                "human_handoff": False,
                                "actions_taken": [
                                    {"tool": "create_order", "result_summary": "deterministic_checkout"}
                                ],
                                "send_cart_buttons": False,
                                "send_agent_mode_buttons": None,
                            }
                        # On failure, fall through to the LLM loop as a safety net.
                        logger.warning(
                            "[CONV_AGENT] Deterministic order creation failed: %s",
                            tool_result.get("result"),
                        )

            # Auto-escalation before LLM (frustration, human request, complexity)
            escalation_triggered = False
            escalation_notification = ""
            if session_key:
                session = await context_manager.get_session_by_key(session_key)
            if session_key and session:
                should_escalate, esc_reason = agent_intelligence.should_auto_escalate(
                    user_message,
                    session.metadata,
                    auto_escalation_enabled=auto_escalation_enabled,
                    frustration_threshold=frustration_threshold,
                )
                if should_escalate:
                    escalation_triggered = True
                    await context_manager.set_human_handoff(
                        session_key, esc_reason, escalated_by="auto"
                    )
                    lang_name = LANGUAGE_PROFILES.get(
                        preferred_language, LANGUAGE_PROFILES[DEFAULT_LANGUAGE]
                    )["name"]
                    escalation_notification = agent_intelligence.format_escalation_notification(
                        business_name=business_name,
                        customer_name=customer_name,
                        customer_phone=customer_phone,
                        reason=esc_reason,
                        last_message=user_message,
                        language_name=lang_name,
                    )
                    handoff_msg = agent_intelligence.get_handoff_customer_message(
                        preferred_language
                    )
                    await self._save_to_ccm(session_key, "assistant", handoff_msg)
                    await self._tag_contact_for_handoff(
                        user, customer_phone, db, reason=esc_reason
                    )
                    return {
                        "response_text": handoff_msg,
                        "image_urls": [],
                        "cards": [],
                        "order_created": False,
                        "order_cancelled": False,
                        "order_data": None,
                        "order_notification": "",
                        "escalation_triggered": True,
                        "escalation_notification": escalation_notification,
                        "human_handoff": True,
                        "send_agent_mode_buttons": "staff",
                        "actions_taken": [
                            {"tool": "escalate_to_human", "result_summary": f"auto:{esc_reason}"}
                        ],
                    }

            # Build the system prompt
            system_prompt = self._build_system_prompt(
                business_name=business_name,
                order_type=order_type,
                currency=currency,
                delivery_methods=delivery_methods,
                custom_prompt=custom_system_prompt,
                customer_phone=customer_phone,
                customer_name=customer_name,
                preferred_language=preferred_language,
                auto_escalation_enabled=auto_escalation_enabled,
                business_config=business_config,
            )

            cart_context = await self._build_cart_context_block(session_key, currency)
            if cart_context:
                system_prompt += cart_context

            delivery_context = await self._build_delivery_location_block(session_key)
            if delivery_context:
                system_prompt += delivery_context

            # Harness: inject agent context into system prompt
            if self._harness_enabled:
                try:
                    self._harness_reset_turn()
                    harness_context = await self._harness_build_context(
                        user, "conversational_agent", db
                    )
                    if harness_context:
                        system_prompt += f"\n\n# Agent Context (Auto-Generated)\n{harness_context}"
                except Exception as e:
                    logger.warning(f"[CONV_AGENT] Harness context injection failed: {e}")

            # Load conversation history from CCM
            messages = await self._load_conversation_history(
                session_key=session_key,
                system_prompt=system_prompt
            )

            # Add current user message unless trigger already persisted identical turn
            user_stripped = (user_message or "").strip()
            if messages and messages[-1].get("role") == "user":
                if (messages[-1].get("content") or "").strip() != user_stripped:
                    messages.append({"role": "user", "content": user_message})
            elif user_stripped:
                messages.append({"role": "user", "content": user_message})

            # Run the inner tool-calling loop (max 3 iterations)
            actions_taken = []
            order_created = False
            order_cancelled = False
            order_data = None
            order_notification = ""
            escalation_triggered = False
            escalation_notification = ""
            human_handoff = False
            send_agent_mode_buttons: Optional[str] = None
            collected_image_urls: List[str] = []
            collected_product_cards: List[Dict[str, Any]] = []
            sent_product_ids: set = set()  # Track product IDs already sent as cards this turn
            last_search_product_image_map: List[Dict[str, Any]] = []  # Per-chunk product→image data from latest search
            send_cart_buttons_after_turn = False
            checkout_keywords = ("order", "cart", "checkout", "pay", "total", "confirm", "delivery")
            msg_lower = (user_message or "").lower()
            has_checkout_intent = any(k in msg_lower for k in checkout_keywords)
            if session_key:
                try:
                    session = await context_manager.get_session_by_key(session_key)
                    if session and context_manager.get_cart(session):
                        has_checkout_intent = True
                except Exception:
                    pass
            max_iterations = 6 if has_checkout_intent else 4

            await self._maybe_send_welcome_quick_replies(
                session_key=session_key,
                business_name=business_name,
                customer_name=customer_name,
                user=user,
                db=db,
                catalog_word=catalog_word,
            )

            # Assemble dynamic tools
            from .dynamic_tool_registry import dynamic_tool_registry
            dynamic_tools = list(AGENT_SUB_TOOLS)
            for t_name in enabled_mcp_tool_names:
                schema = dynamic_tool_registry.get_tool(t_name)
                if schema:
                    dynamic_tools.append(dynamic_tool_registry.convert_tools_to_openai_format([schema])[0])

            for iteration in range(max_iterations):
                # Call LLM with sub-tools
                # Use gpt-4o-mini for speed — 3x faster than gpt-4o with
                # equivalent tool-calling accuracy for commerce conversations.
                # max_tokens=4096 is needed because display_product_cards
                # generates large JSON arguments (5+ products × ~100 tokens each).
                response = await self.llm_service.chat_completion(
                    messages=messages,
                    tools=dynamic_tools,
                    temperature=0.3,
                    max_tokens=4096,
                    provider="openai",
                    use_background_model=True
                )

                if response.error:
                    logger.error(f"[CONV_AGENT] LLM error: {response.error}")
                    return self._fallback_response(
                        business_name, error_code="llm_error", business_phone=business_phone
                    )

                # If no tool calls, we have the final response
                if not response.tools_called:
                    final_text = response.content or f"Thank you for contacting {business_name}! How can I help you?"

                    # ── PRODUCTION IMAGE HANDLING ──
                    # Strip ALL image URLs from the LLM's text response.
                    # Images ONLY go through product cards — never as bare URLs.
                    text_image_urls = extract_image_urls(final_text)
                    if text_image_urls:
                        final_text = strip_image_urls(final_text, text_image_urls)

                    # If product cards were sent, clear image_urls entirely
                    # to prevent downstream bare media sends via tool_executor
                    if collected_product_cards:
                        image_urls = []  # Cards already delivered images
                    else:
                        image_urls = _dedupe_keep_order(collected_image_urls)

                    final_text = self._format_for_channel(final_text, platform)

                    # Harness: post-execution quality gate
                    if self._harness_enabled:
                        try:
                            quality = await self._harness_evaluate_response(
                                final_text, user_message, iterations=iteration + 1
                            )
                            # Block only for critical safety issues
                            if self._harness_should_block_response(quality):
                                logger.warning(f"[CONV_AGENT] Response blocked by safety gate (score={quality.safety:.2f})")
                                final_text = self._harness_get_safe_fallback(business_name)
                        except Exception as e:
                            logger.warning(f"[CONV_AGENT] Quality gate failed: {e}")

                    # Save assistant response to CCM
                    await self._save_to_ccm(session_key, "assistant", final_text)

                    result = {
                        "response_text": final_text,
                        "image_urls": image_urls,
                        "cards": collected_product_cards,
                        "order_created": order_created,
                        "order_cancelled": order_cancelled,
                        "order_data": order_data,
                        "order_notification": order_notification,
                        "escalation_triggered": escalation_triggered,
                        "escalation_notification": escalation_notification,
                        "human_handoff": human_handoff,
                        "actions_taken": actions_taken,
                        "send_cart_buttons": send_cart_buttons_after_turn and not order_created,
                        "send_agent_mode_buttons": send_agent_mode_buttons,
                    }
                    return result

                # Process tool calls
                # Add assistant message with tool calls to conversation
                messages.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [
                        {
                            "id": f"call_{iteration}_{i}",
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["arguments"])
                            }
                        }
                        for i, tc in enumerate(response.tools_called)
                    ]
                })

                for i, tool_call in enumerate(response.tools_called):
                    tool_name = tool_call["name"]
                    raw_args = tool_call.get("arguments", {})
                    if isinstance(raw_args, str):
                        try:
                            tool_args = json.loads(raw_args)
                        except Exception:
                            tool_args = {}
                    elif isinstance(raw_args, dict):
                        tool_args = dict(raw_args)
                    else:
                        tool_args = {}
                    
                    tool_call["arguments"] = tool_args
                    call_id = f"call_{iteration}_{i}"

                    logger.info(f"[CONV_AGENT] Sub-tool call: {tool_name}({json.dumps(tool_args)[:200]})")

                    # Harness: pre-execution guardrail validation
                    if self._harness_enabled:
                        try:
                            available = [t.get("function", t).get("name", "") for t in dynamic_tools]
                            guardrail_result = await self._harness_validate_tool_call(
                                tool_name, tool_args, user, available
                            )
                            if not guardrail_result.passed:
                                corrective = await self._harness_handle_guardrail_failure(
                                    guardrail_result, tool_name, tool_args
                                )
                                # Inject corrective message as tool result
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": call_id,
                                    "content": json.dumps({"error": corrective})
                                })
                                actions_taken.append({
                                    "tool": tool_name,
                                    "args": tool_args,
                                    "result_summary": f"BLOCKED: {guardrail_result.reason}"
                                })
                                continue
                        except Exception as e:
                            logger.warning(f"[CONV_AGENT] Guardrail check failed: {e}")

                    # ── Dedup guard: filter out already-sent products ──
                    # The LLM sometimes calls display_product_cards again in
                    # a later iteration with the same products.  Each call
                    # actually sends WhatsApp messages, so we must prevent
                    # duplicates from reaching the customer.
                    if tool_name == "display_product_cards" and sent_product_ids:
                        incoming_products = tool_args.get("products", [])
                        new_products = [
                            p for p in incoming_products
                            if p.get("id") not in sent_product_ids
                        ]
                        if not new_products:
                            # All products already sent — skip this call entirely
                            logger.info(
                                f"[CONV_AGENT] Skipping duplicate display_product_cards "
                                f"(all {len(incoming_products)} products already sent)"
                            )
                            messages.append({
                                "role": "tool",
                                "tool_call_id": call_id,
                                "content": (
                                    "SKIPPED: These product cards were already sent to "
                                    "the customer earlier in this conversation turn. "
                                    "Do NOT call display_product_cards again with the "
                                    "same products. Just respond with your text message."
                                )
                            })
                            actions_taken.append({
                                "tool": tool_name,
                                "args": tool_args,
                                "result_summary": "SKIPPED: duplicate cards"
                            })
                            continue
                        elif len(new_products) < len(incoming_products):
                            # Some products already sent — only send the new ones
                            logger.info(
                                f"[CONV_AGENT] Filtered display_product_cards: "
                                f"{len(incoming_products)} → {len(new_products)} "
                                f"(removed {len(incoming_products) - len(new_products)} duplicates)"
                            )
                            tool_args = {**tool_args, "products": new_products}

                    # ── Programmatic image correction for display_product_cards ──
                    # Even if the LLM assigned wrong images, fix them before
                    # the cards are actually sent to the customer.
                    if tool_name == "display_product_cards" and last_search_product_image_map:
                        incoming_products = tool_args.get("products", [])
                        corrected = self._correct_product_image_urls(
                            incoming_products, last_search_product_image_map
                        )
                        if corrected:
                            tool_args = {**tool_args, "products": corrected}

                    # Execute the sub-tool
                    tool_result = await self._execute_sub_tool(
                        tool_name=tool_name,
                        arguments=tool_args,
                        kb_id=kb_id,
                        order_type=order_type,
                        currency=currency,
                        business_name=business_name,
                        storage_config=storage_config,
                        session_key=session_key,
                        user=user,
                        db=db,
                        background_tasks=background_tasks,
                        user_message=user_message,
                        default_customer_phone=customer_phone,
                        default_customer_name=customer_name,
                        preferred_language=preferred_language,
                        business_phone=business_phone,
                    )

                    if tool_name == "escalate_to_human" and tool_result.get("success"):
                        escalation_triggered = True
                        human_handoff = True
                        send_agent_mode_buttons = "staff"
                        escalation_notification = tool_result.get("escalation_notification", "")

                    if tool_name == "show_options_menu" and tool_result.get("success"):
                        send_agent_mode_buttons = "assistant"

                    # Harness: track tool call for quality evaluation
                    if self._harness_enabled:
                        self._harness_track_tool_call(tool_name, tool_args, tool_result)

                    # Harness: handle tool errors with feedback loop
                    if not tool_result.get("success") and tool_result.get("error") and self._harness_enabled:
                        try:
                            feedback = await self._harness_handle_tool_error(
                                tool_name, str(tool_result.get("error", "")), tool_args
                            )
                            if feedback.corrective_message:
                                tool_result["harness_correction"] = feedback.corrective_message
                        except Exception as e:
                            logger.warning(f"[CONV_AGENT] Feedback loop failed: {e}")

                    actions_taken.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "result_summary": str(tool_result.get("result", ""))[:200]
                    })

                    # Capture image URLs from product search payloads even when
                    # the model summary omits raw links in final text.
                    if tool_name == "search_products":
                        tool_images = self._extract_image_urls_from_search_result(tool_result)
                        if tool_images:
                            collected_image_urls = _dedupe_keep_order(collected_image_urls + tool_images)
                        # Capture structured per-chunk product→image map for
                        # programmatic correction of display_product_cards.
                        chunks = self._extract_structured_products_from_chunks(tool_result)
                        if chunks:
                            last_search_product_image_map = chunks
                            
                    if tool_name == "display_product_cards":
                        tool_cards = tool_result.get("cards", [])
                        if tool_cards:
                            # Deduplicate: only add cards not already collected
                            for card in tool_cards:
                                card_id = card.get("id", "")
                                if card_id and card_id not in sent_product_ids:
                                    collected_product_cards.append(card)
                                    sent_product_ids.add(card_id)
                                elif not card_id:
                                    # No ID — append but can't deduplicate
                                    collected_product_cards.append(card)
                        # Remove images that were already sent as part of product cards
                        # to prevent duplicate bare image sends
                        sent_card_images = set(tool_result.get("sent_image_urls", []))
                        if sent_card_images:
                            collected_image_urls = [
                                u for u in collected_image_urls if u not in sent_card_images
                            ]

                    # Check if an order was created
                    if tool_name == "calculate_total" and tool_result.get("success") and session_key:
                        try:
                            await context_manager.set_pending_confirmation(
                                session_key,
                                tool_args.get("items", []),
                                tool_result.get("data") or {},
                            )
                        except Exception as e:
                            logger.warning(f"[CONV_AGENT] pending_confirmation failed: {e}")

                    if tool_name == "manage_cart" and tool_result.get("success"):
                        send_cart_buttons_after_turn = True

                    if tool_name == "create_order" and tool_result.get("success"):
                        order_created = True
                        order_data = tool_result.get("order_data", tool_result)
                        if session_key:
                            try:
                                await context_manager.clear_cart(session_key)
                                await context_manager.clear_pending_confirmation(session_key)
                            except Exception as e:
                                logger.warning(f"[CONV_AGENT] post-order session cleanup failed: {e}")
                        order_notification = self._format_business_notification(
                            order_data, business_name, currency
                        )

                    # Check if an order was cancelled
                    if tool_name == "cancel_order" and tool_result.get("success"):
                        order_cancelled = True
                        cancel_data = tool_result.get("cancellation_data", {})
                        # OrderService format_order_notification handles cancellation type
                        notif_result = await self.order_service.format_order_notification(
                            order_data=cancel_data,
                            business_name=business_name,
                            currency=currency,
                            notification_type="cancellation"
                        )
                        if isinstance(notif_result, dict):
                            order_notification = notif_result.get("message", "")
                        else:
                            order_notification = str(notif_result)

                    # Build the tool result message for the LLM
                    # For display_product_cards: tell the LLM cards were already sent
                    # so it doesn't repeat product details in its text response
                    if tool_name == "display_product_cards" and tool_result.get("cards_sent", 0) > 0:
                        cards_sent_count = tool_result.get("cards_sent", 0)
                        llm_tool_msg = (
                            f"SUCCESS: {cards_sent_count} interactive product card(s) have been sent "
                            f"directly to the customer's chat as rich media messages. "
                            f"Each card shows the product image, name, price, and action buttons. "
                            f"DO NOT list these products again in your text response — "
                            f"the customer has already received them visually. "
                            f"Instead, briefly acknowledge that you've shared the products "
                            f"and ask if they'd like to order or see more."
                        )
                    else:
                        llm_tool_msg = json.dumps(tool_result, default=str)

                    # Add tool result to conversation
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": llm_tool_msg
                    })

            # If we exhausted iterations, return whatever we have
            final_text = response.content or f"Thank you for your patience! Our team at {business_name} will assist you shortly."

            # Strip bare image URLs from text — images only go through cards
            text_image_urls = extract_image_urls(final_text)
            if text_image_urls:
                final_text = strip_image_urls(final_text, text_image_urls)

            # If product cards were sent, clear image_urls
            if collected_product_cards:
                image_urls = []
            else:
                image_urls = _dedupe_keep_order(collected_image_urls)

            final_text = self._format_for_channel(final_text, platform)

            if order_created and getattr(settings, "ORDER_TRACKING_ENABLED", True):
                # Let the order tracking service handle all confirmations and payment buttons.
                # Suppress the LLM's response to prevent double-prompting.
                # BUT save a hidden context to the CCM so the LLM knows the order ID for M-Pesa payments!
                oid = order_data.get("order_id") if isinstance(order_data, dict) else ""
                hidden_context = f"[SYSTEM: Order {oid} was successfully created. Do not mention this to the user.]"
                await self._save_to_ccm(session_key, "assistant", hidden_context)
                final_text = ""
            else:
                await self._save_to_ccm(session_key, "assistant", final_text)

            return {
                "response_text": final_text,
                "image_urls": image_urls,
                "cards": collected_product_cards,
                "order_created": order_created,
                "order_cancelled": order_cancelled,
                "order_data": order_data,
                "order_notification": order_notification,
                "escalation_triggered": escalation_triggered,
                "escalation_notification": escalation_notification,
                "human_handoff": human_handoff,
                "actions_taken": actions_taken,
                "send_cart_buttons": send_cart_buttons_after_turn and not order_created,
                "send_agent_mode_buttons": send_agent_mode_buttons,
            }

        except Exception as e:
            logger.error(f"[CONV_AGENT] Execute error: {e}", exc_info=True)
            return self._fallback_response(
                business_config.get("business_name", "Our Business"),
                error_code="exception",
                business_phone=business_config.get("business_phone", ""),
            )

    def _detect_channel_platform(self, explicit_platform: Optional[str], session_key: str) -> str:
        """Resolve channel platform for formatting rules."""
        if explicit_platform in {"whatsapp", "telegram"}:
            return explicit_platform
        if session_key.startswith("ccm:whatsapp:"):
            return "whatsapp"
        if session_key.startswith("ccm:telegram:"):
            return "telegram"
        return "whatsapp"

    def _format_for_channel(self, text: str, platform: str) -> str:
        """
        Normalize assistant text for WhatsApp/Telegram rendering.
        Keeps emphasis simple and avoids markdown patterns that degrade on chat clients.
        """
        if not text:
            return text

        # Strip fenced code blocks and markdown headers.
        text = re.sub(r"```[\s\S]*?```", "", text)
        text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.MULTILINE)

        # Replace markdown bullets with a chat-friendly symbol.
        text = re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.MULTILINE)

        # Keep bold/italic patterns broadly compatible:
        # - Convert markdown __bold__ to WhatsApp/Telegram *bold*.
        text = re.sub(r"__(.+?)__", r"*\1*", text)

        # Normalize excessive whitespace while preserving paragraph breaks.
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        return text

    def _ensure_image_urls_in_text(self, text: str, image_urls: List[str]) -> str:
        """
        Ensure image URLs are present in response text for backward compatibility.
        Older workflows may not map `step_1.image_urls` into send-message steps.
        """
        if not image_urls:
            return text
        existing = set(extract_image_urls(text))
        missing = [u for u in image_urls if u not in existing]
        if not missing:
            return text
        return f"{text}\n\nProduct images:\n" + "\n".join(missing)

    def _extract_image_urls_from_search_result(self, tool_result: Dict[str, Any]) -> List[str]:
        """
        Pull image URLs from search_products response payloads.
        Handles both synthesized text and raw RAG chunk data.
        """
        urls: List[str] = []
        urls.extend(extract_image_urls(str(tool_result.get("result", ""))))

        data = tool_result.get("data", {})
        results = data.get("results", []) if isinstance(data, dict) else []
        for item in results:
            if not isinstance(item, dict):
                continue
            urls.extend(extract_image_urls(str(item.get("text", ""))))
            urls.extend(extract_image_urls(str(item.get("source", ""))))
            urls.extend(extract_image_urls(str(item.get("file", ""))))
            # Some KB ingestion pipelines preserve extra metadata.
            for key in ("image_url", "image", "thumbnail", "photo_url", "media_url"):
                if item.get(key):
                    urls.extend(extract_image_urls(str(item.get(key))))

        return _dedupe_keep_order(urls)

    def _extract_structured_products_from_chunks(
        self, tool_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Extract per-chunk product data with strictly associated image URLs.

        Unlike _extract_image_urls_from_search_result (which pools all images),
        this method keeps each RAG chunk's images bound to that chunk's text.
        This prevents image cross-contamination when the LLM later maps
        products to image_urls for display_product_cards.

        Returns a list of dicts:
            [{"chunk_text": "...", "image_urls": ["https://..."]}, ...]
        """
        data = tool_result.get("data", {})
        results = data.get("results", []) if isinstance(data, dict) else []
        if not results:
            return []

        structured: List[Dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            chunk_text = item.get("text", "") or ""
            if not chunk_text.strip():
                continue

            # Collect image URLs ONLY from this specific chunk.
            # Prefer the image_urls bound to the chunk at ingestion (most reliable
            # product↔image link); fall back to parsing the chunk text.
            chunk_urls: List[str] = []
            meta_image_urls = item.get("image_urls")
            if isinstance(meta_image_urls, list):
                chunk_urls.extend([u for u in meta_image_urls if isinstance(u, str) and u])
            chunk_urls.extend(extract_image_urls(chunk_text))
            chunk_urls.extend(extract_image_urls(str(item.get("source", ""))))
            chunk_urls.extend(extract_image_urls(str(item.get("file", ""))))
            for key in ("image_url", "image", "thumbnail", "photo_url", "media_url"):
                val = item.get(key)
                if val:
                    chunk_urls.extend(extract_image_urls(str(val)))

            chunk_urls = _dedupe_keep_order(chunk_urls)
            structured.append({
                # Keep enough text to locate every product (this map is used only
                # for programmatic image correction, never sent to the LLM).
                "chunk_text": chunk_text[:8000],
                "image_urls": chunk_urls,
                # Highest-confidence binding: alt-text → URL from markdown images.
                "image_alt_map": extract_markdown_image_map(chunk_text),
            })

        return structured

    # Matches lines like "Image URL: https://..." or "Photo: https://..." in
    # legacy chunk text where images were not stored as markdown syntax.
    _LABELED_IMAGE_LINE_PATTERN = re.compile(
        r'^\s*(?:image\s*(?:url)?|photo(?:\s*url)?|picture(?:\s*url)?'
        r'|thumbnail(?:\s*url)?|img(?:\s*url)?|media(?:\s*url)?)'
        r'\s*[:=]\s*(https?://\S+)',
        re.IGNORECASE | re.MULTILINE,
    )

    @staticmethod
    def _normalize_product_name(value: str) -> str:
        """Lowercase, trim, and collapse whitespace for reliable name matching."""
        return re.sub(r"\s+", " ", (value or "").strip().lower())

    @staticmethod
    def _image_positions(text: str) -> List[Tuple[int, str]]:
        """Return [(position, url)] for every image URL in the text, in order."""
        out: List[Tuple[int, str]] = []
        seen = set()
        if not text:
            return out
        for m in _MARKDOWN_IMAGE_PATTERN.finditer(text):
            url = (m.group(2) or "").strip().rstrip('.,;:!?)"\'>]')
            if url and url not in seen:
                seen.add(url)
                out.append((m.start(), url))
        for pat in (_IMAGE_EXT_PATTERN, _IMAGE_HOST_PATTERN):
            for m in pat.finditer(text):
                url = (m.group(0) or "").rstrip('.,;:!?)"\'>]')
                if url and url not in seen:
                    seen.add(url)
                    out.append((m.start(), url))
        out.sort(key=lambda t: t[0])
        return out

    @classmethod
    def _bind_images_to_products(
        cls,
        products: List[Dict[str, Any]],
        chunk_map: List[Dict[str, Any]],
    ) -> Dict[str, str]:
        """
        Build {normalized_product_name: image_url} using three deterministic rules:

        1. **Exact alt-text** (highest confidence): an image written as
           ``![Product Name](url)`` whose alt-text equals a product name.
        2. **Positional**: every image belongs to the product whose name most
           recently precedes it in the chunk text.
        3. **Labeled URL** (legacy fallback): lines like
           ``Image URL: https://...`` are matched to the product whose name
           most recently precedes the line.  This handles chunks ingested
           before the markdown-image format was introduced.

        Works whether the catalog is one big blob chunk or one chunk per product.
        """
        target_names: List[str] = []
        for p in products:
            n = cls._normalize_product_name(p.get("name"))
            if n and n not in target_names:
                target_names.append(n)
        if not target_names:
            return {}

        result: Dict[str, str] = {}

        for chunk in chunk_map:
            text = chunk.get("chunk_text") or ""
            if not text:
                continue
            text_lower = text.lower()

            # Rule 1: alt-text exactly equals a product name.
            for alt_norm, url in (chunk.get("image_alt_map") or {}).items():
                if alt_norm in target_names and url:
                    result.setdefault(alt_norm, url)

            # Locate each product name's position within this chunk.
            name_positions: List[Tuple[int, str]] = []
            for n in target_names:
                pos = text_lower.find(n)
                if pos >= 0:
                    name_positions.append((pos, n))
            if not name_positions:
                continue
            name_positions.sort(key=lambda t: t[0])

            # Rule 2: assign each image to the closest product name (minimum absolute distance).
            for img_pos, url in cls._image_positions(text):
                best_owner = None
                min_dist = float("inf")
                for pos, n in name_positions:
                    dist = abs(pos - img_pos)
                    if dist < min_dist:
                        min_dist = dist
                        best_owner = n
                if best_owner:
                    result.setdefault(best_owner, url)  # first image per product wins

            # Rule 3 (legacy fallback): labeled URL lines like
            # "Image URL: https://...", "Photo: https://...", etc.
            # These exist in chunks ingested before the markdown format fix.
            for m in cls._LABELED_IMAGE_LINE_PATTERN.finditer(text):
                url = (m.group(1) or "").strip().rstrip('.,;:!?)"\'>[\]')
                if not url:
                    continue
                label_pos = m.start()
                best_owner = None
                min_dist = float("inf")
                for pos, n in name_positions:
                    dist = abs(pos - label_pos)
                    if dist < min_dist:
                        min_dist = dist
                        best_owner = n
                if best_owner:
                    result.setdefault(best_owner, url)

            # Rule 3b: single-product chunk with a single metadata image_url.
            # Per-row ingestion creates one chunk per product. If the chunk
            # mentions exactly one of our target products and carries exactly
            # one image in its metadata, we can safely bind them.
            chunk_image_urls = chunk.get("image_urls") or []
            if len(name_positions) == 1 and len(chunk_image_urls) == 1:
                sole_name = name_positions[0][1]
                result.setdefault(sole_name, chunk_image_urls[0])

        return result

    @classmethod
    def _correct_product_image_urls(
        cls,
        products: List[Dict[str, Any]],
        chunk_map: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Programmatic safety net that binds each product card to the CORRECT
        image, or no image at all.

        Runs *after* the LLM builds display_product_cards but *before* the cards
        are sent, so it catches image mix-ups (e.g. a soda showing a water photo)
        regardless of what the LLM did. Binding is deterministic and positional
        (see _bind_images_to_products): the image that follows a product in the
        catalog text is that product's image.
        """
        if not products or not chunk_map:
            return products

        name_to_url = cls._bind_images_to_products(products, chunk_map)

        corrected = []
        for product in products:
            product = dict(product)  # shallow copy to avoid mutating the original
            name = cls._normalize_product_name(product.get("name"))
            chosen_url = name_to_url.get(name) if name else None
            current_url = product.get("image_url", "") or ""

            if chosen_url:
                if current_url != chosen_url:
                    logger.info(
                        "[CONV_AGENT] 🔧 Image corrected for '%s': '%s' → '%s'",
                        product.get("name", "?"),
                        current_url[:40] or "(none)",
                        chosen_url[:60],
                    )
                product["image_url"] = chosen_url
            else:
                # Keep the LLM-provided image if available, as chunk mapping might have missed it
                if current_url:
                    logger.info(
                        "[CONV_AGENT] ⚠️ Keeping unverified image for '%s' (no confident match in chunks)",
                        product.get("name", "?"),
                    )
                product["image_url"] = current_url

            corrected.append(product)

        return corrected

    # ── Product parser: RAG chunks → structured product dicts ──────────

    _PRICE_LINE_RE = re.compile(
        r'(?:price|cost|bei|amount)\s*[:=]\s*(?:KES|Ksh|KSH|\$|USD|EUR)?\s*([\d,]+\.?\d*)',
        re.IGNORECASE,
    )
    _PRICE_DASH_RE = re.compile(
        r'[-–—]\s*(?:KES|Ksh|KSH|\$|USD|EUR)?\s*([\d,]+\.?\d*)',
    )
    _PRICE_ANYWHERE_RE = re.compile(
        r'(?:KES|Ksh|KSH|\$|USD|EUR)\s*([\d,]+\.?\d*)|([\d,]+\.?\d*)\s*(?:KES|Ksh|KSH|\$|USD|EUR)',
        re.IGNORECASE,
    )
    _MARKDOWN_IMG_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')

    @classmethod
    def _parse_products_from_search_results(
        cls, search_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Parse RAG search result chunks into structured product dicts
        ready for ``display_product_cards``.

        This replaces the previous approach of asking the LLM to extract
        id / name / price / description / image_url from free text, which
        was fragile and frequently dropped images or hallucinated prices.
        """
        results = search_data.get("results", []) if isinstance(search_data, dict) else []
        if not results:
            return []

        products: List[Dict[str, Any]] = []
        seen_names: set = set()

        for idx, item in enumerate(results):
            if not isinstance(item, dict):
                continue
            chunk_text = (item.get("text") or "").strip()
            if not chunk_text:
                continue

            name = ""
            price = 0.0
            desc_parts: List[str] = []
            image_url = ""

            # ── Image: prefer metadata, fallback to markdown in text ──
            meta_images = item.get("image_urls", [])
            if isinstance(meta_images, list) and meta_images:
                image_url = meta_images[0]

            lines = chunk_text.split("\n")
            for i, raw_line in enumerate(lines):
                line = raw_line.strip()
                if not line:
                    continue

                # Markdown image
                md_img = cls._MARKDOWN_IMG_RE.search(line)
                if md_img:
                    if not image_url:
                        image_url = md_img.group(2).strip()
                    continue

                # Label: Value
                label_m = re.match(r'^([A-Za-z][A-Za-z\s]{0,25}?)\s*:\s*(.+)$', line)
                if label_m:
                    label = label_m.group(1).strip().lower()
                    value = label_m.group(2).strip()

                    if label in ("price", "cost", "bei", "amount"):
                        num_m = re.search(r'[\d,]+\.?\d*', value.replace(",", ""))
                        if num_m:
                            try:
                                price = float(num_m.group())
                            except ValueError:
                                pass
                    elif label in ("description", "details", "maelezo", "info"):
                        desc_parts.append(value)
                    elif "image" in label or "photo" in label or "pic" in label or "thumb" in label:
                        if not image_url and value.startswith("http"):
                            image_url = value.rstrip('.,;:!?)\'">')
                    elif label in ("name", "product", "item", "title"):
                        if not name:
                            name = value
                    elif label not in ("id", "sku"):
                        desc_parts.append(f"{label.title()}: {value}")
                elif i == 0 and not name:
                    # First non-label line → product name.
                    # Also try to extract a trailing price  "Masala Tea - KES 100"
                    pm = cls._PRICE_DASH_RE.search(line)
                    if pm:
                        name = line[:pm.start()].strip().rstrip("-–— ")
                        if not price:
                            try:
                                price = float(pm.group(1).replace(",", ""))
                            except ValueError:
                                pass
                    else:
                        name = line
                elif not name:
                    name = line
                else:
                    desc_parts.append(line)

            # Fallback: try extracting price from full text if still 0
            if not price:
                pm = cls._PRICE_LINE_RE.search(chunk_text)
                if pm:
                    try:
                        price = float(pm.group(1).replace(",", ""))
                    except ValueError:
                        pass
            
            if not price:
                pm = cls._PRICE_ANYWHERE_RE.search(chunk_text)
                if pm:
                    val = pm.group(1) or pm.group(2)
                    if val:
                        try:
                            price = float(val.replace(",", ""))
                        except ValueError:
                            pass

            if not name:
                continue

            # Deduplicate
            name_norm = cls._normalize_product_name(name)
            if name_norm in seen_names:
                continue
            seen_names.add(name_norm)

            products.append({
                "id": f"prod_{idx}",
                "name": name,
                "price": price,
                "description": " | ".join(desc_parts[:3]) if desc_parts else "",
                "image_url": image_url or "",
            })

        return products[:10]

    # ═══════════════════════════════════════════════════════════
    # SYSTEM PROMPT BUILDER.
    # ═══════════════════════════════════════════════════════════

    def _build_system_prompt(
        self,
        business_name: str,
        order_type: str,
        currency: str,
        delivery_methods: list,
        custom_prompt: str = "",
        customer_phone: str = "",
        customer_name: str = "",
        preferred_language: str = DEFAULT_LANGUAGE,
        auto_escalation_enabled: bool = True,
        business_config: Dict[str, Any] = None,
    ) -> str:
        """Build the business-specific system prompt for the AI agent."""

        delivery_str = ", ".join(delivery_methods) if delivery_methods else "delivery, pickup"
        customer_context = ""
        if customer_phone or customer_name:
            customer_context = "\n## Known customer (from WhatsApp) — ALREADY IDENTIFIED\n"
            if customer_name:
                customer_context += f"- Name on file: {customer_name}\n"
            if customer_phone:
                customer_context += (
                    f"- Phone on file: {customer_phone}\n"
                    "- Use this phone for order lookup and M-Pesa unless they ask to use a different number.\n"
                )
            customer_context += (
                "- **IMPORTANT**: You already have this customer's name and phone. "
                "Do NOT ask them to provide their name or phone number again. "
                "Use these values directly when calling `validate_order` and `create_order`. "
                "If the customer provides a different name or phone, use the new one instead.\n"
            )

        # Extract extra real estate configs
        scheduling_provider = (business_config or {}).get("scheduling_provider", "native")
        calendar_link = (business_config or {}).get("calendar_link", "")

        scheduling_instructions = ""
        if scheduling_provider in ["calendly", "google_calendar"] and calendar_link:
            scheduling_instructions = f"To schedule a viewing, provide this exact calendar link to the customer: {calendar_link}"
        else:
            scheduling_instructions = "To schedule a viewing, propose 3 available time slots in the next few days and ask them to choose one. Once they choose, confirm the slot."

        # Industry-specific context
        industry_context = {
            "food": (
                f"You are the ordering assistant for {business_name}, a food/restaurant business. "
                "Help customers browse the menu, recommend items, and place orders. "
                "Always mention prices when discussing menu items. "
                "Ask about portion sizes, sides, and drinks to upsell naturally."
            ),
            "clothing": (
                f"You are the shopping assistant for {business_name}, a clothing/fashion store. "
                "Help customers browse clothing, find their sizes, and place orders. "
                "When a customer asks to browse or looks for an item, IMMEDIATELY use the `search_products` tool to show them options. "
                "Do NOT block them by asking for size, color, or fit first. You can ask for preferences ONLY IF they explicitly ask for advice."
            ),
            "retail": (
                f"You are the shopping assistant for {business_name}, a retail store. "
                "Help customers find products, check availability, and place orders. "
                "Provide product details and pricing when available."
            ),
            "real_estate": (
                f"You are the real estate assistant for {business_name}, a property management or real estate company. "
                "Help clients find properties for rent or sale, schedule viewings, report maintenance issues, and manage rent payments.\n\n"
                "**REAL ESTATE STRICT RULES:**\n"
                "1. **Property Search:** When a user asks for properties, ALWAYS use the `search_products` tool. Properties are stored as products. **CRITICAL:** When constructing the `query` argument, keep it EXTREMELY SIMPLE and keyword-based (e.g., '3 bedroom Mombasa' or 'apartment'). NEVER include conversational phrases or strict numeric filters like 'under 66190 KES' in the query string, because extra words confuse the semantic search engine and return 0 results. Instead, use a broad keyword query and let the user see the options. NEVER hallucinate that you are searching.\n"
                "2. **Lead Qualification:** If the user's request is too broad, gently ask for preferences (Budget, Location, Bedrooms). However, if they have provided these or just want to see what you have, DO NOT block them. Immediately call `search_products` to show them the properties. ALWAYS remember preferences from previous messages.\n"
                "3. **Brochures:** If a customer asks for more details or a brochure for a specific property, check if a PDF or link is available in the knowledge base and share it. Alternatively, explicitly offer to send a 'property brochure PDF' via WhatsApp.\n"
                f"4. **Scheduling:** {scheduling_instructions}\n"
                "5. **Escalation:** If a customer expresses high urgency, says they want to buy immediately, or books a viewing, label them internally as a HOT LEAD so the human team gets notified.\n"
                "6. **Locations:** Always provide the property location. When a viewing is booked, ensure you provide the exact map location if available."
            ),
            "general": (
                f"You are the customer service assistant for {business_name}. "
                "Help customers with inquiries, browse products/services, and place orders."
            )
        }

        if order_type == "food":
            catalog_word = "menu"
        elif order_type in ("clothing", "apparel"):
            catalog_word = "collection"
        elif order_type == "real_estate":
            catalog_word = "properties"
        elif order_type == "services":
            catalog_word = "services"
        else:
            catalog_word = "catalog"

        base_context = industry_context.get(order_type, industry_context["general"])

        if order_type == "real_estate":
            prompt = f"""{base_context}

## Your Capabilities
- Search the property database to answer client questions using `search_products`.
- Display properties as interactive cards with images using `display_product_cards`.
- Escalate to a live human agent using `escalate_to_human` when needed.

## Conversation Flow
1. Greet the client warmly and ask how you can help (e.g., renting, buying, viewings).
2. When they ask for properties: ALWAYS use `search_products` to search the database.
3. NEVER list properties as plain text. ALWAYS use `display_product_cards` to show results.
4. Keep responses brief and friendly (WhatsApp chat style, under 150 words).
5. Always use {currency} for prices.
6. Use emojis naturally but sparingly (1-3 per message).
7. Do NOT mention "carts", "checkout", "orders", or "delivery" as this is a real estate service.
"""
        else:
            prompt = f"""{base_context}

## Your Capabilities
- Search the product {catalog_word} to answer customer questions
- Display products as interactive cards with images and "Add to Cart" buttons
- Collect customer details (name, phone, delivery address)
- Create orders when the customer is ready
- Calculate order totals
- Initiate M-Pesa payments
- Escalate to a live human agent using `escalate_to_human` when needed

## Order Flow
1. Greet the customer warmly and ask how you can help
2. When they browse: search the catalog, then ALWAYS use `display_product_cards` to show results
3. When they want to order: check the "Known customer" section below — if name and phone are already there, DO NOT ask for them again. Only ask for info that is genuinely missing.
4. Ask about delivery method ({delivery_str}) — if only one method is available, use it automatically without asking
5. If delivery, collect the delivery address — customers can *share their location pin* on WhatsApp (📍) instead of typing
6. If a delivery location is already saved in context below, use it — do not ask them to type the address again
7. IMPORTANT ON CHECKOUT: If the customer provides their name, phone, or delivery details (like answering a checkout prompt), YOU MUST IMMEDIATELY proceed with checkout. DO NOT start a new conversation or ask them to browse the {catalog_word}. If you need their delivery address, ask for it now.
8. Call `calculate_total` with the cart items to get the order total — this step is REQUIRED before creating the order
9. Call `validate_order`, then show a clear summary and ask the customer to reply *YES* to confirm
10. Only after they confirm, create the order using `create_order`
11. After order is created, offer M-Pesa payment using `initiate_mpesa_payment`
12. If a customer wants to cancel an order, FIRST call `get_user_orders` to show their orders with Cancel buttons — do NOT guess the Order ID and do NOT ask them to type it. NEVER ask the customer for their phone number — their orders are looked up automatically and securely from the WhatsApp number they are messaging from. If the order_id is already provided (e.g. from a button click), proceed directly with `cancel_order`
13. If a customer wants to see their order history, check, or track an order status, call `get_user_orders` (with no arguments — NEVER ask for or accept a typed phone number) then ALWAYS call `display_order_cards` with the results
14. If the customer has items in their cart (see Cart section below), reference the cart when summarizing their order
15. After placing an order, the customer automatically receives a receipt and status updates on WhatsApp — you do not need to send the receipt manually unless asked

## Cart Management (IMPORTANT)
- Customers can tap *View my cart*, *Clear cart*, or *Checkout* buttons, or type things like "my cart", "clear cart", "remove chicken", "change pilau to 2"
- Customers can also ASK to add items by typing things like "4 mutton biryani and 4 red bulls", "add chapati to my cart", etc.
- ALWAYS use `manage_cart` for ALL cart operations — do NOT pretend the cart changed without calling the tool
- `manage_cart` actions: add | view | clear | remove | set_quantity (quantity 0 removes)
- **Adding items flow**: When a customer asks for items, FIRST call `search_products` to find the correct name and price, THEN call `manage_cart(action="add", product_name=..., unit_price=..., quantity=...)` for EACH item. You MUST call `manage_cart` with action `add` to actually add items — just saying "I've added them" is NOT enough.
- After cart changes, keep replies short and friendly; mention they can tap the buttons below

## CRITICAL Product Display Rules
- ALWAYS use `display_product_cards` when showing products with images/prices
- NEVER list products as plain text with numbered lists — customers can't interact with text
- NEVER include raw image URLs (https://...) in your text responses
- After `display_product_cards` succeeds, just say something brief like "Here's what we have! 🛒 Tap a product to add it to your cart."
- Do NOT repeat product names, prices, or descriptions in text after cards are sent
- If `display_product_cards` fails, describe products briefly in text WITHOUT image URLs

## CRITICAL Order Display Rules
- ALWAYS use `display_order_cards` after `get_user_orders` returns orders
- NEVER list orders as plain text — customers need buttons to take action
- After `display_order_cards` succeeds, say something brief like "Here are your orders! Tap a button to take action. 📋"
- Do NOT repeat order IDs, statuses, or totals in text after cards are sent
- NEVER ask customers to type an Order ID — they should tap the Cancel button on the order card instead

## Navigation & Menus
- If the customer explicitly asks for the "menu", "help", "options", or "home", you MUST call `show_options_menu`.
- If you reach a dead end (e.g. cart cleared, order completed, nothing left to do) or don't understand the request, you MUST call `show_options_menu` to help them navigate.
- NEVER list the main menu options in plain text. Always use the `show_options_menu` tool.

## Response Style Rules
- Keep responses brief and friendly (WhatsApp chat style, under 150 words)
- Always use {currency} for prices
- Use emojis naturally but sparingly (1-3 per message)
- Never make up product information — always search the catalog first
- If the customer's request is unclear, ask a simple clarifying question
- Be conversational, not robotic. Sound like a helpful shop assistant, not a machine.

## Delivery & Payment
- Available delivery methods: {delivery_str}
- For M-Pesa: only initiate after order is confirmed and customer agrees to pay now
"""

        prompt += agent_intelligence.build_language_instruction(preferred_language)

        if auto_escalation_enabled:
            prompt += (
                "\n## Human escalation (IMPORTANT)\n"
                "- If the customer asks for a person, manager, or human agent — call `escalate_to_human` immediately.\n"
                "- If you cannot help after 2 attempts, or they are upset — call `escalate_to_human`.\n"
                "- For bulk/corporate orders, serious complaints, or unusual requests — escalate.\n"
                "- After escalating, send a short reassuring message in their language; do not keep troubleshooting.\n"
            )

        # ── Anti-hallucination & anti-false-escalation guardrails ──
        prompt += (
            "\n## ANTI-HALLUCINATION RULES (CRITICAL)\n"
            "- Messages that look like product/food names (e.g. 'masala tea', 'pilau', 'red bull', "
            "'chicken', 'burger', 'latte') are ALWAYS product search queries. "
            "You MUST call `search_products` for them. NEVER escalate for these.\n"
            "- NEVER say a product is unavailable unless `search_products` returned 0 results.\n"
            "- NEVER make up prices, product names, or descriptions. Always search the catalog first.\n"
            "- If the previous turn had a display issue (e.g. cards failed to send), "
            "try again by calling `search_products` and `display_product_cards`. Do NOT escalate.\n"
            "- NEVER list products as numbered plain text. ALWAYS use `display_product_cards`.\n"
        )

        if customer_context:
            prompt += customer_context

        if custom_prompt:
            prompt += f"\n## Additional Business Instructions\n{custom_prompt}\n"

        return prompt

    async def _detect_language_llm(
        self, text: str, supported: List[str]
    ) -> Optional[str]:
        """
        Refine language detection with a cheap LLM call for ambiguous messages
        (e.g. code-mixed Sheng) where the keyword heuristic is unreliable.
        Returns a language code from the allowed set, or None.
        """
        try:
            options = list(dict.fromkeys(list(supported) + (["sheng"] if "sw" in supported else [])))
            if not options:
                return None
            labels = ", ".join(options)
            resp = await self.llm_service.chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a language detector. Identify the language of the user's "
                            f"message and respond with ONLY one code from: {labels}. "
                            "Use 'sheng' for Kenyan Swahili-English street slang. "
                            "Return just the code, nothing else."
                        ),
                    },
                    {"role": "user", "content": (text or "")[:500]},
                ],
                temperature=0,
                max_tokens=5,
                provider="openai",
                use_background_model=True,
            )
            if resp and not getattr(resp, "error", None) and getattr(resp, "content", ""):
                code = re.sub(r"[^a-z]", "", resp.content.strip().lower())
                if code in options:
                    return code
        except Exception as e:
            logger.warning(f"[CONV_AGENT] LLM language detect failed: {e}")
        return None

    def _parse_supported_languages(self, raw: Any) -> List[str]:
        """Parse supported language codes from workflow config."""
        default = getattr(
            settings,
            "AGENT_DEFAULT_SUPPORTED_LANGUAGES",
            "en,sw,fr,ar,es",
        )
        if raw is None or raw == "":
            raw = default
        if isinstance(raw, list):
            codes = [str(x).strip().lower()[:2] for x in raw if x]
        else:
            codes = [p.strip().lower()[:2] for p in str(raw).split(",") if p.strip()]
        valid = [c for c in codes if c in LANGUAGE_PROFILES]
        return valid or ["en", "sw"]

    @staticmethod
    def _config_bool(value: Any, default: bool) -> bool:
        if value is None or value == "":
            return default
        if isinstance(value, bool):
            return value
        s = str(value).strip()
        if s.startswith("{{") or s.startswith("$"):
            return default
        return s.lower() in ("1", "true", "yes", "on")

    @staticmethod
    def _safe_int_config(value: Any, default: int) -> int:
        if value is None or value == "":
            return default
        if isinstance(value, int):
            return value
        s = str(value).strip()
        if s.startswith("{{") or s.startswith("$"):
            return default
        try:
            return int(float(s))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float_config(value: Any, default: float) -> float:
        if value is None or value == "":
            return default
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip()
        if s.startswith("{{") or s.startswith("$"):
            return default
        try:
            return float(s)
        except (TypeError, ValueError):
            return default

    async def _tag_contact_for_handoff(
        self,
        user: User,
        customer_phone: str,
        db: AsyncSession,
        reason: str = "",
    ) -> None:
        """Tag WhatsApp contact so the dashboard highlights human-handoff chats."""
        if not customer_phone:
            return
        try:
            from sqlalchemy import select, and_, or_
            from ..models import WhatsAppContact

            phone_clean = re.sub(r"\D", "", str(customer_phone))
            if not phone_clean:
                return
            suffix = phone_clean[-9:] if len(phone_clean) >= 9 else phone_clean
            result = await db.execute(
                select(WhatsAppContact).where(
                    and_(
                        WhatsAppContact.user_id == user.id,
                        or_(
                            WhatsAppContact.phone_number == customer_phone,
                            WhatsAppContact.phone_number.like(f"%{suffix}"),
                        ),
                    )
                ).limit(5)
            )
            contact = None
            for c in result.scalars().all():
                c_digits = re.sub(r"\D", "", c.phone_number or "")
                if c_digits and (
                    c_digits == phone_clean
                    or c_digits.endswith(suffix)
                    or phone_clean.endswith(c_digits[-9:] if len(c_digits) >= 9 else c_digits)
                ):
                    contact = c
                    break
            if not contact:
                return
            tags = list(contact.tags or [])
            for tag in ("human_handoff", "needs_attention"):
                if tag not in tags:
                    tags.append(tag)
            contact.tags = tags
            notes = contact.notes or ""
            marker = f"[Handoff: {reason}]"
            if marker not in notes:
                contact.notes = f"{notes}\n{marker}".strip() if notes else marker
            await db.commit()
        except Exception as e:
            logger.warning(f"[CONV_AGENT] Contact handoff tag failed: {e}")

    async def _build_delivery_location_block(self, session_key: str) -> str:
        if not session_key:
            return ""
        try:
            session = await context_manager.get_session_by_key(session_key)
            if not session:
                return ""
            loc = context_manager.get_delivery_location(session)
            if not loc:
                return ""
            addr = context_manager.get_delivery_address(session)
            maps_url = loc.get("maps_url", "")
            block = (
                f"\n## Saved delivery location (from WhatsApp 📍 — use for delivery)\n"
                f"Address: {addr}\n"
            )
            if maps_url:
                block += f"Map: {maps_url}\n"
            block += (
                "Include this in `delivery_address` for validate_order and create_order. "
                "Set delivery_method to delivery.\n"
            )
            return block
        except Exception as e:
            logger.warning(f"[CONV_AGENT] delivery location block failed: {e}")
            return ""

    async def _apply_saved_delivery_address(
        self,
        arguments: Dict[str, Any],
        session_key: str,
    ) -> Dict[str, Any]:
        """Fill delivery_address from CCM when the agent omitted it."""
        if arguments.get("delivery_address") or not session_key:
            return arguments
        try:
            session = await context_manager.get_session_by_key(session_key)
            if session:
                addr = context_manager.get_delivery_address(session)
                if addr:
                    arguments = {**arguments, "delivery_address": addr}
                    if not arguments.get("delivery_method"):
                        arguments["delivery_method"] = "delivery"
        except Exception:
            pass
        return arguments

    async def _build_cart_context_block(self, session_key: str, currency: str, catalog_word: str = "menu") -> str:
        if not session_key:
            return ""
        try:
            session = await context_manager.get_session_by_key(session_key)
            if not session:
                return ""
            cart = context_manager.get_cart(session)
            if not cart:
                return ""
            from .whatsapp_ordering_helpers import format_cart_summary
            summary = format_cart_summary(cart, currency, catalog_word)
            return (
                f"\n## Current cart (persisted — do not ignore)\n{summary}\n"
                "When the customer is ready to checkout, use these cart items for "
                "`calculate_total`, `validate_order`, and `create_order`.\n"
                "Use `manage_cart` to add more items, view, clear, remove, or update quantities.\n"
            )
        except Exception as e:
            logger.warning(f"[CONV_AGENT] cart context block failed: {e}")
            return ""

    async def _maybe_send_welcome_quick_replies(
        self,
        session_key: str,
        business_name: str,
        customer_name: str,
        user: User,
        db: AsyncSession,
        catalog_word: str = "menu",
    ) -> None:
        if not session_key or not session_key.startswith("ccm:whatsapp:"):
            return
        try:
            session = await context_manager.get_session_by_key(session_key)
            if not session or session.metadata.get("welcome_sent"):
                return
            user_msgs = [m for m in session.messages if m.get("role") == "user"]
            if len(user_msgs) > 2:
                return

            parts = session_key.split(":")
            recipient = parts[3] if len(parts) >= 4 else ""
            if not recipient:
                return

            from sqlalchemy import select
            from ..models import Connection, ConnectionStatus
            from .whatsapp_service import WhatsAppService

            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user.id,
                    Connection.platform == "whatsapp",
                    Connection.status == ConnectionStatus.ACTIVE,
                )
            )
            connection = result.scalar_one_or_none()
            if not connection:
                return
            config = connection.config or {}
            if not config.get("access_token") or not config.get("phone_number_id"):
                return

            greet_name = customer_name.split()[0] if customer_name else "there"
            body = (
                f"Hi {greet_name}! 👋 Welcome to *{business_name}*.\n\n"
                "Tap an option below or tell me what you'd like."
            )
            wa = WhatsAppService()
            await wa.send_quick_reply_buttons(
                to_number=recipient,
                body_text=body,
                buttons=[
                    {"id": "menu:browse", "title": f"Browse {catalog_word}"},
                    {"id": "agent:human", "title": "Talk to us"},
                    {"id": "menu:cart", "title": "View cart"},
                    {"id": "menu:orders", "title": "My orders"},
                    {"id": "menu:new_arrivals", "title": "New Arrivals"},
                    {"id": "menu:offers", "title": "Special Offers"},
                ],
                config={
                    "access_token": config.get("access_token"),
                    "phone_number_id": config.get("phone_number_id"),
                },
            )
            session.metadata["welcome_sent"] = True
            await context_manager.save_session(session)
        except Exception as e:
            logger.warning(f"[CONV_AGENT] welcome quick replies failed: {e}")

    @staticmethod
    def _t(lang: str, en: str, sw: str) -> str:
        """Tiny localization helper: Swahili when lang=='sw', else English."""
        return sw if (lang or "en").lower().startswith("sw") else en

    async def _resolve_checkout_delivery(
        self,
        session_key: str,
        explicit_method: Optional[str],
        delivery_methods: list,
    ) -> Tuple[Optional[str], str]:
        """
        Pick delivery method + address for checkout.
        Uses saved WhatsApp location when available; falls back to single-option config.
        """
        delivery_address = ""
        if explicit_method:
            if explicit_method == "delivery" and session_key:
                try:
                    session = await context_manager.get_session_by_key(session_key)
                    if session:
                        delivery_address = context_manager.get_delivery_address(session)
                except Exception:
                    pass
            return explicit_method, delivery_address

        if session_key:
            try:
                session = await context_manager.get_session_by_key(session_key)
                if session:
                    delivery_address = context_manager.get_delivery_address(session)
                    if delivery_address:
                        return "delivery", delivery_address
            except Exception:
                pass

        if isinstance(delivery_methods, list) and len(delivery_methods) == 1:
            method = delivery_methods[0]
            if method == "delivery" and session_key:
                try:
                    session = await context_manager.get_session_by_key(session_key)
                    if session:
                        delivery_address = context_manager.get_delivery_address(session)
                except Exception:
                    pass
            return method, delivery_address

        return None, delivery_address

    async def _start_checkout_flow(
        self,
        session_key: str,
        cart: List[Dict[str, Any]],
        currency: str,
        customer_name: str,
        customer_phone: str,
        delivery_methods: list,
        preferred_language: str = DEFAULT_LANGUAGE,
        catalog_word: str = "menu",
        user: Optional[User] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """Begin checkout: ask for missing details or jump straight to order summary."""
        resolved_delivery, saved_addr = await self._resolve_checkout_delivery(
            session_key, None, delivery_methods
        )

        if customer_phone and customer_name:
            logger.info("[CONV_AGENT] Checkout: customer known, presenting confirmation")
            return await self._present_checkout_confirmation(
                session_key=session_key,
                cart=cart,
                currency=currency,
                customer_name=customer_name,
                customer_phone=customer_phone,
                delivery_method=resolved_delivery,
                delivery_methods=delivery_methods,
                preferred_language=preferred_language,
                delivery_address=saved_addr,
                user=user,
                db=db,
            )

        await context_manager.update_session_metadata(
            session_key, {"awaiting_checkout_details": True}
        )
        from .whatsapp_ordering_helpers import format_cart_summary
        summary = format_cart_summary(cart, currency, catalog_word)
        missing = []
        if not customer_name:
            missing.append("1️⃣ Your name")
        if not customer_phone:
            missing.append("2️⃣ Your phone number")
        if len(delivery_methods) > 1 and not resolved_delivery:
            missing.append(
                f"{'3' if len(missing) == 2 else '2' if len(missing) == 1 else '1'}️⃣ "
                f"Delivery or pickup?"
            )
        missing_str = "\n".join(missing)
        reply = (
            f"{summary}\n\n"
            f"Great! To complete your order, please share:\n{missing_str}\n"
            "(I'll use your WhatsApp number for contact.)"
        )
        return await self._cart_fast_path_result(
            session_key,
            reply,
            actions_taken=[{"tool": "manage_cart", "result_summary": "checkout"}],
            send_cart_buttons=False,
        )

    async def _present_checkout_confirmation(
        self,
        session_key: str,
        cart: List[Dict[str, Any]],
        currency: str,
        customer_name: str,
        customer_phone: str,
        delivery_method: Optional[str],
        delivery_methods: list,
        preferred_language: str = DEFAULT_LANGUAGE,
        delivery_address: str = "",
        user: Optional[User] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Deterministic checkout step: if the delivery method is still ambiguous,
        ask for it; otherwise compute the total, persist the pending order, and
        ask the customer to reply YES to confirm.
        """
        from .whatsapp_ordering_helpers import format_checkout_confirmation

        # Auto-pick delivery when a saved address exists or only one method is offered
        if not delivery_method:
            delivery_method, auto_addr = await self._resolve_checkout_delivery(
                session_key, None, delivery_methods
            )
            if auto_addr and not delivery_address:
                delivery_address = auto_addr

        # Still need the customer to choose delivery vs pickup
        if not delivery_method:
            await context_manager.update_session_metadata(
                session_key,
                {
                    "awaiting_checkout_details": True,
                    "checkout_draft": {
                        "name": customer_name or "",
                        "phone": customer_phone or "",
                        "delivery_method": "",
                        "stage": "need_delivery",
                    },
                },
            )
            return await self._cart_fast_path_result(
                session_key,
                self._t(
                    preferred_language,
                    "Got it! One last thing — would you like *delivery* or *pickup*? 🚚🏬",
                    "Sawa! Jambo la mwisho — ungependa *delivery* au *pickup*? 🚚🏬",
                ),
                actions_taken=[{"tool": "checkout", "result_summary": "need_delivery_method"}],
                send_cart_buttons=False,
            )

        # Fill delivery address from a saved WhatsApp location pin when delivering
        if delivery_method == "delivery" and not delivery_address:
            try:
                session = await context_manager.get_session_by_key(session_key)
                if session:
                    delivery_address = context_manager.get_delivery_address(session)
            except Exception:
                delivery_address = ""

        # Require delivery address if still missing
        if delivery_method == "delivery" and not delivery_address:
            await context_manager.update_session_metadata(
                session_key,
                {
                    "awaiting_checkout_details": True,
                    "checkout_draft": {
                        "name": customer_name or "",
                        "phone": customer_phone or "",
                        "delivery_method": "delivery",
                        "delivery_address": "",
                        "stage": "need_delivery_address",
                    },
                },
            )
            return await self._cart_fast_path_result(
                session_key,
                self._t(
                    preferred_language,
                    "Almost done! Please provide your *delivery address* or drop a WhatsApp location pin 📍.",
                    "Tumekaribia! Tafadhali nipe *mahali pa kuleta mzigo* au tuma location pin ya WhatsApp 📍.",
                ),
                actions_taken=[{"tool": "checkout", "result_summary": "need_delivery_address"}],
                send_cart_buttons=False,
            )

        # Compute total and persist the pending order
        total_result = await self.order_service.handle_operation(
            operation="calculate_order_total",
            items=cart,
            currency=currency,
        )
        try:
            await context_manager.set_pending_confirmation(session_key, cart, total_result)
            await context_manager.update_session_metadata(
                session_key,
                {
                    "checkout_customer": {
                        "name": customer_name,
                        "phone": customer_phone,
                        "delivery_method": delivery_method,
                        "delivery_address": delivery_address,
                    },
                    "awaiting_order_confirmation": True,
                    "awaiting_checkout_details": False,
                    "checkout_draft": {},
                },
            )
        except Exception as e:
            logger.warning(f"[CONV_AGENT] present_checkout persist failed: {e}")

        reply = format_checkout_confirmation(
            cart=cart,
            currency=currency,
            customer_name=customer_name,
            customer_phone=customer_phone,
            delivery_method=delivery_method,
            delivery_address=delivery_address,
            lang=preferred_language,
        )

        # Show a tappable "Pay with M-Pesa" button (after the summary text) so the
        # customer can confirm + pay in one tap — no need to type "YES". The button
        # is dispatched by the whatsapp_send_message step, after this reply.
        return await self._cart_fast_path_result(
            session_key,
            reply,
            actions_taken=[{"tool": "checkout", "result_summary": "awaiting_confirmation"}],
            send_cart_buttons=False,
            send_checkout_pay_button=True,
        )

    async def _send_checkout_pay_button(
        self,
        session_key: str,
        user: Optional[User],
        db: Optional[AsyncSession],
        to_number: str = "",
        preferred_language: Optional[str] = None,
    ) -> None:
        """Send the 'Pay with M-Pesa' confirm button on the checkout screen."""
        if not user or not db or not session_key or not session_key.startswith("ccm:whatsapp:"):
            return
        try:
            parts = session_key.split(":")
            recipient = parts[3] if len(parts) >= 4 else ""
            if not recipient and to_number:
                recipient = str(to_number).strip().replace(" ", "")
            if not recipient:
                return

            from sqlalchemy import select
            from ..models import Connection, ConnectionStatus
            from .whatsapp_service import WhatsAppService

            if not preferred_language:
                try:
                    _sess = await context_manager.get_session_by_key(session_key)
                    preferred_language = (
                        context_manager.get_preferred_language(_sess)
                        if _sess else DEFAULT_LANGUAGE
                    )
                except Exception:
                    preferred_language = DEFAULT_LANGUAGE

            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user.id,
                    Connection.platform == "whatsapp",
                    Connection.status == ConnectionStatus.ACTIVE,
                )
            )
            connection = result.scalar_one_or_none()
            if not connection:
                return
            config = connection.config or {}
            if not config.get("access_token") or not config.get("phone_number_id"):
                return

            body_text = self._t(
                preferred_language,
                "Ready to pay? Tap *Pay with M-Pesa* and I'll send a prompt to your phone. 📲",
                "Uko tayari kulipa? Bonyeza *Pay with M-Pesa* nitatuma ombi kwa simu yako. 📲",
            )
            pay_label = self._t(preferred_language, "Pay with M-Pesa", "Lipa na M-Pesa")
            btn_result = await WhatsAppService().send_quick_reply_buttons(
                to_number=recipient,
                body_text=body_text,
                buttons=[{"id": "checkout_confirm_pay", "title": pay_label}],
                config={
                    "access_token": config.get("access_token"),
                    "phone_number_id": config.get("phone_number_id"),
                },
            )
            if not btn_result.get("success"):
                logger.warning(
                    f"[CONV_AGENT] checkout pay button failed: {btn_result.get('error')}"
                )
        except Exception as e:
            logger.warning(f"[CONV_AGENT] checkout pay button failed: {e}", exc_info=True)

    async def _cart_fast_path_result(
        self,
        session_key: str,
        reply: str,
        actions_taken: Optional[List[Dict[str, Any]]] = None,
        send_cart_buttons: bool = False,
        send_checkout_pay_button: bool = False,
    ) -> Dict[str, Any]:
        """
        Cart command result — text goes out via workflow whatsapp_send_message step
        (same path as all other replies). Buttons optionally after that in tool_executor.
        """
        if session_key and reply:
            await self._save_to_ccm(session_key, "assistant", reply)
        return {
            "response_text": reply,
            "image_urls": [],
            "cards": [],
            "order_created": False,
            "order_cancelled": False,
            "order_data": None,
            "order_notification": "",
            "escalation_triggered": False,
            "escalation_notification": "",
            "human_handoff": False,
            "actions_taken": actions_taken or [],
            "send_cart_buttons": send_cart_buttons,
            "send_checkout_pay_button": send_checkout_pay_button,
            "send_agent_mode_buttons": None,
        }

    async def _send_cart_action_buttons(
        self,
        session_key: str,
        user: User,
        db: AsyncSession,
        body_text: str = "What would you like to do next?",
        currency: str = "KES",
        to_number: str = "",
    ) -> None:
        """Cart screen: remove-item list (if not empty) + checkout / add / clear buttons."""
        if not session_key or not session_key.startswith("ccm:whatsapp:"):
            return
        try:
            parts = session_key.split(":")
            recipient = parts[3] if len(parts) >= 4 else ""
            if not recipient and to_number:
                recipient = str(to_number).strip().replace(" ", "")
            if not recipient:
                logger.warning(
                    f"[CONV_AGENT] cart buttons: no recipient (session_key={session_key!r})"
                )
                return

            from sqlalchemy import select
            from ..models import Connection, ConnectionStatus
            from .whatsapp_service import WhatsAppService
            from .whatsapp_ordering_helpers import (
                build_cart_remove_list_rows,
                cart_action_buttons,
            )

            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user.id,
                    Connection.platform == "whatsapp",
                    Connection.status == ConnectionStatus.ACTIVE,
                )
            )
            connection = result.scalar_one_or_none()
            if not connection:
                logger.warning(
                    f"[CONV_AGENT] cart buttons: no active WhatsApp connection for user {user.id}"
                )
                return
            config = connection.config or {}
            if not config.get("access_token") or not config.get("phone_number_id"):
                logger.warning("[CONV_AGENT] cart buttons: missing WhatsApp credentials")
                return

            wa_config = {
                "access_token": config.get("access_token"),
                "phone_number_id": config.get("phone_number_id"),
            }
            wa = WhatsAppService()

            session = await context_manager.get_session_by_key(session_key)
            cart = context_manager.get_cart(session) if session else []
            has_items = len(cart) > 0

            catalog_word = "menu"
            if session and session.metadata:
                catalog_word = session.metadata.get("catalog_word", "menu")

            sections = []
            if has_items:
                remove_rows = build_cart_remove_list_rows(cart, currency)
                if remove_rows:
                    sections.append({"title": "Remove an item", "rows": remove_rows})

            button_body = (
                body_text[:1024]
                if body_text and body_text != "What would you like to do next?"
                else (
                    "Ready to checkout or keep shopping? 🛒"
                    if has_items
                    else f"Your cart is empty — browse the {catalog_word} to add items."
                )
            )

            actions = cart_action_buttons(cart_has_items=has_items, catalog_word=catalog_word)
            action_rows = [{"id": btn["id"][:200], "title": btn["title"][:24]} for btn in actions]
            # Put main actions first
            sections.insert(0, {"title": "Actions", "rows": action_rows})

            btn_result = await wa.send_list_message(
                to_number=recipient,
                body_text=button_body,
                button_label="Options",
                sections=sections,
                config=wa_config,
            )
            if not btn_result.get("success"):
                logger.warning(
                    f"[CONV_AGENT] cart action buttons failed: {btn_result.get('error')}"
                )
        except Exception as e:
            logger.warning(f"[CONV_AGENT] cart action buttons failed: {e}", exc_info=True)

    async def _send_agent_mode_buttons(
        self,
        session_key: str,
        user: User,
        db: AsyncSession,
        *,
        handoff_active: bool,
        to_number: str = "",
    ) -> None:
        """Send Talk to us / Order with AI reply buttons after handoff or release."""
        if not session_key or not session_key.startswith("ccm:whatsapp:"):
            return
        try:
            parts = session_key.split(":")
            recipient = parts[3] if len(parts) >= 4 else ""
            if not recipient and to_number:
                recipient = str(to_number).strip().replace(" ", "")
            if not recipient:
                return

            from sqlalchemy import select
            from ..models import Connection, ConnectionStatus
            from .whatsapp_service import WhatsAppService
            from .whatsapp_ordering_helpers import (
                agent_mode_buttons,
                agent_mode_button_body,
            )

            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user.id,
                    Connection.platform == "whatsapp",
                    Connection.status == ConnectionStatus.ACTIVE,
                )
            )
            connection = result.scalar_one_or_none()
            if not connection:
                return
            config = connection.config or {}
            if not config.get("access_token") or not config.get("phone_number_id"):
                return

            catalog_word = "menu"
            session = await context_manager.get_session_by_key(session_key)
            if session and session.metadata:
                catalog_word = session.metadata.get("catalog_word", "menu")

            wa = WhatsAppService()
            btn_result = await wa.send_quick_reply_buttons(
                to_number=recipient,
                body_text=agent_mode_button_body(handoff_active),
                buttons=agent_mode_buttons(handoff_active, catalog_word=catalog_word),
                config={
                    "access_token": config.get("access_token"),
                    "phone_number_id": config.get("phone_number_id"),
                },
            )
            if not btn_result.get("success"):
                logger.warning(
                    f"[CONV_AGENT] agent mode buttons failed: {btn_result.get('error')}"
                )
        except Exception as e:
            logger.warning(f"[CONV_AGENT] agent mode buttons failed: {e}", exc_info=True)

    # ═══════════════════════════════════════════════════════════
    # CONVERSATION HISTORY (CCM integration)
    # ═══════════════════════════════════════════════════════════

    async def _load_conversation_history(
        self, session_key: str, system_prompt: str
    ) -> List[Dict[str, str]]:
        """Load conversation history from CCM and format for the LLM."""
        messages = [{"role": "system", "content": system_prompt}]

        if not session_key:
            return messages

        try:
            from .conversation_context_manager import context_manager

            # Try to load session by key
            session = await context_manager.get_session_by_key(session_key)
            if not session:
                return messages

            # Get context messages (includes history)
            context_messages = await context_manager.get_context_messages(
                session, system_prompt=system_prompt, max_tokens=2000
            )

            if context_messages and len(context_messages) > 1:
                # context_messages already includes system prompt, use as-is
                return context_messages

        except Exception as e:
            logger.warning(f"[CONV_AGENT] Failed to load CCM history: {e}")

        return messages

    async def _save_to_ccm(self, session_key: str, role: str, content: str):
        """Save a message to CCM conversation history."""
        if not session_key:
            return
        try:
            session = await context_manager.get_session_by_key(session_key)
            if session:
                await context_manager.add_message(session, role, content)
        except Exception as e:
            logger.warning(f"[CONV_AGENT] Failed to save to CCM: {e}")

    # ═══════════════════════════════════════════════════════════
    # SUB-TOOL EXECUTOR
    # ═══════════════════════════════════════════════════════════

    async def _execute_sub_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        kb_id: str,
        order_type: str,
        currency: str,
        business_name: str,
        storage_config: Dict[str, Any],
        session_key: str,
        user: User,
        db: AsyncSession,
        background_tasks: Optional['BackgroundTasks'] = None,
        user_message: str = "",
        default_customer_phone: str = "",
        default_customer_name: str = "",
        preferred_language: str = DEFAULT_LANGUAGE,
        business_phone: str = "",
    ) -> Dict[str, Any]:
        """Execute one of the agent's sub-tools."""

        try:
            # ── SECURITY: order & payment tools must ALWAYS use the phone number
            # that sent this WhatsApp message. Never trust a phone the LLM or the
            # customer typed — otherwise someone could view, track, or cancel
            # another person's orders (and trigger their payment) simply by
            # entering a different number (IDOR / data leak). ──
            if default_customer_phone:
                if tool_name in ("create_order", "validate_order", "cancel_order", "get_user_orders"):
                    if arguments.get("customer_phone") and arguments.get("customer_phone") != default_customer_phone:
                        logger.warning(
                            "[CONV_AGENT] 🔒 Overriding %s customer_phone %r → sender %r",
                            tool_name, arguments.get("customer_phone"), default_customer_phone,
                        )
                    arguments["customer_phone"] = default_customer_phone
                elif tool_name == "initiate_mpesa_payment":
                    if arguments.get("phone_number") and arguments.get("phone_number") != default_customer_phone:
                        logger.warning(
                            "[CONV_AGENT] 🔒 Overriding STK phone_number %r → sender %r",
                            arguments.get("phone_number"), default_customer_phone,
                        )
                    arguments["phone_number"] = default_customer_phone

            if tool_name == "escalate_to_human":
                return await self._sub_escalate_to_human(
                    arguments=arguments,
                    session_key=session_key,
                    business_name=business_name,
                    customer_phone=default_customer_phone,
                    customer_name=default_customer_name,
                    preferred_language=preferred_language,
                    user_message=user_message,
                    user=user,
                    db=db,
                )

            if tool_name == "search_products":
                return await self._sub_search_products(
                    query=arguments.get("query", ""),
                    kb_id=kb_id,
                    user=user,
                    db=db
                )

            elif tool_name == "create_order":
                if not arguments.get("customer_phone") and default_customer_phone:
                    arguments["customer_phone"] = default_customer_phone
                if not arguments.get("customer_name") and default_customer_name:
                    arguments["customer_name"] = default_customer_name
                return await self._sub_create_order(
                    arguments=arguments,
                    order_type=order_type,
                    currency=currency,
                    business_name=business_name,
                    storage_config=storage_config,
                    user=user,
                    db=db,
                    background_tasks=background_tasks,
                    session_key=session_key,
                    user_message=user_message,
                    business_phone=business_phone,
                )

            elif tool_name == "validate_order":
                if not arguments.get("customer_phone") and default_customer_phone:
                    arguments["customer_phone"] = default_customer_phone
                if not arguments.get("customer_name") and default_customer_name:
                    arguments["customer_name"] = default_customer_name
                return await self._sub_validate_order(
                    arguments=arguments,
                    order_type=order_type,
                    currency=currency,
                    session_key=session_key,
                )

            elif tool_name == "manage_cart":
                return await self._sub_manage_cart(
                    arguments=arguments,
                    session_key=session_key,
                    currency=currency,
                )

            elif tool_name == "calculate_total":
                return await self._sub_calculate_total(
                    items=arguments.get("items", []),
                    currency=currency,
                    session_key=session_key,
                )

            elif tool_name == "initiate_mpesa_payment":
                return await self._sub_initiate_mpesa_payment(
                    order_id=arguments.get("order_id", ""),
                    phone_number=arguments.get("phone_number", ""),
                    amount=arguments.get("amount", 0),
                    description=arguments.get("description", f"Payment to {business_name}"),
                    session_key=session_key,
                    storage_config=storage_config,
                    business_name=business_name,
                    user=user,
                    db=db,
                )
                
            elif tool_name == "display_product_cards":
                return await self._sub_display_product_cards(
                    products=arguments.get("products", []),
                    session_key=session_key,
                    currency=currency,
                    user=user,
                    db=db,
                    order_type=order_type,
                )

            elif tool_name == "cancel_order":
                if not arguments.get("customer_phone") and default_customer_phone:
                    arguments["customer_phone"] = default_customer_phone
                return await self._sub_cancel_order(
                    arguments=arguments,
                    storage_config=storage_config,
                    business_name=business_name,
                    currency=currency,
                    user=user,
                    db=db,
                    background_tasks=background_tasks,
                )

            elif tool_name == "get_user_orders":
                if not arguments.get("customer_phone") and default_customer_phone:
                    arguments["customer_phone"] = default_customer_phone
                return await self._sub_get_user_orders(
                    arguments=arguments,
                    storage_config=storage_config,
                    user=user,
                    db=db
                )

            elif tool_name == "display_order_cards":
                return await self._sub_display_order_cards(
                    orders=arguments.get("orders", []),
                    session_key=session_key,
                    currency=currency,
                    user=user,
                    db=db,
                )

            elif tool_name == "show_options_menu":
                return {
                    "success": True,
                    "result_summary": "options_menu_requested"
                }

            else:
                # Dynamic MCP Tool execution (Harness delegation)
                from .tool_executor import ToolExecutor
                executor = ToolExecutor()
                return await executor.execute_tool(tool_name, arguments, user, db, background_tasks=background_tasks)

        except Exception as e:
            logger.error(f"[CONV_AGENT] Sub-tool {tool_name} error: {e}")
            return {"success": False, "error": str(e)}

    async def _sub_escalate_to_human(
        self,
        arguments: Dict[str, Any],
        session_key: str,
        business_name: str,
        customer_phone: str,
        customer_name: str,
        preferred_language: str,
        user_message: str,
        user: User,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Pause AI and notify business owner for live human support."""
        reason_raw = (arguments.get("reason") or "agent_escalation").strip().lower()
        reason_map = {
            "customer_requested": "customer_requested_human",
            "customer_requested_human": "customer_requested_human",
            "frustrated": "high_frustration",
            "frustration": "high_frustration",
            "complex_request": "complex_query",
            "complex": "complex_query",
            "cannot_help": "agent_escalation",
            "complaint": "high_frustration",
        }
        reason = reason_map.get(reason_raw, "agent_escalation")

        if session_key:
            await context_manager.set_human_handoff(
                session_key, reason, escalated_by="agent"
            )

        lang_name = LANGUAGE_PROFILES.get(
            preferred_language, LANGUAGE_PROFILES[DEFAULT_LANGUAGE]
        )["name"]
        summary = (arguments.get("summary") or user_message or "")[:300]
        escalation_notification = agent_intelligence.format_escalation_notification(
            business_name=business_name,
            customer_name=customer_name,
            customer_phone=customer_phone,
            reason=reason,
            last_message=summary or user_message,
            language_name=lang_name,
        )

        await self._tag_contact_for_handoff(user, customer_phone, db, reason=reason)

        return {
            "success": True,
            "result": "Conversation escalated to human agent. AI paused for this customer.",
            "escalation_notification": escalation_notification,
            "human_handoff": True,
        }

    async def _sub_search_products(
        self, query: str, kb_id: str, user: User, db: AsyncSession
    ) -> Dict[str, Any]:
        """Search the business knowledge base via RAG."""
        if not kb_id:
            return {"success": False, "result": "No knowledge base configured for this business."}

        try:
            from .whatsapp_ordering_helpers import normalize_search_query
            from .tool_executor import ToolExecutor
            executor = ToolExecutor()

            normalized_query = normalize_search_query(query)
            result = await executor.execute_tool(
                "rag_search",
                {
                    "query": normalized_query,
                    "kb_id": kb_id,
                    "top_k": 5,
                    "rerank": True,
                    "rerank_top_n": 3
                },
                user, db
            )
            if not result.get("success") and normalized_query != query:
                result = await executor.execute_tool(
                    "rag_search",
                    {
                        "query": query,
                        "kb_id": kb_id,
                        "top_k": 5,
                        "rerank": True,
                        "rerank_top_n": 3,
                    },
                    user,
                    db,
                )
            logger.info(f"[CONV_AGENT] search_products result length: {len(str(result.get('result', '')))} chars")

            if result.get("success"):
                search_text = result.get("result", "No results found")

                # ── Build structured product-image mapping ──
                # Extract per-chunk image URLs so each product's image stays
                # strictly bound to its own RAG chunk.  This prevents the LLM
                # from accidentally swapping images between products.
                structured_chunks = self._extract_structured_products_from_chunks(result)

                # ── Pre-parse products so the LLM doesn't have to ──
                # This guarantees correct image_url bindings and prevents
                # the LLM from constructing a huge JSON that gets truncated.
                pre_parsed = self._parse_products_from_search_results(
                    result.get("data", {})
                )
                # Apply programmatic image correction from chunk map
                if pre_parsed and structured_chunks:
                    pre_parsed = self._correct_product_image_urls(
                        pre_parsed, structured_chunks
                    )

                products_json_block = ""
                if pre_parsed:
                    try:
                        products_json_block = (
                            "\n\nREADY_TO_DISPLAY_PRODUCTS (pass this array directly as the `products` argument to display_product_cards):\n"
                            + json.dumps(pre_parsed, ensure_ascii=False)
                        )
                    except (TypeError, ValueError):
                        products_json_block = ""

                # Build concise instruction
                if products_json_block:
                    instruction = (
                        "\n\nINSTRUCTION: Call `display_product_cards` NOW with the READY_TO_DISPLAY_PRODUCTS "
                        "JSON array above as the `products` argument. Do NOT modify the products — pass them as-is. "
                        "Do NOT list products as plain text. "
                        "If the customer explicitly asked to ADD items to their cart, also call "
                        "`manage_cart(action='add', product_name=..., unit_price=..., quantity=...)` "
                        "for each item they requested."
                    )
                else:
                    # Fallback: include chunk map so LLM can extract manually
                    structured_block = ""
                    if structured_chunks:
                        chunks_with_images = [
                            c for c in structured_chunks if c.get("image_urls")
                        ]
                        if chunks_with_images:
                            try:
                                structured_block = (
                                    "\n\nSTRUCTURED_PRODUCT_IMAGE_MAP:\n"
                                    + json.dumps(chunks_with_images, ensure_ascii=False)
                                )
                            except (TypeError, ValueError):
                                structured_block = ""
                    products_json_block = structured_block
                    instruction = (
                        "\n\nINSTRUCTION: If products were found, call `display_product_cards` to show them. "
                        "Extract each product's id, name, price, description, and image_url. "
                        "CRITICAL: If the search results indicate the product is not found or not in context, "
                        "DO NOT call `display_product_cards` and do NOT invent products. Just apologize to the customer. "
                        "Do NOT list products as plain text. "
                        "If the customer explicitly asked to ADD items, also call "
                        "`manage_cart(action='add', product_name=..., unit_price=..., quantity=...)` "
                        "for each item they requested."
                    )

                return {
                    "success": True,
                    "result": f"{search_text}{products_json_block}{instruction}",
                    "data": result.get("data", {})
                }
            else:
                return {"success": False, "result": result.get("error", "Search failed")}

        except Exception as e:
            logger.error(f"[CONV_AGENT] RAG search error: {e}")
            return {"success": False, "result": f"Search error: {str(e)}"}

    async def _sub_validate_order(
        self,
        arguments: Dict[str, Any],
        order_type: str,
        currency: str,
        session_key: str = "",
    ) -> Dict[str, Any]:
        """Validate order fields before confirmation."""
        try:
            arguments = await self._apply_saved_delivery_address(arguments, session_key)
            order_data = {
                "customer": {
                    "name": arguments.get("customer_name", ""),
                    "phone": arguments.get("customer_phone", ""),
                },
                "items": arguments.get("items", []),
                "delivery_method": arguments.get("delivery_method", "pickup"),
                "delivery_address": arguments.get("delivery_address", ""),
                "currency": currency,
                "order_type": order_type,
            }
            result = await self.order_service.handle_operation(
                operation="validate_order",
                order_data=order_data,
                order_type=order_type,
            )
            is_valid = result.get("is_valid", False)
            if is_valid:
                result["result"] = (
                    f"{result.get('message', 'Order looks good.')}\n"
                    "INSTRUCTION: Show the customer a clear order summary with total, "
                    "then ask them to reply YES to confirm before calling create_order."
                )
            return {
                "success": is_valid,
                "result": result.get(
                    "message", result.get("error", "Validation failed")
                ),
                "data": result,
            }
        except Exception as e:
            return {"success": False, "result": f"Validation error: {str(e)}"}

    async def _sub_manage_cart(
        self,
        arguments: Dict[str, Any],
        session_key: str,
        currency: str,
        catalog_word: str = "menu",
    ) -> Dict[str, Any]:
        """Add items to, view, clear, remove, or update quantities in the persisted cart."""
        from .whatsapp_ordering_helpers import (
            format_cart_summary,
            cart_cleared_message,
            cart_item_removed_message,
            cart_quantity_updated_message,
        )

        action = (arguments.get("action") or "view").strip().lower()
        product_id = arguments.get("product_id", "") or ""
        product_name = arguments.get("product_name", "") or ""
        quantity = arguments.get("quantity")
        unit_price = arguments.get("unit_price")

        # Clean unit_price and quantity
        clean_price = 0.0
        if unit_price is not None:
            try:
                if isinstance(unit_price, str):
                    import re
                    cleaned = re.sub(r'[^\d.]', '', unit_price)
                    clean_price = float(cleaned) if cleaned else 0.0
                else:
                    clean_price = float(unit_price)
            except (ValueError, TypeError):
                clean_price = 0.0

        clean_qty = 1.0
        if quantity is not None:
            try:
                if isinstance(quantity, str):
                    import re
                    cleaned = re.sub(r'[^\d.]', '', str(quantity))
                    clean_qty = float(cleaned) if cleaned else 1.0
                else:
                    clean_qty = float(quantity)
            except (ValueError, TypeError):
                clean_qty = 1.0

        if not session_key:
            return {"success": False, "result": "No active session for cart."}

        try:
            if action == "add":
                if not product_name:
                    return {
                        "success": False,
                        "result": "product_name is required to add an item to the cart.",
                    }
                item = {
                    "id": product_id or product_name[:50],
                    "name": product_name,
                    "quantity": clean_qty,
                    "unit_price": clean_price,
                }
                cart = await context_manager.add_cart_item(session_key, item)
                # The item is now persisted. Never let a formatting error turn a
                # successful add into a failure the customer sees as an error.
                try:
                    summary = format_cart_summary(cart, currency, catalog_word)
                except Exception as fmt_err:
                    logger.warning(f"[CONV_AGENT] cart summary format failed: {fmt_err}")
                    summary = ""
                result_text = f"✅ Added *{product_name}* × {item['quantity']:g} to the cart."
                if summary:
                    result_text += f"\n\n{summary}"
                return {
                    "success": True,
                    "result": result_text,
                    "cart": cart,
                    "cart_empty": False,
                }
            if action == "view":
                session = await context_manager.get_session_by_key(session_key)
                cart = context_manager.get_cart(session) if session else []
                summary = format_cart_summary(cart, currency, catalog_word)
                return {
                    "success": True,
                    "result": summary,
                    "cart": cart,
                    "cart_empty": len(cart) == 0,
                }

            if action == "clear":
                await context_manager.clear_cart(session_key)
                return {
                    "success": True,
                    "result": cart_cleared_message(catalog_word),
                    "cart": [],
                    "cart_empty": True,
                }

            if action == "remove":
                cart, removed, removed_name = await context_manager.remove_cart_item(
                    session_key, product_id=product_id, product_name=product_name
                )
                if removed:
                    msg = (
                        f"{cart_item_removed_message(removed_name)}\n\n"
                        f"{format_cart_summary(cart, currency, catalog_word)}"
                    )
                else:
                    label = product_name or product_id or "that item"
                    msg = (
                        f"I couldn't find *{label}* in your cart.\n\n"
                        f"{format_cart_summary(cart, currency, catalog_word)}"
                    )
                return {
                    "success": True,
                    "result": msg,
                    "cart": cart,
                    "removed": removed,
                }

            if action == "set_quantity":
                if quantity is None:
                    return {
                        "success": False,
                        "result": "Please specify quantity for set_quantity.",
                    }
                qty = clean_qty
                cart, ok, item_name, key = await context_manager.set_cart_item_quantity(
                    session_key,
                    qty,
                    product_id=product_id,
                    product_name=product_name,
                )
                if not ok:
                    label = product_name or product_id or "that item"
                    return {
                        "success": False,
                        "result": (
                            f"I couldn't find *{label}* in your cart.\n\n"
                            f"{format_cart_summary(cart, currency, catalog_word)}"
                        ),
                        "cart": cart,
                    }
                msg = (
                    f"{cart_quantity_updated_message(item_name, qty)}\n\n"
                    f"{format_cart_summary(cart, currency, catalog_word)}"
                )
                return {
                    "success": True,
                    "result": msg,
                    "cart": cart,
                }

            return {"success": False, "result": f"Unknown cart action: {action}"}

        except Exception as e:
            logger.error(f"[CONV_AGENT] manage_cart error: {e}")
            return {"success": False, "result": f"Cart error: {str(e)}"}

    async def _sub_create_order(
        self,
        arguments: Dict[str, Any],
        order_type: str,
        currency: str,
        business_name: str,
        storage_config: Dict[str, Any] = None,
        user: User = None,
        db: AsyncSession = None,
        background_tasks: Optional['BackgroundTasks'] = None,
        session_key: str = "",
        user_message: str = "",
        business_phone: str = "",
    ) -> Dict[str, Any]:
        """Create an order via OrderService, then persist to connected storage."""
        try:
            from .whatsapp_ordering_helpers import is_order_confirmation_message

            arguments = await self._apply_saved_delivery_address(arguments, session_key)

            session = None
            if session_key:
                session = await context_manager.get_session_by_key(session_key)
            pending = (
                session.metadata.get("pending_confirmation") if session else None
            )
            confirmed = (
                is_order_confirmation_message(user_message)
                or (session and session.metadata.get("order_confirmed"))
            )
            if not pending:
                # Try to auto-create pending_confirmation from cart
                if session_key:
                    cart_session = await context_manager.get_session_by_key(session_key)
                    cart = context_manager.get_cart(cart_session) if cart_session else []
                    if cart:
                        logger.info(
                            "[CONV_AGENT] create_order: auto-creating pending_confirmation from cart (%d items)",
                            len(cart),
                        )
                        await context_manager.set_pending_confirmation(
                            session_key, cart, {"source": "auto_from_cart_at_create"}
                        )
                        pending = {"items": cart}
                if not pending:
                    return {
                        "success": False,
                        "result": (
                            "CHECKOUT_REQUIRED: Call calculate_total first, show the customer "
                            "the order summary with total, then ask them to reply YES (or Ndio) "
                            "to confirm before create_order."
                        ),
                        "error": "CHECKOUT_REQUIRED",
                    }
            if not confirmed:
                return {
                    "success": False,
                    "result": (
                        "ORDER_NOT_CONFIRMED: The customer has not confirmed yet. "
                        "Show them the order summary with total and ask them to reply "
                        "YES (or Ndio) to confirm. Do NOT call create_order until they confirm."
                    ),
                    "error": "ORDER_NOT_CONFIRMED",
                }

            order_result = await self.order_service.handle_operation(
                operation="create_order",
                customer_name=arguments.get("customer_name", ""),
                customer_phone=arguments.get("customer_phone", ""),
                customer_email=arguments.get("customer_email", ""),
                items=arguments.get("items", []),
                order_type=order_type,
                delivery_method=arguments.get("delivery_method", "pickup"),
                delivery_address=arguments.get("delivery_address", ""),
                notes=arguments.get("notes", ""),
                currency=currency,
                business_name=business_name
            )

            if order_result.get("success"):
                order_obj = order_result.get("order") or order_result
                if session_key:
                    try:
                        session = await context_manager.get_session_by_key(session_key)
                        loc = (
                            context_manager.get_delivery_location(session)
                            if session
                            else {}
                        )
                        if loc:
                            order_obj["delivery_location"] = loc
                            order_obj["delivery_latitude"] = loc.get("latitude")
                            order_obj["delivery_longitude"] = loc.get("longitude")
                    except Exception:
                        pass

                receipt = await self.order_service.handle_operation(
                    operation="format_order_receipt",
                    order_data=order_obj,
                    business_name=business_name,
                    business_phone=business_phone,
                    currency=currency,
                )
                order_result["receipt"] = receipt.get("result", "")

                if storage_config and storage_config.get("provider") not in (None, "", "none"):
                    await self._persist_to_storage(
                        order_data=order_obj,
                        storage_config=storage_config,
                        business_name=business_name,
                        user=user,
                        db=db,
                        background_tasks=background_tasks,
                    )

                if session_key:
                    try:
                        await context_manager.clear_pending_confirmation(session_key)
                    except Exception as e:
                        logger.warning(f"[CONV_AGENT] clear_pending_confirmation: {e}")

                if getattr(settings, "ORDER_TRACKING_ENABLED", True):
                    notify_phone = arguments.get("customer_phone", "")
                    if notify_phone and user:
                        if background_tasks:
                            background_tasks.add_task(
                                self._bg_notify_order_placed,
                                str(user.id),
                                notify_phone,
                                order_result,
                                business_name,
                                business_phone,
                                currency,
                            )
                        else:
                            await self._bg_notify_order_placed(
                                str(user.id),
                                notify_phone,
                                order_result,
                                business_name,
                                business_phone,
                                currency,
                            )

            return {
                "success": order_result.get("success", False),
                "result": order_result.get("result", "Order creation failed"),
                "order_data": order_result,
            }

        except Exception as e:
            logger.error(f"[CONV_AGENT] Order creation error: {e}")
            return {"success": False, "result": f"Order error: {str(e)}"}

    @staticmethod
    async def _bg_notify_order_placed(
        user_id: str,
        customer_phone: str,
        order_data: Dict[str, Any],
        business_name: str,
        business_phone: str,
        currency: str,
    ) -> None:
        """Background task: confirmation, receipt, and tracking registry."""
        try:
            from ..database import get_session_maker
            from ..models import User
            from sqlalchemy import select
            from .order_tracking_service import order_tracking_service

            session_maker = get_session_maker()
            async with session_maker() as db:
                result = await db.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if not user:
                    return
                await order_tracking_service.notify_order_placed(
                    user=user,
                    db=db,
                    customer_phone=customer_phone,
                    order_data=order_data,
                    business_name=business_name,
                    business_phone=business_phone,
                    currency=currency,
                )
        except Exception as e:
            logger.warning(f"[CONV_AGENT] Order tracking notify failed: {e}")

    async def _sub_calculate_total(
        self,
        items: List[Dict],
        currency: str,
        session_key: str = "",
    ) -> Dict[str, Any]:
        """Calculate order total via OrderService."""
        try:
            result = await self.order_service.handle_operation(
                operation="calculate_order_total",
                items=items,
                currency=currency
            )
            if result.get("success") and session_key:
                try:
                    await context_manager.set_pending_confirmation(
                        session_key, items, result
                    )
                except Exception as e:
                    logger.warning(f"[CONV_AGENT] set_pending_confirmation: {e}")
            return {
                "success": True,
                "result": (
                    f"{result.get('result', '')}\n"
                    "INSTRUCTION: Present this total to the customer and ask them to reply "
                    "YES to confirm the order."
                ),
                "data": result
            }
        except Exception as e:
            return {"success": False, "result": f"Calculation error: {str(e)}"}

    async def _customer_owns_order(
        self,
        order_id: str,
        customer_phone: str,
        storage_config: Dict[str, Any],
        user: User,
        db: AsyncSession,
    ) -> bool:
        """
        Return True only if ``order_id`` belongs to ``customer_phone``.

        Checks the ephemeral order-tracking registry first (fast), then the
        connected storage (orders are looked up filtered by the customer's
        phone, so a match proves ownership). Used to gate cancellation so a
        customer can never act on another person's order.
        """
        oid = str(order_id or "").strip().lower()
        if not oid or not customer_phone:
            return False

        # 1) Tracking registry (records the phone the order was placed from)
        try:
            from .order_tracking_service import order_tracking_service
            reg = order_tracking_service.get_registered_order(str(user.id), order_id)
            if reg and reg.get("customer_phone"):
                reg_digits = re.sub(r"\D", "", str(reg.get("customer_phone")))
                snd_digits = re.sub(r"\D", "", str(customer_phone))
                if reg_digits and (reg_digits == snd_digits or reg_digits.endswith(snd_digits[-9:]) or snd_digits.endswith(reg_digits[-9:])):
                    return True
        except Exception as e:
            logger.warning(f"[CONV_AGENT] ownership registry check failed: {e}")

        # 2) Connected storage — list THIS customer's orders and look for the id
        provider = (storage_config or {}).get("provider", "none")
        if provider in (None, "", "none"):
            # No persistent store to verify against; rely on the registry result
            # above (already returned True if matched). Be safe → deny.
            return False
        try:
            from .tool_executor import ToolExecutor
            executor = ToolExecutor()
            orders = []
            if provider == "google_sheets":
                orders = await self._get_orders_from_google_sheets(executor, customer_phone, storage_config, user, db)
            elif provider == "airtable":
                orders = await self._get_orders_from_airtable(executor, customer_phone, storage_config, user, db)
            for o in orders or []:
                if str(o.get("Order ID", "")).strip().lower() == oid:
                    return True
        except Exception as e:
            logger.warning(f"[CONV_AGENT] ownership storage check failed: {e}")
        return False

    async def _sub_cancel_order(
        self,
        arguments: Dict[str, Any],
        storage_config: Dict[str, Any],
        business_name: str,
        currency: str,
        user: User,
        db: AsyncSession,
        background_tasks: Optional['BackgroundTasks'] = None,
    ) -> Dict[str, Any]:
        """Cancel an order and update connected storage."""
        try:
            order_id = arguments.get("order_id", "")
            reason = arguments.get("reason", "Customer requested cancellation via chat")
            customer_phone = arguments.get("customer_phone", "")

            # SECURITY: only allow cancelling an order that actually belongs to
            # this customer (the WhatsApp sender). Prevents anyone from cancelling
            # another person's order by typing/guessing an order ID.
            if customer_phone:
                owns = await self._customer_owns_order(
                    order_id, customer_phone, storage_config, user, db
                )
                if not owns:
                    return {
                        "success": False,
                        "result": (
                            "I couldn't find that order under your number. You can only "
                            "cancel your own orders — tap *My Orders* to see them and use "
                            "the Cancel button on the one you want."
                        ),
                    }

            cancel_result = await self.order_service.handle_operation(
                operation="cancel_order",
                order_id=order_id,
                reason=reason,
                cancelled_by="customer"
            )

            if cancel_result.get("success"):
                if storage_config and storage_config.get("provider") not in (None, "", "none"):
                    provider = storage_config.get("provider")
                    if background_tasks:
                        background_tasks.add_task(
                            self._run_update_task,
                            provider, order_id, "cancelled", storage_config, user
                        )
                    else:
                        await self._run_update_task(
                            provider, order_id, "cancelled", storage_config, user
                        )

                if getattr(settings, "ORDER_TRACKING_ENABLED", True) and customer_phone and user:
                    if background_tasks:
                        background_tasks.add_task(
                            self._bg_notify_status_change,
                            str(user.id),
                            order_id,
                            "cancelled",
                            customer_phone,
                            business_name,
                            currency,
                            "",
                        )
                    else:
                        await self._bg_notify_status_change(
                            str(user.id),
                            order_id,
                            "cancelled",
                            customer_phone,
                            business_name,
                            currency,
                            "",
                        )

            return {
                "success": cancel_result.get("success", False),
                "result": cancel_result.get("message", "Order cancellation failed"),
                "cancellation_data": cancel_result
            }

        except Exception as e:
            logger.error(f"[CONV_AGENT] Order cancellation error: {e}")
            return {"success": False, "result": f"Cancellation error: {str(e)}"}

    @staticmethod
    async def _bg_notify_status_change(
        user_id: str,
        order_id: str,
        new_status: str,
        customer_phone: str,
        business_name: str,
        currency: str,
        notes: str,
    ) -> None:
        try:
            from ..database import get_session_maker
            from ..models import User
            from sqlalchemy import select
            from .order_tracking_service import order_tracking_service

            session_maker = get_session_maker()
            async with session_maker() as db:
                result = await db.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if not user:
                    return
                await order_tracking_service.notify_status_change(
                    user=user,
                    db=db,
                    order_id=order_id,
                    new_status=new_status,
                    customer_phone=customer_phone,
                    business_name=business_name,
                    currency=currency,
                    notes=notes,
                )
        except Exception as e:
            logger.warning(f"[CONV_AGENT] Status tracking notify failed: {e}")

    async def _sub_get_user_orders(
        self,
        arguments: Dict[str, Any],
        storage_config: Dict[str, Any],
        user: User,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Fetch user order history from connected storage."""
        customer_phone = arguments.get("customer_phone", "")
        if not customer_phone:
            return {"success": False, "result": "Customer phone number is required to look up orders."}

        provider = storage_config.get("provider", "none")
        if provider in (None, "", "none"):
            return {"success": False, "result": "No database connected. Cannot retrieve order history."}

        try:
            from .tool_executor import ToolExecutor
            executor = ToolExecutor()
            
            orders = []
            if provider == "google_sheets":
                orders = await self._get_orders_from_google_sheets(executor, customer_phone, storage_config, user, db)
            elif provider == "airtable":
                orders = await self._get_orders_from_airtable(executor, customer_phone, storage_config, user, db)
            else:
                return {"success": False, "result": f"Storage provider {provider} is not supported for order history."}

            if not orders:
                return {"success": True, "result": f"No orders found for phone number {customer_phone}."}

            # Statuses that allow cancellation (from STATUS_TRANSITIONS in order_service.py)
            CANCELLABLE_STATUSES = {"pending", "confirmed", "preparing", "ready", "shipped", "out_for_delivery"}

            # Enrich orders with cancellability flag and format for the LLM as JSON
            simplified_orders = []
            for o in orders:
                status_raw = (o.get("Status") or "").strip().lower().replace(" ", "_")
                is_cancellable = status_raw in CANCELLABLE_STATUSES

                simplified_orders.append({
                    "order_id": o.get('Order ID'),
                    "status": o.get('Status'),
                    "date": o.get('Created At'),
                    "total": f"{o.get('Subtotal')} {o.get('Currency', 'KES')}",
                    "items": o.get('Items'),
                    "can_cancel": is_cancellable
                })
            
            import json
            summary = (
                f"Found {len(orders)} order(s) for {customer_phone}.\n\n"
                f"INSTRUCTION: You MUST now call `display_order_cards` and pass this exact JSON array as the 'orders' argument:\n"
                f"{json.dumps(simplified_orders, indent=2)}\n\n"
                "CRITICAL: Do NOT list these orders in text in your response to the user. The interactive cards are the ONLY way orders should be shown."
            )
            return {"success": True, "result": summary, "orders": orders}

        except Exception as e:
            logger.error(f"[CONV_AGENT] Get user orders error: {e}")
            return {"success": False, "result": f"Failed to retrieve order history: {str(e)}"}

    async def _get_orders_from_google_sheets(
        self, executor, phone: str, storage_config: Dict[str, Any], user: User, db: AsyncSession
    ) -> List[Dict[str, Any]]:
        spreadsheet_id = storage_config.get("spreadsheet_id", "")
        if not spreadsheet_id:
            return []

        sheet_name = (storage_config.get("orders_sheet_name") or "Orders").strip() or "Orders"
        
        orders_headers_required = [
            "Order ID", "Status", "Customer Name", "Customer Phone", 
            "Customer Email", "Items", "Item Count", "Subtotal", 
            "Currency", "Delivery Method", "Delivery Address", 
            "Notes", "Order Type", "Created At"
        ]
        
        orders_headers = await self._ensure_sheet_headers_with_fallback(
            executor=executor,
            spreadsheet_id=spreadsheet_id,
            preferred_sheet=sheet_name,
            fallback_sheets=["Orders", "Sheet1"],
            required_headers=orders_headers_required,
            user=user,
            db=db,
        )
        if not orders_headers:
            return []
            
        actual_sheet_name = orders_headers["sheet_name"]

        read_res = await executor.execute_tool(
            "google_workspace_sheets",
            {
                "operation": "read_range",
                "spreadsheet_id": spreadsheet_id,
                "range_name": f"{actual_sheet_name}!A:ZZ",
            },
            user,
            db,
        )
        if not read_res.get("success"):
            return []

        values = read_res.get("values") or []
        if len(values) < 2:
            return []

        headers = values[0]
        header_norms = [_normalize_header(h) for h in headers]
        
        target_norm = _normalize_header("Customer Phone")
        if target_norm not in header_norms:
            return []
            
        phone_idx = header_norms.index(target_norm)
        
        # We need these indices to extract data
        key_fields = ["Order ID", "Status", "Created At", "Subtotal", "Currency", "Items"]
        key_indices = {}
        for f in key_fields:
            fn = _normalize_header(f)
            if fn in header_norms:
                key_indices[f] = header_norms.index(fn)

        found_orders = []
        # Reverse to get newest first (assuming appended at bottom)
        for row in reversed(values[1:]):
            if len(row) > phone_idx and _phones_match(_safe_str(row[phone_idx]), phone):
                order = {}
                for f, idx in key_indices.items():
                    order[f] = _safe_str(row[idx]) if len(row) > idx else ""
                found_orders.append(order)
                
            # Limit to 10 most recent to prevent huge context
            if len(found_orders) >= 10:
                break
                
        return found_orders

    async def _get_orders_from_airtable(
        self, executor, phone: str, storage_config: Dict[str, Any], user: User, db: AsyncSession
    ) -> List[Dict[str, Any]]:
        base_id = storage_config.get("airtable_base_id", "")
        if not base_id:
            return []
            
        table_name = storage_config.get("airtable_orders_table", "Orders")
        
        search_res = await executor.execute_tool(
            "airtable_record_management",
            {
                "operation": "search_records",
                "base_id": base_id,
                "table_name": table_name,
                "formula": f"{{Customer Phone}} = '{phone}'",
                "max_records": 10
            },
            user,
            db
        )
        
        records = search_res.get("records", []) if search_res.get("success") else []
        if not records and not search_res.get("success"):
            # Try read_records fallback
            read_res = await executor.execute_tool(
                "airtable_record_management",
                {
                    "operation": "read_records",
                    "base_id": base_id,
                    "table_name": table_name,
                    "max_records": 100
                },
                user,
                db
            )
            all_records = read_res.get("records", []) if read_res.get("success") else []
            records = [r for r in all_records if _phones_match(r.get("fields", {}).get("Customer Phone"), phone)][:10]

        found_orders = []
        for r in records:
            fields = r.get("fields", {})
            found_orders.append({
                "Order ID": fields.get("Order ID", ""),
                "Status": fields.get("Status", ""),
                "Created At": fields.get("Created At", ""),
                "Subtotal": fields.get("Subtotal", ""),
                "Currency": fields.get("Currency", "KES"),
                "Items": fields.get("Items", "")
            })
            
        return found_orders

    async def _sub_initiate_mpesa_payment(
        self,
        *,
        order_id: str,
        phone_number: str,
        amount: Any,
        description: str,
        session_key: Optional[str],
        storage_config: Dict[str, Any],
        business_name: str,
        user: User,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """
        Initiate an STK push using tenant Daraja credentials from MpesaAgentConfig.
        Stores callback mapping in Redis with TTL (ephemeral, no long-term DB row).
        """
        try:
            if not order_id:
                return {"success": False, "error": "order_id is required"}
            if not phone_number:
                return {"success": False, "error": "phone_number is required"}

            # Try to fetch the actual amount from cached order to prevent LLM hallucinations
            from ..services.order_tracking_service import OrderTrackingService
            track_svc = OrderTrackingService()
            cached_order = track_svc.get_registered_order(str(user.id), order_id)
            if cached_order and cached_order.get("order"):
                _order = cached_order["order"]
                # OrderService.create_order persists `subtotal`; calculate_order_total
                # adds `grand_total`. Check all known amount fields so we never charge 0.
                actual_amount = (
                    _order.get("total_amount")
                    or _order.get("grand_total")
                    or _order.get("total")
                    or _order.get("subtotal")
                )
                if actual_amount:
                    try:
                        amount = float(actual_amount)
                    except (ValueError, TypeError):
                        pass

            # Format phone number to 254XXXXXXXXX for M-Pesa
            import re
            phone_number = re.sub(r"\D", "", str(phone_number))
            if phone_number.startswith("0"):
                phone_number = "254" + phone_number[1:]
            elif phone_number.startswith("7") or phone_number.startswith("1"):
                if len(phone_number) == 9:
                    phone_number = "254" + phone_number

            # Coerce amount to int KES
            try:
                amount_int = int(float(amount))
            except Exception:
                amount_int = 0
            if amount_int < 1:
                return {"success": False, "error": "amount must be at least 1 KES"}

            from sqlalchemy import select
            from ..models import MpesaAgentConfig
            from ..services.mpesa_reconciliation_service import MpesaReconciliationService
            from ..services.daraja_service import DarajaService
            from ..config import settings

            # Load tenant Daraja config (stored per business owner)
            res = await db.execute(select(MpesaAgentConfig).where(MpesaAgentConfig.user_id == user.id))
            cfg = res.scalar_one_or_none()
            if not cfg or not cfg.webhook_secret:
                return {
                    "success": False,
                    "error": "M-Pesa is not configured for this business. Ask the business to set Daraja credentials in Settings → Mpesa Webhooks.",
                }

            # Decrypt credentials
            recon = MpesaReconciliationService()
            decrypted = recon.decrypt_config_credentials(cfg)
            if not decrypted.get("daraja_consumer_key") or not decrypted.get("daraja_consumer_secret"):
                return {"success": False, "error": "Daraja Consumer Key/Secret missing in business settings"}
            if not cfg.daraja_passkey or not cfg.daraja_shortcode:
                return {"success": False, "error": "Daraja passkey/shortcode missing in business settings"}

            # Build callback URL (tenant-scoped)
            base_url = (cfg.callback_url_override or settings.API_BASE_URL).rstrip("/")
            callback_url = f"{base_url}/api/agents/daraja/callback/{cfg.webhook_secret}"

            # Build callback routing metadata
            platform = "whatsapp"
            sender_id = phone_number
            if session_key and session_key.startswith("ccm:"):
                # session_key format: ccm:{platform}:{owner_user_id}:{sender_id}
                parts = session_key.split(":")
                if len(parts) >= 4:
                    platform = parts[1] or "whatsapp"
                    sender_id = parts[3] or sender_id
            else:
                # Derive from phone; WhatsApp default
                platform = "whatsapp"
                sender_id = phone_number

            tenant_env = (cfg.daraja_environment or "sandbox").lower()
            daraja = DarajaService(environment=tenant_env)
            stk_res = await daraja.stk_push(
                phone_number=phone_number,
                amount=amount_int,
                account_reference=order_id[:12],
                transaction_desc=description[:13] if description else f"Order {order_id}"[:13],
                callback_url=callback_url,
                consumer_key=decrypted["daraja_consumer_key"],
                consumer_secret=decrypted["daraja_consumer_secret"],
                short_code=cfg.daraja_shortcode,
                passkey=decrypted.get("daraja_passkey"),
            )

            if not stk_res.get("success"):
                return {"success": False, "error": stk_res.get("error", "Failed to initiate STK push")}

            merchant_request_id = stk_res.get("merchant_request_id")
            checkout_request_id = stk_res.get("checkout_request_id")

            # Ephemeral callback mapping (24h TTL)
            payload = {
                "user_id": str(user.id),
                "session_key": session_key or "",
                "platform": platform,
                "sender_id": sender_id,
                "customer_phone": phone_number,
                "order_id": order_id,
                "amount": amount_int,
                "currency": "KES",
                "business_name": business_name,
                "storage_config": storage_config or {},
                "created_at": datetime.utcnow().isoformat(),
            }
            if checkout_request_id:
                cache_service.set(f"mpesa:stk:checkout:{checkout_request_id}", payload, expire_seconds=86400)
            if merchant_request_id:
                cache_service.set(f"mpesa:stk:merchant:{merchant_request_id}", payload, expire_seconds=86400)

            return {
                "success": True,
                "result": "M-Pesa payment initiated. Customer should check phone to complete payment.",
                "checkout_request_id": checkout_request_id,
                "merchant_request_id": merchant_request_id,
                "order_id": order_id,
                "amount": amount_int,
                "currency": "KES",
                "customer_message": stk_res.get("customer_message"),
            }

        except Exception as e:
            logger.error(f"[CONV_AGENT] initiate_mpesa_payment error: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def _sub_display_product_cards(
        self,
        products: List[Dict[str, Any]],
        session_key: str,
        currency: str,
        user: User,
        db: AsyncSession,
        order_type: str = "general",
    ) -> Dict[str, Any]:
        """
        Send product cards as native interactive messages on WhatsApp/Telegram.

        Instead of just collecting card data and hoping the workflow maps it,
        this method sends each product as a native WhatsApp interactive button
        message with:
        - Image header (product photo)
        - Body: *Product Name*\nPrice: KES 1,500\n\nDescription
        - Buttons: "Add to Cart" | "View Details"

        This is what real e-commerce bots (Jumia, Glovo, etc.) do.

        Falls back to passive card collection if:
        - Platform is not WhatsApp
        - WhatsApp credentials are not available
        - Any send failure (cards still returned in response data)
        """
        if not products:
            return {
                "success": True,
                "result": "No products to display.",
                "cards": []
            }

        # Cap at 10 products to prevent:
        # 1) Token overflow in LLM tool call arguments (the JSON gets truncated)
        # 2) WhatsApp/Telegram message floods (too many cards annoy users)
        MAX_PRODUCT_CARDS = 10
        if len(products) > MAX_PRODUCT_CARDS:
            logger.info(
                f"[CONV_AGENT] Capping product cards from {len(products)} to {MAX_PRODUCT_CARDS}"
            )
            products = products[:MAX_PRODUCT_CARDS]

        # Detect platform and extract recipient phone
        platform = "whatsapp"
        recipient = ""
        if session_key:
            if session_key.startswith("ccm:whatsapp:"):
                platform = "whatsapp"
                # session_key format: ccm:whatsapp:{owner_user_id}:{sender_phone}
                parts = session_key.split(":")
                if len(parts) >= 4:
                    recipient = parts[3]
                elif len(parts) >= 3:
                    recipient = parts[2]
            elif session_key.startswith("ccm:telegram:"):
                platform = "telegram"
                parts = session_key.split(":")
                if len(parts) >= 4:
                    recipient = parts[3]
                elif len(parts) >= 3:
                    recipient = parts[2]

        # If we can't determine the recipient, fall back to passive collection
        if not recipient:
            logger.warning("[CONV_AGENT] Cannot extract recipient from session_key — falling back to passive cards")
            return {
                "success": True,
                "result": f"Formatted {len(products)} products as cards.",
                "cards": products
            }

        # WhatsApp: send native interactive cards
        if platform == "whatsapp":
            return await self._send_whatsapp_product_cards(
                products=products,
                recipient=recipient,
                currency=currency,
                user=user,
                db=db,
                order_type=order_type,
            )

        # Telegram: send photo + caption cards
        if platform == "telegram":
            return await self._send_telegram_product_cards(
                products=products,
                chat_id=recipient,
                currency=currency,
                user=user,
                db=db,
            )

        # Unknown platform — passive fallback
        return {
            "success": True,
            "result": f"Formatted {len(products)} products as cards.",
            "cards": products
        }

    async def _send_whatsapp_product_cards(
        self,
        products: List[Dict[str, Any]],
        recipient: str,
        currency: str,
        user: User,
        db: AsyncSession,
        order_type: str = "general",
    ) -> Dict[str, Any]:
        """Send each product as a native WhatsApp interactive button message."""
        try:
            from sqlalchemy import select
            from ..models import Connection, ConnectionStatus
            from .whatsapp_service import WhatsAppService

            # Get user's WhatsApp connection credentials
            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user.id,
                    Connection.platform == "whatsapp",
                    Connection.status == ConnectionStatus.ACTIVE
                )
            )
            connection = result.scalar_one_or_none()

            if not connection:
                logger.warning("[CONV_AGENT] No WhatsApp connection — falling back to passive cards")
                return {
                    "success": True,
                    "result": f"Formatted {len(products)} products (WhatsApp not connected).",
                    "cards": products
                }

            config = connection.config or {}
            access_token = config.get("access_token")
            phone_number_id = config.get("phone_number_id")

            if not access_token or not phone_number_id:
                logger.warning("[CONV_AGENT] WhatsApp credentials incomplete — falling back to passive cards")
                return {
                    "success": True,
                    "result": f"Formatted {len(products)} products (WhatsApp credentials missing).",
                    "cards": products
                }

            whatsapp = WhatsAppService()
            wa_config = {"access_token": access_token, "phone_number_id": phone_number_id}

            import asyncio

            sent = 0
            failed = 0
            sent_image_urls = []

            # Pre-cache all product details for button click resolution
            card_products = products[:5]  # Cap at 5 cards for speed + UX
            for idx, product in enumerate(card_products):
                base_id = str(product.get("id", "")).strip()
                # Append idx to guarantee uniqueness even if LLM hallucinates duplicate IDs
                safe_id = f"{base_id}_{idx}" if base_id else f"item_{idx}"
                from .whatsapp_ordering_helpers import sanitize_product_button_id
                unique_id = sanitize_product_button_id(safe_id)
                product["id"] = unique_id  # Update dict so _send_one_card uses the unique ID
                
                try:
                    cache_service.set(
                        f"product_card:{phone_number_id}:{unique_id}",
                        {
                            "name": product.get("name", "Product"),
                            "price": product.get("price", 0),
                            "description": (product.get("description", ""))[:200],
                            "image_url": product.get("image_url", ""),
                            "currency": currency,
                        },
                        expire_seconds=86400
                    )
                except Exception as cache_err:
                    logger.warning(f"[CONV_AGENT] Failed to cache product card: {cache_err}")

            # Configure button actions based on order_type
            primary_title = "Add to Cart"
            primary_prefix = "cart"
            if order_type == "real_estate":
                primary_title = "Inquire"
                primary_prefix = "inquire"

            # Send all cards concurrently for speed
            async def _send_one_card(product, idx):
                name = product.get("name", "Product")
                price = product.get("price", 0)
                description = product.get("description", "")
                
                from .whatsapp_ordering_helpers import sanitize_image_url_for_whatsapp
                image_url = sanitize_image_url_for_whatsapp(product.get("image_url", ""))
                
                product_id = product.get("id", str(idx + 1))

                try:
                    card_result = await whatsapp.send_product_card(
                        to_number=recipient,
                        name=name,
                        price=price,
                        description=description,
                        image_url=image_url,
                        product_id=product_id,
                        config=wa_config,
                        primary_action_title=primary_title,
                        primary_action_id_prefix=primary_prefix,
                    )
                    if card_result.get("success"):
                        logger.info(f"[CONV_AGENT] ✅ Sent product card: {name} → {recipient}")
                        return {"sent": True, "image_url": image_url}
                    else:
                        if image_url:
                            # Fallback to image + caption
                            caption = f"*{name}*\n💰 {currency} {price:,.0f}\n\n{description}"
                            if len(caption) > 1024:
                                caption = caption[:1021] + "..."
                            await whatsapp.send_media_message(
                                to_number=recipient,
                                media_url=image_url,
                                media_type="image",
                                caption=caption,
                                config=wa_config,
                            )
                            logger.info(f"[CONV_AGENT] ✅ Sent product as image+caption: {name} → {recipient}")
                            return {"sent": True, "image_url": image_url}
                        else:
                            # No image — fallback to text
                            text = f"*{name}*\n💰 {currency} {price:,.0f}\n\n{description}"
                            await whatsapp.send_message(
                                to_number=recipient,
                                message=text,
                                config=wa_config,
                            )
                            logger.info(f"[CONV_AGENT] ✅ Sent product as text: {name} → {recipient}")
                            return {"sent": True}
                except Exception as card_err:
                    logger.warning(f"[CONV_AGENT] ❌ Failed to send card for {name}: {card_err}")
                    return {"sent": False}

            # Fire all card sends in parallel
            results = await asyncio.gather(
                *[_send_one_card(p, i) for i, p in enumerate(card_products)],
                return_exceptions=True
            )

            for r in results:
                if isinstance(r, dict) and r.get("sent"):
                    sent += 1
                    if r.get("image_url"):
                        sent_image_urls.append(r["image_url"])
                else:
                    failed += 1

            summary = f"Sent {sent} product card(s) to the customer"
            if failed:
                summary += f" ({failed} failed)"

            return {
                "success": sent > 0,
                "result": summary,
                "cards": products,
                "cards_sent": sent,
                "cards_failed": failed,
                "sent_image_urls": sent_image_urls,
            }

        except Exception as e:
            logger.error(f"[CONV_AGENT] _send_whatsapp_product_cards error: {e}", exc_info=True)
            return {
                "success": True,  # Don't fail the whole turn
                "result": f"Formatted {len(products)} products (card send failed: {e})",
                "cards": products
            }

    async def _send_telegram_product_cards(
        self,
        products: List[Dict[str, Any]],
        chat_id: str,
        currency: str,
        user: User,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Send each product as a Telegram photo + caption message."""
        try:
            from sqlalchemy import select
            from ..models import Connection, ConnectionStatus

            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user.id,
                    Connection.platform == "telegram",
                    Connection.status == ConnectionStatus.ACTIVE
                )
            )
            connection = result.scalar_one_or_none()

            if not connection:
                return {
                    "success": True,
                    "result": f"Formatted {len(products)} products (Telegram not connected).",
                    "cards": products
                }

            import aiohttp
            bot_token = (connection.config or {}).get("bot_token", "")
            if not bot_token:
                return {
                    "success": True,
                    "result": f"Formatted {len(products)} products (Telegram token missing).",
                    "cards": products
                }

            sent = 0
            sent_image_urls = []

            for product in products[:10]:
                name = product.get("name", "Product")
                price = product.get("price", 0)
                description = product.get("description", "")
                image_url = product.get("image_url", "")
                
                from .whatsapp_ordering_helpers import sanitize_image_url_for_whatsapp
                image_url = sanitize_image_url_for_whatsapp(image_url)

                caption = f"*{name}*\n💰 {currency} {price:,.0f}\n\n{description}"
                if len(caption) > 1024:
                    caption = caption[:1021] + "..."

                try:
                    if image_url:
                        url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                        payload = {
                            "chat_id": chat_id,
                            "photo": image_url,
                            "caption": caption,
                            "parse_mode": "Markdown",
                        }
                    else:
                        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                        payload = {
                            "chat_id": chat_id,
                            "text": caption,
                            "parse_mode": "Markdown",
                        }

                    async with aiohttp.ClientSession() as session:
                        async with session.post(url, json=payload) as resp:
                            if resp.status == 200:
                                sent += 1
                                if image_url:
                                    sent_image_urls.append(image_url)
                                logger.info(f"[CONV_AGENT] ✅ Sent Telegram card: {name} → {chat_id}")
                            else:
                                resp_text = await resp.text()
                                logger.warning(f"[CONV_AGENT] ❌ Telegram send failed: {resp_text[:200]}")
                except Exception as tg_err:
                    logger.warning(f"[CONV_AGENT] ❌ Telegram card error for {name}: {tg_err}")

            return {
                "success": sent > 0,
                "result": f"Sent {sent} product card(s) via Telegram",
                "cards": products,
                "cards_sent": sent,
                "sent_image_urls": sent_image_urls,
            }

        except Exception as e:
            logger.error(f"[CONV_AGENT] _send_telegram_product_cards error: {e}", exc_info=True)
            return {
                "success": True,
                "result": f"Formatted {len(products)} products (Telegram send failed: {e})",
                "cards": products
            }

    # ═══════════════════════════════════════════════════════════
    # ORDER CARD DISPLAY (Interactive buttons for order history)
    # ═══════════════════════════════════════════════════════════

    async def _sub_display_order_cards(
        self,
        orders: List[Dict[str, Any]],
        session_key: str,
        currency: str,
        user: User,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """
        Send order history as native interactive messages with action buttons.

        Each order card shows:
        - Order ID and status with emoji
        - Date, items summary, total
        - Contextual buttons: Cancel Order (if cancellable), Order Details

        Mirrors the display_product_cards pattern but for orders.
        """
        if not orders:
            return {
                "success": True,
                "result": "No orders to display.",
                "cards_sent": 0
            }

        # Cap at 10 orders to prevent message floods
        MAX_ORDER_CARDS = 10
        if len(orders) > MAX_ORDER_CARDS:
            orders = orders[:MAX_ORDER_CARDS]

        # Detect platform and extract recipient
        platform = "whatsapp"
        recipient = ""
        if session_key:
            if session_key.startswith("ccm:whatsapp:"):
                platform = "whatsapp"
                parts = session_key.split(":")
                if len(parts) >= 4:
                    recipient = parts[3]
                elif len(parts) >= 3:
                    recipient = parts[2]
            elif session_key.startswith("ccm:telegram:"):
                platform = "telegram"
                parts = session_key.split(":")
                if len(parts) >= 4:
                    recipient = parts[3]
                elif len(parts) >= 3:
                    recipient = parts[2]

        if not recipient:
            logger.warning("[CONV_AGENT] Cannot extract recipient from session_key — falling back to text")
            return {
                "success": True,
                "result": f"Formatted {len(orders)} order(s) as cards (no recipient).",
                "cards_sent": 0
            }

        if platform == "whatsapp":
            return await self._send_whatsapp_order_cards(
                orders=orders,
                recipient=recipient,
                currency=currency,
                user=user,
                db=db,
            )

        if platform == "telegram":
            return await self._send_telegram_order_cards(
                orders=orders,
                chat_id=recipient,
                currency=currency,
                user=user,
                db=db,
            )

        return {
            "success": True,
            "result": f"Formatted {len(orders)} order(s) as cards (unsupported platform).",
            "cards_sent": 0
        }

    async def _send_whatsapp_order_cards(
        self,
        orders: List[Dict[str, Any]],
        recipient: str,
        currency: str,
        user: User,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Send each order as a WhatsApp interactive button message with action buttons."""
        try:
            from sqlalchemy import select
            from ..models import Connection, ConnectionStatus
            from .whatsapp_service import WhatsAppService

            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user.id,
                    Connection.platform == "whatsapp",
                    Connection.status == ConnectionStatus.ACTIVE
                )
            )
            connection = result.scalar_one_or_none()

            if not connection:
                return {
                    "success": True,
                    "result": f"Formatted {len(orders)} order(s) (WhatsApp not connected).",
                    "cards_sent": 0
                }

            config = connection.config or {}
            access_token = config.get("access_token")
            phone_number_id = config.get("phone_number_id")

            if not access_token or not phone_number_id:
                return {
                    "success": True,
                    "result": f"Formatted {len(orders)} order(s) (WhatsApp credentials missing).",
                    "cards_sent": 0
                }

            whatsapp = WhatsAppService()
            wa_config = {"access_token": access_token, "phone_number_id": phone_number_id}

            # Statuses that allow cancellation
            CANCELLABLE_STATUSES = {"pending", "confirmed", "preparing", "ready", "shipped", "out_for_delivery"}

            sent = 0
            failed = 0

            for order in orders:
                order_id = order.get("order_id", order.get("Order ID", "N/A"))
                status = order.get("status", order.get("Status", "unknown"))
                status_lower = status.strip().lower().replace(" ", "_")
                date = order.get("date", order.get("Created At", ""))
                total = order.get("total", "")
                items = order.get("items", order.get("Items", ""))

                if not total:
                    subtotal = order.get("Subtotal", "0")
                    order_currency = order.get("Currency", currency)
                    total = f"{order_currency} {subtotal}"

                try:
                    send_result = await whatsapp.send_order_card(
                        to_number=recipient,
                        order_id=order_id,
                        status=status,
                        date=date,
                        total=total,
                        items=items,
                        is_cancellable=status_lower in CANCELLABLE_STATUSES,
                        config=wa_config,
                    )
                    if send_result.get("success"):
                        sent += 1
                        logger.info(f"[CONV_AGENT] ✅ Sent order card: {order_id} → {recipient}")
                    else:
                        failed += 1
                        logger.warning(f"[CONV_AGENT] ❌ Order card send failed for {order_id}: {send_result}")
                except Exception as card_err:
                    failed += 1
                    logger.warning(f"[CONV_AGENT] ❌ Order card error for {order_id}: {card_err}")

            summary = f"Sent {sent} order card(s) with action buttons to the customer"
            if failed:
                summary += f" ({failed} failed)"

            return {
                "success": sent > 0,
                "result": summary,
                "cards_sent": sent,
                "cards_failed": failed,
            }

        except Exception as e:
            logger.error(f"[CONV_AGENT] _send_whatsapp_order_cards error: {e}", exc_info=True)
            return {
                "success": True,
                "result": f"Formatted {len(orders)} order(s) (WhatsApp send failed: {e})",
                "cards_sent": 0
            }

    async def _send_telegram_order_cards(
        self,
        orders: List[Dict[str, Any]],
        chat_id: str,
        currency: str,
        user: User,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Send each order as a Telegram message with inline keyboard buttons."""
        try:
            from sqlalchemy import select
            from ..models import Connection, ConnectionStatus

            result = await db.execute(
                select(Connection).filter(
                    Connection.user_id == user.id,
                    Connection.platform == "telegram",
                    Connection.status == ConnectionStatus.ACTIVE
                )
            )
            connection = result.scalar_one_or_none()

            if not connection:
                return {
                    "success": True,
                    "result": f"Formatted {len(orders)} order(s) (Telegram not connected).",
                    "cards_sent": 0
                }

            bot_token = (connection.config or {}).get("bot_token", "")
            if not bot_token:
                return {
                    "success": True,
                    "result": f"Formatted {len(orders)} order(s) (Telegram token missing).",
                    "cards_sent": 0
                }

            import aiohttp

            # Statuses that allow cancellation
            CANCELLABLE_STATUSES = {"pending", "confirmed", "preparing", "ready", "shipped", "out_for_delivery"}

            STATUS_ICONS = {
                "pending": "🕐", "confirmed": "✅", "preparing": "👨‍🍳",
                "ready": "📦", "shipped": "🚚", "out_for_delivery": "🏍️",
                "delivered": "✅", "cancelled": "❌", "refunded": "💰",
            }

            sent = 0

            for order in orders:
                order_id = order.get("order_id", order.get("Order ID", "N/A"))
                status = order.get("status", order.get("Status", "unknown"))
                status_lower = status.strip().lower().replace(" ", "_")
                date = order.get("date", order.get("Created At", ""))
                total = order.get("total", "")
                items = order.get("items", order.get("Items", ""))

                if not total:
                    subtotal = order.get("Subtotal", "0")
                    order_currency = order.get("Currency", currency)
                    total = f"{order_currency} {subtotal}"

                status_icon = STATUS_ICONS.get(status_lower, "📋")
                status_display = status.replace("_", " ").title()

                text = (
                    f"{status_icon} *Order {order_id}*\n"
                    f"Status: *{status_display}*\n"
                    f"📅 {date}\n"
                    f"💰 Total: *{total}*\n"
                    f"📝 {items}"
                )

                # Build inline keyboard buttons
                buttons = []
                if status_lower in CANCELLABLE_STATUSES:
                    buttons.append([
                        {"text": "❌ Cancel Order", "callback_data": f"cancel_order:{order_id}"}
                    ])
                buttons.append([
                    {"text": "📋 Order Details", "callback_data": f"order_details:{order_id}"}
                ])

                try:
                    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                    payload = {
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                        "reply_markup": {
                            "inline_keyboard": buttons
                        }
                    }

                    async with aiohttp.ClientSession() as session:
                        async with session.post(url, json=payload) as resp:
                            if resp.status == 200:
                                sent += 1
                                logger.info(f"[CONV_AGENT] ✅ Sent Telegram order card: {order_id} → {chat_id}")
                            else:
                                resp_text = await resp.text()
                                logger.warning(f"[CONV_AGENT] ❌ Telegram order card failed: {resp_text[:200]}")
                except Exception as tg_err:
                    logger.warning(f"[CONV_AGENT] ❌ Telegram order card error for {order_id}: {tg_err}")

            return {
                "success": sent > 0,
                "result": f"Sent {sent} order card(s) with action buttons via Telegram",
                "cards_sent": sent,
            }

        except Exception as e:
            logger.error(f"[CONV_AGENT] _send_telegram_order_cards error: {e}", exc_info=True)
            return {
                "success": True,
                "result": f"Formatted {len(orders)} order(s) (Telegram send failed: {e})",
                "cards_sent": 0
            }

    # ═══════════════════════════════════════════════════════════
    # ORDER STORAGE PERSISTENCE (Google Sheets / Airtable)
    # ═══════════════════════════════════════════════════════════

    async def _run_persist_task(
        self,
        provider: str,
        order_data: Dict[str, Any],
        customer: Dict[str, Any],
        items_summary: str,
        now: str,
        storage_config: Dict[str, Any],
        user: User
    ):
        """Background worker for persisting to external storage using a fresh DB session."""
        try:
            from ..database import get_session_maker
            from .tool_executor import ToolExecutor
            executor = ToolExecutor()
            session_maker = get_session_maker()
            
            async with session_maker() as new_db:
                if provider == "google_sheets":
                    await self._persist_to_google_sheets(
                        executor, order_data, customer, items_summary,
                        now, storage_config, user, new_db
                    )
                elif provider == "airtable":
                    await self._persist_to_airtable(
                        executor, order_data, customer, items_summary,
                        now, storage_config, user, new_db
                    )
        except Exception as e:
            logger.error(f"[CONV_AGENT] Background persistence failed (non-fatal): {e}")

    async def _persist_to_storage(
        self,
        order_data: Dict[str, Any],
        storage_config: Dict[str, Any],
        business_name: str,
        user: User,
        db: AsyncSession,
        background_tasks: Optional['BackgroundTasks'] = None
    ):
        """
        Persist order + customer data to the business's connected storage.
        Uses existing MCP tools (google_workspace_sheets / airtable_record_management).
        Failures here are non-fatal — logged but never break the order flow.
        """
        provider = storage_config.get("provider", "none")
        if provider in (None, "", "none"):
            return

        try:
            # Extract order fields for storage
            customer = order_data.get("customer", {})
            items = order_data.get("items", [])
            items_summary = "; ".join(
                f"{it.get('name', '?')} x{it.get('quantity', 1)}"
                for it in items
            )
            now = order_data.get("created_at", datetime.now().isoformat())

            if background_tasks:
                background_tasks.add_task(
                    self._run_persist_task,
                    provider, order_data, customer, items_summary, now, storage_config, user
                )
            else:
                from .tool_executor import ToolExecutor
                executor = ToolExecutor()
                if provider == "google_sheets":
                    await self._persist_to_google_sheets(
                        executor, order_data, customer, items_summary,
                        now, storage_config, user, db
                    )
                elif provider == "airtable":
                    await self._persist_to_airtable(
                        executor, order_data, customer, items_summary,
                        now, storage_config, user, db
                    )
                else:
                    logger.warning(f"[CONV_AGENT] Unknown storage provider: {provider}")

        except Exception as e:
            logger.warning(f"[CONV_AGENT] Storage persistence setup failed (non-fatal): {e}")

    async def _run_update_task(
        self,
        provider: str,
        order_id: str,
        status: str,
        storage_config: Dict[str, Any],
        user: User
    ):
        """Background worker for updating order status in external storage."""
        try:
            from ..database import get_session_maker
            from .tool_executor import ToolExecutor
            executor = ToolExecutor()
            session_maker = get_session_maker()
            
            async with session_maker() as new_db:
                if provider == "google_sheets":
                    await self._update_order_status_in_google_sheets(
                        executor, order_id, status, storage_config, user, new_db
                    )
                elif provider == "airtable":
                    await self._update_order_status_in_airtable(
                        executor, order_id, status, storage_config, user, new_db
                    )
        except Exception as e:
            logger.error(f"[CONV_AGENT] Background status update failed (non-fatal): {e}")

    async def _update_order_status_in_google_sheets(
        self,
        executor,
        order_id: str,
        status: str,
        storage_config: Dict[str, Any],
        user: User,
        db: AsyncSession
    ):
        spreadsheet_id = storage_config.get("spreadsheet_id", "")
        if not spreadsheet_id or not order_id:
            return

        sheet_name = (storage_config.get("orders_sheet_name") or "Orders").strip() or "Orders"

        orders_headers_required = [
            "Order ID", "Status", "Customer Name", "Customer Phone", 
            "Customer Email", "Items", "Item Count", "Subtotal", 
            "Currency", "Delivery Method", "Delivery Address", 
            "Notes", "Order Type", "Created At"
        ]
        
        orders_headers = await self._ensure_sheet_headers_with_fallback(
            executor=executor,
            spreadsheet_id=spreadsheet_id,
            preferred_sheet=sheet_name,
            fallback_sheets=["Orders", "Sheet1"],
            required_headers=orders_headers_required,
            user=user,
            db=db,
        )
        if not orders_headers:
            return
            
        actual_sheet_name = orders_headers["sheet_name"]

        # Read the sheet to find the Order ID and Status columns
        read_res = await executor.execute_tool(
            "google_workspace_sheets",
            {
                "operation": "read_range",
                "spreadsheet_id": spreadsheet_id,
                "range_name": f"{actual_sheet_name}!A:ZZ",
            },
            user,
            db,
        )
        if not read_res.get("success"):
            return

        values = read_res.get("values") or []
        if not values or len(values) < 2:
            return

        headers = values[0]
        header_norms = [_normalize_header(h) for h in headers]
        
        target_norm = _normalize_header("Order ID")
        status_norm = _normalize_header("Status")
        
        if target_norm not in header_norms or status_norm not in header_norms:
            return
            
        order_idx = header_norms.index(target_norm)
        status_idx = header_norms.index(status_norm)
        
        # Find the row
        target_row_num = None
        for r_idx, row in enumerate(values):
            if r_idx == 0:
                continue
            if len(row) > order_idx and _safe_str(row[order_idx]).strip() == order_id:
                target_row_num = r_idx + 1 # 1-based index
                break
                
        if not target_row_num:
            logger.info(f"[CONV_AGENT] Order {order_id} not found in Sheets for update")
            return
            
        status_col_a1 = _col_idx_to_a1(status_idx)
        range_to_update = f"{actual_sheet_name}!{status_col_a1}{target_row_num}"
        
        await executor.execute_tool(
            "google_workspace_sheets",
            {
                "operation": "write_range",
                "spreadsheet_id": spreadsheet_id,
                "range_name": range_to_update,
                "values": [[status]],
            },
            user,
            db,
        )
        logger.info(f"[CONV_AGENT] Updated order {order_id} status to {status} in Sheets")

    async def _update_order_status_in_airtable(
        self,
        executor,
        order_id: str,
        status: str,
        storage_config: Dict[str, Any],
        user: User,
        db: AsyncSession
    ):
        base_id = storage_config.get("airtable_base_id", "")
        if not base_id or not order_id:
            return
            
        table_name = storage_config.get("airtable_orders_table", "Orders")
        
        # First find the record ID
        search_res = await executor.execute_tool(
            "airtable_record_management",
            {
                "operation": "search_records",
                "base_id": base_id,
                "table_name": table_name,
                "formula": f"{{Order ID}} = '{order_id}'",
                "max_records": 1
            },
            user,
            db
        )
        
        if not search_res.get("success") or not search_res.get("records"):
            # Try fallback read if search fails or is unsupported
            read_res = await executor.execute_tool(
                "airtable_record_management",
                {
                    "operation": "read_records",
                    "base_id": base_id,
                    "table_name": table_name,
                    "max_records": 100
                },
                user,
                db
            )
            records = read_res.get("records", []) if read_res.get("success") else []
            target_record = next((r for r in records if r.get("fields", {}).get("Order ID") == order_id), None)
        else:
            target_record = search_res.get("records")[0]
            
        if not target_record:
            logger.info(f"[CONV_AGENT] Order {order_id} not found in Airtable for update")
            return
            
        record_id = target_record.get("id")
        
        # Update the record
        update_res = await executor.execute_tool(
            "airtable_record_management",
            {
                "operation": "update_records",
                "base_id": base_id,
                "table_name": table_name,
                "records_data": [
                    {"id": record_id, "fields": {"Status": status}}
                ]
            },
            user,
            db
        )
        
        if update_res.get("error"):
            logger.warning(f"[CONV_AGENT] Airtable update failed: {update_res.get('error')}")
        else:
            logger.info(f"[CONV_AGENT] Updated order {order_id} status to {status} in Airtable")

    async def persist_payment_transaction_to_storage(
        self,
        transaction_data: Dict[str, Any],
        storage_config: Dict[str, Any],
        user: User,
        db: AsyncSession,
    ):
        """
        Persist successful payment transaction data to connected storage.
        """
        provider = (storage_config or {}).get("provider", "none")
        if provider in (None, "", "none"):
            return
        try:
            from .tool_executor import ToolExecutor
            executor = ToolExecutor()
            if provider == "google_sheets":
                await self._persist_transaction_to_google_sheets(
                    executor=executor,
                    transaction_data=transaction_data,
                    storage_config=storage_config,
                    user=user,
                    db=db,
                )
            elif provider == "airtable":
                await self._persist_transaction_to_airtable(
                    executor=executor,
                    transaction_data=transaction_data,
                    storage_config=storage_config,
                    user=user,
                    db=db,
                )
        except Exception as e:
            logger.warning(f"[CONV_AGENT] Transaction persistence failed (non-fatal): {e}")

    async def _persist_to_google_sheets(
        self,
        executor,
        order_data: Dict[str, Any],
        customer: Dict[str, Any],
        items_summary: str,
        created_at: str,
        storage_config: Dict[str, Any],
        user: User,
        db: AsyncSession
    ):
        """Append order + customer rows to Google Sheets via existing MCP tool.

        This is schema-aware:
        - Ensures required header columns exist (creates/repairs header row)
        - Appends by matching values to column names (not by raw index)
        - Prevents duplicates by checking Order ID / Customer Phone
        """
        spreadsheet_id = storage_config.get("spreadsheet_id", "")
        if not spreadsheet_id:
            logger.warning("[CONV_AGENT] Google Sheets storage: no spreadsheet_id configured")
            return

        orders_sheet = (storage_config.get("orders_sheet_name") or "Orders").strip() or "Orders"
        customers_sheet = (storage_config.get("customers_sheet_name") or "Customers").strip() or "Customers"

        order_id = _safe_str(order_data.get("order_id", "")).strip()
        customer_phone = _safe_str(customer.get("phone", "")).strip()

        orders_headers_required = [
            "Order ID",
            "Status",
            "Customer Name",
            "Customer Phone",
            "Customer Email",
            "Items",
            "Item Count",
            "Subtotal",
            "Currency",
            "Delivery Method",
            "Delivery Address",
            "Notes",
            "Order Type",
            "Created At",
        ]

        customers_headers_required = [
            "Customer Phone",
            "Customer Name",
            "Customer Email",
            "Last Order ID",
            "Last Order Date",
            "Source",
        ]

        # Ensure tabs + headers exist (best-effort with fallbacks)
        orders_headers = await self._ensure_sheet_headers_with_fallback(
            executor=executor,
            spreadsheet_id=spreadsheet_id,
            preferred_sheet=orders_sheet,
            fallback_sheets=["Orders", "Sheet1"],
            required_headers=orders_headers_required,
            user=user,
            db=db,
        )
        customers_headers = await self._ensure_sheet_headers_with_fallback(
            executor=executor,
            spreadsheet_id=spreadsheet_id,
            preferred_sheet=customers_sheet,
            fallback_sheets=["Customers", "Sheet1"],
            required_headers=customers_headers_required,
            user=user,
            db=db,
        )

        # If we couldn't validate headers, don't write blindly.
        if not orders_headers or not customers_headers:
            logger.warning("[CONV_AGENT] Sheets schema validation failed; skipping append to avoid misplaced rows.")
            return

        # Dedup: don't append same Order ID more than once.
        if order_id:
            exists = await self._sheet_value_exists(
                executor=executor,
                spreadsheet_id=spreadsheet_id,
                sheet_name=orders_headers["sheet_name"],
                headers=orders_headers["headers"],
                header_name="Order ID",
                value=order_id,
                user=user,
                db=db,
            )
            if exists:
                logger.info(f"[CONV_AGENT] Order {order_id} already exists in Sheets; skipping duplicate append.")
            else:
                order_record = {
                    "Order ID": order_id,
                    "Status": _safe_str(order_data.get("status", "pending")),
                    "Customer Name": _safe_str(customer.get("name", "")),
                    "Customer Phone": customer_phone,
                    "Customer Email": _safe_str(customer.get("email", "")),
                    "Items": _safe_str(items_summary),
                    "Item Count": _safe_str(order_data.get("item_count", 0)),
                    "Subtotal": _safe_str(order_data.get("subtotal", 0)),
                    "Currency": _safe_str(order_data.get("currency", "KES")),
                    "Delivery Method": _safe_str(order_data.get("delivery_method", "")),
                    "Delivery Address": _safe_str(order_data.get("delivery_address", "")),
                    "Notes": _safe_str(order_data.get("notes", "")),
                    "Order Type": _safe_str(order_data.get("order_type", "")),
                    "Created At": _safe_str(created_at),
                }
                await self._append_record_by_headers(
                    executor=executor,
                    spreadsheet_id=spreadsheet_id,
                    sheet_name=orders_headers["sheet_name"],
                    headers=orders_headers["headers"],
                    record=order_record,
                    user=user,
                    db=db,
                )

    async def _persist_transaction_to_google_sheets(
        self,
        executor,
        transaction_data: Dict[str, Any],
        storage_config: Dict[str, Any],
        user: User,
        db: AsyncSession,
    ):
        spreadsheet_id = storage_config.get("spreadsheet_id", "")
        if not spreadsheet_id:
            logger.warning("[CONV_AGENT] Google Sheets transaction storage: no spreadsheet_id configured")
            return

        tx_sheet = (storage_config.get("transactions_sheet_name") or "Transactions").strip() or "Transactions"
        tx_headers_required = [
            "Order ID",
            "Transaction ID",
            "Checkout Request ID",
            "Merchant Request ID",
            "Amount",
            "Currency",
            "Customer Phone",
            "Status",
            "Result Code",
            "Result Desc",
            "Paid At",
            "Source",
        ]
        tx_headers = await self._ensure_sheet_headers_with_fallback(
            executor=executor,
            spreadsheet_id=spreadsheet_id,
            preferred_sheet=tx_sheet,
            fallback_sheets=["Transactions", "Sheet1"],
            required_headers=tx_headers_required,
            user=user,
            db=db,
        )
        if not tx_headers:
            return

        transaction_id = _safe_str(transaction_data.get("transaction_id", "")).strip()
        if transaction_id:
            exists = await self._sheet_value_exists(
                executor=executor,
                spreadsheet_id=spreadsheet_id,
                sheet_name=tx_headers["sheet_name"],
                headers=tx_headers["headers"],
                header_name="Transaction ID",
                value=transaction_id,
                user=user,
                db=db,
            )
            if exists:
                logger.info(f"[CONV_AGENT] Transaction {transaction_id} already exists in Sheets; skipping")
                return

        record = {
            "Order ID": _safe_str(transaction_data.get("order_id", "")),
            "Transaction ID": transaction_id,
            "Checkout Request ID": _safe_str(transaction_data.get("checkout_request_id", "")),
            "Merchant Request ID": _safe_str(transaction_data.get("merchant_request_id", "")),
            "Amount": _safe_str(transaction_data.get("amount", 0)),
            "Currency": _safe_str(transaction_data.get("currency", "KES")),
            "Customer Phone": _safe_str(transaction_data.get("customer_phone", "")),
            "Status": _safe_str(transaction_data.get("status", "paid")),
            "Result Code": _safe_str(transaction_data.get("result_code", "")),
            "Result Desc": _safe_str(transaction_data.get("result_desc", "")),
            "Paid At": _safe_str(transaction_data.get("paid_at", datetime.utcnow().isoformat())),
            "Source": "mpesa_stk",
        }
        await self._append_record_by_headers(
            executor=executor,
            spreadsheet_id=spreadsheet_id,
            sheet_name=tx_headers["sheet_name"],
            headers=tx_headers["headers"],
            record=record,
            user=user,
            db=db,
        )

        # Dedup: don't append same customer phone more than once.
        if customer_phone:
            cust_exists = await self._sheet_value_exists(
                executor=executor,
                spreadsheet_id=spreadsheet_id,
                sheet_name=customers_headers["sheet_name"],
                headers=customers_headers["headers"],
                header_name="Customer Phone",
                value=customer_phone,
                user=user,
                db=db,
            )
            if cust_exists:
                logger.info(f"[CONV_AGENT] Customer {customer_phone} already exists in Sheets; not duplicating row.")
            else:
                customer_record = {
                    "Customer Phone": customer_phone,
                    "Customer Name": _safe_str(customer.get("name", "")),
                    "Customer Email": _safe_str(customer.get("email", "")),
                    "Last Order ID": order_id,
                    "Last Order Date": _safe_str(created_at),
                    "Source": "whatsapp",
                }
                await self._append_record_by_headers(
                    executor=executor,
                    spreadsheet_id=spreadsheet_id,
                    sheet_name=customers_headers["sheet_name"],
                    headers=customers_headers["headers"],
                    record=customer_record,
                    user=user,
                    db=db,
                )

    async def _ensure_sheet_headers_with_fallback(
        self,
        executor,
        spreadsheet_id: str,
        preferred_sheet: str,
        fallback_sheets: List[str],
        required_headers: List[str],
        user: User,
        db: AsyncSession,
    ) -> Optional[Dict[str, Any]]:
        """
        Ensure the header row exists for a sheet tab. If the preferred tab doesn't exist,
        tries fallbacks. Returns {"sheet_name": str, "headers": List[str]} or None.
        """
        candidate_sheets = _dedupe_keep_order([preferred_sheet] + (fallback_sheets or []))
        last_error = ""
        for sheet_name in candidate_sheets:
            try:
                headers = await self._ensure_sheet_headers(
                    executor=executor,
                    spreadsheet_id=spreadsheet_id,
                    sheet_name=sheet_name,
                    required_headers=required_headers,
                    user=user,
                    db=db,
                )
                if headers:
                    return {"sheet_name": sheet_name, "headers": headers}
            except Exception as e:
                last_error = str(e)
        logger.warning(f"[CONV_AGENT] Failed to ensure sheet headers for any candidate tabs: {candidate_sheets}. Last error: {last_error}")
        return None

    async def _ensure_sheet_headers(
        self,
        executor,
        spreadsheet_id: str,
        sheet_name: str,
        required_headers: List[str],
        user: User,
        db: AsyncSession,
    ) -> Optional[List[str]]:
        """
        Read row 1, ensure required headers exist, and write updated header row if needed.
        Returns the final header list.
        """
        # Read existing header row (A1:ZZ1)
        read_res = await executor.execute_tool(
            "google_workspace_sheets",
            {
                "operation": "read_range",
                "spreadsheet_id": spreadsheet_id,
                "range_name": f"{sheet_name}!A1:ZZ1",
            },
            user,
            db,
        )
        if not read_res.get("success"):
            raise Exception(read_res.get("error", "Failed to read header row"))

        values = (read_res.get("values") or [])
        existing_row = values[0] if values and isinstance(values[0], list) else []
        existing_headers = [h for h in (existing_row or []) if _safe_str(h).strip() != ""]

        if not existing_headers:
            # Sheet is empty — create header row.
            write_res = await executor.execute_tool(
                "google_workspace_sheets",
                {
                    "operation": "write_range",
                    "spreadsheet_id": spreadsheet_id,
                    "range_name": f"{sheet_name}!A1",
                    "values": [required_headers],
                },
                user,
                db,
            )
            if not write_res.get("success"):
                raise Exception(write_res.get("error", "Failed to write header row"))
            return required_headers

        existing_norm = [_normalize_header(h) for h in existing_headers]
        required_norm = [_normalize_header(h) for h in required_headers]

        missing = [required_headers[i] for i, rn in enumerate(required_norm) if rn not in existing_norm]
        if not missing:
            # Use existing header list as canonical
            return existing_headers

        # Extend existing header list with missing required headers.
        merged = existing_headers + missing
        write_res = await executor.execute_tool(
            "google_workspace_sheets",
            {
                "operation": "write_range",
                "spreadsheet_id": spreadsheet_id,
                "range_name": f"{sheet_name}!A1",
                "values": [merged],
            },
            user,
            db,
        )
        if not write_res.get("success"):
            raise Exception(write_res.get("error", "Failed to update header row"))
        return merged

    async def _append_record_by_headers(
        self,
        executor,
        spreadsheet_id: str,
        sheet_name: str,
        headers: List[str],
        record: Dict[str, Any],
        user: User,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Append a record aligned to the given header columns."""
        header_norm_to_idx = {_normalize_header(h): i for i, h in enumerate(headers)}
        row = [""] * len(headers)
        for k, v in (record or {}).items():
            idx = header_norm_to_idx.get(_normalize_header(k))
            if idx is None:
                continue
            row[idx] = _safe_str(v)

        # Append to full-width range; Google will place values starting at first column.
        res = await executor.execute_tool(
            "google_workspace_sheets",
            {
                "operation": "append_rows",
                "spreadsheet_id": spreadsheet_id,
                "range_name": f"{sheet_name}!A:ZZ",
                "values": [row],
            },
            user,
            db,
        )
        if not res.get("success"):
            logger.warning(f"[CONV_AGENT] Append row failed for {sheet_name}: {res.get('error')}")
        return res

    async def _sheet_value_exists(
        self,
        executor,
        spreadsheet_id: str,
        sheet_name: str,
        headers: List[str],
        header_name: str,
        value: str,
        user: User,
        db: AsyncSession,
    ) -> bool:
        """Check if a given value already exists in a named header column."""
        if not value:
            return False
        header_norms = [_normalize_header(h) for h in headers]
        target_norm = _normalize_header(header_name)
        if target_norm not in header_norms:
            return False
        idx = header_norms.index(target_norm)
        col = _col_idx_to_a1(idx)

        read_res = await executor.execute_tool(
            "google_workspace_sheets",
            {
                "operation": "read_range",
                "spreadsheet_id": spreadsheet_id,
                "range_name": f"{sheet_name}!{col}2:{col}",
            },
            user,
            db,
        )
        if not read_res.get("success"):
            # If we can't read, don't block writes completely.
            return False

        values = read_res.get("values") or []
        # values is list of [cell] rows
        existing = {(_safe_str(r[0]).strip()) for r in values if isinstance(r, list) and r}
        return value.strip() in existing

    async def _append_row_with_fallback_ranges(
        self,
        executor,
        spreadsheet_id: str,
        candidate_ranges: List[str],
        row: List[Any],
        user: User,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """
        Append a row to Google Sheets with resilient range fallback.
        This prevents silent failure when a configured tab doesn't exist.
        """
        last_error = "Unknown Sheets append failure"
        for range_name in _dedupe_keep_order(candidate_ranges):
            try:
                result = await executor.execute_tool(
                    "google_workspace_sheets",
                    {
                        "operation": "append_rows",
                        "spreadsheet_id": spreadsheet_id,
                        "range_name": range_name,
                        "values": [row],
                    },
                    user,
                    db,
                )
                if result.get("success"):
                    return {"success": True, "range_name": range_name, "result": result}
                last_error = result.get("error", last_error)
            except Exception as e:
                last_error = str(e)
        return {"success": False, "error": last_error}

    async def _persist_to_airtable(
        self,
        executor,
        order_data: Dict[str, Any],
        customer: Dict[str, Any],
        items_summary: str,
        created_at: str,
        storage_config: Dict[str, Any],
        user: User,
        db: AsyncSession
    ):
        """Create order + customer records in Airtable via existing MCP tool."""
        base_id = storage_config.get("airtable_base_id", "")
        if not base_id:
            logger.warning("[CONV_AGENT] Airtable storage: no base_id configured")
            return

        orders_table = storage_config.get("airtable_orders_table", "Orders")
        customers_table = storage_config.get("airtable_customers_table", "Customers")

        # ── Create order record ──
        order_record = {
            "Order ID": order_data.get("order_id", ""),
            "Status": order_data.get("status", "pending"),
            "Customer Name": customer.get("name", ""),
            "Customer Phone": customer.get("phone", ""),
            "Customer Email": customer.get("email", ""),
            "Items": items_summary,
            "Item Count": order_data.get("item_count", 0),
            "Subtotal": order_data.get("subtotal", 0),
            "Currency": order_data.get("currency", "KES"),
            "Delivery Method": order_data.get("delivery_method", ""),
            "Delivery Address": order_data.get("delivery_address", ""),
            "Notes": order_data.get("notes", ""),
            "Order Type": order_data.get("order_type", ""),
            "Created At": created_at,
        }

        try:
            result = await executor.execute_tool(
                "airtable_record_management",
                {
                    "operation": "create_records",
                    "base_id": base_id,
                    "table_name": orders_table,
                    "records_data": [order_record]
                },
                user, db
            )
            if not result.get("error"):
                logger.info(f"[CONV_AGENT] Order {order_data.get('order_id')} saved to Airtable")
            else:
                logger.warning(f"[CONV_AGENT] Airtable order save error: {result.get('error')}")
        except Exception as e:
            logger.warning(f"[CONV_AGENT] Airtable order save failed: {e}")

        # ── Create customer record ──
        customer_record = {
            "Phone": customer.get("phone", ""),
            "Name": customer.get("name", ""),
            "Email": customer.get("email", ""),
            "Last Order": order_data.get("order_id", ""),
            "Last Order Date": created_at,
            "Platform": "whatsapp",
        }

        try:
            result = await executor.execute_tool(
                "airtable_record_management",
                {
                    "operation": "create_records",
                    "base_id": base_id,
                    "table_name": customers_table,
                    "records_data": [customer_record]
                },
                user, db
            )
            if not result.get("error"):
                logger.info(f"[CONV_AGENT] Customer {customer.get('name')} saved to Airtable")
            else:
                logger.warning(f"[CONV_AGENT] Airtable customer save error: {result.get('error')}")
        except Exception as e:
            logger.warning(f"[CONV_AGENT] Airtable customer save failed: {e}")

    async def _persist_transaction_to_airtable(
        self,
        executor,
        transaction_data: Dict[str, Any],
        storage_config: Dict[str, Any],
        user: User,
        db: AsyncSession,
    ):
        base_id = storage_config.get("airtable_base_id", "")
        if not base_id:
            logger.warning("[CONV_AGENT] Airtable transaction storage: no base_id configured")
            return

        table = storage_config.get("airtable_transactions_table", "Transactions")
        record = {
            "Order ID": transaction_data.get("order_id", ""),
            "Transaction ID": transaction_data.get("transaction_id", ""),
            "Checkout Request ID": transaction_data.get("checkout_request_id", ""),
            "Merchant Request ID": transaction_data.get("merchant_request_id", ""),
            "Amount": transaction_data.get("amount", 0),
            "Currency": transaction_data.get("currency", "KES"),
            "Customer Phone": transaction_data.get("customer_phone", ""),
            "Status": transaction_data.get("status", "paid"),
            "Result Code": transaction_data.get("result_code", ""),
            "Result Desc": transaction_data.get("result_desc", ""),
            "Paid At": transaction_data.get("paid_at", datetime.utcnow().isoformat()),
            "Source": "mpesa_stk",
        }
        try:
            result = await executor.execute_tool(
                "airtable_record_management",
                {
                    "operation": "create_records",
                    "base_id": base_id,
                    "table_name": table,
                    "records_data": [record],
                },
                user,
                db,
            )
            if result.get("error"):
                logger.warning(f"[CONV_AGENT] Airtable transaction save error: {result.get('error')}")
        except Exception as e:
            logger.warning(f"[CONV_AGENT] Airtable transaction save failed: {e}")

    # ═══════════════════════════════════════════════════════════
    # NOTIFICATION FORMATTING
    # ═══════════════════════════════════════════════════════════

    def _format_business_notification(
        self,
        order_data: Dict[str, Any],
        business_name: str,
        currency: str
    ) -> str:
        """Format a WhatsApp notification message for the business owner."""
        actual_order = order_data.get("order", order_data)
        
        order_id = actual_order.get("order_id", order_data.get("order_id", "N/A"))
        customer = actual_order.get("customer", {}).get("name", "Unknown")
        phone = actual_order.get("customer", {}).get("phone", "N/A")
        delivery = actual_order.get("delivery_method", "N/A")
        address = actual_order.get("delivery_address", "")
        total = actual_order.get("subtotal", actual_order.get("total", 0))
        items = actual_order.get("items", [])

        items_text = ""
        for item in items:
            name = item.get("name", "Item")
            qty = item.get("quantity", 1)
            unit = item.get("unit", "pcs")
            price = item.get("unit_price", 0)
            items_text += f"  • {name} x{qty} {unit}"
            if price:
                items_text += f" @ {currency} {price:,.0f}"
            items_text += "\n"

        notification = (
            f"🔔 *NEW ORDER — {business_name}*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📋 Order: {order_id}\n"
            f"👤 Customer: {customer}\n"
            f"📱 Phone: {phone}\n"
            f"🚚 Delivery: {delivery.replace('_', ' ').title()}\n"
        )

        if address:
            notification += f"📍 Address: {address}\n"

        notification += (
            f"\n📦 *Items:*\n{items_text}"
            f"\n💰 *Total: {currency} {total:,.0f}*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.utcnow().strftime('%d %b %Y, %H:%M UTC')}"
        )

        return notification

    def _format_email_notification(
        self,
        order_data: Dict[str, Any],
        business_name: str,
        currency: str
    ) -> Dict[str, str]:
        """Format an email notification for the business owner."""
        actual_order = order_data.get("order", order_data)
        
        order_id = actual_order.get("order_id", order_data.get("order_id", "N/A"))
        customer = actual_order.get("customer", {}).get("name", "Unknown")
        phone = actual_order.get("customer", {}).get("phone", "N/A")
        total = actual_order.get("subtotal", actual_order.get("total", 0))

        subject = f"New Order {order_id} — {customer} ({currency} {total:,.0f})"
        body = (
            f"A new order has been placed on {business_name}.\n\n"
            f"Order ID: {order_id}\n"
            f"Customer: {customer}\n"
            f"Phone: {phone}\n"
            f"Total: {currency} {total:,.0f}\n\n"
            f"Please check your dashboard for full details."
        )

        return {"subject": subject, "body": body}

    # ═══════════════════════════════════════════════════════════
    # FALLBACK
    # ═══════════════════════════════════════════════════════════

    def _fallback_response(
        self,
        business_name: str,
        error_code: str = "generic",
        business_phone: str = "",
    ) -> Dict[str, Any]:
        """Return a safe fallback when the agent encounters an error."""
        phone_hint = f" Please call {business_phone}." if business_phone else ""
        messages = {
            "no_kb": (
                f"Thanks for messaging {business_name}! "
                f"Our menu isn't available in chat yet.{phone_hint}"
            ),
            "llm_error": (
                f"Thanks for contacting {business_name}! "
                f"We're having a brief technical issue.{phone_hint} We'll help you shortly. 🙏"
            ),
            "generic": (
                f"Thank you for contacting {business_name}! "
                f"We're experiencing a brief issue.{phone_hint} Our team will respond shortly. 🙏"
            ),
        }
        return {
            "response_text": messages.get(error_code, messages["generic"]),
            "image_urls": [],
            "cards": [],
            "order_created": False,
            "order_cancelled": False,
            "order_data": None,
            "order_notification": "",
            "escalation_triggered": False,
            "escalation_notification": "",
            "human_handoff": False,
            "actions_taken": []
        }
