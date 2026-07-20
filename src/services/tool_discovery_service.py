"""
Tool Discovery Service — On-demand tool search and schema inspection.

Implements Cloudflare's search()/execute() pattern for progressive capability
discovery. Instead of loading ALL tool schemas into context, the LLM gets
lightweight meta-tools that let it discover what it needs.

Key insight: 200+ tools × ~200 tokens each = 40,000+ tokens upfront.
With discovery: 3 meta-tools × ~100 tokens each = 300 tokens base cost.
The LLM searches for what it needs, inspects schemas, then writes code.
"""

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ToolDiscoveryService:
    """
    Provides on-demand tool discovery for Code Mode.
    
    Instead of presenting all tools upfront (token-expensive), the LLM uses
    these meta-tools to progressively discover capabilities:
    
    1. search_tools(query) → Find tools matching a query
    2. get_tool_schema(tool_name) → Get full parameter schema for a tool
    3. list_categories() → List available tool categories
    """
    
    def __init__(self):
        self._tool_cache: Dict[str, Dict[str, Any]] = {}
        self._category_cache: Dict[str, List[str]] = {}
    
    def update_cache(self, tools: List[Dict[str, Any]]):
        """Update the internal tool cache from registry tools."""
        self._tool_cache = {t["name"]: t for t in tools if "name" in t}
        
        # Build category index
        self._category_cache = {}
        for tool in tools:
            category = tool.get("category", "general")
            if category not in self._category_cache:
                self._category_cache[category] = []
            self._category_cache[category].append(tool["name"])
    
    def search_tools(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, str]]:
        """
        Search for tools matching a query string.
        
        Uses BM25-style keyword matching across tool names and descriptions.
        Returns compact results (name + description only, no full schemas).
        
        Args:
            query: Search query (e.g., "send email", "create contact", "payment")
            category: Optional category filter (e.g., "messaging", "crm")
            limit: Maximum number of results
            
        Returns:
            List of {name, description, category} dicts
        """
        query_lower = query.lower()
        query_tokens = set(re.split(r'\W+', query_lower))
        query_tokens.discard("")
        
        results: List[Dict[str, Any]] = []
        
        for name, tool in self._tool_cache.items():
            # Category filter
            tool_category = tool.get("category", "general")
            if category and tool_category != category:
                continue
            
            # Score the tool
            score = self._score_tool(tool, query_lower, query_tokens)
            
            if score > 0:
                results.append({
                    "name": name,
                    "description": tool.get("description", "")[:120],
                    "category": tool_category,
                    "_score": score
                })
        
        # Sort by score descending
        results.sort(key=lambda x: x["_score"], reverse=True)
        
        # Remove internal score and limit
        for r in results:
            del r["_score"]
        
        return results[:limit]
    
    def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Get the full schema for a specific tool.
        
        Returns the complete inputSchema so the LLM can inspect parameters,
        types, required fields, and descriptions before writing code.
        
        Args:
            tool_name: Exact tool name (e.g., "slack_send_message")
            
        Returns:
            Tool definition dict with full schema, or None if not found
        """
        tool = self._tool_cache.get(tool_name)
        if not tool:
            # Try fuzzy match
            for name, t in self._tool_cache.items():
                if tool_name in name or name in tool_name:
                    tool = t
                    break
        
        if not tool:
            return None
        
        return {
            "name": tool.get("name"),
            "description": tool.get("description", ""),
            "category": tool.get("category", "general"),
            "inputSchema": tool.get("inputSchema", {}),
            "always_available": tool.get("always_available", False),
        }
    
    def list_categories(self) -> List[Dict[str, Any]]:
        """
        List all available tool categories with tool counts.
        
        Returns:
            List of {category, tool_count, example_tools} dicts
        """
        results = []
        for category, tool_names in sorted(self._category_cache.items()):
            results.append({
                "category": category,
                "tool_count": len(tool_names),
                "example_tools": tool_names[:5],  # First 5 as examples
            })
        return results
    
    def _score_tool(
        self,
        tool: Dict[str, Any],
        query_lower: str,
        query_tokens: set
    ) -> float:
        """
        Score a tool's relevance to a search query using BM25-inspired matching.
        
        Scoring factors:
        - Exact substring match in name (highest weight)
        - Exact substring match in description
        - Token overlap with name
        - Token overlap with description
        """
        name = tool.get("name", "").lower()
        description = tool.get("description", "").lower()
        category = tool.get("category", "").lower()
        
        score = 0.0
        
        # Exact substring match in name (highest signal)
        if query_lower in name:
            score += 10.0
        
        # Exact substring match in description
        if query_lower in description:
            score += 5.0
        
        # Token overlap with name
        name_tokens = set(re.split(r'[_.\W]+', name))
        name_overlap = len(query_tokens & name_tokens)
        score += name_overlap * 3.0
        
        # Token overlap with description
        desc_tokens = set(re.split(r'\W+', description))
        desc_overlap = len(query_tokens & desc_tokens)
        score += desc_overlap * 1.0
        
        # Category match bonus
        if query_lower in category:
            score += 2.0
        
        # Boost for exact category token match
        cat_tokens = set(re.split(r'\W+', category))
        if query_tokens & cat_tokens:
            score += 1.5
        
        return score
    
    def get_discovery_tools_schema(self) -> List[Dict[str, Any]]:
        """
        Returns the OpenAI function-calling schema for the discovery meta-tools.
        These are the only tools exposed to the LLM in Code Mode.
        """
        return [
            {
                "name": "search_tools",
                "description": (
                    "Search for available tools by keyword. Returns matching tool names "
                    "and descriptions. Use this to discover what tools are available before "
                    "writing code. Example: search_tools('send email') or search_tools('payment', category='finance')"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (e.g., 'send message', 'create contact', 'payment')"
                        },
                        "category": {
                            "type": "string",
                            "description": "Optional category filter (e.g., 'messaging', 'crm', 'finance')"
                        }
                    },
                    "required": ["query"]
                },
                "category": "system",
                "always_available": True
            },
            {
                "name": "get_tool_schema",
                "description": (
                    "Get the full parameter schema for a specific tool. Use this to inspect "
                    "what parameters a tool accepts before writing code to call it."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "description": "Exact tool name (e.g., 'slack_send_message')"
                        }
                    },
                    "required": ["tool_name"]
                },
                "category": "system",
                "always_available": True
            },
            {
                "name": "list_tool_categories",
                "description": (
                    "List all available tool categories with tool counts. "
                    "Use this to understand what capabilities are available."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
                "category": "system",
                "always_available": True
            },
        ]


# Module-level singleton
tool_discovery_service = ToolDiscoveryService()
