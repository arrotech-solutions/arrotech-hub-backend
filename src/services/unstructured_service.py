"""
Unstructured Service
Exposes operations for 20+ file formats partition.
"""
import logging
import os
import httpx
from typing import Dict, Any

logger = logging.getLogger(__name__)

class UnstructuredService:
    def __init__(self):
        self.api_key = os.getenv("UNSTRUCTURED_API_KEY")
        self.api_url = os.getenv("UNSTRUCTURED_API_URL", "https://api.unstructured.io/general/v0/general")

    async def unstructured_partition_document(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """Partitions multi-format document."""
        if not self.api_key:
             return {"success": False, "error": "Unstructured API key not configured"}
             
        try:
            headers = {
                "unstructured-api-key": self.api_key,
                "Accept": "application/json"
            }
            files = {"files": (filename, file_content)}
            
            async with httpx.AsyncClient() as client:
                res = await client.post(
                    self.api_url,
                    headers=headers,
                    files=files,
                    timeout=60.0
                )
                res.raise_for_status()
                elements = res.json()
                return {"success": True, "elements": elements}
        except Exception as e:
            logger.error(f"Error calling Unstructured API: {e}")
            return {"success": False, "error": str(e)}

    async def unstructured_chunk_elements(self, elements: list) -> Dict[str, Any]:
        """Chunks unstructured parsed elements locally."""
        try:
            chunks = []
            current_chunk = ""
            for el in elements:
                text = el.get("text", "")
                if len(current_chunk) + len(text) > 1000:
                    chunks.append(current_chunk)
                    current_chunk = text
                else:
                    current_chunk += " " + text
            if current_chunk:
                chunks.append(current_chunk)
            return {"success": True, "chunks": chunks}
        except Exception as e:
            return {"success": False, "error": str(e)}

