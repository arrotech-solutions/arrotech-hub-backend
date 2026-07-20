"""
Qdrant Vector DB Service
"""
import logging
import os
import httpx
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class QdrantService:
    def __init__(self):
        self.url = os.getenv("QDRANT_URL")
        self.api_key = os.getenv("QDRANT_API_KEY")

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        return headers

    async def qdrant_upsert_points(self, collection_name: str, points: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Upsert points into a Qdrant collection."""
        if not self.url:
            return {"success": False, "error": "Qdrant URL not configured"}
            
        try:
            url = f"{self.url.rstrip('/')}/collections/{collection_name}/points"
            async with httpx.AsyncClient() as client:
                res = await client.put(
                    url,
                    headers=self._get_headers(),
                    json={"points": points},
                    timeout=30.0
                )
                res.raise_for_status()
                return {"success": True, "upserted": len(points)}
        except Exception as e:
            logger.error(f"Error upserting to Qdrant: {e}")
            return {"success": False, "error": str(e)}

    async def qdrant_search(self, collection_name: str, query_vector: List[float], filter_conditions: Dict[str, Any] = None, limit: int = 5) -> Dict[str, Any]:
        """Search points using vector similarity, with optional payload filters."""
        if not self.url:
             return {"success": False, "error": "Qdrant URL not configured"}
             
        try:
            url = f"{self.url.rstrip('/')}/collections/{collection_name}/points/search"
            payload = {
                "vector": query_vector,
                "limit": limit,
                "with_payload": True
            }
            if filter_conditions:
                 payload["filter"] = filter_conditions
                 
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    url,
                    headers=self._get_headers(),
                    json=payload,
                    timeout=15.0
                )
                res.raise_for_status()
                data = res.json()
                return {"success": True, "result": data.get("result", [])}
        except Exception as e:
            logger.error(f"Error querying Qdrant: {e}")
            return {"success": False, "error": str(e)}

    async def qdrant_delete_collection(self, collection_name: str) -> Dict[str, Any]:
        """Delete an entire collection."""
        if not self.url:
             return {"success": False, "error": "Qdrant URL not configured"}
             
        try:
            url = f"{self.url.rstrip('/')}/collections/{collection_name}"
            async with httpx.AsyncClient() as client:
                res = await client.delete(url, headers=self._get_headers(), timeout=15.0)
                res.raise_for_status()
                return {"success": True, "status": "deleted", "collection": collection_name}
        except Exception as e:
             logger.error(f"Error deleting Qdrant collection: {e}")
             return {"success": False, "error": str(e)}

