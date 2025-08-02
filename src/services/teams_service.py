"""
Microsoft Teams service for Mini-Hub MCP Server.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
from pydantic import BaseModel

from ..config import settings

logger = logging.getLogger(__name__)


class TeamsMessage(BaseModel):
    """Microsoft Teams message model."""
    content: str
    content_type: str = "text"
    attachments: Optional[List[Dict[str, Any]]] = None


class TeamsService:
    """Microsoft Teams API service."""

    def __init__(self):
        self.webhook_url: Optional[str] = None
        self.access_token: Optional[str] = None
        self.tenant_id: Optional[str] = None
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None

    async def initialize(self):
        """Initialize Teams client."""
        if settings.TEAMS_WEBHOOK_URL:
            self.webhook_url = settings.TEAMS_WEBHOOK_URL
            logger.info("Teams webhook URL initialized")
        elif settings.TEAMS_ACCESS_TOKEN:
            self.access_token = settings.TEAMS_ACCESS_TOKEN
            self.tenant_id = settings.TEAMS_TENANT_ID
            self.client_id = settings.TEAMS_CLIENT_ID
            self.client_secret = settings.TEAMS_CLIENT_SECRET
            logger.info("Teams Graph API initialized")
        else:
            logger.warning("Teams credentials not configured")

    async def test_connection(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Test Teams connection by verifying credentials and permissions."""
        try:
            # Use config credentials if provided, otherwise use settings
            webhook_url = config.get("webhook_url") if config else settings.TEAMS_WEBHOOK_URL
            access_token = config.get("access_token") if config else settings.TEAMS_ACCESS_TOKEN
            tenant_id = config.get("tenant_id") if config else settings.TEAMS_TENANT_ID
            client_id = config.get("client_id") if config else settings.TEAMS_CLIENT_ID
            client_secret = config.get("client_secret") if config else settings.TEAMS_CLIENT_SECRET

            if not webhook_url and not access_token:
                return {
                    "success": False,
                    "error": "No Teams credentials provided. Need either webhook URL or Graph API credentials."
                }

            # Test webhook connection if webhook URL is provided
            if webhook_url:
                return await self._test_webhook_connection(webhook_url)
            
            # Test Graph API connection if access token is provided
            if access_token:
                return await self._test_graph_api_connection(access_token, tenant_id, client_id, client_secret)

            return {
                "success": False,
                "error": "Invalid Teams configuration"
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Teams connection test failed: {str(e)}"
            }

    async def _test_webhook_connection(self, webhook_url: str) -> Dict[str, Any]:
        """Test Teams webhook connection."""
        try:
            async with aiohttp.ClientSession() as session:
                test_message = {
                    "text": "🔧 Testing Microsoft Teams connection...",
                    "type": "message"
                }
                
                async with session.post(webhook_url, json=test_message) as response:
                    if response.status == 200:
                        return {
                            "success": True,
                            "message": "Teams webhook connection test successful",
                            "method": "webhook"
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"Webhook test failed with status {response.status}"
                        }
        except Exception as e:
            return {
                "success": False,
                "error": f"Webhook connection test failed: {str(e)}"
            }

    async def _test_graph_api_connection(self, access_token: str, tenant_id: str, client_id: str, client_secret: str) -> Dict[str, Any]:
        """Test Teams Graph API connection."""
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            async with aiohttp.ClientSession() as session:
                # Test by getting user profile
                user_url = "https://graph.microsoft.com/v1.0/me"
                async with session.get(user_url, headers=headers) as response:
                    if response.status == 200:
                        user_data = await response.json()
                        return {
                            "success": True,
                            "message": "Teams Graph API connection test successful",
                            "method": "graph_api",
                            "user": {
                                "id": user_data.get("id"),
                                "display_name": user_data.get("displayName"),
                                "email": user_data.get("userPrincipalName")
                            }
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"Graph API test failed with status {response.status}"
                        }
        except Exception as e:
            return {
                "success": False,
                "error": f"Graph API connection test failed: {str(e)}"
            }

    async def send_message(self, channel: str, message: str, 
                          message_type: str = "text", attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Send a message to a Teams channel."""
        try:
            if self.webhook_url:
                return await self._send_webhook_message(channel, message, message_type, attachments)
            elif self.access_token:
                return await self._send_graph_api_message(channel, message, message_type, attachments)
            else:
                return {
                    "success": False,
                    "error": "Teams service not properly initialized"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to send Teams message: {str(e)}"
            }

    async def _send_webhook_message(self, channel: str, message: str, message_type: str, attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Send message via Teams webhook."""
        try:
            teams_message = {
                "text": message,
                "type": "message"
            }

            # Add attachments if provided
            if attachments:
                teams_message["attachments"] = attachments

            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=teams_message) as response:
                    if response.status == 200:
                        return {
                            "success": True,
                            "message": "Message sent successfully via webhook",
                            "channel": channel,
                            "message_id": f"webhook_{datetime.now().isoformat()}"
                        }
                    else:
                        response_text = await response.text()
                        return {
                            "success": False,
                            "error": f"Webhook request failed with status {response.status}: {response_text}"
                        }
        except Exception as e:
            return {
                "success": False,
                "error": f"Webhook message sending failed: {str(e)}"
            }

    async def _send_graph_api_message(self, channel: str, message: str, message_type: str, attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Send message via Teams Graph API."""
        try:
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            # Create message payload
            message_payload = {
                "body": {
                    "content": message,
                    "contentType": message_type
                }
            }

            # Add attachments if provided
            if attachments:
                message_payload["attachments"] = attachments

            # Send to channel
            channel_url = f"https://graph.microsoft.com/v1.0/teams/{channel}/channels/{channel}/messages"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(channel_url, json=message_payload, headers=headers) as response:
                    if response.status == 201:
                        response_data = await response.json()
                        return {
                            "success": True,
                            "message": "Message sent successfully via Graph API",
                            "channel": channel,
                            "message_id": response_data.get("id")
                        }
                    else:
                        response_text = await response.text()
                        return {
                            "success": False,
                            "error": f"Graph API request failed with status {response.status}: {response_text}"
                        }
        except Exception as e:
            return {
                "success": False,
                "error": f"Graph API message sending failed: {str(e)}"
            }

    async def send_adaptive_card(self, channel: str, card_content: Dict[str, Any]) -> Dict[str, Any]:
        """Send an adaptive card to a Teams channel."""
        try:
            if self.webhook_url:
                return await self._send_webhook_adaptive_card(channel, card_content)
            elif self.access_token:
                return await self._send_graph_api_adaptive_card(channel, card_content)
            else:
                return {
                    "success": False,
                    "error": "Teams service not properly initialized"
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to send adaptive card: {str(e)}"
            }

    async def _send_webhook_adaptive_card(self, channel: str, card_content: Dict[str, Any]) -> Dict[str, Any]:
        """Send adaptive card via webhook."""
        try:
            teams_message = {
                "type": "message",
                "attachments": [
                    {
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": card_content
                    }
                ]
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=teams_message) as response:
                    if response.status == 200:
                        return {
                            "success": True,
                            "message": "Adaptive card sent successfully via webhook",
                            "channel": channel
                        }
                    else:
                        response_text = await response.text()
                        return {
                            "success": False,
                            "error": f"Webhook adaptive card failed with status {response.status}: {response_text}"
                        }
        except Exception as e:
            return {
                "success": False,
                "error": f"Webhook adaptive card sending failed: {str(e)}"
            }

    async def _send_graph_api_adaptive_card(self, channel: str, card_content: Dict[str, Any]) -> Dict[str, Any]:
        """Send adaptive card via Graph API."""
        try:
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            message_payload = {
                "body": {
                    "content": "",
                    "contentType": "html"
                },
                "attachments": [
                    {
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": card_content
                    }
                ]
            }

            channel_url = f"https://graph.microsoft.com/v1.0/teams/{channel}/channels/{channel}/messages"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(channel_url, json=message_payload, headers=headers) as response:
                    if response.status == 201:
                        response_data = await response.json()
                        return {
                            "success": True,
                            "message": "Adaptive card sent successfully via Graph API",
                            "channel": channel,
                            "message_id": response_data.get("id")
                        }
                    else:
                        response_text = await response.text()
                        return {
                            "success": False,
                            "error": f"Graph API adaptive card failed with status {response.status}: {response_text}"
                        }
        except Exception as e:
            return {
                "success": False,
                "error": f"Graph API adaptive card sending failed: {str(e)}"
            }

    async def list_channels(self) -> Dict[str, Any]:
        """List available Teams channels."""
        try:
            if not self.access_token:
                return {
                    "success": False,
                    "error": "Graph API access token required for listing channels"
                }

            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            async with aiohttp.ClientSession() as session:
                # Get teams first
                teams_url = "https://graph.microsoft.com/v1.0/me/joinedTeams"
                async with session.get(teams_url, headers=headers) as response:
                    if response.status == 200:
                        teams_data = await response.json()
                        channels = []
                        
                        for team in teams_data.get("value", []):
                            team_id = team.get("id")
                            team_name = team.get("displayName")
                            
                            # Get channels for each team
                            channels_url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels"
                            async with session.get(channels_url, headers=headers) as channels_response:
                                if channels_response.status == 200:
                                    team_channels = await channels_response.json()
                                    for channel in team_channels.get("value", []):
                                        channels.append({
                                            "id": channel.get("id"),
                                            "name": channel.get("displayName"),
                                            "team_id": team_id,
                                            "team_name": team_name,
                                            "description": channel.get("description")
                                        })

                        return {
                            "success": True,
                            "channels": channels,
                            "count": len(channels)
                        }
                    else:
                        response_text = await response.text()
                        return {
                            "success": False,
                            "error": f"Failed to get teams: {response_text}"
                        }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to list channels: {str(e)}"
            }

    async def get_channel_members(self, channel_id: str) -> Dict[str, Any]:
        """Get members of a specific channel."""
        try:
            if not self.access_token:
                return {
                    "success": False,
                    "error": "Graph API access token required for getting channel members"
                }

            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            async with aiohttp.ClientSession() as session:
                members_url = f"https://graph.microsoft.com/v1.0/teams/{channel_id}/members"
                async with session.get(members_url, headers=headers) as response:
                    if response.status == 200:
                        members_data = await response.json()
                        members = []
                        
                        for member in members_data.get("value", []):
                            members.append({
                                "id": member.get("id"),
                                "display_name": member.get("displayName"),
                                "email": member.get("userPrincipalName"),
                                "role": member.get("roles", [])
                            })

                        return {
                            "success": True,
                            "members": members,
                            "count": len(members)
                        }
                    else:
                        response_text = await response.text()
                        return {
                            "success": False,
                            "error": f"Failed to get channel members: {response_text}"
                        }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get channel members: {str(e)}"
            }

    async def create_channel(self, team_id: str, channel_name: str, description: str = None) -> Dict[str, Any]:
        """Create a new channel in a team."""
        try:
            if not self.access_token:
                return {
                    "success": False,
                    "error": "Graph API access token required for creating channels"
                }

            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            channel_data = {
                "displayName": channel_name,
                "description": description or "",
                "membershipType": "standard"
            }

            async with aiohttp.ClientSession() as session:
                channels_url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels"
                async with session.post(channels_url, json=channel_data, headers=headers) as response:
                    if response.status == 201:
                        channel_info = await response.json()
                        return {
                            "success": True,
                            "message": "Channel created successfully",
                            "channel": {
                                "id": channel_info.get("id"),
                                "name": channel_info.get("displayName"),
                                "description": channel_info.get("description")
                            }
                        }
                    else:
                        response_text = await response.text()
                        return {
                            "success": False,
                            "error": f"Failed to create channel: {response_text}"
                        }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to create channel: {str(e)}"
            }

    async def send_meeting_notification(self, channel: str, meeting_title: str, meeting_time: str, 
                                       meeting_link: str = None, attendees: List[str] = None) -> Dict[str, Any]:
        """Send a meeting notification to a Teams channel."""
        try:
            # Create adaptive card for meeting notification
            card_content = {
                "type": "AdaptiveCard",
                "version": "1.0",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": f"📅 **{meeting_title}**",
                        "weight": "Bolder",
                        "size": "Large"
                    },
                    {
                        "type": "TextBlock",
                        "text": f"**Time:** {meeting_time}",
                        "spacing": "Medium"
                    }
                ],
                "actions": []
            }

            if meeting_link:
                card_content["actions"].append({
                    "type": "Action.OpenUrl",
                    "title": "Join Meeting",
                    "url": meeting_link
                })

            if attendees:
                attendee_text = ", ".join(attendees)
                card_content["body"].append({
                    "type": "TextBlock",
                    "text": f"**Attendees:** {attendee_text}",
                    "spacing": "Medium"
                })

            return await self.send_adaptive_card(channel, card_content)

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to send meeting notification: {str(e)}"
            }

    async def send_alert(self, channel: str, alert_type: str, message: str, severity: str = "info") -> Dict[str, Any]:
        """Send an alert message to a Teams channel."""
        try:
            # Create adaptive card for alert
            severity_colors = {
                "info": "blue",
                "warning": "yellow", 
                "error": "red",
                "success": "green"
            }
            
            severity_icons = {
                "info": "ℹ️",
                "warning": "⚠️",
                "error": "🚨",
                "success": "✅"
            }

            color = severity_colors.get(severity, "blue")
            icon = severity_icons.get(severity, "ℹ️")

            card_content = {
                "type": "AdaptiveCard",
                "version": "1.0",
                "body": [
                    {
                        "type": "TextBlock",
                        "text": f"{icon} **{alert_type.upper()}**",
                        "weight": "Bolder",
                        "size": "Large",
                        "color": color
                    },
                    {
                        "type": "TextBlock",
                        "text": message,
                        "spacing": "Medium",
                        "wrap": True
                    }
                ]
            }

            return await self.send_adaptive_card(channel, card_content)

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to send alert: {str(e)}"
            }

    async def get_team_info(self, team_id: str) -> Dict[str, Any]:
        """Get information about a specific team."""
        try:
            if not self.access_token:
                return {
                    "success": False,
                    "error": "Graph API access token required for getting team info"
                }

            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            async with aiohttp.ClientSession() as session:
                team_url = f"https://graph.microsoft.com/v1.0/teams/{team_id}"
                async with session.get(team_url, headers=headers) as response:
                    if response.status == 200:
                        team_data = await response.json()
                        return {
                            "success": True,
                            "team": {
                                "id": team_data.get("id"),
                                "display_name": team_data.get("displayName"),
                                "description": team_data.get("description"),
                                "visibility": team_data.get("visibility"),
                                "created_date": team_data.get("createdDateTime")
                            }
                        }
                    else:
                        response_text = await response.text()
                        return {
                            "success": False,
                            "error": f"Failed to get team info: {response_text}"
                        }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get team info: {str(e)}"
            }

    async def search_messages(self, query: str, channel_id: str = None, limit: int = 20) -> Dict[str, Any]:
        """Search for messages in Teams."""
        try:
            if not self.access_token:
                return {
                    "success": False,
                    "error": "Graph API access token required for searching messages"
                }

            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }

            # Build search query
            search_url = f"https://graph.microsoft.com/v1.0/search/query"
            search_body = {
                "requests": [
                    {
                        "entityTypes": ["message"],
                        "query": {
                            "queryString": query
                        },
                        "from": 0,
                        "size": limit
                    }
                ]
            }

            if channel_id:
                search_body["requests"][0]["query"]["queryString"] += f" channel:{channel_id}"

            async with aiohttp.ClientSession() as session:
                async with session.post(search_url, json=search_body, headers=headers) as response:
                    if response.status == 200:
                        search_data = await response.json()
                        messages = []
                        
                        for result in search_data.get("value", []):
                            for hit in result.get("hitsContainers", []):
                                for hit_item in hit.get("hits", []):
                                    resource = hit_item.get("resource", {})
                                    messages.append({
                                        "id": resource.get("id"),
                                        "subject": resource.get("subject"),
                                        "body": resource.get("body", {}).get("content"),
                                        "from": resource.get("from", {}).get("user", {}).get("displayName"),
                                        "created_date": resource.get("createdDateTime")
                                    })

                        return {
                            "success": True,
                            "messages": messages,
                            "count": len(messages),
                            "query": query
                        }
                    else:
                        response_text = await response.text()
                        return {
                            "success": False,
                            "error": f"Failed to search messages: {response_text}"
                        }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to search messages: {str(e)}"
            } 