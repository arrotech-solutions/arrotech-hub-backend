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

    # First: strip full Markdown image syntax ![alt](url)
    text = _MARKDOWN_IMAGE_PATTERN.sub('', text)

    # Then: strip any remaining bare image URLs
    for url in image_urls:
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

def _col_idx_to_a1(col_idx_0_based: int) -> str:
    """Convert 0-based column index to Excel/Sheets column letters (A, B, ..., AA, AB, ...)."""
    if col_idx_0_based < 0:
        raise ValueError("Column index must be >= 0")
    n = col_idx_0_based + 1
    letters = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters

def _normalize_header(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip()).lower()

def _build_row_for_headers(headers: List[str], values_by_header: Dict[str, Any]) -> List[Any]:
    """
    Build an ordered row aligned to `headers`.
    `values_by_header` keys are compared case-insensitively.
    """
    normalized_map = {_normalize_header(k): v for k, v in (values_by_header or {}).items()}
    row: List[Any] = []
    for h in headers:
        row.append(normalized_map.get(_normalize_header(h), ""))
    return row



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
    }
]


class ConversationalAgentService:
    """
    Agentic AI that can call sub-tools within a single workflow step.

    Sub-tools available to the AI:
    - search_products(query) → RAG search against business KB
    - create_order(...) → OrderService.create_order
    - calculate_total(items) → OrderService.calculate_order_total
    """

    def __init__(self):
        self.llm_service = LLMService()
        self.order_service = OrderService()

    async def execute(
        self,
        user_message: str,
        session_key: str,
        business_config: Dict[str, Any],
        user: User,
        db: AsyncSession
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
                "airtable_base_id": business_config.get("storage_airtable_base_id", ""),
                "airtable_orders_table": business_config.get("storage_airtable_orders_table", "Orders"),
                "airtable_customers_table": business_config.get("storage_airtable_customers_table", "Customers"),
            }

            # Build the system prompt
            system_prompt = self._build_system_prompt(
                business_name=business_name,
                order_type=order_type,
                currency=currency,
                delivery_methods=delivery_methods,
                custom_prompt=custom_system_prompt
            )

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
            order_data = None
            order_notification = ""
            collected_image_urls: List[str] = []
            max_iterations = 3

            for iteration in range(max_iterations):
                # Call LLM with sub-tools
                response = await self.llm_service.chat_completion(
                    messages=messages,
                    tools=AGENT_SUB_TOOLS,
                    temperature=0.3,
                    max_tokens=800,
                    provider="openai"
                )

                if response.error:
                    logger.error(f"[CONV_AGENT] LLM error: {response.error}")
                    return self._fallback_response(business_name)

                # If no tool calls, we have the final response
                if not response.tools_called:
                    final_text = response.content or f"Thank you for contacting {business_name}! How can I help you?"

                    # Extract image URLs from AI response (for metadata)
                    # NOTE: Do NOT strip URLs from response_text here.
                    # The smart dispatcher in tool_executor.py handles
                    # extraction + native media sending at send-time.
                    image_urls = _dedupe_keep_order(
                        extract_image_urls(final_text) + collected_image_urls
                    )
                    final_text = self._ensure_image_urls_in_text(final_text, image_urls)
                    final_text = self._format_for_channel(final_text, platform)

                    # Save assistant response to CCM
                    await self._save_to_ccm(session_key, "assistant", final_text)

                    return {
                        "response_text": final_text,
                        "image_urls": image_urls,
                        "order_created": order_created,
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

                    # Execute the sub-tool
                    tool_result = await self._execute_sub_tool(
                        tool_name=tool_name,
                        arguments=tool_args,
                        kb_id=kb_id,
                        order_type=order_type,
                        currency=currency,
                        business_name=business_name,
                        storage_config=storage_config,
                        user=user,
                        db=db
                    )

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

                    # Check if an order was created
                    if tool_name == "create_order" and tool_result.get("success"):
                        order_created = True
                        order_data = tool_result.get("order_data", tool_result)
                        order_notification = self._format_business_notification(
                            order_data, business_name, currency
                        )

                    # Add tool result to conversation
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(tool_result, default=str)
                    })

            # If we exhausted iterations, return whatever we have
            final_text = response.content or f"Thank you for your patience! Our team at {business_name} will assist you shortly."

            # Extract image URLs from AI response (for metadata)
            image_urls = _dedupe_keep_order(
                extract_image_urls(final_text) + collected_image_urls
            )
            final_text = self._ensure_image_urls_in_text(final_text, image_urls)
            final_text = self._format_for_channel(final_text, platform)

            await self._save_to_ccm(session_key, "assistant", final_text)

            return {
                "response_text": final_text,
                "image_urls": image_urls,
                "order_created": order_created,
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
- Collect customer details (name, phone, delivery address)
- Create orders when the customer is ready
- Calculate order totals

## Order Flow
1. Greet the customer and help them browse products/menu
2. When they want to order, collect: name, phone number, items with quantities
3. Ask about delivery method ({delivery_str})
4. If delivery, collect the delivery address
5. Confirm the order summary with total price
6. Create the order

## Rules
- Keep responses brief and friendly (WhatsApp style, under 200 words)
- Always use {currency} for prices
- Use emojis naturally but don't overdo it
- If you don't know a price, search the catalog first
- Never make up product information — always search first
- If the customer's request is unclear, ask for clarification
- Respond in the same language as the customer
- Available delivery methods: {delivery_str}
- When showing products that have images, ALWAYS include the full image URL on its own line so the customer can see the product photo
- Never shorten or omit image URLs — include the complete URL exactly as provided in the catalog data
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
        user: User,
        db: AsyncSession
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
                    db=db
                )

            elif tool_name == "calculate_total":
                return await self._sub_calculate_total(
                    items=arguments.get("items", []),
                    currency=currency
                )

            else:
                return {"success": False, "error": f"Unknown sub-tool: {tool_name}"}

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

            if result.get("success"):
                return {
                    "success": True,
                    "result": result.get("result", "No results found"),
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
        db: AsyncSession = None
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
                        db=db
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

    # ═══════════════════════════════════════════════════════════
    # ORDER STORAGE PERSISTENCE (Google Sheets / Airtable)
    # ═══════════════════════════════════════════════════════════

    async def _persist_to_storage(
        self,
        order_data: Dict[str, Any],
        storage_config: Dict[str, Any],
        business_name: str,
        user: User,
        db: AsyncSession
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
            from .tool_executor import ToolExecutor
            executor = ToolExecutor()

            # Extract order fields for storage
            customer = order_data.get("customer", {})
            items = order_data.get("items", [])
            items_summary = "; ".join(
                f"{it.get('name', '?')} x{it.get('quantity', 1)}"
                for it in items
            )
            now = order_data.get("created_at", datetime.now().isoformat())

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
            logger.warning(f"[CONV_AGENT] Storage persistence failed (non-fatal): {e}")

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
        """
        Persist order + customer rows to Google Sheets via existing MCP tool.
        Schema-aware:
        - Ensures header columns exist (creates/extends header row)
        - Writes values into correct columns by header name
        - Avoids duplicate order rows (idempotent by Order ID)
        - Avoids duplicate customers when possible (updates row if phone exists)
        """
        spreadsheet_id = storage_config.get("spreadsheet_id", "")
        if not spreadsheet_id:
            logger.warning("[CONV_AGENT] Google Sheets storage: no spreadsheet_id configured")
            return

        orders_sheet = storage_config.get("orders_sheet_name", "Orders") or "Orders"
        customers_sheet = storage_config.get("customers_sheet_name", "Customers") or "Customers"

        # Canonical column sets (kept stable for consistent exports)
        required_order_headers = [
            "Order ID",
            "Order Status",
            "Customer Name",
            "Customer Phone",
            "Customer Email",
            "Items Summary",
            "Item Count",
            "Subtotal",
            "Currency",
            "Delivery Method",
            "Delivery Address",
            "Notes",
            "Order Type",
            "Created At",
        ]

        required_customer_headers = [
            "Phone",
            "Name",
            "Email",
            "Last Order",
            "Last Order Date",
            "Platform",
        ]

        order_id = order_data.get("order_id", "")

        # Ensure header rows exist and include required columns
        orders_headers = await self._ensure_sheet_headers(
            executor=executor,
            spreadsheet_id=spreadsheet_id,
            sheet_name=orders_sheet,
            required_headers=required_order_headers,
            user=user,
            db=db,
        )
        customers_headers = await self._ensure_sheet_headers(
            executor=executor,
            spreadsheet_id=spreadsheet_id,
            sheet_name=customers_sheet,
            required_headers=required_customer_headers,
            user=user,
            db=db,
        )

        try:
            # Idempotency: if order already exists in Orders tab, do not append again.
            if order_id and await self._sheet_contains_value(
                executor=executor,
                spreadsheet_id=spreadsheet_id,
                sheet_name=orders_sheet,
                headers=orders_headers,
                header_name="Order ID",
                value=order_id,
                user=user,
                db=db,
            ):
                logger.info(f"[CONV_AGENT] Order {order_id} already exists in Sheets — skipping duplicate append")
            else:
                order_values = {
                    "Order ID": order_id,
                    "Order Status": order_data.get("status", "pending"),
                    "Customer Name": customer.get("name", ""),
                    "Customer Phone": customer.get("phone", ""),
                    "Customer Email": customer.get("email", ""),
                    "Items Summary": items_summary,
                    "Item Count": order_data.get("item_count", 0),
                    "Subtotal": order_data.get("subtotal", 0),
                    "Currency": order_data.get("currency", "KES"),
                    "Delivery Method": order_data.get("delivery_method", ""),
                    "Delivery Address": order_data.get("delivery_address", ""),
                    "Notes": order_data.get("notes", ""),
                    "Order Type": order_data.get("order_type", ""),
                    "Created At": created_at,
                }
                order_row = _build_row_for_headers(orders_headers, order_values)
                order_append = await self._append_row_with_fallback_ranges(
                    executor=executor,
                    spreadsheet_id=spreadsheet_id,
                    candidate_ranges=[
                        f"{orders_sheet}!A:ZZ",
                        "Orders!A:ZZ",
                        "Sheet1!A:ZZ",
                        "A:ZZ",
                    ],
                    row=order_row,
                    user=user,
                    db=db,
                )
                if order_append.get("success"):
                    logger.info(f"[CONV_AGENT] Order {order_id} saved to Google Sheets ({order_append.get('range_name')})")
                else:
                    logger.warning(f"[CONV_AGENT] Sheets order save error: {order_append.get('error')}")
        except Exception as e:
            logger.warning(f"[CONV_AGENT] Sheets order save failed: {e}")

        try:
            platform = storage_config.get("platform", "whatsapp") or "whatsapp"
            customer_phone = customer.get("phone", "")
            customer_values = {
                "Phone": customer_phone,
                "Name": customer.get("name", ""),
                "Email": customer.get("email", ""),
                "Last Order": order_id,
                "Last Order Date": created_at,
                "Platform": platform,
            }

            # Prefer update-in-place if customer phone already exists
            updated = False
            if customer_phone:
                updated = await self._upsert_customer_by_phone(
                    executor=executor,
                    spreadsheet_id=spreadsheet_id,
                    sheet_name=customers_sheet,
                    headers=customers_headers,
                    phone_header="Phone",
                    phone_value=customer_phone,
                    values_by_header=customer_values,
                    user=user,
                    db=db,
                )

            if not updated:
                customer_row = _build_row_for_headers(customers_headers, customer_values)
                customer_append = await self._append_row_with_fallback_ranges(
                    executor=executor,
                    spreadsheet_id=spreadsheet_id,
                    candidate_ranges=[
                        f"{customers_sheet}!A:ZZ",
                        "Customers!A:ZZ",
                        "Sheet1!A:ZZ",
                        "A:ZZ",
                    ],
                    row=customer_row,
                    user=user,
                    db=db,
                )
                if customer_append.get("success"):
                    logger.info(f"[CONV_AGENT] Customer {customer.get('name')} saved to Google Sheets ({customer_append.get('range_name')})")
                else:
                    logger.warning(f"[CONV_AGENT] Sheets customer save error: {customer_append.get('error')}")
        except Exception as e:
            logger.warning(f"[CONV_AGENT] Sheets customer save failed: {e}")

    async def _ensure_sheet_headers(
        self,
        executor,
        spreadsheet_id: str,
        sheet_name: str,
        required_headers: List[str],
        user: User,
        db: AsyncSession,
        header_row_index: int = 1,
        max_header_cols: int = 200,
    ) -> List[str]:
        """
        Ensure the header row exists and contains at least `required_headers`.
        If the sheet is empty, it writes a header row.
        If some headers are missing, it appends them to the end of the header row.
        Returns the final header list.
        """
        # Read current header row
        range_name = f"{sheet_name}!A{header_row_index}:{_col_idx_to_a1(max_header_cols - 1)}{header_row_index}"
        res = await executor.execute_tool(
            "google_workspace_sheets",
            {"operation": "read_range", "spreadsheet_id": spreadsheet_id, "range_name": range_name},
            user,
            db,
        )
        if not res.get("success"):
            logger.warning(f"[CONV_AGENT] Sheets header read failed ({sheet_name}): {res.get('error')}")
            # Fall back to required headers to avoid crashing persistence
            return required_headers[:]

        values = (res.get("values") or [])
        current = values[0] if values else []
        current_headers = [str(h).strip() for h in current if str(h).strip()]
        normalized_existing = {_normalize_header(h) for h in current_headers}
        missing = [h for h in required_headers if _normalize_header(h) not in normalized_existing]

        if not current_headers:
            # Empty sheet — write full header row
            await executor.execute_tool(
                "google_workspace_sheets",
                {
                    "operation": "write_range",
                    "spreadsheet_id": spreadsheet_id,
                    "range_name": f"{sheet_name}!A{header_row_index}",
                    "values": [required_headers],
                    "value_input_option": "USER_ENTERED",
                },
                user,
                db,
            )
            return required_headers[:]

        if missing:
            new_headers = current_headers + missing
            await executor.execute_tool(
                "google_workspace_sheets",
                {
                    "operation": "write_range",
                    "spreadsheet_id": spreadsheet_id,
                    "range_name": f"{sheet_name}!A{header_row_index}",
                    "values": [new_headers],
                    "value_input_option": "USER_ENTERED",
                },
                user,
                db,
            )
            return new_headers

        return current_headers

    async def _sheet_contains_value(
        self,
        executor,
        spreadsheet_id: str,
        sheet_name: str,
        headers: List[str],
        header_name: str,
        value: str,
        user: User,
        db: AsyncSession,
        search_limit_rows: int = 2000,
    ) -> bool:
        """Check if a given `value` exists in a column identified by `header_name`."""
        if not value or not headers:
            return False
        target_norm = _normalize_header(header_name)
        col_idx = next((i for i, h in enumerate(headers) if _normalize_header(h) == target_norm), None)
        if col_idx is None:
            return False
        col_letter = _col_idx_to_a1(col_idx)
        range_name = f"{sheet_name}!{col_letter}2:{col_letter}{search_limit_rows}"
        res = await executor.execute_tool(
            "google_workspace_sheets",
            {"operation": "read_range", "spreadsheet_id": spreadsheet_id, "range_name": range_name},
            user,
            db,
        )
        if not res.get("success"):
            return False
        values = res.get("values") or []
        flat = [str(r[0]).strip() for r in values if r and str(r[0]).strip()]
        return str(value).strip() in flat

    async def _upsert_customer_by_phone(
        self,
        executor,
        spreadsheet_id: str,
        sheet_name: str,
        headers: List[str],
        phone_header: str,
        phone_value: str,
        values_by_header: Dict[str, Any],
        user: User,
        db: AsyncSession,
        search_limit_rows: int = 2000,
    ) -> bool:
        """
        If a customer row exists (matched by phone), update fields on that row.
        Returns True if updated, False if not found or update failed.
        """
        if not phone_value or not headers:
            return False

        phone_norm = _normalize_header(phone_header)
        phone_col_idx = next((i for i, h in enumerate(headers) if _normalize_header(h) == phone_norm), None)
        if phone_col_idx is None:
            return False

        phone_col_letter = _col_idx_to_a1(phone_col_idx)
        phone_range = f"{sheet_name}!{phone_col_letter}2:{phone_col_letter}{search_limit_rows}"
        res = await executor.execute_tool(
            "google_workspace_sheets",
            {"operation": "read_range", "spreadsheet_id": spreadsheet_id, "range_name": phone_range},
            user,
            db,
        )
        if not res.get("success"):
            return False

        rows = res.get("values") or []
        normalized_phone_value = str(phone_value).strip()
        match_row_offset = None  # 0-based within the read range (starting at row 2)
        for idx, r in enumerate(rows):
            cell = str(r[0]).strip() if r else ""
            if cell == normalized_phone_value:
                match_row_offset = idx
                break
        if match_row_offset is None:
            return False

        sheet_row_number = 2 + match_row_offset

        # Update only known headers in-place (write_range supports a 2D array starting at A1 cell)
        # We'll write a full row aligned to headers, but only across header length.
        updated_row = _build_row_for_headers(headers, values_by_header)
        end_col = _col_idx_to_a1(len(headers) - 1)
        write_range = f"{sheet_name}!A{sheet_row_number}:{end_col}{sheet_row_number}"
        write_res = await executor.execute_tool(
            "google_workspace_sheets",
            {
                "operation": "write_range",
                "spreadsheet_id": spreadsheet_id,
                "range_name": write_range,
                "values": [updated_row],
                "value_input_option": "USER_ENTERED",
            },
            user,
            db,
        )
        return bool(write_res.get("success"))

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
            "order_created": False,
            "order_data": None,
            "order_notification": "",
            "actions_taken": []
        }
