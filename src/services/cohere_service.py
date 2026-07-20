"""
Cohere Embeddings & Reranking Service
"""
import logging
import os
import httpx
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class CohereService:
    def __init__(self):
        self.api_key = os.getenv("COHERE_API_KEY")

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def cohere_embed(self, texts: List[str], model: str = "embed-multilingual-v3.0") -> Dict[str, Any]:
        """Generate multilingual embeddings."""
        if not self.api_key:
             return {"success": False, "error": "Cohere API key not configured"}
             
        try:
            payload = {
                "texts": texts,
                "model": model,
                "input_type": "search_document"
            }
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    "https://api.cohere.ai/v1/embed",
                    headers=self._get_headers(),
                    json=payload,
                    timeout=30.0
                )
                res.raise_for_status()
                data = res.json()
                return {"success": True, "embeddings": data.get("embeddings"), "model": model}
        except Exception as e:
            logger.error(f"Error calling Cohere embed: {e}")
            return {"success": False, "error": str(e)}

    async def cohere_rerank(self, query: str, documents: List[str], top_n: int = 3) -> Dict[str, Any]:
        """Rerank retrieved documents based on relevance to query."""
        if not self.api_key:
             return {"success": False, "error": "Cohere API key not configured"}
             
        try:
            payload = {
                "query": query,
                "documents": documents,
                "model": "rerank-multilingual-v2.0",
                "top_n": top_n
            }
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    "https://api.cohere.ai/v1/rerank",
                    headers=self._get_headers(),
                    json=payload,
                    timeout=30.0
                )
                res.raise_for_status()
                data = res.json()
                return {"success": True, "results": data.get("results", [])}
        except Exception as e:
             logger.error(f"Error calling Cohere rerank: {e}")
             return {"success": False, "error": str(e)}

