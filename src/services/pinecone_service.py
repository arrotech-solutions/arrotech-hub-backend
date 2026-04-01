"""
Pinecone Vector DB Service
Uses namespaces for multi-tenancy.
"""
import logging
import os
import httpx
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class PineconeService:
    def __init__(self):
        self.api_key = os.getenv("PINECONE_API_KEY")
        # In a real scenario, this would ideally be pulled from the KB config 
        # but for REST, Pinecone requires the specific index host.
        self.host = os.getenv("PINECONE_INDEX_HOST") 

    def _get_headers(self):
        return {
            "Api-Key": self.api_key or "",
            "Content-Type": "application/json"
        }

    async def pinecone_upsert_vectors(self, index_host: str, namespace: str, vectors: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Upsert vectors into a namespace over Pinecone REST API."""
        target_host = index_host or self.host
        if not self.api_key or not target_host:
            return {"success": False, "error": "Pinecone API Key or Index Host not configured"}

        url = f"https://{target_host}/vectors/upsert"
        payload = {
            "vectors": vectors,
            "namespace": namespace
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=self._get_headers(), json=payload, timeout=30.0)
                response.raise_for_status()
                data = response.json()
                return {"success": True, "upserted_count": data.get("upsertedCount", 0)}
        except Exception as e:
            logger.error(f"Error upserting to Pinecone: {e}")
            return {"success": False, "error": str(e)}

    async def pinecone_query(self, index_host: str, namespace: str, vector: List[float], top_k: int = 5) -> Dict[str, Any]:
        """Query vectors within a specific namespace."""
        target_host = index_host or self.host
        if not self.api_key or not target_host:
             return {"success": False, "error": "Pinecone API Key or Index Host not configured"}

        url = f"https://{target_host}/query"
        payload = {
            "vector": vector,
            "topK": top_k,
            "namespace": namespace,
            "includeMetadata": True,
            "includeValues": False
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=self._get_headers(), json=payload, timeout=15.0)
                response.raise_for_status()
                data = response.json()
                return {"success": True, "matches": data.get("matches", [])}
        except Exception as e:
            logger.error(f"Error querying Pinecone: {e}")
            return {"success": False, "error": str(e)}

    async def pinecone_delete_namespace(self, index_host: str, namespace: str) -> Dict[str, Any]:
        """Deletes an entire customer's namespace data upon offboarding."""
        target_host = index_host or self.host
        if not self.api_key or not target_host:
             return {"success": False, "error": "Pinecone API Key or Index Host not configured"}

        url = f"https://{target_host}/vectors/delete"
        payload = {
            "deleteAll": True,
            "namespace": namespace
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=self._get_headers(), json=payload, timeout=30.0)
                response.raise_for_status()
                return {"success": True, "deleted": True, "namespace": namespace}
        except Exception as e:
            logger.error(f"Error deleting Pinecone namespace: {e}")
            return {"success": False, "error": str(e)}

