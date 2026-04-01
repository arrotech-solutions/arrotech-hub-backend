"""
Weaviate Vector DB Service
"""
import logging
import os
import httpx
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class WeaviateService:
    def __init__(self):
        self.url = os.getenv("WEAVIATE_URL")
        self.api_key = os.getenv("WEAVIATE_API_KEY")

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def weaviate_add_objects(self, class_name: str, objects: List[Dict[str, Any]], tenant: str = None) -> Dict[str, Any]:
        """Add objects supporting Weaviate native multi-tenancy."""
        if not self.url:
             return {"success": False, "error": "Weaviate URL not configured"}
             
        try:
            formatted_objects = []
            for obj in objects:
                item = {
                    "class": class_name,
                    "properties": obj.get("properties", {}),
                    "vector": obj.get("vector", [])
                }
                if tenant:
                    item["tenant"] = tenant
                formatted_objects.append(item)
                
            async with httpx.AsyncClient() as client:
                url = f"{self.url.rstrip('/')}/v1/batch/objects"
                res = await client.post(url, headers=self._get_headers(), json={"objects": formatted_objects}, timeout=30.0)
                res.raise_for_status()
                return {"success": True, "added": len(objects)}
        except Exception as e:
             logger.error(f"Error adding to Weaviate: {e}")
             return {"success": False, "error": str(e)}

    async def weaviate_hybrid_search(self, class_name: str, query: str, vector: List[float], tenant: str = None, limit: int = 5) -> Dict[str, Any]:
        """Perform a hybrid search (semantic + keyword)."""
        if not self.url:
              return {"success": False, "error": "Weaviate URL not configured"}
              
        try:
            graphql_query = f"""
            {{
              Get {{
                {class_name}(
                  hybrid: {{query: "{query}", vector: {vector}}}
                  limit: {limit}
                  {f'tenant: "{tenant}"' if tenant else ''}
                ) {{
                  _additional {{ id distance }}
                  text
                }}
              }}
            }}
            """
            async with httpx.AsyncClient() as client:
                url = f"{self.url.rstrip('/')}/v1/graphql"
                res = await client.post(url, headers=self._get_headers(), json={"query": graphql_query}, timeout=15.0)
                res.raise_for_status()
                data = res.json()
                results = data.get("data", {}).get("Get", {}).get(class_name, [])
                return {"success": True, "results": results}
        except Exception as e:
             logger.error(f"Error searching Weaviate: {e}")
             return {"success": False, "error": str(e)}

    async def weaviate_delete_tenant(self, class_name: str, tenant: str) -> Dict[str, Any]:
        """Deletes a specific tenant inside a Weaviate class."""
        if not self.url:
             return {"success": False, "error": "Weaviate URL not configured"}
             
        try:
            url = f"{self.url.rstrip('/')}/v1/schema/{class_name}/tenants"
            async with httpx.AsyncClient() as client:
                res = await client.request("DELETE", url, headers=self._get_headers(), json=[tenant], timeout=30.0)
                res.raise_for_status()
                return {"success": True, "status": "tenant_deleted", "tenant": tenant}
        except Exception as e:
            logger.error(f"Error deleting Weaviate tenant: {e}")
            return {"success": False, "error": str(e)}

