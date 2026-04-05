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
        url = f"https://api.telegram.org/bot{self.bot_token}/setWebhook"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json={"url": webhook_url, "drop_pending_updates": True}, timeout=10.0)
                response.raise_for_status()
                data = response.json()
                if data.get("ok"):
                    logger.info(f"Telegram webhook successfully registered to {webhook_url}")
                else:
                    logger.error(f"Failed to set Telegram webhook: {data}")
            except Exception as e:
                logger.error(f"Exception while setting Telegram webhook: {e}")
