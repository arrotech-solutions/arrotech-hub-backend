"""
Tool Context Engine - Builds rich tool awareness context for the AI assistant.

This service creates a comprehensive, connection-aware tool catalog that enables
the AI to understand what tools are available, which connections are active,
and what capabilities the user can leverage.
"""

import logging
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Connection, ConnectionStatus, User

logger = logging.getLogger(__name__)


# Platform metadata for enriched tool context
PLATFORM_METADATA = {
    "slack": {
        "display_name": "Slack",
        "icon": "💬",
        "color": "purple",
        "category": "communication",
        "description": "Team messaging and collaboration",
        "capabilities_when_connected": [
            "Send and receive messages in channels",
            "Create and manage channels",
            "Get team member info",
            "Post notifications and alerts"
        ]
    },
    "hubspot": {
        "display_name": "HubSpot",
        "icon": "🧡",
        "color": "orange",
        "category": "crm",
        "description": "CRM, contacts, deals, and sales pipeline",
        "capabilities_when_connected": [
            "Manage contacts and companies",
            "Track and update deals",
            "View sales pipeline analytics",
            "Create and manage tasks"
        ]
    },
    "google_workspace": {
        "display_name": "Google Workspace",
        "icon": "📧",
        "color": "blue",
        "category": "productivity",
        "description": "Gmail, Calendar, Drive, and Sheets",
        "capabilities_when_connected": [
            "Send and read emails via Gmail",
            "Manage calendar events",
            "Access Google Drive files",
            "Read and write Google Sheets"
        ]
    },
    "ga4": {
        "display_name": "Google Analytics 4",
        "icon": "📊",
        "color": "yellow",
        "category": "analytics",
        "description": "Website and app analytics",
        "capabilities_when_connected": [
            "View real-time website traffic",
            "Analyze user behavior and conversions",
            "Track campaign performance",
            "Generate analytics reports"
        ]
    },
    "whatsapp": {
        "display_name": "WhatsApp Business",
        "icon": "📱",
        "color": "green",
        "category": "communication",
        "description": "Business messaging via WhatsApp",
        "capabilities_when_connected": [
            "Send and receive WhatsApp messages",
            "Manage contact lists",
            "Set up auto-replies",
            "Track message delivery"
        ]
    },
    "powerbi": {
        "display_name": "Power BI",
        "icon": "📈",
        "color": "yellow",
        "category": "analytics",
        "description": "Business intelligence and data visualization",
        "capabilities_when_connected": [
            "View and embed dashboards",
            "Refresh datasets",
            "Access report data",
            "Manage workspaces"
        ]
    },
    "salesforce": {
        "display_name": "Salesforce",
        "icon": "☁️",
        "color": "blue",
        "category": "crm",
        "description": "Enterprise CRM and sales management",
        "capabilities_when_connected": [
            "Manage leads and opportunities",
            "Track sales activities",
            "View reports and dashboards",
            "Automate sales workflows"
        ]
    },
    "asana": {
        "display_name": "Asana",
        "icon": "✅",
        "color": "coral",
        "category": "project_management",
        "description": "Project and task management",
        "capabilities_when_connected": [
            "Create and manage tasks",
            "Track project progress",
            "Assign work to team members",
            "Set deadlines and milestones"
        ]
    },
    "zoom": {
        "display_name": "Zoom",
        "icon": "🎥",
        "color": "blue",
        "category": "communication",
        "description": "Video conferencing and meetings",
        "capabilities_when_connected": [
            "Schedule and create meetings",
            "Get meeting recordings",
            "Manage meeting participants",
            "View meeting analytics"
        ]
    },
    "teams": {
        "display_name": "Microsoft Teams",
        "icon": "👥",
        "color": "purple",
        "category": "communication",
        "description": "Team collaboration and meetings",
        "capabilities_when_connected": [
            "Send messages in channels",
            "Schedule meetings",
            "Manage team members",
            "Share files and documents"
        ]
    },
    "facebook": {
        "display_name": "Facebook",
        "icon": "📘",
        "color": "blue",
        "category": "social_media",
        "description": "Social media management",
        "capabilities_when_connected": [
            "Post to pages and groups",
            "Manage ad campaigns",
            "View page insights",
            "Respond to comments and messages"
        ]
    },
    "twitter": {
        "display_name": "Twitter/X",
        "icon": "🐦",
        "color": "blue",
        "category": "social_media",
        "description": "Social media posting and monitoring",
        "capabilities_when_connected": [
            "Post tweets and threads",
            "Monitor mentions",
            "Analyze engagement",
            "Schedule content"
        ]
    },
    "linkedin": {
        "display_name": "LinkedIn",
        "icon": "💼",
        "color": "blue",
        "category": "social_media",
        "description": "Professional networking and content",
        "capabilities_when_connected": [
            "Post professional content",
            "Manage company page",
            "Track post performance",
            "Network outreach"
        ]
    },
    "instagram": {
        "display_name": "Instagram",
        "icon": "📸",
        "color": "pink",
        "category": "social_media",
        "description": "Visual content and social media",
        "capabilities_when_connected": [
            "Post images and stories",
            "Manage business profile",
            "View engagement analytics",
            "Reply to comments and DMs"
        ]
    },
    "mpesa": {
        "display_name": "M-Pesa",
        "icon": "💰",
        "color": "green",
        "category": "payments",
        "description": "Mobile money payments (Kenya)",
        "capabilities_when_connected": [
            "Process STK push payments",
            "Check transaction status",
            "View payment history",
            "Reconcile payments"
        ]
    },
    "xero": {
        "display_name": "Xero",
        "icon": "📒",
        "color": "blue",
        "category": "accounting",
        "description": "Cloud accounting and invoicing",
        "capabilities_when_connected": [
            "Create and send invoices",
            "Track expenses",
            "Reconcile bank transactions",
            "Generate financial reports"
        ]
    }
}

# Category labels for display
CATEGORY_LABELS = {
    "communication": "💬 Communication",
    "crm": "🧡 CRM & Sales",
    "productivity": "📧 Productivity",
    "analytics": "📊 Analytics & Reporting",
    "social_media": "📱 Social Media",
    "payments": "💰 Payments & Finance",
    "accounting": "📒 Accounting",
    "project_management": "✅ Project Management",
    "marketing": "📢 Marketing",
    "advanced": "🧠 AI & Advanced",
    "general": "⚡ General Tools",
    "automation": "🔄 Automation",
    "file_management": "📁 File Management",
    "content": "✍️ Content Creation",
    "data": "📊 Data & Insights",
}


class ToolContextEngine:
    """Builds rich, connection-aware tool context for the AI assistant."""

    async def get_user_connections(self, user_id: uuid.UUID, db: AsyncSession) -> List[Dict[str, Any]]:
        """Get all connections for a user with their statuses."""
        try:
            stmt = select(Connection).where(Connection.user_id == user_id)
            result = await db.execute(stmt)
            connections = result.scalars().all()
            
            return [
                {
                    "id": conn.id,
                    "platform": conn.platform,
                    "name": conn.name,
                    "status": conn.status,
                    "last_sync": str(conn.last_sync) if conn.last_sync else None,
                    "error_message": conn.error_message
                }
                for conn in connections
            ]
        except Exception as e:
            logger.error(f"Error fetching user connections: {e}")
            return []

    def _get_platform_meta(self, platform: str) -> Dict[str, Any]:
        """Get platform metadata with fallback for unknown platforms."""
        platform_key = platform.lower().replace(" ", "_").replace("-", "_")
        if platform_key in PLATFORM_METADATA:
            return PLATFORM_METADATA[platform_key]
        
        # Fuzzy match
        for key, meta in PLATFORM_METADATA.items():
            if key in platform_key or platform_key in key:
                return meta
        
        return {
            "display_name": platform.replace("_", " ").title(),
            "icon": "🔌",
            "color": "gray",
            "category": "general",
            "description": f"{platform.replace('_', ' ').title()} integration",
            "capabilities_when_connected": [f"Use {platform.replace('_', ' ').title()} tools"]
        }

    async def build_tool_awareness_context(
        self, 
        user_id: uuid.UUID, 
        db: AsyncSession,
        available_tools: List[Dict[str, Any]] = None
    ) -> str:
        """
        Build a comprehensive tool awareness context block for the system prompt.
        
        Returns a structured string that gives the AI full awareness of:
        - Connected apps and their capabilities
        - Tools that require connections the user doesn't have
        - Always-available tools
        - Workflow suggestions based on active connections
        """
        connections = await self.get_user_connections(user_id, db)
        
        # Classify connections by status
        active_connections = [c for c in connections if c["status"] == ConnectionStatus.ACTIVE]
        inactive_connections = [c for c in connections if c["status"] != ConnectionStatus.ACTIVE]
        
        active_platforms = {c["platform"].lower() for c in active_connections}
        
        # Build the context sections
        context_parts = []
        
        # Section 1: Connected Apps Status
        context_parts.append("## YOUR CONNECTED APPS STATUS:")
        if active_connections:
            for conn in active_connections:
                meta = self._get_platform_meta(conn["platform"])
                # Count tools for this platform from available_tools
                platform_tool_count = 0
                if available_tools:
                    for tool in available_tools:
                        t = tool.get('function', tool)
                        tool_name = t.get('name', '').lower()
                        if conn["platform"].lower() in tool_name:
                            platform_tool_count += 1
                
                tool_count_str = f" — {platform_tool_count} tools available" if platform_tool_count > 0 else ""
                context_parts.append(
                    f"✅ {meta['icon']} {meta['display_name']} (Connected){tool_count_str}"
                )
                caps = meta.get("capabilities_when_connected", [])
                if caps:
                    for cap in caps[:3]:
                        context_parts.append(f"   • {cap}")
        else:
            context_parts.append("⚠️ No apps connected yet. The user can still use built-in tools.")
        
        if inactive_connections:
            context_parts.append("")
            for conn in inactive_connections:
                meta = self._get_platform_meta(conn["platform"])
                status_icon = "⚠️" if conn["status"] == "error" else "⬡"
                context_parts.append(
                    f"{status_icon} {meta['display_name']} — Status: {conn['status']}"
                )
        
        # Section 2: Apps Not Connected (that could be)
        all_known_platforms = set(PLATFORM_METADATA.keys())
        connected_platform_keys = set()
        for c in connections:
            key = c["platform"].lower().replace(" ", "_").replace("-", "_")
            connected_platform_keys.add(key)
            for k in PLATFORM_METADATA:
                if k in key or key in k:
                    connected_platform_keys.add(k)
        
        unconnected = all_known_platforms - connected_platform_keys
        if unconnected:
            context_parts.append("")
            context_parts.append("## APPS AVAILABLE TO CONNECT:")
            for platform_key in sorted(unconnected):
                meta = PLATFORM_METADATA[platform_key]
                context_parts.append(
                    f"⬡ {meta['icon']} {meta['display_name']} — {meta['description']}"
                )
            context_parts.append(
                '\nIf the user asks about tools from unconnected platforms, guide them: '
                '"You can connect [platform] in Settings → Connections to unlock these capabilities."'
            )
        
        # Section 3: Capability Matrix (based on active connections)
        context_parts.append("")
        context_parts.append("## WHAT YOU CAN DO RIGHT NOW:")
        
        # Always-available capabilities
        context_parts.append("### Always Available (no connection required):")
        always_available = [
            "Generate files, PDFs, CSVs, and QR codes",
            "Search the web for real-time information",
            "Create content, emails, and marketing copy",
            "Analyze trends and generate forecasts",
            "Score leads and map customer journeys",
            "Run A/B tests and predictive analytics",
            "Create and manage automation workflows",
            "Translate content into multiple languages"
        ]
        for cap in always_available:
            context_parts.append(f"  • {cap}")
        
        # Connection-specific capabilities
        if active_connections:
            context_parts.append("")
            context_parts.append("### Unlocked by Your Connections:")
            for conn in active_connections:
                meta = self._get_platform_meta(conn["platform"])
                caps = meta.get("capabilities_when_connected", [])
                for cap in caps:
                    context_parts.append(f"  • {cap} (via {meta['display_name']})")
        
        # Section 4: Workflow Suggestions
        if len(active_platforms) >= 2:
            context_parts.append("")
            context_parts.append("## SUGGESTED CROSS-PLATFORM WORKFLOWS:")
            suggestions = self._generate_workflow_suggestions(active_platforms)
            for suggestion in suggestions[:5]:
                context_parts.append(f"  💡 {suggestion}")
        
        # Section 5: Behavioral Rules
        context_parts.append("")
        context_parts.append("## AI ASSISTANT BEHAVIORAL RULES:")
        context_parts.append("""When responding to users:
1. **Tool Selection Transparency**: When you call a tool, briefly explain WHY you selected it
2. **Connection Awareness**: If a user asks for something requiring an unconnected app, tell them which app to connect and where
3. **Capability Guidance**: When asked "what can you do?", reference the specific tools and connections above
4. **Workflow Suggestions**: When a task could benefit from combining multiple tools, proactively suggest it
5. **Error Context**: If a tool fails, explain what happened in simple terms and suggest alternatives
6. **Data Presentation**: Present results clearly — use tables for data, bullet points for summaries
7. **Proactive Insights**: After completing a task, suggest related actions the user might want to take""")
        
        return "\n".join(context_parts)

    def _generate_workflow_suggestions(self, active_platforms: set) -> List[str]:
        """Generate smart workflow suggestions based on connected platforms."""
        suggestions = []
        
        if "slack" in active_platforms and "hubspot" in active_platforms:
            suggestions.append(
                "Create a HubSpot deal and automatically notify your team on Slack"
            )
            suggestions.append(
                "Get daily CRM pipeline updates sent to a Slack channel"
            )
        
        if "slack" in active_platforms and "google_workspace" in active_platforms:
            suggestions.append(
                "Schedule a meeting via Google Calendar and send invites on Slack"
            )
        
        if "hubspot" in active_platforms and "google_workspace" in active_platforms:
            suggestions.append(
                "Auto-send follow-up emails via Gmail when a HubSpot deal moves stages"
            )
        
        if "mpesa" in active_platforms and "xero" in active_platforms:
            suggestions.append(
                "Automatically reconcile M-Pesa payments with Xero invoices"
            )
        
        if "mpesa" in active_platforms and "slack" in active_platforms:
            suggestions.append(
                "Get real-time M-Pesa payment notifications in Slack"
            )
        
        if "whatsapp" in active_platforms and "hubspot" in active_platforms:
            suggestions.append(
                "Auto-create HubSpot contacts from WhatsApp conversations"
            )
        
        if "ga4" in active_platforms and "slack" in active_platforms:
            suggestions.append(
                "Send daily Google Analytics traffic reports to Slack"
            )
        
        if "ga4" in active_platforms and "hubspot" in active_platforms:
            suggestions.append(
                "Correlate website traffic with CRM deal closures"
            )
        
        if "whatsapp" in active_platforms and "slack" in active_platforms:
            suggestions.append(
                "Forward important WhatsApp business messages to Slack"
            )
        
        if not suggestions:
            suggestions.append(
                "Connect more apps to unlock powerful cross-platform automations"
            )
        
        return suggestions

    def build_tool_selection_explanation(
        self,
        tool_name: str,
        user_query: str,
        connections: List[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """
        Build a human-readable explanation of why a specific tool was selected.
        Returns both a simple and detailed explanation.
        """
        # Determine the platform from the tool name
        platform = None
        for platform_key in PLATFORM_METADATA:
            if platform_key in tool_name.lower():
                platform = platform_key
                break
        
        meta = self._get_platform_meta(platform) if platform else None
        
        # Build connection status
        connection_status = "built-in"
        if connections and platform:
            for conn in connections:
                if platform in conn.get("platform", "").lower():
                    connection_status = conn.get("status", "unknown")
                    break
        
        # Build tool display name
        tool_display = tool_name.replace("_", " ").title()
        platform_display = meta["display_name"] if meta else "Built-in"
        platform_icon = meta["icon"] if meta else "⚡"
        
        return {
            "tool_name": tool_name,
            "tool_display": tool_display,
            "platform": platform_display,
            "platform_icon": platform_icon,
            "platform_color": meta["color"] if meta else "gray",
            "category": meta["category"] if meta else "general",
            "connection_status": connection_status,
            "reason": f"Selected {tool_display} via {platform_display} to handle your request",
        }

    async def get_capabilities_summary(
        self,
        user_id: uuid.UUID,
        db: AsyncSession,
        available_tools: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Get a structured summary of all capabilities, suitable for the frontend.
        Used by the /chat/tools/capabilities endpoint and dynamic welcome screen.
        """
        connections = await self.get_user_connections(user_id, db)
        active_connections = [c for c in connections if c["status"] == ConnectionStatus.ACTIVE]
        active_platforms = {c["platform"].lower() for c in active_connections}
        
        # Build connected apps list
        connected_apps = []
        for conn in active_connections:
            meta = self._get_platform_meta(conn["platform"])
            connected_apps.append({
                "platform": conn["platform"],
                "display_name": meta["display_name"],
                "icon": meta["icon"],
                "color": meta["color"],
                "category": meta["category"],
                "status": conn["status"],
                "capabilities": meta.get("capabilities_when_connected", [])
            })
        
        # Build available-to-connect list
        all_known = set(PLATFORM_METADATA.keys())
        connected_keys = set()
        for c in connections:
            key = c["platform"].lower().replace(" ", "_").replace("-", "_")
            connected_keys.add(key)
            for k in PLATFORM_METADATA:
                if k in key or key in k:
                    connected_keys.add(k)
        
        available_to_connect = []
        for key in sorted(all_known - connected_keys):
            meta = PLATFORM_METADATA[key]
            available_to_connect.append({
                "platform": key,
                "display_name": meta["display_name"],
                "icon": meta["icon"],
                "color": meta["color"],
                "category": meta["category"],
                "description": meta["description"],
                "capabilities": meta.get("capabilities_when_connected", [])
            })
        
        # Build dynamic suggestions based on connections
        suggestions = self._build_dynamic_suggestions(active_platforms, connected_apps)
        
        # Categorize tools
        tool_categories = {}
        if available_tools:
            for tool in available_tools:
                t = tool.get('function', tool)
                cat = t.get('category', 'general')
                cat_label = CATEGORY_LABELS.get(cat, f"🔧 {cat.replace('_', ' ').title()}")
                if cat_label not in tool_categories:
                    tool_categories[cat_label] = 0
                tool_categories[cat_label] += 1
        
        return {
            "connected_apps": connected_apps,
            "available_to_connect": available_to_connect,
            "suggestions": suggestions,
            "tool_categories": tool_categories,
            "total_tools": len(available_tools) if available_tools else 0,
            "total_connected": len(active_connections),
            "workflow_suggestions": self._generate_workflow_suggestions(active_platforms)
        }

    def _build_dynamic_suggestions(
        self,
        active_platforms: set,
        connected_apps: List[Dict[str, Any]]
    ) -> List[Dict[str, str]]:
        """Build dynamic chat suggestions based on user's connected apps."""
        suggestions = []
        
        # Connection-specific suggestions
        for app in connected_apps:
            platform = app["platform"].lower()
            
            if "slack" in platform:
                suggestions.append({
                    "title": "Team Update",
                    "prompt": "Send a summary of today's key activities to #team-updates on Slack",
                    "icon": "💬",
                    "platform": "slack"
                })
            
            if "hubspot" in platform:
                suggestions.append({
                    "title": "Pipeline Review",
                    "prompt": "Show me my top 5 deals by revenue this month from HubSpot",
                    "icon": "🧡",
                    "platform": "hubspot"
                })
            
            if "mpesa" in platform:
                suggestions.append({
                    "title": "Payment Summary",
                    "prompt": "Show me today's M-Pesa payment reconciliation summary",
                    "icon": "💰",
                    "platform": "mpesa"
                })
            
            if "google_workspace" in platform:
                suggestions.append({
                    "title": "Schedule Meeting",
                    "prompt": "Schedule a 30-minute team standup for tomorrow at 9 AM",
                    "icon": "📧",
                    "platform": "google_workspace"
                })
            
            if "whatsapp" in platform:
                suggestions.append({
                    "title": "Customer Outreach",
                    "prompt": "Send a WhatsApp message to my VIP customers about our new promotion",
                    "icon": "📱",
                    "platform": "whatsapp"
                })
            
            if "ga4" in platform:
                suggestions.append({
                    "title": "Traffic Report",
                    "prompt": "Generate a weekly website traffic and conversion report",
                    "icon": "📊",
                    "platform": "ga4"
                })
        
        # Always-available fallback suggestions
        if len(suggestions) < 2:
            suggestions.extend([
                {
                    "title": "Market Analysis",
                    "prompt": "Research current trends in the AI industry and summarize key opportunities",
                    "icon": "📈",
                    "platform": "built-in"
                },
                {
                    "title": "Content Creation",
                    "prompt": "Write a professional LinkedIn post about our latest product launch",
                    "icon": "✍️",
                    "platform": "built-in"
                },
                {
                    "title": "Data Export",
                    "prompt": "Create a CSV report of this quarter's key metrics",
                    "icon": "📁",
                    "platform": "built-in"
                },
                {
                    "title": "Workflow Builder",
                    "prompt": "Help me create an automation workflow for daily team standup reminders",
                    "icon": "🔄",
                    "platform": "built-in"
                }
            ])
        
        return suggestions[:6]  # Max 6 suggestions


# Global instance
tool_context_engine = ToolContextEngine()
