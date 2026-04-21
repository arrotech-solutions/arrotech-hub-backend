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
                    image_urls = extract_image_urls(final_text)

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
                        user=user,
                        db=db
                    )

                    actions_taken.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "result_summary": str(tool_result.get("result", ""))[:200]
                    })

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
            image_urls = extract_image_urls(final_text)

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
                    business_name=business_name
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
        business_name: str
    ) -> Dict[str, Any]:
        """Create an order via OrderService."""
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
                # Also generate a receipt
                receipt = await self.order_service.handle_operation(
                    operation="format_order_receipt",
                    order_data=order_result,
                    business_name=business_name,
                    currency=currency
                )
                order_result["receipt"] = receipt.get("result", "")

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
