"""
Trello service for Mini-Hub MCP Server (via Atlassian OAuth 2.0).
"""

import logging
import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import aiohttp
from ..config import settings

logger = logging.getLogger(__name__)


class TrelloService:
    """Trello API service using Atlassian OAuth 2.0."""

    def __init__(self):
        self.access_token: Optional[str] = None
        self.access_token_secret: Optional[str] = None
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
        
        # Trello OAuth 1.0a endpoints
        self.request_token_url = "https://trello.com/1/OAuthGetRequestToken"
        self.authorize_url = "https://trello.com/1/OAuthAuthorizeToken"
        self.access_token_url = "https://trello.com/1/OAuthGetAccessToken"
        self.api_base_url = "https://api.trello.com/1"

    async def initialize(self):
        """Initialize Trello credentials."""
        self.client_id = getattr(settings, "TRELLO_CLIENT_ID", None)
        self.client_secret = getattr(settings, "TRELLO_CLIENT_SECRET", None)
        
        if self.client_id and self.client_secret:
             logger.info("Trello credentials initialized")
        else:
             logger.warning("Trello credentials not fully configured")

    async def get_request_token(self, redirect_uri: str) -> Dict[str, str]:
        """Get OAuth 1.0a request token."""
        # Note: requests_oauthlib is synchronous. For high throughput, run in threadpool.
        from requests_oauthlib import OAuth1Session
        
        if not self.client_id or not self.client_secret:
            raise ValueError("Trello config missing")

        oauth = OAuth1Session(
            client_key=self.client_id,
            client_secret=self.client_secret,
            callback_uri=redirect_uri
        )
        
        try:
            fetch_response = await asyncio.to_thread(oauth.fetch_request_token, self.request_token_url)
            return fetch_response
        except Exception as e:
            logger.error(f"Error fetching Trello request token: {e}")
            raise

    def get_auth_url(self, resource_owner_key: str, app_name: str = "Arrotech Hub") -> str:
        """Generate authorization URL."""
        # Standard Trello authorize URL
        # scope=read,write&expiration=never&name=...
        params = {
            "oauth_token": resource_owner_key,
            "scope": "read,write",
            "expiration": "never",
            "name": app_name
        }
        return f"{self.authorize_url}?{urlencode(params)}"

    async def exchange_token(self, resource_owner_key: str, resource_owner_secret: str,verifier: str) -> Dict[str, str]:
        """Exchange request token and verifier for access token."""
        from requests_oauthlib import OAuth1Session
        
        oauth = OAuth1Session(
            client_key=self.client_id,
            client_secret=self.client_secret,
            resource_owner_key=resource_owner_key,
            resource_owner_secret=resource_owner_secret,
            verifier=verifier
        )
        
        try:
            tokens = await asyncio.to_thread(oauth.fetch_access_token, self.access_token_url)
            return tokens
        except Exception as e:
             logger.error(f"Error fetching Trello access token: {e}")
             raise

    async def _request(self, method: str, endpoint: str, params: Dict = None, json_data: Dict = None) -> Any:
        """Helper to make authenticated requests to Trello API via OAuth 1.0a."""
        if not self.access_token:
             return {"success": False, "error": "Access token required"}

        from requests_oauthlib import OAuth1Session
        
        # We need the secret too for OAuth 1.0a signing.
        # Ensure it's set on the instance (retrieved from DB config usually)
        if not self.access_token_secret:
             # Fallback if we only stored token? Trello OAuth1 usually needs secret.
             # If we didn't save it, signing might fail. 
             # For now assume it's set.
             pass

        oauth = OAuth1Session(
            client_key=self.client_id,
            client_secret=self.client_secret,
            resource_owner_key=self.access_token,
            resource_owner_secret=self.access_token_secret
        )
        
        url = f"{self.api_base_url}/{endpoint}"
        
        # OAuth1Session uses requests (sync). Run in thread.
        def _do_req():
            if method.upper() == "GET":
                return oauth.get(url, params=params)
            elif method.upper() == "POST":
                # Trello accepts data in params or body
                return oauth.post(url, params=params, json=json_data)
            elif method.upper() == "PUT":
                 return oauth.put(url, params=params, json=json_data)
            elif method.upper() == "DELETE":
                 return oauth.delete(url, params=params)
            else:
                 return None

        try:
            resp = await asyncio.to_thread(_do_req)
            if not resp:
                 return {"success": False, "error": "Invalid method"}
                 
            if resp.status_code == 200:
                return resp.json()
            else:
                try:
                     return {"success": False, "error": f"Trello Error ({resp.status_code}): {resp.text}"}
                except:
                     return {"success": False, "error": f"Trello Error ({resp.status_code})"}
        except Exception as e:
             return {"success": False, "error": f"Request failed: {str(e)}"}

    async def get_boards(self) -> Dict[str, Any]:
        """Get user's boards."""
        # /members/me/boards
        response = await self._request("GET", "members/me/boards")
        
        if isinstance(response, dict) and "error" in response:
            return response

        # Normalize output
        boards = []
        for b in response:
            boards.append({
                "id": b.get("id"),
                "name": b.get("name"),
                "url": b.get("url"),
                "desc": b.get("desc")
            })
            
        return {"success": True, "boards": boards, "count": len(boards)}

    async def get_lists(self, board_id: str) -> Dict[str, Any]:
        """Get lists on a board."""
        # /boards/{id}/lists
        response = await self._request("GET", f"boards/{board_id}/lists")
        
        if isinstance(response, dict) and "error" in response:
            return response

        lists = []
        for l in response:
            lists.append({
                "id": l.get("id"),
                "name": l.get("name"),
                "closed": l.get("closed"),
                "board_id": l.get("idBoard")
            })
            
        return {"success": True, "lists": lists, "count": len(lists)}

    async def search_cards(self, query: str, limit: int = 20) -> Dict[str, Any]:
        """Search for cards with list info."""
        # /search?query=...&modelTypes=cards&card_fields=all
        params = {
            "query": query,
            "modelTypes": "cards",
            "cards_limit": limit,
            "partial": "true",  # Allow partial matches
            "card_list": "true"  # Include list info
        }
        response = await self._request("GET", "search", params=params)
        
        if isinstance(response, dict) and "error" in response:
            return response
        
        # Build a cache of list IDs to names
        list_cache: Dict[str, str] = {}
        
        cards = []
        for c in response.get("cards", []):
            list_id = c.get("idList")
            list_name = ""
            
            # Try to get list name from embedded list object if Trello returned it
            if c.get("list"):
                list_name = c.get("list", {}).get("name", "")
            elif list_id and list_id not in list_cache:
                # Fetch list info if not cached
                try:
                    list_info = await self._request("GET", f"lists/{list_id}")
                    if isinstance(list_info, dict) and "name" in list_info:
                        list_cache[list_id] = list_info.get("name", "")
                        list_name = list_cache[list_id]
                except:
                    list_name = ""
            elif list_id in list_cache:
                list_name = list_cache[list_id]
            
            cards.append({
                "id": c.get("id"),
                "name": c.get("name"),
                "url": c.get("url"),
                "board_id": c.get("idBoard"),
                "list_id": list_id,
                "list": {"name": list_name, "id": list_id},
                "listName": list_name,  # For easier frontend access
                "due": c.get("due"),
                "closed": c.get("closed")
            })
            
        return {"success": True, "cards": cards, "count": len(cards)}

    async def create_card(self, list_id: str, name: str, desc: str = "", due: str = None) -> Dict[str, Any]:
        """Create a new card on a list."""
        payload = {
            "idList": list_id,
            "name": name,
            "desc": desc
        }
        if due:
            payload["due"] = due
            
        response = await self._request("POST", "cards", params=payload) # Trello often takes query params for POST too, but body preferred usually. 
        # API says: POST /1/cards - Arguments in query or body. Using "params" often works robustly with Trello.
        
        if isinstance(response, dict) and "error" in response:
            return response
            
        return {
            "success": True, 
            "message": "Card created", 
            "card": {
                "id": response.get("id"),
                "name": response.get("name"),
                "url": response.get("url")
            }
        }

    async def update_card(self, card_id: str, list_id: str = None, name: str = None, desc: str = None, closed: bool = None) -> Dict[str, Any]:
        """Update a card (move to list, rename, close, etc)."""
        payload = {}
        if list_id:
            payload["idList"] = list_id
        if name:
            payload["name"] = name
        if desc:
            payload["desc"] = desc
        if closed is not None:
             payload["closed"] = str(closed).lower()

        if not payload:
             return {"success": False, "error": "No update parameters provided"}

        response = await self._request("PUT", f"cards/{card_id}", params=payload)
        
        if isinstance(response, dict) and "error" in response:
            return response

        return {
            "success": True,
            "message": "Card updated",
            "card": response
        }
