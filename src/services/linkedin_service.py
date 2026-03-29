"""
LinkedIn Service for CRM and lead generation operations.
"""

import logging
from typing import Any, Dict, List, Optional
import aiohttp

from ..models import Connection

logger = logging.getLogger(__name__)


class LinkedinService:
    """LinkedIn API service for profile, company, and connection management."""
    
    def __init__(self):
        self.base_url = "https://api.linkedin.com/v2"
        self.access_token = None
    
    async def initialize(self, connection: Connection):
        """Initialize LinkedIn service with connection."""
        self.connection = connection
        # Authentication should be established from connection config
        if self.connection and self.connection.config:
            self.access_token = self.connection.config.get("access_token")
    
    async def _make_request(self, method: str, endpoint: str, params: Dict = None, data: Dict = None) -> Dict:
        """Make authenticated request to LinkedIn API."""
        if not self.access_token:
            return {"success": False, "error": "Not authenticated with LinkedIn. Missing access token."}
        
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                if method == "GET":
                    async with session.get(url, headers=headers, params=params) as response:
                        response_data = await response.json()
                        return {"success": response.status in (200, 201), "data": response_data, "status": response.status}
                elif method == "POST":
                    async with session.post(url, headers=headers, json=data) as response:
                        response_data = await response.json()
                        return {"success": response.status in (200, 201), "data": response_data, "status": response.status}
                return {"success": False, "error": f"Unsupported method: {method}"}
        except Exception as e:
            logger.error(f"Error making LinkedIn request: {e}")
            return {"success": False, "error": str(e)}

    async def search_people(self, keywords: str, limit: int = 10) -> Dict[str, Any]:
        """Search for people matching keywords."""
        try:
            # Note: LinkedIn restricts general people search API heavily. 
            # This is a conceptual implementation mapped to typical search endpoints or Sales Navigator.
            endpoint = "/people-search" 
            params = {"keywords": keywords, "count": limit}
            result = await self._make_request("GET", endpoint, params=params)
            
            if result.get("success"):
                return {
                    "success": True,
                    "people": result.get("data", {}).get("elements", []),
                    "message": f"Found people matching: {keywords}"
                }
            return result
        except Exception as e:
            logger.error(f"Error searching LinkedIn people: {e}")
            return {"success": False, "error": str(e)}

    async def get_profile(self, profile_id: str = "me") -> Dict[str, Any]:
        """Get profile information for a user."""
        try:
            endpoint = f"/me" if profile_id == "me" else f"/people/(id:{profile_id})"
            # Projection to get typical fields
            params = {"projection": "(id,firstName,lastName,profilePicture,headline,vanityName)"}
            result = await self._make_request("GET", endpoint, params=params)
            
            if result.get("success"):
                return {
                    "success": True,
                    "profile": result.get("data", {})
                }
            return result
        except Exception as e:
            logger.error(f"Error getting LinkedIn profile: {e}")
            return {"success": False, "error": str(e)}

    async def search_companies(self, keywords: str, limit: int = 10) -> Dict[str, Any]:
        """Search for companies on LinkedIn."""
        try:
            endpoint = "/organizations" 
            params = {"q": "search", "query": keywords, "count": limit}
            result = await self._make_request("GET", endpoint, params=params)
            
            if result.get("success"):
                return {
                    "success": True,
                    "companies": result.get("data", {}).get("elements", [])
                }
            return result
        except Exception as e:
            logger.error(f"Error searching LinkedIn companies: {e}")
            return {"success": False, "error": str(e)}

    async def get_company(self, company_id: str) -> Dict[str, Any]:
        """Get details for a specific company."""
        try:
            endpoint = f"/organizations/{company_id}"
            result = await self._make_request("GET", endpoint)
            
            if result.get("success"):
                return {
                    "success": True,
                    "company": result.get("data", {})
                }
            return result
        except Exception as e:
            logger.error(f"Error getting LinkedIn company: {e}")
            return {"success": False, "error": str(e)}

    async def get_connections(self, limit: int = 50) -> Dict[str, Any]:
        """Get connections for the authenticated user."""
        try:
            endpoint = "/connections"
            params = {"q": "viewer", "count": limit}
            result = await self._make_request("GET", endpoint, params=params)
            
            if result.get("success"):
                return {
                    "success": True,
                    "connections": result.get("data", {}).get("elements", []),
                    "total": result.get("data", {}).get("paging", {}).get("total", 0)
                }
            return result
        except Exception as e:
            logger.error(f"Error getting LinkedIn connections: {e}")
            return {"success": False, "error": str(e)}

    async def create_post(self, text: str, visibility: str = "PUBLIC") -> Dict[str, Any]:
        """Create a text post on LinkedIn for the authenticated user."""
        try:
            # First, we need the user's URN id. We can get it via get_profile
            profile_res = await self.get_profile("me")
            if not profile_res.get("success"):
                return {"success": False, "error": "Failed to retrieve user profile to create post"}
            
            person_id = profile_res.get("profile", {}).get("id")
            if not person_id:
                return {"success": False, "error": "Could not extract user ID"}
                
            author_urn = f"urn:li:person:{person_id}"
            
            endpoint = "/ugcPosts"
            data = {
                "author": author_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {
                            "text": text
                        },
                        "shareMediaCategory": "NONE"
                    }
                },
                "visibility": {
                    "com.linkedin.ugc.MemberNetworkVisibility": visibility
                }
            }
            
            result = await self._make_request("POST", endpoint, data=data)
            
            if result.get("success"):
                return {
                    "success": True,
                    "post": result.get("data", {}),
                    "message": "Successfully created LinkedIn post."
                }
            return result
        except Exception as e:
            logger.error(f"Error creating LinkedIn post: {e}")
            return {"success": False, "error": str(e)}

    async def get_analytics(self, metric_type: str = "visitors") -> Dict[str, Any]:
        """Get analytics for the user's professional profile/network."""
        try:
            endpoint = "/networkSizes/urn:li:person:me"
            
            result = await self._make_request("GET", endpoint)
            
            if result.get("success"):
                return {
                    "success": True,
                    "analytics": result.get("data", {}),
                    "message": f"Successfully retrieved LinkedIn {metric_type} analytics."
                }
            return result
        except Exception as e:
            logger.error(f"Error getting LinkedIn analytics: {e}")
            return {"success": False, "error": str(e)}
