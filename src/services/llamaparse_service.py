"""
LlamaParse Service
Exposes PDF and complex document parsing operations.
"""
import logging
import os
import httpx
from typing import Dict, Any

logger = logging.getLogger(__name__)

class LlamaParseService:
    def __init__(self):
        self.api_key = os.getenv("LLAMAPARSE_API_KEY")
        self.base_url = "https://api.cloud.llamaindex.ai/api/parsing"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}"
        }

    async def llamaparse_parse_document(self, file_content: bytes, filename: str = "document.pdf") -> Dict[str, Any]:
        """Parses a document returning clean markdown."""
        if not self.api_key:
            return {"success": False, "error": "LlamaParse API key not configured"}
            
        try:
            files = {"file": (filename, file_content)}
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/upload",
                    headers=self._get_headers(),
                    files=files,
                    timeout=60.0
                )
                response.raise_for_status()
                data = response.json()
                job_id = data.get("id")
                return {"success": True, "job_id": job_id}
        except Exception as e:
            logger.error(f"Error starting LlamaParse job: {e}")
            return {"success": False, "error": str(e)}

    async def llamaparse_get_job_result(self, job_id: str) -> Dict[str, Any]:
        """Gets result of async parsing job."""
        if not self.api_key:
            return {"success": False, "error": "LlamaParse API key not configured"}
            
        try:
            async with httpx.AsyncClient() as client:
                status_res = await client.get(
                    f"{self.base_url}/job/{job_id}",
                    headers=self._get_headers(),
                    timeout=10.0
                )
                status_res.raise_for_status()
                status_data = status_res.json()
                
                if status_data.get("status") != "SUCCESS":
                    return {"success": True, "status": status_data.get("status")}
                    
                result_res = await client.get(
                    f"{self.base_url}/job/{job_id}/result/markdown",
                    headers=self._get_headers(),
                    timeout=30.0
                )
                result_res.raise_for_status()
                result_data = result_res.json()
                
                return {"success": True, "status": "SUCCESS", "markdown": result_data.get("markdown", "")}
        except Exception as e:
            logger.error(f"Error fetching LlamaParse result: {e}")
            return {"success": False, "error": str(e)}

    async def llamaparse_parse_from_url(self, url: str) -> Dict[str, Any]:
        """Parses from public URL by downloading temporarily to memory."""
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(url, timeout=30.0)
                res.raise_for_status()
                content = res.content
                filename = url.split("/")[-1] or "download.pdf"
                return await self.llamaparse_parse_document(content, filename)
        except Exception as e:
             logger.error(f"Error downloading file from URL: {e}")
             return {"success": False, "error": str(e)}

