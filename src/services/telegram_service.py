import httpx
import logging
import re
from typing import Dict, Any, Optional

from ..config import settings

logger = logging.getLogger(__name__)

class TelegramService:
    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        if not self.bot_token:
            logger.warning("[TelegramService] TELEGRAM_BOT_TOKEN is not set in environment.")

    async def send_message(self, chat_id: str, message: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Send a text message to a Telegram chat.
        """
        bot_token = config.get("bot_token") if config else self.bot_token
        
        if not bot_token:
            return {"success": False, "error": "Telegram Bot Token is not configured"}

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        
        # Format message for Telegram Markdown (Legacy)
        formatted_message = self._format_markdown_for_telegram(message)
        
        payload = {
            "chat_id": chat_id,
            "text": formatted_message,
            "parse_mode": "Markdown"
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, timeout=10.0)
                response.raise_for_status()
                data = response.json()
                
                if data.get("ok"):
                    logger.info(f"Successfully sent Telegram message to {chat_id}")
                    return {"success": True, "result": "Message sent successfully"}
                else:
                    logger.error(f"Telegram API returned error: {data}")
                    return {"success": False, "error": data.get("description", "Unknown error")}
                    
            except httpx.HTTPError as e:
                logger.error(f"HTTP Error sending Telegram message: {e}")
                return {"success": False, "error": str(e)}
            except Exception as e:
                logger.error(f"Unexpected error in Telegram send_message: {e}")
                return {"success": False, "error": str(e)}

    async def send_chat_action(self, chat_id: str, action: str = "typing", config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Send a chat action (like typing) to a Telegram chat.
        Valid actions: typing, upload_photo, record_video, etc.
        """
        bot_token = config.get("bot_token") if config else self.bot_token
        
        if not bot_token:
            return {"success": False, "error": "Telegram Bot Token is not configured"}

        url = f"https://api.telegram.org/bot{bot_token}/sendChatAction"
        
        payload = {
            "chat_id": chat_id,
            "action": action
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, timeout=5.0)
                response.raise_for_status()
                data = response.json()
                
                if data.get("ok"):
                    return {"success": True, "result": f"Action '{action}' sent successfully"}
                else:
                    return {"success": False, "error": data.get("description", "Unknown error")}
                    
            except Exception as e:
                logger.error(f"Unexpected error in Telegram send_chat_action: {e}")
                return {"success": False, "error": str(e)}

    async def send_photo(
        self,
        chat_id: str,
        photo_url: str,
        caption: str = "",
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send a photo message to a Telegram chat.
        Uses Telegram's sendPhoto API for native image display.
        """
        bot_token = config.get("bot_token") if config else self.bot_token

        if not bot_token:
            return {"success": False, "error": "Telegram Bot Token is not configured"}

        url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

        payload = {
            "chat_id": chat_id,
            "photo": photo_url,
        }

        if caption:
            # Format caption for Telegram Markdown
            formatted_caption = self._format_markdown_for_telegram(caption)
            payload["caption"] = formatted_caption
            payload["parse_mode"] = "Markdown"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, timeout=15.0)
                response.raise_for_status()
                data = response.json()

                if data.get("ok"):
                    logger.info(f"Successfully sent Telegram photo to {chat_id}")
                    return {"success": True, "result": "Photo sent successfully"}
                else:
                    logger.error(f"Telegram sendPhoto API returned error: {data}")
                    return {"success": False, "error": data.get("description", "Unknown error")}

            except httpx.HTTPError as e:
                logger.error(f"HTTP Error sending Telegram photo: {e}")
                return {"success": False, "error": str(e)}
            except Exception as e:
                logger.error(f"Unexpected error in Telegram send_photo: {e}")
                return {"success": False, "error": str(e)}

    async def send_order_card(
        self,
        chat_id: str,
        order_id: str,
        status: str,
        date: str,
        total: str,
        items: str,
        is_cancellable: bool = True,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Send an order card with inline keyboard action buttons.

        Renders order details as a Telegram message with inline keyboard
        buttons. The callback_data uses format 'cancel_order:{order_id}'
        which gets parsed in the webhook handler.
        """
        bot_token = config.get("bot_token") if config else self.bot_token

        if not bot_token:
            return {"success": False, "error": "Telegram Bot Token is not configured"}

        # Status emoji mapping
        status_lower = status.strip().lower().replace(" ", "_")
        status_icon = {
            "pending": "🕐", "confirmed": "✅", "preparing": "👨‍🍳",
            "ready": "📦", "shipped": "🚚", "out_for_delivery": "🏍️",
            "delivered": "✅", "cancelled": "❌", "refunded": "💰",
        }.get(status_lower, "📋")

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
        if is_cancellable:
            buttons.append([
                {"text": "❌ Cancel Order", "callback_data": f"cancel_order:{order_id}"}
            ])
        buttons.append([
            {"text": "📋 Order Details", "callback_data": f"order_details:{order_id}"}
        ])

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": {
                "inline_keyboard": buttons
            }
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, timeout=10.0)
                response.raise_for_status()
                data = response.json()

                if data.get("ok"):
                    logger.info(f"Successfully sent Telegram order card {order_id} to {chat_id}")
                    return {"success": True, "result": "Order card sent successfully"}
                else:
                    logger.error(f"Telegram API returned error for order card: {data}")
                    return {"success": False, "error": data.get("description", "Unknown error")}

            except httpx.HTTPError as e:
                logger.error(f"HTTP Error sending Telegram order card: {e}")
                return {"success": False, "error": str(e)}
            except Exception as e:
                logger.error(f"Unexpected error in Telegram send_order_card: {e}")
                return {"success": False, "error": str(e)}

    def _format_markdown_for_telegram(self, text: str) -> str:
        """
        Convert standard Markdown to Telegram's Markdown (Legacy) format.
        Telegram Legacy Markdown uses:
        - *bold*
        - _italic_
        - `code`
        - [text](url)
        """
        if not text:
            return ""

        # 1. Handle Bold: **text** -> *text*
        # (Standard AI output uses double asterisks for bold)
        text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)

        # 2. Handle Headers: # Header -> *Header*
        text = re.sub(r'^(#{1,6})\s+(.+)$', r'*\2*', text, flags=re.MULTILINE)

        # 3. Handle Escaping for Legacy Markdown
        # Telegram Legacy Markdown is actually very loose, but we should 
        # ensure no stray single asterisks break the formatting.
        # For now, the simple bold conversion is what's requested.

        return text

    async def get_me(self, bot_token: Optional[str] = None) -> Dict[str, Any]:
        """Validate a bot token via getMe."""
        token = bot_token or self.bot_token
        if not token:
            return {"success": False, "error": "Telegram Bot Token is not configured"}

        url = f"https://api.telegram.org/bot{token}/getMe"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, timeout=10.0)
                data = response.json()
                if response.status_code == 200 and data.get("ok"):
                    return {"success": True, "result": data.get("result", {})}
                return {
                    "success": False,
                    "error": data.get("description", "Invalid bot token"),
                }
            except Exception as e:
                return {"success": False, "error": str(e)}

    async def set_webhook(
        self,
        bot_token: str,
        webhook_url: str,
        *,
        secret_token: Optional[str] = None,
        drop_pending_updates: bool = True,
    ) -> Dict[str, Any]:
        """Register Telegram webhook for a bot token."""
        if not bot_token:
            return {"success": False, "error": "Telegram Bot Token is not configured"}

        payload: Dict[str, Any] = {
            "url": webhook_url,
            "drop_pending_updates": drop_pending_updates,
            "allowed_updates": ["message", "callback_query"],
        }
        if secret_token:
            payload["secret_token"] = secret_token

        set_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(set_url, json=payload, timeout=10.0)
                data = response.json()
                if data.get("ok"):
                    return {"success": True, "webhook_url": webhook_url}
                return {
                    "success": False,
                    "error": data.get("description", "Failed to set webhook"),
                }
            except Exception as e:
                return {"success": False, "error": str(e)}

    async def provision_bot(self, bot_token: str) -> Dict[str, Any]:
        """
        Validate bot token, store bot identity, and register a tenant-scoped webhook.
        Returns config fields to persist on the Connection.
        """
        me = await self.get_me(bot_token)
        if not me.get("success"):
            return me

        bot_info = me.get("result") or {}
        bot_id = str(bot_info.get("id") or "")
        bot_username = bot_info.get("username") or ""
        if not bot_id:
            return {"success": False, "error": "Could not resolve bot id from Telegram"}

        base_url = settings.API_BASE_URL.rstrip("/")
        if "localhost" in base_url or "127.0.0.1" in base_url:
            webhook_url = f"{base_url}/api/telegram/webhook/{bot_id}"
            logger.warning(
                "Telegram webhook points at localhost — use a public API_BASE_URL "
                "(e.g. ngrok) for production inbound messages."
            )
        else:
            webhook_url = f"{base_url}/api/telegram/webhook/{bot_id}"

        webhook_result = await self.set_webhook(bot_token, webhook_url)
        if not webhook_result.get("success"):
            # Still return bot identity so connection can be saved; webhook can be retried
            logger.error(
                "Failed to set Telegram webhook for bot %s: %s",
                bot_id,
                webhook_result.get("error"),
            )

        return {
            "success": True,
            "bot_id": bot_id,
            "bot_username": bot_username,
            "webhook_url": webhook_url,
            "webhook_registered": bool(webhook_result.get("success")),
            "webhook_error": webhook_result.get("error"),
        }

    @staticmethod
    def verify_login_widget_hash(data: Dict[str, Any], bot_token: str) -> bool:
        """Verify Telegram Login Widget callback hash."""
        import hashlib
        import hmac

        if not bot_token or not data.get("hash"):
            return False
        check_hash = str(data.get("hash"))
        pairs = []
        for key in sorted(k for k in data.keys() if k != "hash"):
            value = data.get(key)
            if value is None or value == "":
                continue
            pairs.append(f"{key}={value}")
        data_check_string = "\n".join(pairs)
        secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
        calculated = hmac.new(
            secret_key, data_check_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(calculated, check_hash)

    async def handle_update(
        self,
        payload: Dict[str, Any],
        db,
        *,
        bot_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process an inbound Telegram update and route to the owner's ordering workflows.
        Called from Celery after webhook receipt.
        """
        from sqlalchemy import select, and_
        from ..models import Connection
        from .telegram_workflow_trigger import TelegramWorkflowTrigger

        message_obj = payload.get("message") or {}
        message_text = (message_obj.get("text") or "").strip()

        # Location → delivery-style text (parity with WhatsApp location handling)
        if not message_text and message_obj.get("location"):
            loc = message_obj["location"]
            message_text = (
                f"My location is latitude {loc.get('latitude')}, "
                f"longitude {loc.get('longitude')}"
            )

        chat = message_obj.get("chat") or {}
        sender = message_obj.get("from") or {}
        chat_id = str(chat.get("id") or "")
        sender_id = str(sender.get("id") or "")
        sender_name = (
            " ".join(
                filter(
                    None,
                    [sender.get("first_name"), sender.get("last_name")],
                )
            ).strip()
            or sender.get("username")
            or "Customer"
        )

        if not message_text or not chat_id:
            logger.debug("[TelegramService] Ignoring update without text/chat_id")
            return {"success": True, "skipped": True}

        connection = await self._resolve_connection(db, bot_id=bot_id)
        if not connection:
            logger.warning(
                "[TelegramService] No Telegram connection matched bot_id=%s — drop update",
                bot_id,
            )
            return {"success": False, "error": "No matching Telegram connection"}

        await TelegramWorkflowTrigger.on_message_received(
            user_id=connection.user_id,
            sender_id=sender_id,
            chat_id=chat_id,
            message=message_text,
            sender_name=sender_name,
            connection_config=connection.config or {},
        )
        return {"success": True, "user_id": str(connection.user_id)}

    async def _resolve_connection(self, db, *, bot_id: Optional[str] = None):
        """Find the active Telegram connection for this webhook bot."""
        from sqlalchemy import select, and_
        from ..models import Connection

        result = await db.execute(
            select(Connection).where(
                and_(
                    Connection.platform == "telegram",
                    Connection.status == "active",
                )
            )
        )
        connections = result.scalars().all()
        matches = []
        for conn in connections:
            cfg = conn.config or {}
            if bot_id:
                if str(cfg.get("bot_id") or "") == str(bot_id):
                    matches.append(conn)
            else:
                # Legacy shared webhook: match env bot token
                token = cfg.get("bot_token") or ""
                if self.bot_token and token == self.bot_token:
                    matches.append(conn)
                elif not self.bot_token and token:
                    # No env token — only accept if exactly one telegram connection
                    matches.append(conn)

        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            logger.error(
                "[TelegramService] Ambiguous Telegram routing (%s connections). "
                "Each business needs its own BotFather bot + /webhook/{bot_id}.",
                len(matches),
            )
            return None
        return None

    async def initialize(self):
        """
        Auto-registers the Telegram Webhook on startup for the shared env bot (legacy).
        Per-tenant bots register via provision_bot on connect.
        """
        if not self.bot_token:
            logger.info("Skipping Telegram webhook init (no bot token)")
            return

        # Ensure the base URL is properly formatted
        base_url = settings.API_BASE_URL.rstrip('/')
        
        # Fallback for local development using ngrok if needed (but API_BASE_URL should be set)
        if "localhost" in base_url or "127.0.0.1" in base_url:
            logger.warning("Telegram Webhook cannot be set to localhost. Please use a public URL via ngrok/localtunnel.")
            return

        # Prefer bot-id scoped path when we can resolve getMe
        me = await self.get_me(self.bot_token)
        bot_id = str((me.get("result") or {}).get("id") or "") if me.get("success") else ""
        webhook_url = (
            f"{base_url}/api/telegram/webhook/{bot_id}"
            if bot_id
            else f"{base_url}/api/telegram/webhook"
        )
        
        async with httpx.AsyncClient() as client:
            try:
                # 1. Check current webhook info
                info_url = f"https://api.telegram.org/bot{self.bot_token}/getWebhookInfo"
                info_resp = await client.get(info_url, timeout=10.0)
                if info_resp.status_code == 200:
                    info_data = info_resp.json()
                    current_url = info_data.get("result", {}).get("url", "")
                    if current_url == webhook_url:
                        logger.info("Telegram webhook is already correctly configured.")
                        return

                # 2. Set webhook if not matching
                set_url = f"https://api.telegram.org/bot{self.bot_token}/setWebhook"
                response = await client.post(set_url, json={"url": webhook_url, "drop_pending_updates": True}, timeout=10.0)
                response.raise_for_status()
                data = response.json()
                if data.get("ok"):
                    logger.info(f"Telegram webhook successfully registered to {webhook_url}")
                else:
                    logger.error(f"Failed to set Telegram webhook: {data}")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning("Telegram setWebhook rate limited (429). Webhook is likely already set.")
                else:
                    logger.error(f"HTTP Error while checking/setting Telegram webhook: {e}")
            except Exception as e:
                logger.error(f"Exception while setting Telegram webhook: {e}")
