"""
Tool API Generator — Converts DynamicToolRegistry tool definitions into a typed Python API.

This is the core of Code Mode: instead of presenting 200+ tools as individual function-calling
schemas (consuming massive tokens), we generate a compact Python API that the LLM writes code
against. The API is injected into the sandbox context.

Inspired by:
- Cloudflare Code Mode: https://blog.cloudflare.com/code-mode/
- FastMCP Code Mode: https://gofastmcp.com/servers/transforms/code-mode
- Anthropic Programmatic Tool Calling
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# JSON Schema type → Python type hint mapping
SCHEMA_TYPE_MAP = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}

# Tools that should NOT be exposed in the Code Mode API
# (they are meta-tools or handled separately)
EXCLUDED_TOOLS = {
    "execute_python_code",       # Would cause recursion
    "search_tools",              # Meta-tool for discovery
    "get_tool_schema",           # Meta-tool for discovery
    "list_tool_categories",      # Meta-tool for discovery
}

# Platform prefix → display name mapping
PLATFORM_DISPLAY_NAMES = {
    "slack": "Slack",
    "hubspot": "HubSpot",
    "gmail": "Gmail",
    "calendar": "Calendar",
    "drive": "Google Drive",
    "sheets": "Google Sheets",
    "docs": "Google Docs",
    "analytics": "Google Analytics",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "teams": "Microsoft Teams",
    "salesforce": "Salesforce",
    "zoho": "Zoho",
    "asana": "Asana",
    "jira": "Jira",
    "trello": "Trello",
    "clickup": "ClickUp",
    "notion": "Notion",
    "todoist": "Todoist",
    "stripe": "Stripe",
    "mpesa": "M-Pesa",
    "paystack": "Paystack",
    "quickbooks": "QuickBooks",
    "xero": "Xero",
    "maps": "Google Maps",
    "web": "Web Tools",
    "content": "Content Creation",
    "file": "File Management",
    "inbox": "Unified Inbox",
    "tasks": "Unified Tasks",
    "knowledge": "Knowledge Base",
    "workflow": "Workflows",
    "order": "Orders",
    "product": "Products",
    "daraja": "Daraja (Safaricom)",
    "tiktok": "TikTok",
    "powerbi": "Power BI",
    "zoom": "Zoom",
    "microsoft": "Microsoft",
    "airtable": "Airtable",
}


class ToolAPIGenerator:
    """
    Generates a typed Python API from the DynamicToolRegistry tool definitions.
    
    The generated API is a string of Python class definitions that get injected
    into the Code Mode sandbox. Each platform's tools become methods on a class.
    
    Example output:
    ```python
    class slack:
        '''Slack integration tools'''
        async def send_message(channel: str, text: str) -> dict:
            '''Send a message to a Slack channel'''
            return await _call("slack_send_message", {"channel": channel, "text": text})
    ```
    """
    
    def generate_api(self, tools: List[Dict[str, Any]], compact: bool = True) -> str:
        """
        Generate the complete Python API string from a list of tool definitions.
        
        Args:
            tools: List of tool definitions from DynamicToolRegistry
            compact: If True, generate minimal docstrings for token efficiency
            
        Returns:
            Python source code string defining the typed API classes
        """
        # Filter out excluded tools
        tools = [t for t in tools if t.get("name") not in EXCLUDED_TOOLS]
        
        # Group tools by platform prefix
        grouped = self._group_tools_by_platform(tools)
        
        # Generate API classes
        lines = [
            '"""Available tool API — write Python code using these classes."""',
            "",
        ]
        
        for platform, platform_tools in sorted(grouped.items()):
            class_code = self._generate_platform_class(platform, platform_tools, compact)
            lines.append(class_code)
            lines.append("")
        
        api_code = "\n".join(lines)
        
        # Log token estimate
        token_estimate = len(api_code.split()) * 1.3  # rough estimate
        logger.info(
            f"Generated Code Mode API: {len(grouped)} platforms, "
            f"{len(tools)} tools, ~{int(token_estimate)} tokens"
        )
        
        return api_code
    
    def generate_api_reference(self, tools: List[Dict[str, Any]]) -> str:
        """
        Generate a compact API reference (no code, just descriptions).
        Used for the system prompt to give the LLM an overview.
        
        Returns a markdown-style reference ~500 tokens for 100+ tools.
        """
        tools = [t for t in tools if t.get("name") not in EXCLUDED_TOOLS]
        grouped = self._group_tools_by_platform(tools)
        
        lines = ["# Available Tools (use via Code Mode)"]
        for platform, platform_tools in sorted(grouped.items()):
            display_name = PLATFORM_DISPLAY_NAMES.get(platform, platform.title())
            tool_names = [self._get_method_name(t, platform) for t in platform_tools]
            lines.append(f"- **{display_name}**: {', '.join(tool_names)}")
        
        return "\n".join(lines)
    
    def _group_tools_by_platform(self, tools: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group tools by their platform prefix."""
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        
        for tool in tools:
            name = tool.get("name", "")
            platform = self._extract_platform(name)
            if platform not in grouped:
                grouped[platform] = []
            grouped[platform].append(tool)
        
        return grouped
    
    def _extract_platform(self, tool_name: str) -> str:
        """Extract the platform prefix from a tool name."""
        # Handle dot notation (e.g., "maps.geocode" → "maps")
        if "." in tool_name:
            return tool_name.split(".")[0]
        
        # Handle underscore notation (e.g., "slack_send_message" → "slack")
        parts = tool_name.split("_")
        if len(parts) >= 2:
            # Check if first part is a known platform
            if parts[0] in PLATFORM_DISPLAY_NAMES:
                return parts[0]
            # Check first two parts (e.g., "web_search" → "web")
            if parts[0] in PLATFORM_DISPLAY_NAMES:
                return parts[0]
        
        return "tools"  # fallback for ungrouped tools
    
    def _get_method_name(self, tool: Dict[str, Any], platform: str) -> str:
        """
        Convert a tool name into a Python method name.
        e.g., "slack_send_message" → "send_message"
              "maps.geocode" → "geocode"
        """
        name = tool.get("name", "")
        
        # Remove platform prefix
        if "." in name:
            method = name.split(".", 1)[1]
        elif name.startswith(f"{platform}_"):
            method = name[len(platform) + 1:]
        else:
            method = name
        
        # Sanitize for Python
        method = re.sub(r'[^a-zA-Z0-9_]', '_', method)
        if method[0].isdigit():
            method = f"_{method}"
        
        return method
    
    def _generate_platform_class(
        self, platform: str, tools: List[Dict[str, Any]], compact: bool
    ) -> str:
        """Generate a Python class for a platform's tools."""
        display_name = PLATFORM_DISPLAY_NAMES.get(platform, platform.title())
        class_name = re.sub(r'[^a-zA-Z0-9]', '_', platform)
        
        lines = [f"class {class_name}:"]
        if not compact:
            lines.append(f'    """{display_name} integration tools."""')
        
        for tool in tools:
            method_code = self._generate_method(tool, platform, compact)
            lines.append(method_code)
        
        return "\n".join(lines)
    
    def _generate_method(
        self, tool: Dict[str, Any], platform: str, compact: bool
    ) -> str:
        """Generate a Python async method for a single tool."""
        name = tool.get("name", "")
        description = tool.get("description", "")
        schema = tool.get("inputSchema", {})
        method_name = self._get_method_name(tool, platform)
        
        # Build parameter list
        params, param_dict_entries = self._build_params(schema)
        
        # Build method signature
        param_str = ", ".join(params) if params else ""
        sig = f"    async def {method_name}({param_str}) -> dict:"
        
        # Build docstring (compact = one line)
        if compact:
            doc = f'        """{description[:80]}"""' if description else ""
        else:
            doc = f'        """{description}"""'
        
        # Build body — call _call() with the original tool name
        if param_dict_entries:
            dict_str = ", ".join(param_dict_entries)
            body = f'        return await _call("{name}", {{{dict_str}}})'
        else:
            body = f'        return await _call("{name}", {{}})'
        
        parts = [sig]
        if doc:
            parts.append(doc)
        parts.append(body)
        
        return "\n".join(parts)
    
    def _build_params(self, schema: Dict[str, Any]) -> Tuple[List[str], List[str]]:
        """
        Build Python function parameters and dict entries from JSON Schema.
        
        Returns:
            Tuple of (param_signatures, dict_entries)
            e.g., (["channel: str", "text: str"], ['"channel": channel', '"text": text'])
        """
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        
        params = []
        dict_entries = []
        
        # Sort: required params first, then optional
        sorted_props = sorted(
            properties.items(),
            key=lambda x: (x[0] not in required, x[0])
        )
        
        for prop_name, prop_schema in sorted_props:
            python_type = self._schema_to_type(prop_schema)
            safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', prop_name)
            
            if prop_name in required:
                params.append(f"{safe_name}: {python_type}")
            else:
                default = self._get_default(prop_schema)
                params.append(f"{safe_name}: {python_type} = {default}")
            
            dict_entries.append(f'"{prop_name}": {safe_name}')
        
        return params, dict_entries
    
    def _schema_to_type(self, schema: Dict[str, Any]) -> str:
        """Convert a JSON Schema type to a Python type hint."""
        schema_type = schema.get("type", "any")
        
        if isinstance(schema_type, list):
            # Union type
            types = [SCHEMA_TYPE_MAP.get(t, "Any") for t in schema_type if t != "null"]
            return types[0] if len(types) == 1 else f"({' | '.join(types)})"
        
        if schema_type == "array":
            items = schema.get("items", {})
            item_type = self._schema_to_type(items) if items else "Any"
            return f"list[{item_type}]"
        
        if schema_type == "object":
            return "dict"
        
        return SCHEMA_TYPE_MAP.get(schema_type, "Any")
    
    def _get_default(self, schema: Dict[str, Any]) -> str:
        """Get a Python default value for an optional parameter."""
        if "default" in schema:
            default = schema["default"]
            if isinstance(default, str):
                return f'"{default}"'
            if isinstance(default, bool):
                return str(default)
            if default is None:
                return "None"
            return str(default)
        
        return "None"


# Module-level singleton
tool_api_generator = ToolAPIGenerator()
