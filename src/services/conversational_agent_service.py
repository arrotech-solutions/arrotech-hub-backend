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
            "name": "cancel_order",
            "description": (
                "Cancel an existing order. Use this when a customer explicitly requests to cancel their order. "
                "You must ask for the Order ID. If you already have their phone number from the chat session, you can use it, "
                "otherwise ask for the phone number used to place the order for verification."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "The ID of the order to cancel"},
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
                "check an order status, or if they need to find their Order ID to cancel an order. "
                "Requires the customer's phone number. If you already have their phone number from the chat session, you can use it."
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
    }
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

            # Build the system prompt
            system_prompt = self._build_system_prompt(
                business_name=business_name,
                order_type=order_type,
                currency=currency,
                delivery_methods=delivery_methods,
                custom_prompt=custom_system_prompt
            )

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

            # Add the current user message
            messages.append({"role": "user", "content": user_message})

            # Run the inner tool-calling loop (max 3 iterations)
            actions_taken = []
            order_created = False
            order_cancelled = False
            order_data = None
            order_notification = ""
            collected_image_urls: List[str] = []
            collected_product_cards: List[Dict[str, Any]] = []
            sent_product_ids: set = set()  # Track product IDs already sent as cards this turn
            max_iterations = 3

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
                    return self._fallback_response(business_name)

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

                    return {
                        "response_text": final_text,
                        "image_urls": image_urls,
                        "cards": collected_product_cards,
                        "order_created": order_created,
                        "order_cancelled": order_cancelled,
                        "order_data": order_data,
                        "order_notification": order_notification,
                        "actions_taken": actions_taken
                    }

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
                        background_tasks=background_tasks
                    )

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
                    if tool_name == "create_order" and tool_result.get("success"):
                        order_created = True
                        order_data = tool_result.get("order_data", tool_result)
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

            await self._save_to_ccm(session_key, "assistant", final_text)

            return {
                "response_text": final_text,
                "image_urls": image_urls,
                "cards": collected_product_cards,
                "order_created": order_created,
                "order_cancelled": order_cancelled,
                "order_data": order_data,
                "order_notification": order_notification,
                "actions_taken": actions_taken
            }

        except Exception as e:
            logger.error(f"[CONV_AGENT] Execute error: {e}", exc_info=True)
            return self._fallback_response(
                business_config.get("business_name", "Our Business")
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
        custom_prompt: str = ""
    ) -> str:
        """Build the business-specific system prompt for the AI agent."""

        delivery_str = ", ".join(delivery_methods) if delivery_methods else "delivery, pickup"

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

## Order Flow
1. Greet the customer warmly and ask how you can help
2. When they browse: search the catalog, then ALWAYS use `display_product_cards` to show results
3. When they want to order: collect name, phone number, items with quantities
4. Ask about delivery method ({delivery_str})
5. If delivery, collect the delivery address
6. Confirm the order summary with total price using `calculate_total`
7. Create the order using `create_order`
8. After order is created, offer M-Pesa payment using `initiate_mpesa_payment`
9. If a customer wants to cancel an order, ask for the Order ID and their phone number (if not known), then call `cancel_order`
10. If a customer wants to see their order history or check an order status, use `get_user_orders` with their phone number. Summarize the retrieved orders clearly.

## CRITICAL Product Display Rules
- ALWAYS use `display_product_cards` when showing products with images/prices
- NEVER list products as plain text with numbered lists — customers can't interact with text
- NEVER include raw image URLs (https://...) in your text responses
- After `display_product_cards` succeeds, just say something brief like "Here's what we have! 🛒 Tap a product to add it to your cart."
- Do NOT repeat product names, prices, or descriptions in text after cards are sent
- If `display_product_cards` fails, describe products briefly in text WITHOUT image URLs

## Response Style Rules
- Keep responses brief and friendly (WhatsApp chat style, under 150 words)
- Always use {currency} for prices
- Use emojis naturally but sparingly (1-3 per message)
- Respond in the same language the customer uses
- Never make up product information — always search the catalog first
- If the customer's request is unclear, ask a simple clarifying question
- Be conversational, not robotic. Sound like a helpful shop assistant, not a machine.

## Delivery & Payment
- Available delivery methods: {delivery_str}
- For M-Pesa: only initiate after order is confirmed and customer agrees to pay now
"""

        if custom_prompt:
            prompt += f"\n## Additional Business Instructions\n{custom_prompt}\n"

        return prompt

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
        background_tasks: Optional['BackgroundTasks'] = None
    ) -> Dict[str, Any]:
        """Execute one of the agent's sub-tools."""

        try:
            if tool_name == "search_products":
                return await self._sub_search_products(
                    query=arguments.get("query", ""),
                    kb_id=kb_id,
                    user=user,
                    db=db
                )

            elif tool_name == "create_order":
                return await self._sub_create_order(
                    arguments=arguments,
                    order_type=order_type,
                    currency=currency,
                    business_name=business_name,
                    storage_config=storage_config,
                    user=user,
                    db=db,
                    background_tasks=background_tasks
                )

            elif tool_name == "calculate_total":
                return await self._sub_calculate_total(
                    items=arguments.get("items", []),
                    currency=currency
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
                return await self._sub_cancel_order(
                    arguments=arguments,
                    storage_config=storage_config,
                    business_name=business_name,
                    user=user,
                    db=db,
                    background_tasks=background_tasks
                )

            elif tool_name == "get_user_orders":
                return await self._sub_get_user_orders(
                    arguments=arguments,
                    storage_config=storage_config,
                    user=user,
                    db=db
                )

            else:
                # Dynamic MCP Tool execution (Harness delegation)
                from .tool_executor import ToolExecutor
                executor = ToolExecutor()
                return await executor.execute_tool(tool_name, arguments, user, db, background_tasks=background_tasks)

        except Exception as e:
            logger.error(f"[CONV_AGENT] Sub-tool {tool_name} error: {e}")
            return {"success": False, "error": str(e)}

    async def _sub_search_products(
        self, query: str, kb_id: str, user: User, db: AsyncSession
    ) -> Dict[str, Any]:
        """Search the business knowledge base via RAG."""
        if not kb_id:
            return {"success": False, "result": "No knowledge base configured for this business."}

        try:
            from .tool_executor import ToolExecutor
            executor = ToolExecutor()

            result = await executor.execute_tool(
                "rag_search",
                {
                    "query": query,
                    "kb_id": kb_id,
                    "top_k": 5,
                    "rerank": True,
                    "rerank_top_n": 3
                },
                user, db
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
                        "and pass them to `display_product_cards`. Do NOT list products in plain text."
                    ),
                    "data": result.get("data", {})
                }
            else:
                return {"success": False, "result": result.get("error", "Search failed")}

        except Exception as e:
            logger.error(f"[CONV_AGENT] RAG search error: {e}")
            return {"success": False, "result": f"Search error: {str(e)}"}

    async def _sub_create_order(
        self,
        arguments: Dict[str, Any],
        order_type: str,
        currency: str,
        business_name: str,
        storage_config: Dict[str, Any] = None,
        user: User = None,
        db: AsyncSession = None,
        background_tasks: Optional['BackgroundTasks'] = None
    ) -> Dict[str, Any]:
        """Create an order via OrderService, then persist to connected storage."""
        try:
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
                # Generate a receipt
                receipt = await self.order_service.handle_operation(
                    operation="format_order_receipt",
                    order_data=order_result,
                    business_name=business_name,
                    currency=currency
                )
                order_result["receipt"] = receipt.get("result", "")

                # ── Persist to connected storage (non-fatal) ──
                if storage_config and storage_config.get("provider") not in (None, "", "none"):
                    await self._persist_to_storage(
                        order_data=order_result.get("order", order_result),
                        storage_config=storage_config,
                        business_name=business_name,
                        user=user,
                        db=db,
                        background_tasks=background_tasks
                    )

            return {
                "success": order_result.get("success", False),
                "result": order_result.get("result", "Order creation failed"),
                "order_data": order_result
            }

        except Exception as e:
            logger.error(f"[CONV_AGENT] Order creation error: {e}")
            return {"success": False, "result": f"Order error: {str(e)}"}

    async def _sub_calculate_total(
        self, items: List[Dict], currency: str
    ) -> Dict[str, Any]:
        """Calculate order total via OrderService."""
        try:
            result = await self.order_service.handle_operation(
                operation="calculate_order_total",
                items=items,
                currency=currency
            )
            return {
                "success": True,
                "result": result.get("result", ""),
                "data": result
            }
        except Exception as e:
            return {"success": False, "result": f"Calculation error: {str(e)}"}

    async def _sub_cancel_order(
        self,
        arguments: Dict[str, Any],
        storage_config: Dict[str, Any],
        business_name: str,
        user: User,
        db: AsyncSession,
        background_tasks: Optional['BackgroundTasks'] = None
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
                # Persist status update to storage
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

            return {
                "success": cancel_result.get("success", False),
                "result": cancel_result.get("message", "Order cancellation failed"),
                "cancellation_data": cancel_result
            }

        except Exception as e:
            logger.error(f"[CONV_AGENT] Order cancellation error: {e}")
            return {"success": False, "result": f"Cancellation error: {str(e)}"}

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

            # Format orders for the LLM
            formatted_orders = []
            for o in orders:
                formatted_orders.append(
                    f"- Order ID: {o.get('Order ID')}\n"
                    f"  Status: {o.get('Status')}\n"
                    f"  Date: {o.get('Created At')}\n"
                    f"  Total: {o.get('Subtotal')} {o.get('Currency', 'KES')}\n"
                    f"  Items: {o.get('Items')}"
                )
            
            summary = f"Found {len(orders)} order(s) for {customer_phone}:\n\n" + "\n\n".join(formatted_orders)
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
                product_id = product.get("id", str(idx + 1))
                try:
                    cache_service.set(
                        f"product_card:{phone_number_id}:{product_id}",
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

    def _fallback_response(self, business_name: str) -> Dict[str, Any]:
        """Return a safe fallback when the agent encounters an error."""
        return {
            "response_text": (
                f"Thank you for contacting {business_name}! "
                "We're experiencing a brief issue. Our team will respond shortly. 🙏"
            ),
            "image_urls": [],
            "cards": [],
            "order_created": False,
            "order_cancelled": False,
            "order_data": None,
            "order_notification": "",
            "actions_taken": []
        }
