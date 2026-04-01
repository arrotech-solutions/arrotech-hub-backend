"""
HuggingFace Local Embeddings Service
"""
import logging
import os
import httpx
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class HuggingFaceService:
    def __init__(self):
        self.api_key = os.getenv("HUGGINGFACE_API_KEY")
        
    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def huggingface_batch_embed(self, texts: List[str], model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> Dict[str, Any]:
        """Creates embeddings for a batch of text via Inference API."""
        try:
            url = f"https://api-inference.huggingface.co/pipeline/feature-extraction/{model_name}"
            
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    url,
                    headers=self._get_headers(),
                    json={"inputs": texts},
                    timeout=30.0
                )
                res.raise_for_status()
                embeddings = res.json()
                
                if isinstance(embeddings, dict) and "error" in embeddings:
                     return {"success": False, "error": embeddings["error"]}
                     
                return {"success": True, "embeddings": embeddings, "model": model_name}
        except Exception as e:
            logger.error(f"Error calling HuggingFace inference: {e}")
            return {"success": False, "error": str(e)}

    async def huggingface_embed_text(self, text: str, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> Dict[str, Any]:
        """Creates an embedding vector locally."""
        res = await self.huggingface_batch_embed([text], model_name)
        if res.get("success"):
            return {"success": True, "embedding": res["embeddings"][0], "model": model_name}
        return res

