"""
Notion service for Mini-Hub MCP Server.
"""

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, quote

import aiohttp

from ..config import settings

logger = logging.getLogger(__name__)


class NotionService:
    """Notion API service."""

    def __init__(self):
        self.access_token: Optional[str] = None
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
    
    async def initialize(self):
        """Initialize Notion client."""
        self.client_id = getattr(settings, "NOTION_CLIENT_ID", None)
        self.client_secret = getattr(settings, "NOTION_CLIENT_SECRET", None)
        
        if self.client_id and self.client_secret:
             logger.info("Notion credentials initialized")
        else:
             logger.warning("Notion credentials not fully configured")

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        """Generate Notion OAuth authorization URL."""
        if not self.client_id:
            raise ValueError("Notion client_id must be configured")

        # Notion uses basic auth or client_id in query? 
        # https://developers.notion.com/docs/authorization
        # URL: https://api.notion.com/v1/oauth/authorize?client_id=...&response_type=code&owner=user&redirect_uri=...&state=...
        
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "owner": "user",
            "redirect_uri": redirect_uri,
            "state": state
        }
        
        base_url = "https://api.notion.com/v1/oauth/authorize"
        return f"{base_url}?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange authorization code for access token."""
        if not self.client_id or not self.client_secret:
            raise ValueError("Notion credentials must be configured")

        token_url = "https://api.notion.com/v1/oauth/token"
        
        # Notion requires Basic Auth with client_id:client_secret encoded.
        # OR sending them in body. Docs say Basic Auth header is preferred.
        
        auth = aiohttp.BasicAuth(login=self.client_id, password=self.client_secret)
        
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, json=data, auth=auth) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    raise Exception(f"Failed to exchange token: {response.status} - {error_text}")

    async def search_pages(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """Search for pages in Notion."""
        if not self.access_token:
            return {"success": False, "error": "Access token required"}

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }

        # Search API
        url = "https://api.notion.com/v1/search"
        payload = {
            "query": query,
            "page_size": limit,
            "filter": {
                "property": "object",
                "value": "page"
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    results = []
                    for item in data.get("results", []):
                        # Extract title
                        title = "Untitled"
                        props = item.get("properties", {})
                        # Search for title property
                        for prop_val in props.values():
                            if prop_val.get("type") == "title":
                                title_obj = prop_val.get("title", [])
                                if title_obj:
                                    title = "".join([t.get("plain_text", "") for t in title_obj])
                                break
                        
                        results.append({
                            "id": item.get("id"),
                            "title": title,
                            "url": item.get("url"),
                            "last_edited": item.get("last_edited_time"),
                            "icon": item.get("icon")
                        })
                        
                    return {
                        "success": True,
                        "pages": results,
                        "count": len(results),
                        "query": query
                    }
                else:
                    text = await response.text()
                    return {"success": False, "error": f"Failed to search Notion: {text}"}

    async def create_page(self, parent_id: str, title: str, content: str = "") -> Dict[str, Any]:
        """Create a new page."""
        if not self.access_token:
            return {"success": False, "error": "Access token required"}

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }

        url = "https://api.notion.com/v1/pages"
        
        # Simple page creation with title
        payload = {
            "parent": {"page_id": parent_id} if "-" in parent_id else {"database_id": parent_id}, # Crude heuristic, user should specify type or we guess
            # Actually, robust way is to ask user if parent is DB or Page. 
            # For simplicity, let's assume parent_id is passed correctly. 
            # But wait, if we don't know the type, it's hard.
            # Let's try to default to page_id, but if it fails...
            # A common pattern is likely "search for parent" then "create".
            # For now, let's assume page_id as parent.
            "properties": {
                "title": [
                    {
                        "text": {
                            "content": title
                        }
                    }
                ]
            }
        }
        
        # If content provided, add as children blocks
        if content:
             payload["children"] = [
                 {
                     "object": "block",
                     "type": "paragraph",
                     "paragraph": {
                         "rich_text": [
                             {
                                 "type": "text",
                                 "text": {
                                     "content": content
                                 }
                             }
                         ]
                     }
                 }
             ]

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "success": True, 
                        "message": "Page created successfully", 
                        "page_id": data.get("id"), 
                        "url": data.get("url")
                    }
                else:
                    text = await response.text()
                    return {"success": False, "error": f"Failed to create page: {text}"}
