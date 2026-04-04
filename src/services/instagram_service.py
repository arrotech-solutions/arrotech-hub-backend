"""
Instagram Service for Graph API Interactions
"""

import logging
import httpx
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Constants
FACEBOOK_GRAPH_URL = "https://graph.facebook.com/v22.0"

class InstagramService:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.client = httpx.AsyncClient()

    async def get_page_id(self) -> Optional[str]:
        """Fetch the connected Facebook Page ID."""
        try:
            url = f"{FACEBOOK_GRAPH_URL}/me/accounts"
            params = {"access_token": self.access_token}
            response = await self.client.get(url, params=params)
            data = response.json()
            if data.get("data") and len(data["data"]) > 0:
                # Usually returns multiple pages, grab the first one as default
                return data["data"][0]["id"]
            return None
        except Exception as e:
            logger.error(f"Error fetching page ID: {e}")
            return None

    async def send_dm(self, recipient_id: str, message: str, page_id: Optional[str] = None) -> Dict[str, Any]:
        """Send a direct message via Graph API."""
        try:
            if not page_id:
                page_id = await self.get_page_id()
                
            if not page_id:
                # Sometimes the access token is a page token already. We can try 'me'.
                page_id = "me"
                
            url = f"{FACEBOOK_GRAPH_URL}/{page_id}/messages"
            payload = {
                "recipient": {"id": recipient_id},
                "message": {"text": message}
            }
            params = {"access_token": self.access_token}
            
            response = await self.client.post(url, json=payload, params=params)
            data = response.json()
            
            if response.status_code != 200:
                logger.error(f"Failed to send Instagram DM: {data}")
                return {
                    "success": False,
                    "error": data.get("error", {}).get("message", "Unknown Graph API error")
                }
                
            return {
                "success": True,
                "message": "Message sent successfully",
                "message_id": data.get("message_id")
            }
        except Exception as e:
            logger.error(f"Exception sending Instagram DM: {e}")
            return {
                "success": False,
                "error": str(e)
            }
