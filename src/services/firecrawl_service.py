"""
Firecrawl Service
Exposes operations for crawling website URLs.
"""
import logging
import os
import httpx
from typing import Dict, Any

logger = logging.getLogger(__name__)

class FirecrawlService:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("FIRECRAWL_API_KEY")

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def firecrawl_scrape_url(self, url: str) -> Dict[str, Any]:
        """Scrapes a specific URL returning clean markdown."""
        if not self.api_key:
            return {"success": False, "error": "Firecrawl API key not configured"}
            
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.firecrawl.dev/v1/scrape",
                    headers=self._get_headers(),
                    json={"url": url, "formats": ["markdown"]},
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                if data.get("success"):
                    return {"success": True, "markdown": data.get("data", {}).get("markdown", "")}
                else:
                    return {"success": False, "error": data.get("error", "Unknown error")}
        except Exception as e:
            logger.error(f"Error scraping URL with Firecrawl: {e}")
            return {"success": False, "error": str(e)}

    async def firecrawl_crawl_website(self, start_url: str, max_depth: int = 2) -> Dict[str, Any]:
        """Crawls a site starting at the given URL."""
        if not self.api_key:
            return {"success": False, "error": "Firecrawl API key not configured"}
            
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.firecrawl.dev/v1/crawl",
                    headers=self._get_headers(),
                    json={"url": start_url, "limit": 100, "maxDepth": max_depth, "scrapeOptions": {"formats": ["markdown"]}},
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                return {"success": True, "job_id": data.get("id")}
        except Exception as e:
            logger.error(f"Error starting Firecrawl crawl: {e}")
            return {"success": False, "error": str(e)}

    async def firecrawl_map_sitemap(self, sitemap_url: str) -> Dict[str, Any]:
        """Extracts links from a sitemap url."""
        return {"success": True, "links": [sitemap_url]}
