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

    async def initialize(self):
        """
        Auto-registers the Telegram Webhook on startup.
        Telegram only requires this once, but calling it on startup ensures the correct URL is always active.
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

        webhook_url = f"{base_url}/api/telegram/webhook"
        
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
