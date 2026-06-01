"""
WhatsApp Service for integrating with WhatsApp Business API.
"""

import logging
import os
from typing import Any, Dict, List, Optional

import aiohttp

from ..config import settings

logger = logging.getLogger(__name__)


class WhatsAppService:
    """Service for WhatsApp Business API integration."""

    def __init__(self):
        self._initialized = False

    def _get_credentials(self):
        """Get fresh credentials from settings."""
        from ..config import settings
        return {
            "base_url": settings.WHATSAPP_BASE_URL or "https://graph.facebook.com/v22.0",
            "phone_number_id": settings.WHATSAPP_PHONE_NUMBER_ID,
            "business_account_id": settings.WHATSAPP_BUSINESS_ACCOUNT_ID,
            "access_token": settings.WHATSAPP_TOKEN
        }

    async def initialize(self):
        """Initialize the WhatsApp service."""
        if not self._initialized:
            credentials = self._get_credentials()
            if not credentials["phone_number_id"] or not credentials["access_token"]:
                logger.warning("WhatsApp credentials not configured")
            else:
                logger.info("WhatsApp service initialized")
            self._initialized = True

    async def send_message(
        self,
        to_number: str,
        message: str,
        message_type: str = "text",
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Send a message via WhatsApp."""
        try:
            # Get fresh credentials
            credentials = self._get_credentials()

            # Use provided config or fresh credentials
            if config:
                phone_number_id = config.get("phone_number_id")
                access_token = config.get("access_token")
                base_url = config.get("base_url", credentials["base_url"])
                business_account_id = config.get(
                    "business_account_id", credentials["business_account_id"])
            else:
                phone_number_id = credentials["phone_number_id"]
                access_token = credentials["access_token"]
                base_url = credentials["base_url"]
                business_account_id = credentials["business_account_id"]

            if not phone_number_id or not access_token:
                return {
                    "success": False,
                    "error": "WhatsApp credentials not configured"
                }

            # Debug logging
            logger.info(f"WhatsApp Debug - Phone Number ID: {phone_number_id}")
            logger.info(
                f"WhatsApp Debug - Access Token Preview: {access_token[:20] if access_token else 'None'}...")
            logger.info(f"WhatsApp Debug - Base URL: {base_url}")

            # Format phone number (remove + and add country code if needed)
            formatted_number = self._format_phone_number(to_number)
            logger.info(
                f"WhatsApp Debug - Formatted Number: {formatted_number}")

            url = f"{base_url}/{phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            payload = {
                "messaging_product": "whatsapp",
                "to": formatted_number,
                "type": "text",
                "text": {
                    "body": message,
                    "preview_url": True
                }
            }

            async with aiohttp.ClientSession() as session:
                # Log the request details for debugging
                logger.info(f"WhatsApp API Request - URL: {url}")
                logger.info(f"WhatsApp API Request - Headers: {headers}")
                logger.info(f"WhatsApp API Request - Payload: {payload}")

                async with session.post(url, json=payload, headers=headers) as response:
                    result = await response.json()
                    logger.info(
                        f"WhatsApp API Response - Status: {response.status}")
                    logger.info(f"WhatsApp API Response - Result: {result}")

                    if response.status == 200:
                        return {
                            "success": True,
                            "message_id": result.get("messages", [{}])[0].get("id"),
                            "result": f"Message sent to {formatted_number}",
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"WhatsApp API error: {result.get('error', {}).get('message', 'Unknown error')}",
                            "debug_info": {
                                "url": url,
                                "phone_number_id": phone_number_id,
                                "access_token": access_token,
                                "payload": payload,
                                "response": result
                            }
                        }

        except Exception as e:
            logger.error(f"Error sending WhatsApp message: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def mark_message_read(
        self,
        message_id: str,
        show_typing: bool = False,
        to_number: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Mark a message as read and optionally show a typing indicator.

        Per WhatsApp Cloud API docs, the typing indicator is included
        directly in the read-receipt payload — NOT as a separate message.
        The indicator auto-dismisses after 25 seconds or when a reply
        is sent, whichever comes first.
        """
        try:
            credentials = self._get_credentials()
            
            if config:
                phone_number_id = config.get("phone_number_id")
                access_token = config.get("access_token")
                base_url = config.get("base_url", credentials["base_url"])
            else:
                phone_number_id = credentials["phone_number_id"]
                access_token = credentials["access_token"]
                base_url = credentials["base_url"]
                
            if not phone_number_id or not access_token:
                return {"success": False, "error": "WhatsApp credentials not configured"}
                
            url = f"{base_url}/{phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            # Build read receipt payload
            read_payload = {
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id
            }

            # Include typing indicator in the SAME read-receipt request
            # (WhatsApp Cloud API requires this — it's not a separate message type)
            if show_typing:
                read_payload["typing_indicator"] = {
                    "type": "text"
                }
                logger.info(f"[WA_SERVICE] Sending read receipt + typing indicator for message {message_id}")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=read_payload, headers=headers) as response:
                    result = await response.json()
                    if response.status != 200:
                        logger.warning(f"[WA_SERVICE] Failed to mark as read / send typing: {result}")
                    else:
                        if show_typing:
                            logger.info(f"[WA_SERVICE] Read receipt + typing indicator sent successfully")

            return {"success": True, "result": "Read receipt sent"}
                
        except Exception as e:
            logger.error(f"Error marking message read: {e}")
            return {"success": False, "error": str(e)}

    async def send_product_card(
        self,
        to_number: str,
        name: str,
        price: float,
        description: str,
        image_url: str,
        product_id: str,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Send a product card with interactive buttons."""
        try:
            credentials = self._get_credentials()
            
            if config:
                phone_number_id = config.get("phone_number_id")
                access_token = config.get("access_token")
                base_url = config.get("base_url", credentials["base_url"])
            else:
                phone_number_id = credentials["phone_number_id"]
                access_token = credentials["access_token"]
                base_url = credentials["base_url"]
                
            if not phone_number_id or not access_token:
                return {"success": False, "error": "WhatsApp credentials not configured"}
                
            formatted_number = self._format_phone_number(to_number)
            url = f"{base_url}/{phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            body_text = f"*{name}*\nPrice: KES {price}\n\n{description}"
            # Meta body text limit is 1024 characters
            if len(body_text) > 1024:
                body_text = body_text[:1021] + "..."
                
            safe_name = str(name).replace(":", "-")[:100]
            stateless_id = f"{safe_name}:{price}"
            
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": formatted_number,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "header": {
                        "type": "image",
                        "image": {
                            "link": image_url
                        }
                    },
                    "body": {
                        "text": body_text
                    },
                    "action": {
                        "buttons": [
                            {
                                "type": "reply",
                                "reply": {
                                    "id": f"cart:{stateless_id}",
                                    "title": "Add to Cart"
                                }
                            },
                            {
                                "type": "reply",
                                "reply": {
                                    "id": f"details:{stateless_id}",
                                    "title": "View Details"
                                }
                            }
                        ]
                    }
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    result = await response.json()
                    if response.status == 200:
                        return {"success": True, "message_id": result.get("messages", [{}])[0].get("id")}
                    else:
                        logger.warning(f"Failed to send product card: {result}")
                        return {"success": False, "error": result}
                        
        except Exception as e:
            logger.error(f"Error sending product card: {e}")
            return {"success": False, "error": str(e)}

    async def send_order_card(
        self,
        to_number: str,
        order_id: str,
        status: str,
        date: str,
        total: str,
        items: str,
        is_cancellable: bool = True,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Send an order card with interactive action buttons.

        Renders order details as a WhatsApp interactive button message.
        Buttons are contextual:
        - Cancel Order: only shown if the order is in a cancellable status
        - Order Details: always shown
        Button IDs use the format 'cancel_order:{order_id}' for easy
        webhook parsing without requiring a cache lookup.
        """
        try:
            credentials = self._get_credentials()

            if config:
                phone_number_id = config.get("phone_number_id")
                access_token = config.get("access_token")
                base_url = config.get("base_url", credentials["base_url"])
            else:
                phone_number_id = credentials["phone_number_id"]
                access_token = credentials["access_token"]
                base_url = credentials["base_url"]

            if not phone_number_id or not access_token:
                return {"success": False, "error": "WhatsApp credentials not configured"}

            formatted_number = self._format_phone_number(to_number)
            url = f"{base_url}/{phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            # Status emoji mapping
            status_lower = status.strip().lower().replace(" ", "_")
            status_icon = {
                "pending": "🕐", "confirmed": "✅", "preparing": "👨‍🍳",
                "ready": "📦", "shipped": "🚚", "out_for_delivery": "🏍️",
                "delivered": "✅", "cancelled": "❌", "refunded": "💰",
            }.get(status_lower, "📋")

            status_display = status.replace("_", " ").title()

            body_text = (
                f"{status_icon} *Order {order_id}*\n"
                f"Status: *{status_display}*\n"
                f"📅 {date}\n"
                f"💰 Total: *{total}*\n"
                f"📝 {items}"
            )
            # Meta body text limit is 1024 characters
            if len(body_text) > 1024:
                body_text = body_text[:1021] + "..."

            # Build contextual buttons (max 3 per WhatsApp interactive message)
            buttons = []
            if is_cancellable:
                buttons.append({
                    "type": "reply",
                    "reply": {
                        "id": f"cancel_order:{order_id}",
                        "title": "❌ Cancel Order"
                    }
                })
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": f"order_details:{order_id}",
                    "title": "📋 Order Details"
                }
            })

            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": formatted_number,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {
                        "text": body_text
                    },
                    "action": {
                        "buttons": buttons
                    }
                }
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    result = await response.json()
                    if response.status == 200:
                        return {"success": True, "message_id": result.get("messages", [{}])[0].get("id")}
                    else:
                        logger.warning(f"Failed to send order card: {result}")
                        return {"success": False, "error": result}

        except Exception as e:
            logger.error(f"Error sending order card: {e}")
            return {"success": False, "error": str(e)}

    async def send_template_message(
        self,
        to_number: str,
        template_name: str,
        language_code: str = "en_US",
        components: Optional[List[Dict]] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Send a template message via WhatsApp."""
        try:
            # Get fresh credentials
            credentials = self._get_credentials()

            # Use provided config or fresh credentials
            if config:
                phone_number_id = config.get("phone_number_id")
                access_token = config.get("access_token")
                base_url = config.get("base_url", credentials["base_url"])
                business_account_id = config.get(
                    "business_account_id", credentials["business_account_id"])
            else:
                phone_number_id = credentials["phone_number_id"]
                access_token = credentials["access_token"]
                base_url = credentials["base_url"]
                business_account_id = credentials["business_account_id"]

            if not phone_number_id or not access_token:
                return {
                    "success": False,
                    "error": "WhatsApp credentials not configured"
                }

            formatted_number = self._format_phone_number(to_number)

            url = f"{base_url}/{phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            payload = {
                "messaging_product": "whatsapp",
                "to": formatted_number,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {
                        "code": language_code
                    }
                }
            }

            if components:
                payload["template"]["components"] = components

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    result = await response.json()

                    if response.status == 200:
                        return {
                            "success": True,
                            "message_id": result.get("messages", [{}])[0].get("id"),
                            "result": f"Template message sent to {formatted_number}"
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"WhatsApp API error: {result.get('error', {}).get('message', 'Unknown error')}"
                        }

        except Exception as e:
            logger.error(f"Error sending WhatsApp template message: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_phone_number_info(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get information about the WhatsApp phone number."""
        try:
            # Get fresh credentials
            credentials = self._get_credentials()

            # Use provided config or fresh credentials
            if config:
                phone_number_id = config.get("phone_number_id")
                access_token = config.get("access_token")
                base_url = config.get("base_url", credentials["base_url"])
            else:
                phone_number_id = credentials["phone_number_id"]
                access_token = credentials["access_token"]
                base_url = credentials["base_url"]

            if not phone_number_id or not access_token:
                return {
                    "success": False,
                    "error": "WhatsApp credentials not configured"
                }

            url = f"{base_url}/{phone_number_id}"
            headers = {
                "Authorization": f"Bearer {access_token}"
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    result = await response.json()

                    if response.status == 200:
                        return {
                            "success": True,
                            "data": result
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"WhatsApp API error: {result.get('error', {}).get('message', 'Unknown error')}"
                        }

        except Exception as e:
            logger.error(f"Error getting WhatsApp phone number info: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def send_media_message(
        self,
        to_number: str,
        media_url: str,
        media_type: str,
        caption: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Send a media message via WhatsApp."""
        try:
            # Get fresh credentials
            credentials = self._get_credentials()

            # Use provided config or fresh credentials
            if config:
                phone_number_id = config.get("phone_number_id")
                access_token = config.get("access_token")
                base_url = config.get("base_url", credentials["base_url"])
                business_account_id = config.get(
                    "business_account_id", credentials["business_account_id"])
            else:
                phone_number_id = credentials["phone_number_id"]
                access_token = credentials["access_token"]
                base_url = credentials["base_url"]
                business_account_id = credentials["business_account_id"]

            if not phone_number_id or not access_token:
                return {
                    "success": False,
                    "error": "WhatsApp credentials not configured"
                }

            formatted_number = self._format_phone_number(to_number)

            url = f"{base_url}/{phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            payload = {
                "messaging_product": "whatsapp",
                "to": formatted_number,
                "type": media_type,
                media_type: {
                    "link": media_url
                }
            }

            if caption:
                payload[media_type]["caption"] = caption

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    result = await response.json()

                    if response.status == 200:
                        return {
                            "success": True,
                            "message_id": result.get("messages", [{}])[0].get("id"),
                            "result": f"Media message sent to {formatted_number}"
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"WhatsApp API error: {result.get('error', {}).get('message', 'Unknown error')}"
                        }

        except Exception as e:
            logger.error(f"Error sending WhatsApp media message: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def send_location_message(
        self,
        to_number: str,
        latitude: str,
        longitude: str,
        name: Optional[str] = None,
        address: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Send a location message via WhatsApp."""
        try:
            # Get fresh credentials
            credentials = self._get_credentials()

            # Use provided config or fresh credentials
            if config:
                phone_number_id = config.get("phone_number_id")
                access_token = config.get("access_token")
                base_url = config.get("base_url", credentials["base_url"])
                business_account_id = config.get(
                    "business_account_id", credentials["business_account_id"])
            else:
                phone_number_id = credentials["phone_number_id"]
                access_token = credentials["access_token"]
                base_url = credentials["base_url"]
                business_account_id = credentials["business_account_id"]

            if not phone_number_id or not access_token:
                return {
                    "success": False,
                    "error": "WhatsApp credentials not configured"
                }

            formatted_number = self._format_phone_number(to_number)

            url = f"{base_url}/{phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            payload = {
                "messaging_product": "whatsapp",
                "to": formatted_number,
                "type": "location",
                "location": {
                    "latitude": latitude,
                    "longitude": longitude
                }
            }

            if name:
                payload["location"]["name"] = name
            if address:
                payload["location"]["address"] = address

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    result = await response.json()

                    if response.status == 200:
                        return {
                            "success": True,
                            "message_id": result.get("messages", [{}])[0].get("id"),
                            "result": f"Location message sent to {formatted_number}"
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"WhatsApp API error: {result.get('error', {}).get('message', 'Unknown error')}"
                        }

        except Exception as e:
            logger.error(f"Error sending WhatsApp location message: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def list_templates(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """List available WhatsApp templates."""
        try:
            # Get fresh credentials
            credentials = self._get_credentials()

            # Use provided config or fresh credentials
            if config:
                phone_number_id = config.get("phone_number_id")
                access_token = config.get("access_token")
                base_url = config.get("base_url", credentials["base_url"])
                business_account_id = config.get(
                    "business_account_id", credentials["business_account_id"])
            else:
                phone_number_id = credentials["phone_number_id"]
                access_token = credentials["access_token"]
                base_url = credentials["base_url"]
                business_account_id = credentials["business_account_id"]

            if not phone_number_id or not access_token:
                return {
                    "success": False,
                    "error": "WhatsApp credentials not configured"
                }

            url = f"{base_url}/{phone_number_id}/message_templates"
            headers = {
                "Authorization": f"Bearer {access_token}"
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    result = await response.json()

                    if response.status == 200:
                        return {
                            "success": True,
                            "data": result,
                            "result": f"Retrieved {len(result.get('data', []))} templates"
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"WhatsApp API error: {result.get('error', {}).get('message', 'Unknown error')}"
                        }

        except Exception as e:
            logger.error(f"Error listing WhatsApp templates: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def create_template(
        self,
        template_name: str,
        language_code: str = "en_US",
        category: str = "MARKETING",
        components: List[Dict] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new WhatsApp template."""
        try:
            # Get fresh credentials
            credentials = self._get_credentials()

            # Use provided config or fresh credentials
            if config:
                phone_number_id = config.get("phone_number_id")
                access_token = config.get("access_token")
                base_url = config.get("base_url", credentials["base_url"])
                business_account_id = config.get(
                    "business_account_id", credentials["business_account_id"])
            else:
                phone_number_id = credentials["phone_number_id"]
                access_token = credentials["access_token"]
                base_url = credentials["base_url"]
                business_account_id = credentials["business_account_id"]

            if not phone_number_id or not access_token:
                return {
                    "success": False,
                    "error": "WhatsApp credentials not configured"
                }

            url = f"{base_url}/{phone_number_id}/message_templates"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            payload = {
                "name": template_name,
                "language": language_code,
                "category": category
            }

            if components:
                payload["components"] = components

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    result = await response.json()

                    if response.status == 200:
                        return {
                            "success": True,
                            "data": result,
                            "result": f"Template '{template_name}' created successfully"
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"WhatsApp API error: {result.get('error', {}).get('message', 'Unknown error')}"
                        }

        except Exception as e:
            logger.error(f"Error creating WhatsApp template: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    def _product_button_id(product_id: str) -> str:
        """Stable Meta reply button id (max 256 chars)."""
        from .whatsapp_ordering_helpers import sanitize_product_button_id
        return sanitize_product_button_id(product_id)

    async def send_quick_reply_buttons(
        self,
        to_number: str,
        body_text: str,
        buttons: List[Dict[str, str]],
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Send WhatsApp interactive reply buttons (max 3).
        buttons: [{"id": "menu:browse", "title": "Browse menu"}, ...]
        """
        try:
            credentials = self._get_credentials()
            if config:
                phone_number_id = config.get("phone_number_id")
                access_token = config.get("access_token")
                base_url = config.get("base_url", credentials["base_url"])
            else:
                phone_number_id = credentials["phone_number_id"]
                access_token = credentials["access_token"]
                base_url = credentials["base_url"]

            if not phone_number_id or not access_token:
                return {"success": False, "error": "WhatsApp credentials not configured"}

            wa_buttons = []
            for btn in buttons[:3]:
                title = (btn.get("title") or "Option")[:20]
                btn_id = (btn.get("id") or "menu:option")[:256]
                wa_buttons.append({
                    "type": "reply",
                    "reply": {"id": btn_id, "title": title},
                })

            if not wa_buttons:
                return {"success": False, "error": "No buttons provided"}

            formatted_number = self._format_phone_number(to_number)
            url = f"{base_url}/{phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            payload = {
                "messaging_product": "whatsapp",
                "to": formatted_number,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body_text[:1024]},
                    "action": {"buttons": wa_buttons},
                },
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    result = await response.json()
                    if response.status == 200:
                        return {
                            "success": True,
                            "message_id": result.get("messages", [{}])[0].get("id"),
                        }
                    logger.warning(f"Failed to send quick reply buttons: {result}")
                    return {"success": False, "error": result}
        except Exception as e:
            logger.error(f"Error sending quick reply buttons: {e}")
            return {"success": False, "error": str(e)}

    def _format_phone_number(self, phone_number: str) -> str:
        """Format phone number for WhatsApp API."""
        # Remove common prefixes and format
        cleaned = phone_number.replace(
            "+", "").replace("-", "").replace(" ", "")

        # For international numbers, keep the country code
        # WhatsApp API expects numbers without + but with country code
        # Examples: +254711371265 -> 254711371265, +1234567890 -> 1234567890

        # If it's a 10-digit number without country code, assume US
        if len(cleaned) == 10:
            cleaned = "1" + cleaned  # Assume US number

        return cleaned

    async def test_connection(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Test WhatsApp connection by getting phone number info."""
        try:
            # Get fresh credentials
            credentials = self._get_credentials()

            # Use provided config or fresh credentials
            if config:
                phone_number_id = config.get("phone_number_id")
                access_token = config.get("access_token")
                base_url = config.get("base_url", credentials["base_url"])
                business_account_id = config.get(
                    "business_account_id", credentials["business_account_id"])
            else:
                phone_number_id = credentials["phone_number_id"]
                access_token = credentials["access_token"]
                base_url = credentials["base_url"]
                business_account_id = credentials["business_account_id"]

            if not phone_number_id or not access_token:
                return {
                    "success": False,
                    "error": "WhatsApp credentials not configured"
                }

            # Test by getting phone number info
            url = f"{base_url}/{phone_number_id}"
            headers = {
                "Authorization": f"Bearer {access_token}"
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    result = await response.json()

                    if response.status == 200:
                        return {
                            "success": True,
                            "message": "WhatsApp connection successful",
                            "data": result
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"WhatsApp API error: {result.get('error', {}).get('message', 'Unknown error')}"
                        }

        except Exception as e:
            logger.error(f"WhatsApp connection test failed: {e}")
            return {
                "success": False,
                "error": f"WhatsApp connection test failed: {str(e)}"
            }
