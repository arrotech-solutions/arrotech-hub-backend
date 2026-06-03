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
from typing import Any, Dict, List, Optional

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
                "Do NOT guess the order ID. Do NOT call this tool just to check if they have orders."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "The ID of the order to cancel (may come from button click)"},
                    "customer_phone": {"type": "string", "description": "Customer phone number for verification"},
                    "reason": {"type": "string", "description": "Reason for cancellation provided by customer"}
                },
                "required": ["order_id", "customer_phone", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_orders",
            "description": (
                "Search and retrieve the customer's order history and details. Use this when a customer asks to see their past orders, "
                "check an order status, or wants to cancel an order but hasn't provided the exact order ID yet. "
                "Requires the customer's phone number. If you don't have it, ask them for their phone number so you can pull up their orders. "
                "IMPORTANT: After getting results, ALWAYS call `display_order_cards` to show orders as interactive cards with action buttons. "
                "Never list orders as plain text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_phone": {"type": "string", "description": "Customer phone number to search by"}
                },
                "required": ["customer_phone"]
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
            customer_phone = business_config.get("customer_phone", "")
            customer_name = business_config.get("customer_name", "")
            business_phone = business_config.get("business_phone", "")

            from .whatsapp_ordering_helpers import (
                check_user_message_injection,
                injection_safe_reply,
                is_order_confirmation_message,
                match_cart_command,
                format_cart_summary,
                cart_cleared_message,
                cart_item_removed_message,
                cart_quantity_updated_message,
                parse_remove_item_name,
                parse_set_quantity_message,
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
                preferred_language = lang_detection["language_code"]
                if session:
                    existing_lang = session.metadata.get("preferred_language")
                    if not existing_lang or lang_detection["confidence"] >= 0.55:
                        await context_manager.set_preferred_language(
                            session_key, preferred_language
                        )
                    else:
                        preferred_language = context_manager.get_preferred_language(session)
                    streak = agent_intelligence.update_sentiment_streak(
                        session.metadata, user_message
                    )
                    await context_manager.update_session_metadata(
                        session_key, {"negative_sentiment_streak": streak}
                    )
                    session = await context_manager.get_session_by_key(session_key)

            if session_key and is_order_confirmation_message(user_message):
                try:
                    await context_manager.mark_order_confirmed(session_key)
                except Exception as e:
                    logger.warning(f"[CONV_AGENT] mark_order_confirmed failed: {e}")

            # ── Fast path: cart commands (no LLM) — reply sent via workflow step 2 ──
            if session_key:
                cart_cmd = match_cart_command(user_message)
                if cart_cmd == "reset":
                    try:
                        session = await context_manager.get_session_by_key(session_key)
                        if session:
                            await context_manager.clear_session(session)
                    except Exception as e:
                        logger.warning(f"[CONV_AGENT] reset failed: {e}")
                    reply = (
                        f"🔄 Fresh start! Your cart and chat history are cleared.\n\n"
                        f"Welcome back to *{business_name}* — what would you like today?"
                    )
                    return await self._cart_fast_path_result(
                        session_key, reply,
                        actions_taken=[{"tool": "manage_cart", "result_summary": "reset"}],
                        send_cart_buttons=True,
                    )
                if cart_cmd == "clear":
                    await context_manager.clear_cart(session_key)
                    reply = cart_cleared_message()
                    return await self._cart_fast_path_result(
                        session_key, reply,
                        actions_taken=[{"tool": "manage_cart", "result_summary": "clear"}],
                        send_cart_buttons=True,
                    )
                if cart_cmd == "view":
                    session = await context_manager.get_session_by_key(session_key)
                    cart = context_manager.get_cart(session) if session else []
                    reply = format_cart_summary(cart, currency)
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
                            "Browse the menu and tap *Add to Cart* on something you like!"
                        )
                    else:
                        summary = format_cart_summary(cart, currency)
                        reply = (
                            f"{summary}\n\n"
                            "Great! To checkout, please share:\n"
                            "1️⃣ Your name\n"
                            "2️⃣ Delivery or pickup?\n"
                            "(I'll use your WhatsApp number for contact.)"
                        )
                    return await self._cart_fast_path_result(
                        session_key, reply,
                        actions_taken=[{"tool": "manage_cart", "result_summary": "checkout"}],
                        send_cart_buttons=bool(cart),
                    )
                if cart_cmd == "remove":
                    name = parse_remove_item_name(user_message)
                    cart, removed, removed_name = await context_manager.remove_cart_item(
                        session_key, product_name=name
                    )
                    if removed:
                        reply = f"{cart_item_removed_message(removed_name)}\n\n{format_cart_summary(cart, currency)}"
                    else:
                        reply = (
                            f"I couldn't find *{name}* in your cart.\n\n"
                            f"{format_cart_summary(cart, currency)}"
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
                                f"{format_cart_summary(cart, currency)}"
                            )
                        else:
                            reply = (
                                f"I couldn't find *{name}* in your cart.\n\n"
                                f"{format_cart_summary(cart, currency)}"
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
                    tool_args = tool_call["arguments"]
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
                final_text = (
                    f"Thanks! Your order with *{business_name}* is placed. "
                    "You'll get your receipt and status updates here on WhatsApp shortly."
                )

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

    # ═══════════════════════════════════════════════════════════
    # SYSTEM PROMPT BUILDER
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
    ) -> str:
        """Build the business-specific system prompt for the AI agent."""

        delivery_str = ", ".join(delivery_methods) if delivery_methods else "delivery, pickup"
        customer_context = ""
        if customer_phone or customer_name:
            customer_context = "\n## Known customer (from WhatsApp)\n"
            if customer_name:
                customer_context += f"- Name on file: {customer_name}\n"
            if customer_phone:
                customer_context += (
                    f"- Phone on file: {customer_phone}\n"
                    "- Use this phone for order lookup and M-Pesa unless they ask to use a different number.\n"
                )

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
                "Always ask about preferred size, color, and fit when discussing items."
            ),
            "retail": (
                f"You are the shopping assistant for {business_name}, a retail store. "
                "Help customers find products, check availability, and place orders. "
                "Provide product details and pricing when available."
            ),
            "real_estate": (
                f"You are the real estate assistant for {business_name}, a property management or real estate company. "
                "Help clients find properties for rent or sale, schedule viewings, report maintenance issues, and manage rent payments. "
                "Always ask for their preferences such as location, budget, and number of bedrooms when they inquire about properties."
            ),
            "general": (
                f"You are the customer service assistant for {business_name}. "
                "Help customers with inquiries, browse products/services, and place orders."
            )
        }

        base_context = industry_context.get(order_type, industry_context["general"])

        prompt = f"""{base_context}

## Your Capabilities
- Search the product catalog/menu to answer customer questions
- Display products as interactive cards with images and "Add to Cart" buttons
- Collect customer details (name, phone, delivery address)
- Create orders when the customer is ready
- Calculate order totals
- Initiate M-Pesa payments
- Escalate to a live human agent using `escalate_to_human` when needed

## Order Flow
1. Greet the customer warmly and ask how you can help
2. When they browse: search the catalog, then ALWAYS use `display_product_cards` to show results
3. When they want to order: collect name, phone number, items with quantities
4. Ask about delivery method ({delivery_str})
5. If delivery, collect the delivery address — customers can *share their location pin* on WhatsApp (📍) instead of typing
6. If a delivery location is already saved in context below, use it — do not ask them to type the address again
7. Confirm the order summary with total price using `calculate_total`
8. Call `validate_order`, then show a clear summary and ask the customer to reply *YES* to confirm
9. Only after they confirm, create the order using `create_order`
10. After order is created, offer M-Pesa payment using `initiate_mpesa_payment`
11. If a customer wants to cancel an order, FIRST call `get_user_orders` to show their orders with Cancel buttons — do NOT guess the Order ID and do NOT ask them to type it. If you don't know their phone number, ask for it so you can look up their orders. If the order_id is already provided (e.g. from a button click), proceed directly with `cancel_order`
12. If a customer wants to see their order history or check an order status, call `get_user_orders` then ALWAYS call `display_order_cards` with the results
13. If the customer has items in their cart (see Cart section below), reference the cart when summarizing their order
14. After placing an order, the customer automatically receives a receipt and status updates on WhatsApp — you do not need to send the receipt manually unless asked

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

        if customer_context:
            prompt += customer_context

        if custom_prompt:
            prompt += f"\n## Additional Business Instructions\n{custom_prompt}\n"

        return prompt

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

    async def _build_cart_context_block(self, session_key: str, currency: str) -> str:
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
            summary = format_cart_summary(cart, currency)
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
                    {"id": "menu:browse", "title": "Browse menu"},
                    {"id": "menu:cart", "title": "My cart"},
                    {"id": "agent:human", "title": "Talk to staff"},
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

    async def _cart_fast_path_result(
        self,
        session_key: str,
        reply: str,
        actions_taken: Optional[List[Dict[str, Any]]] = None,
        send_cart_buttons: bool = False,
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

            if has_items:
                remove_rows = build_cart_remove_list_rows(cart, currency)
                if remove_rows:
                    list_result = await wa.send_list_message(
                        to_number=recipient,
                        body_text="Tap an item below to remove it from your cart 🗑️",
                        button_label="Remove item",
                        sections=[{"title": "Your items", "rows": remove_rows}],
                        config=wa_config,
                        footer_text="Up to 10 items shown",
                    )
                    if not list_result.get("success"):
                        logger.warning(
                            f"[CONV_AGENT] cart remove list failed: {list_result.get('error')}"
                        )

            button_body = (
                body_text[:1024]
                if body_text and body_text != "What would you like to do next?"
                else (
                    "Ready to checkout or keep shopping? 🛒"
                    if has_items
                    else "Your cart is empty — browse the menu to add items."
                )
            )
            btn_result = await wa.send_quick_reply_buttons(
                to_number=recipient,
                body_text=button_body,
                buttons=cart_action_buttons(cart_has_items=has_items),
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
        """Send Talk to staff / Order with AI reply buttons after handoff or release."""
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

            wa = WhatsAppService()
            btn_result = await wa.send_quick_reply_buttons(
                to_number=recipient,
                body_text=agent_mode_button_body(handoff_active),
                buttons=agent_mode_buttons(handoff_active),
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
                return {
                    "success": True,
                    "result": (
                        f"{search_text}\n\n"
                        "INSTRUCTION: You MUST now call `display_product_cards` with the products found above. "
                        "Extract each product's id, name, price, description, and image_url from the search results "
                        "and pass them to `display_product_cards`. Do NOT list products in plain text. "
                        "If the customer explicitly asked to ADD items to their cart, also call "
                        "`manage_cart(action='add', product_name=..., unit_price=..., quantity=...)` "
                        "for each item they requested."
                    ),
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
                    "quantity": float(quantity) if quantity else 1,
                    "unit_price": float(unit_price) if unit_price else 0,
                }
                cart = await context_manager.add_cart_item(session_key, item)
                summary = format_cart_summary(cart, currency)
                return {
                    "success": True,
                    "result": (
                        f"✅ Added *{product_name}* × {item['quantity']:g} to the cart.\n\n"
                        f"{summary}"
                    ),
                    "cart": cart,
                    "cart_empty": False,
                }
            if action == "view":
                session = await context_manager.get_session_by_key(session_key)
                cart = context_manager.get_cart(session) if session else []
                summary = format_cart_summary(cart, currency)
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
                    "result": cart_cleared_message(),
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
                        f"{format_cart_summary(cart, currency)}"
                    )
                else:
                    label = product_name or product_id or "that item"
                    msg = (
                        f"I couldn't find *{label}* in your cart.\n\n"
                        f"{format_cart_summary(cart, currency)}"
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
                qty = float(quantity)
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
                            f"{format_cart_summary(cart, currency)}"
                        ),
                        "cart": cart,
                    }
                msg = (
                    f"{cart_quantity_updated_message(item_name, qty)}\n\n"
                    f"{format_cart_summary(cart, currency)}"
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

            # Send all cards concurrently for speed
            async def _send_one_card(product, idx):
                name = product.get("name", "Product")
                price = product.get("price", 0)
                description = product.get("description", "")
                image_url = product.get("image_url", "")
                product_id = product.get("id", str(idx + 1))

                if image_url:
                    try:
                        card_result = await whatsapp.send_product_card(
                            to_number=recipient,
                            name=name,
                            price=price,
                            description=description,
                            image_url=image_url,
                            product_id=product_id,
                            config=wa_config,
                        )
                        if card_result.get("success"):
                            logger.info(f"[CONV_AGENT] ✅ Sent product card: {name} → {recipient}")
                            return {"sent": True, "image_url": image_url}
                        else:
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
                    except Exception as card_err:
                        logger.warning(f"[CONV_AGENT] ❌ Failed to send card for {name}: {card_err}")
                        return {"sent": False}
                else:
                    # No image — send as text
                    text = f"*{name}*\n💰 {currency} {price:,.0f}\n\n{description}"
                    try:
                        await whatsapp.send_message(
                            to_number=recipient,
                            message=text,
                            config=wa_config,
                        )
                        logger.info(f"[CONV_AGENT] ✅ Sent product as text: {name} → {recipient}")
                        return {"sent": True}
                    except Exception as text_err:
                        logger.warning(f"[CONV_AGENT] ❌ Failed to send text for {name}: {text_err}")
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
