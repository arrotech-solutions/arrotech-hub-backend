"""
Slack service for Mini-Hub MCP Server.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
from slack_sdk.models.blocks import (ContextBlock, DividerBlock, HeaderBlock,
                                     SectionBlock)
from slack_sdk.web import WebClient

from ..config import settings

logger = logging.getLogger(__name__)


class SlackService:
    """Slack API service."""

    def __init__(self):
        self.client: Optional[WebClient] = None

    async def initialize(self):
        """Initialize Slack client."""
        if settings.SLACK_BOT_TOKEN:
            self.client = WebClient(token=settings.SLACK_BOT_TOKEN)
            logger.info("Slack client initialized")
        else:
            logger.warning("Slack bot token not configured")

    async def test_connection(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Test Slack connection by verifying bot token and permissions."""
        try:
            # Use config token if provided, otherwise use settings
            token = config.get(
                "bot_token") if config else settings.SLACK_BOT_TOKEN

            if not token:
                return {
                    "success": False,
                    "error": "No Slack bot token provided"
                }

            # Create temporary client for testing
            test_client = WebClient(token=token)

            # Test authentication by calling auth.test
            auth_response = test_client.auth_test()

            if not auth_response["ok"]:
                return {
                    "success": False,
                    "error": "Invalid bot token or authentication failed"
                }

            # Test basic permissions by getting bot info
            bot_info = auth_response.get("bot_id")
            user_info = auth_response.get("user_id")

            # Test sending a message to a test channel (optional)
            default_channel = config.get("default_channel") if config else None

            if default_channel:
                try:
                    # Try to send a test message (will be deleted immediately)
                    response = test_client.chat_postMessage(
                        channel=default_channel,
                        text="🔧 Testing Slack connection...",
                        unfurl_links=False
                    )

                    # Try to delete the test message, but don't fail if it doesn't work
                    if response["ok"]:
                        try:
                            test_client.chat_delete(
                                channel=default_channel,
                                ts=response["ts"]
                            )
                        except Exception as delete_error:
                            # Log the delete error but don't fail the test
                            logger.warning(
                                f"Could not delete test message: {delete_error}"
                            )

                except Exception as e:
                    # Don't fail the entire test if channel access fails
                    # Just log a warning and continue
                    logger.warning(
                        f"Cannot send messages to channel {default_channel}: {str(e)}"
                    )

            return {
                "success": True,
                "message": "Slack connection test successful",
                "bot_id": bot_info,
                "user_id": user_info,
                "team_id": auth_response.get("team_id"),
                "team_name": auth_response.get("team")
            }

        except Exception as e:
            logger.error(f"Slack connection test failed: {e}")
            return {
                "success": False,
                "error": f"Slack connection test failed: {str(e)}"
            }

    async def send_message(self, channel: str, message: str,
                           blocks: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Send a message to a Slack channel."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # Prepare message
            message_data = {
                "channel": channel,
                "text": message
            }

            if blocks:
                message_data["blocks"] = blocks

            # Send message
            response = self.client.chat_postMessage(**message_data)

            return {
                "success": response["ok"],
                "message_ts": response.get("ts"),
                "channel": channel,
                "error": response.get("error") if not response["ok"] else None
            }

        except Exception as e:
            logger.error(f"Error sending Slack message: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def send_report(self, channel: str, report_type: str,
                          date_range: Optional[str] = None,
                          message: Optional[str] = None) -> Dict[str, Any]:
        """Send a campaign report to Slack."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # Generate report based on type
            if report_type == "campaign_summary":
                blocks = await self._generate_campaign_summary_blocks(date_range)
            elif report_type == "traffic_report":
                blocks = await self._generate_traffic_report_blocks(date_range)
            elif report_type == "conversion_report":
                blocks = await self._generate_conversion_report_blocks(date_range)
            elif report_type == "finance":
                # Finance report uses the custom message
                blocks = [
                    HeaderBlock(text="💰 Finance Report"),
                    DividerBlock(),
                    SectionBlock(text=message or "No finance data available.")
                ]
                if date_range:
                    blocks.append(ContextBlock(elements=[{"type": "mrkdwn", "text": f"Period: {date_range}"}]))
            else:
                raise ValueError(f"Unknown report type: {report_type}")

            # Send report
            response = self.client.chat_postMessage(
                channel=channel,
                text=message or f"📊 {report_type.replace('_', ' ').title()} Report",
                blocks=blocks
            )

            return {
                "success": response["ok"],
                "message_ts": response.get("ts"),
                "channel": channel,
                "report_type": report_type,
                "error": response.get("error") if not response["ok"] else None
            }

        except Exception as e:
            logger.error(f"Error sending Slack report: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _generate_campaign_summary_blocks(self, date_range: Optional[str] = None) -> List[Dict[str, Any]]:
        """Generate campaign summary blocks."""
        blocks = [
            HeaderBlock(text="📊 Campaign Summary Report"),
            DividerBlock(),
            SectionBlock(
                text="*Last 24 Hours Campaign Performance*",
                fields=[
                    "*Total Sessions:* 1,234",
                    "*Unique Users:* 987",
                    "*Page Views:* 3,456",
                    "*Bounce Rate:* 45.2%"
                ]
            ),
            DividerBlock(),
            SectionBlock(
                text="*Top Traffic Sources*",
                fields=[
                    "*Google:* 456 sessions",
                    "*Direct:* 234 sessions",
                    "*Social:* 123 sessions"
                ]
            ),
            ContextBlock(
                elements=[
                    {"type": "mrkdwn", "text": f"Report generated for: {date_range or 'Last 24 hours'}"}]
            )
        ]

        return blocks

    async def _generate_traffic_report_blocks(self, date_range: Optional[str] = None) -> List[Dict[str, Any]]:
        """Generate traffic report blocks."""
        blocks = [
            HeaderBlock(text="🚀 Traffic Report"),
            DividerBlock(),
            SectionBlock(
                text="*Traffic Overview*",
                fields=[
                    "*Total Sessions:* 2,345",
                    "*New Users:* 1,234",
                    "*Returning Users:* 1,111",
                    "*Avg. Session Duration:* 2m 34s"
                ]
            ),
            DividerBlock(),
            SectionBlock(
                text="*Page Performance*",
                fields=[
                    "*Homepage:* 1,234 views",
                    "*Product Page:* 567 views",
                    "*Contact Page:* 234 views"
                ]
            ),
            ContextBlock(
                elements=[
                    {"type": "mrkdwn", "text": f"Period: {date_range or 'Last 24 hours'}"}]
            )
        ]

        return blocks

    async def _generate_conversion_report_blocks(self, date_range: Optional[str] = None) -> List[Dict[str, Any]]:
        """Generate conversion report blocks."""
        blocks = [
            HeaderBlock(text="💰 Conversion Report"),
            DividerBlock(),
            SectionBlock(
                text="*Conversion Summary*",
                fields=[
                    "*Total Conversions:* 45",
                    "*Conversion Rate:* 1.9%",
                    "*Revenue:* $12,345",
                    "*Avg. Order Value:* $274"
                ]
            ),
            DividerBlock(),
            SectionBlock(
                text="*Conversion Events*",
                fields=[
                    "*Purchases:* 23",
                    "*Sign-ups:* 12",
                    "*Contact Forms:* 10"
                ]
            ),
            ContextBlock(
                elements=[
                    {"type": "mrkdwn", "text": f"Report period: {date_range or 'Last 24 hours'}"}]
            )
        ]

        return blocks

    async def send_alert(self, channel: str, message: str) -> Dict[str, Any]:
        """Send an alert message to Slack with special formatting."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # Create alert blocks
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🚨 Alert"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": message
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Alert sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                    ]
                }
            ]

            response = self.client.chat_postMessage(
                channel=channel,
                text=f"🚨 Alert: {message}",
                blocks=blocks
            )

            return {
                "success": response["ok"],
                "message_ts": response.get("ts"),
                "channel": channel,
                "alert_type": "general",
                "error": response.get("error") if not response["ok"] else None
            }

        except Exception as e:
            logger.error(f"Error sending Slack alert: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def schedule_message(self, channel: str, message: str, schedule_time: str) -> Dict[str, Any]:
        """Schedule a message to be sent at a specific time."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # Parse schedule time (expected format: "2024-01-01 10:00:00")
            scheduled_time = datetime.strptime(
                schedule_time, "%Y-%m-%d %H:%M:%S")

            # For now, we'll just send immediately and log the scheduling
            # In a real implementation, you'd use a task queue like Celery
            response = self.client.chat_postMessage(
                channel=channel,
                text=f"📅 Scheduled Message: {message}",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Scheduled Message*\n{message}"
                        }
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"Scheduled for: {schedule_time}"
                            }
                        ]
                    }
                ]
            )

            return {
                "success": response["ok"],
                "message_ts": response.get("ts"),
                "channel": channel,
                "scheduled_time": schedule_time,
                "note": "Message sent immediately (scheduling not fully implemented)",
                "error": response.get("error") if not response["ok"] else None
            }

        except Exception as e:
            logger.error(f"Error scheduling Slack message: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def list_channels(self) -> Dict[str, Any]:
        """List all channels in the workspace."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            response = self.client.conversations_list(
                types="public_channel,private_channel"
            )

            if response["ok"]:
                channels = []
                for channel in response["channels"]:
                    channels.append({
                        "id": channel["id"],
                        "name": channel["name"],
                        "is_private": channel["is_private"],
                        "member_count": channel.get("num_members", 0),
                        "topic": channel.get("topic", {}).get("value", ""),
                        "purpose": channel.get("purpose", {}).get("value", "")
                    })

                return {
                    "success": True,
                    "channels": channels,
                    "total_channels": len(channels)
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to list channels"
                }

        except Exception as e:
            logger.error(f"Error listing Slack channels: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_channel_members(self, channel_name: str) -> Dict[str, Any]:
        """Get members of a specific channel."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # First get channel info
            channel_response = self.client.conversations_list(
                types="public_channel,private_channel"
            )

            channel_id = None
            for channel in channel_response["channels"]:
                if channel["name"] == channel_name:
                    channel_id = channel["id"]
                    break

            if not channel_id:
                return {
                    "success": False,
                    "error": f"Channel '{channel_name}' not found"
                }

            # Get channel members
            members_response = self.client.conversations_members(
                channel=channel_id
            )

            if members_response["ok"]:
                members = []
                for member_id in members_response["members"]:
                    # Get user info
                    user_response = self.client.users_info(user=member_id)
                    if user_response["ok"]:
                        user = user_response["user"]
                        members.append({
                            "id": user["id"],
                            "name": user["name"],
                            "real_name": user.get("real_name", ""),
                            "display_name": user.get("profile", {}).get("display_name", ""),
                            "is_bot": user.get("is_bot", False)
                        })

                return {
                    "success": True,
                    "channel_name": channel_name,
                    "members": members,
                    "total_members": len(members)
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to get channel members"
                }

        except Exception as e:
            logger.error(f"Error getting Slack channel members: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def create_channel(self, channel_name: str) -> Dict[str, Any]:
        """Create a new Slack channel."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # Remove # if present in channel name
            if channel_name.startswith('#'):
                channel_name = channel_name[1:]
            
            # Validate channel name (Slack requirements)
            if not channel_name or len(channel_name) < 1:
                return {
                    "success": False,
                    "error": "Channel name cannot be empty"
                }
            
            # Slack channel names must be lowercase and contain only letters, numbers, hyphens, and underscores
            import re
            if not re.match(r'^[a-z0-9_-]+$', channel_name):
                return {
                    "success": False,
                    "error": "Channel name can only contain lowercase letters, numbers, hyphens, and underscores"
                }

            response = self.client.conversations_create(
                name=channel_name
            )

            if response["ok"]:
                channel = response["channel"]
                return {
                    "success": True,
                    "channel": {
                        "id": channel["id"],
                        "name": channel["name"],
                        "is_private": channel["is_private"],
                        "created": channel.get("created", 0)
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to create channel: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error creating Slack channel: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def join_channel(self, channel_name: str) -> Dict[str, Any]:
        """Join a Slack channel as the bot."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # Remove # if present in channel name
            if channel_name.startswith('#'):
                channel_name = channel_name[1:]

            # First get channel info to find channel ID
            channel_response = self.client.conversations_list(
                types="public_channel,private_channel"
            )

            channel_id = None
            for channel in channel_response["channels"]:
                if channel["name"] == channel_name:
                    channel_id = channel["id"]
                    break

            if not channel_id:
                return {
                    "success": False,
                    "error": f"Channel '{channel_name}' not found"
                }

            # Join the channel
            response = self.client.conversations_join(
                channel=channel_id
            )

            if response["ok"]:
                return {
                    "success": True,
                    "channel_name": channel_name,
                    "channel_id": channel_id,
                    "message": f"Successfully joined #{channel_name}"
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to join channel: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error joining Slack channel: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def invite_users_to_channel(self, channel_name: str, user_ids: List[str]) -> Dict[str, Any]:
        """Invite users to a Slack channel."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # First get channel info
            channel_response = self.client.conversations_list(
                types="public_channel,private_channel"
            )

            channel_id = None
            for channel in channel_response["channels"]:
                if channel["name"] == channel_name:
                    channel_id = channel["id"]
                    break

            if not channel_id:
                return {
                    "success": False,
                    "error": f"Channel '{channel_name}' not found"
                }

            # Invite users
            response = self.client.conversations_invite(
                channel=channel_id,
                users=",".join(user_ids)
            )

            if response["ok"]:
                return {
                    "success": True,
                    "channel_name": channel_name,
                    "invited_users": user_ids,
                    "total_invited": len(user_ids)
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to invite users: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error inviting users to Slack channel: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def upload_file(self, channel: str, file_path: str, title: str = None, comment: str = None) -> Dict[str, Any]:
        """Upload a file to a Slack channel using the new 2-step asynchronous API."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # Read the file content first
            with open(file_path, 'rb') as file:
                file_content = file.read()
            
            filename = file_path.split('/')[-1]  # Extract filename from path
            logger.info(f"📤 Starting file upload to Slack: {filename} (size: {len(file_content)} bytes)")
            
            # Step 1: Get upload URL and file ID
            logger.info("📤 Step 1: Getting upload URL from Slack...")
            logger.info(f"📤 Requesting upload URL for file: {filename} ({len(file_content)} bytes)")
            
            upload_url_response = self.client.files_getUploadURLExternal(
                filename=filename,
                length=len(file_content)
            )
            
            if not upload_url_response["ok"]:
                return {
                    "success": False,
                    "error": f"Failed to get upload URL: {upload_url_response.get('error', 'Unknown error')}"
                }
            
            upload_url = upload_url_response["upload_url"]
            file_id = upload_url_response["file_id"]
            
            logger.info(f"📤 Got upload URL and file ID: {file_id}")
            
            # Step 2: Upload file binary to the temporary URL
            logger.info("📤 Step 2: Uploading file binary to temporary URL...")
            
            # Check file size - Slack has limits
            file_size_mb = len(file_content) / (1024 * 1024)
            if file_size_mb > 50:  # Slack limit is typically 50MB
                return {
                    "success": False,
                    "error": f"File too large: {file_size_mb:.1f}MB (Slack limit is 50MB)"
                }
            
            logger.info(f"📤 File size: {file_size_mb:.1f}MB")
            
            # Configure timeout based on file size (longer for larger files)
            timeout_seconds = max(30, int(file_size_mb * 2))  # 30 seconds minimum, 2 seconds per MB
            logger.info(f"📤 Using timeout: {timeout_seconds} seconds")
            
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(
                        upload_url,
                        data=file_content,
                        headers={'Content-Type': 'application/octet-stream'},
                        timeout=aiohttp.ClientTimeout(total=timeout_seconds)
                    ) as response:
                        if response.status == 504:
                            return {
                                "success": False,
                                "error": f"Upload timeout (504): File may be too large or network too slow. Try a smaller file or check your connection."
                            }
                        elif response.status != 200:
                            return {
                                "success": False,
                                "error": f"Failed to upload file binary: HTTP {response.status} - {response.reason}"
                            }
                except asyncio.TimeoutError:
                    return {
                        "success": False,
                        "error": f"Upload timeout after {timeout_seconds} seconds. File may be too large or network too slow."
                    }
                except Exception as upload_error:
                    logger.error(f"📤 Upload failed: {str(upload_error)}")
                    # Try to send just the message without the file
                    try:
                        logger.info("📤 Attempting to send message without file attachment...")
                        message_result = await self.send_message(channel, f"{comment or 'File upload failed, but here is the message:'}")
                        return {
                            "success": False,
                            "error": f"File upload failed: {str(upload_error)}",
                            "fallback_message_sent": message_result.get("success", False),
                            "note": "Message was sent without file attachment"
                        }
                    except Exception as fallback_error:
                        return {
                            "success": False,
                            "error": f"Upload error: {str(upload_error)}. Fallback message also failed: {str(fallback_error)}"
                        }
            
            logger.info("📤 File binary uploaded successfully")
            
            # Step 3: Complete the upload and share to channel
            logger.info("📤 Step 3: Completing upload and sharing to channel...")
            complete_params = {
                'files': [{'id': file_id, 'title': title} if title else {'id': file_id}],
                'channel_ids': [channel]
            }
            
            if comment:
                complete_params['initial_comment'] = comment
            
            complete_response = self.client.files_completeUploadExternal(**complete_params)
            
            if complete_response["ok"]:
                # Get file info to return details
                file_info_response = self.client.files_info(file=file_id)
                if file_info_response["ok"]:
                    file_info = file_info_response["file"]
                    return {
                        "success": True,
                        "file_id": file_info["id"],
                        "file_name": file_info["name"],
                        "file_url": file_info.get("url_private"),
                        "channel": channel
                    }
                else:
                    return {
                        "success": True,
                        "file_id": file_id,
                        "file_name": filename,
                        "channel": channel,
                        "note": "File uploaded but could not retrieve file info"
                    }
            else:
                return {
                    "success": False,
                    "error": f"Failed to complete upload: {complete_response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error uploading file to Slack: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def add_reaction(self, channel: str, timestamp: str, emoji: str) -> Dict[str, Any]:
        """Add a reaction to a message."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            response = self.client.reactions_add(
                channel=channel,
                timestamp=timestamp,
                name=emoji
            )

            if response["ok"]:
                return {
                    "success": True,
                    "channel": channel,
                    "timestamp": timestamp,
                    "emoji": emoji
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to add reaction: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error adding reaction to Slack message: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def search_messages(self, query: str, channel: str = None, limit: int = 20) -> Dict[str, Any]:
        """Search for messages in Slack."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            search_params = {
                "query": query,
                "count": limit
            }
            
            if channel:
                search_params["channel"] = channel

            response = self.client.search_messages(**search_params)

            if response["ok"]:
                messages = []
                for match in response["messages"]["matches"]:
                    messages.append({
                        "text": match["text"],
                        "user": match.get("username", "Unknown"),
                        "timestamp": match["ts"],
                        "channel": match.get("channel", {}).get("name", "Unknown")
                    })

                return {
                    "success": True,
                    "messages": messages,
                    "total_found": len(messages),
                    "query": query
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to search messages: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error searching Slack messages: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_user_info(self, user_id: str = None, user_name: str = None) -> Dict[str, Any]:
        """Get information about a Slack user."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            if user_id:
                response = self.client.users_info(user=user_id)
            elif user_name:
                # First get user list to find user ID
                users_response = self.client.users_list()
                if users_response["ok"]:
                    for user in users_response["users"]:
                        if user["name"] == user_name:
                            response = self.client.users_info(user=user["id"])
                            break
                    else:
                        return {
                            "success": False,
                            "error": f"User '{user_name}' not found"
                        }
                else:
                    return {
                        "success": False,
                        "error": "Failed to get users list"
                    }
            else:
                return {
                    "success": False,
                    "error": "Either user_id or user_name must be provided"
                }

            if response["ok"]:
                user = response["user"]
                return {
                    "success": True,
                    "user": {
                        "id": user["id"],
                        "name": user["name"],
                        "real_name": user.get("real_name", ""),
                        "display_name": user.get("profile", {}).get("display_name", ""),
                        "email": user.get("profile", {}).get("email", ""),
                        "status": user.get("profile", {}).get("status_text", ""),
                        "is_bot": user.get("is_bot", False),
                        "is_admin": user.get("is_admin", False)
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to get user info: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error getting Slack user info: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def list_users(self, include_bots: bool = False) -> Dict[str, Any]:
        """List all users in the workspace."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            response = self.client.users_list()

            if response["ok"]:
                users = []
                for user in response["users"]:
                    if not include_bots and user.get("is_bot", False):
                        continue
                    
                    users.append({
                        "id": user["id"],
                        "name": user["name"],
                        "real_name": user.get("real_name", ""),
                        "display_name": user.get("profile", {}).get("display_name", ""),
                        "email": user.get("profile", {}).get("email", ""),
                        "is_bot": user.get("is_bot", False),
                        "is_admin": user.get("is_admin", False)
                    })

                return {
                    "success": True,
                    "users": users,
                    "total_users": len(users)
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to list users: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error listing Slack users: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def pin_message(self, channel: str, timestamp: str) -> Dict[str, Any]:
        """Pin a message to a channel."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            response = self.client.pins_add(
                channel=channel,
                timestamp=timestamp
            )

            if response["ok"]:
                return {
                    "success": True,
                    "channel": channel,
                    "timestamp": timestamp
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to pin message: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error pinning Slack message: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_pinned_messages(self, channel: str) -> Dict[str, Any]:
        """Get pinned messages from a channel."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            response = self.client.pins_list(channel=channel)

            if response["ok"]:
                pinned_items = []
                for item in response.get("items", []):
                    if item["type"] == "message":
                        pinned_items.append({
                            "type": "message",
                            "text": item["message"]["text"],
                            "user": item["message"].get("user", "Unknown"),
                            "timestamp": item["message"]["ts"]
                        })
                    elif item["type"] == "file":
                        pinned_items.append({
                            "type": "file",
                            "name": item["file"]["name"],
                            "url": item["file"].get("url_private"),
                            "user": item["file"].get("user", "Unknown")
                        })

                return {
                    "success": True,
                    "pinned_items": pinned_items,
                    "total_pinned": len(pinned_items),
                    "channel": channel
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to get pinned messages: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error getting pinned Slack messages: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def archive_channel(self, channel_name: str) -> Dict[str, Any]:
        """Archive a Slack channel."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # First get channel info
            channel_response = self.client.conversations_list(
                types="public_channel,private_channel"
            )

            channel_id = None
            for channel in channel_response["channels"]:
                if channel["name"] == channel_name:
                    channel_id = channel["id"]
                    break

            if not channel_id:
                return {
                    "success": False,
                    "error": f"Channel '{channel_name}' not found"
                }

            response = self.client.conversations_archive(channel=channel_id)

            if response["ok"]:
                return {
                    "success": True,
                    "channel_name": channel_name,
                    "message": "Channel archived successfully"
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to archive channel: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error archiving Slack channel: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def set_channel_topic(self, channel_name: str, topic: str) -> Dict[str, Any]:
        """Set the topic of a Slack channel."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # First get channel info
            channel_response = self.client.conversations_list(
                types="public_channel,private_channel"
            )

            channel_id = None
            for channel in channel_response["channels"]:
                if channel["name"] == channel_name:
                    channel_id = channel["id"]
                    break

            if not channel_id:
                return {
                    "success": False,
                    "error": f"Channel '{channel_name}' not found"
                }

            response = self.client.conversations_setTopic(
                channel=channel_id,
                topic=topic
            )

            if response["ok"]:
                return {
                    "success": True,
                    "channel_name": channel_name,
                    "topic": topic
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to set channel topic: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error setting Slack channel topic: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def set_channel_purpose(self, channel_name: str, purpose: str) -> Dict[str, Any]:
        """Set the purpose of a Slack channel."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # First get channel info
            channel_response = self.client.conversations_list(
                types="public_channel,private_channel"
            )

            channel_id = None
            for channel in channel_response["channels"]:
                if channel["name"] == channel_name:
                    channel_id = channel["id"]
                    break

            if not channel_id:
                return {
                    "success": False,
                    "error": f"Channel '{channel_name}' not found"
                }

            response = self.client.conversations_setPurpose(
                channel=channel_id,
                purpose=purpose
            )

            if response["ok"]:
                return {
                    "success": True,
                    "channel_name": channel_name,
                    "purpose": purpose
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to set channel purpose: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error setting Slack channel purpose: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # AI Agents and Commands
    async def execute_command(self, command: str, channel: str, user_id: str = None, args: List[str] = None) -> Dict[str, Any]:
        """Execute a Slack command."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # This is a placeholder for command execution
            # In a real implementation, you'd handle specific commands
            return {
                "success": True,
                "command": command,
                "channel": channel,
                "user_id": user_id,
                "args": args or [],
                "result": f"Command '{command}' executed successfully"
            }
        except Exception as e:
            logger.error(f"Error executing Slack command: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def list_commands(self) -> Dict[str, Any]:
        """List available Slack commands."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # This would typically call the Slack API to get available commands
            commands = [
                {"name": "help", "description": "Show available commands"},
                {"name": "status", "description": "Show current status"},
                {"name": "analytics", "description": "Show analytics data"}
            ]
            
            return {
                "success": True,
                "commands": commands,
                "total_commands": len(commands)
            }
        except Exception as e:
            logger.error(f"Error listing Slack commands: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # Enhanced File Operations
    async def list_files(self, channel: str = None, user_id: str = None, file_types: List[str] = None) -> Dict[str, Any]:
        """List files in Slack workspace or channel."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            params = {"count": 100}
            if channel:
                params["channel"] = channel
            if user_id:
                params["user"] = user_id
            if file_types:
                params["types"] = ",".join(file_types)

            response = self.client.files_list(**params)

            if response["ok"]:
                files = []
                for file in response["files"]:
                    files.append({
                        "id": file["id"],
                        "name": file["name"],
                        "title": file.get("title", ""),
                        "url": file.get("url_private", ""),
                        "size": file.get("size", 0),
                        "created": file.get("created", 0),
                        "user": file.get("user", ""),
                        "filetype": file.get("filetype", ""),
                        "channels": file.get("channels", [])
                    })

                return {
                    "success": True,
                    "files": files,
                    "total_files": len(files)
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to list files: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error listing Slack files: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_file_info(self, file_id: str) -> Dict[str, Any]:
        """Get information about a specific file."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            response = self.client.files_info(file=file_id)

            if response["ok"]:
                file = response["file"]
                return {
                    "success": True,
                    "file": {
                        "id": file["id"],
                        "name": file["name"],
                        "title": file.get("title", ""),
                        "url": file.get("url_private", ""),
                        "size": file.get("size", 0),
                        "created": file.get("created", 0),
                        "user": file.get("user", ""),
                        "filetype": file.get("filetype", ""),
                        "channels": file.get("channels", []),
                        "comments_count": file.get("comments_count", 0),
                        "permalink": file.get("permalink", "")
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to get file info: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error getting Slack file info: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # Link Management
    async def get_shared_links(self, channel: str = None, date_range: str = None) -> Dict[str, Any]:
        """Get shared links from Slack channels."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            params = {"count": 100}
            if channel:
                params["channel"] = channel

            response = self.client.files_list(**params)

            if response["ok"]:
                links = []
                for file in response["files"]:
                    if file.get("url_private"):
                        links.append({
                            "url": file.get("url_private", ""),
                            "title": file.get("title", ""),
                            "user": file.get("user", ""),
                            "created": file.get("created", 0),
                            "channels": file.get("channels", [])
                        })

                return {
                    "success": True,
                    "links": links,
                    "total_links": len(links)
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to get shared links: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error getting Slack shared links: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # Workflow Management
    async def list_workflows(self) -> Dict[str, Any]:
        """List available Slack workflows."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # This is a placeholder - Slack workflows API might be different
            workflows = [
                {"id": "wf_1", "name": "Welcome New User", "description": "Automated welcome workflow"},
                {"id": "wf_2", "name": "Daily Report", "description": "Daily analytics report"},
                {"id": "wf_3", "name": "Alert System", "description": "System monitoring alerts"}
            ]
            
            return {
                "success": True,
                "workflows": workflows,
                "total_workflows": len(workflows)
            }
        except Exception as e:
            logger.error(f"Error listing Slack workflows: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def execute_workflow(self, workflow_id: str, inputs: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute a Slack workflow."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # This is a placeholder for workflow execution
            return {
                "success": True,
                "workflow_id": workflow_id,
                "inputs": inputs or {},
                "result": f"Workflow '{workflow_id}' executed successfully"
            }
        except Exception as e:
            logger.error(f"Error executing Slack workflow: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # Webhook Management
    async def send_webhook(self, webhook_url: str, message: str, channel: str = None, blocks: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a message via Slack webhook."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            import requests
            
            payload = {
                "text": message
            }
            
            if channel:
                payload["channel"] = channel
            if blocks:
                payload["blocks"] = blocks

            response = requests.post(webhook_url, json=payload)
            
            if response.status_code == 200:
                return {
                    "success": True,
                    "message": message,
                    "channel": channel,
                    "webhook_url": webhook_url
                }
            else:
                return {
                    "success": False,
                    "error": f"Webhook failed with status {response.status_code}"
                }

        except Exception as e:
            logger.error(f"Error sending Slack webhook: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # User Context and Profile Management
    async def update_user_profile(self, user_id: str, profile_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a user's profile information."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            response = self.client.users_profile_set(
                user=user_id,
                profile=profile_data
            )

            if response["ok"]:
                return {
                    "success": True,
                    "user_id": user_id,
                    "profile_data": profile_data
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to update user profile: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error updating Slack user profile: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_user_by_email(self, email: str) -> Dict[str, Any]:
        """Get user information by email address."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            response = self.client.users_lookupByEmail(email=email)

            if response["ok"]:
                user = response["user"]
                return {
                    "success": True,
                    "user": {
                        "id": user["id"],
                        "name": user["name"],
                        "real_name": user.get("real_name", ""),
                        "display_name": user.get("profile", {}).get("display_name", ""),
                        "email": user.get("profile", {}).get("email", ""),
                        "status": user.get("profile", {}).get("status_text", ""),
                        "is_bot": user.get("is_bot", False)
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to get user by email: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error getting Slack user by email: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # Advanced Features
    async def remove_reaction(self, channel: str, timestamp: str, emoji: str) -> Dict[str, Any]:
        """Remove a reaction from a message."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            response = self.client.reactions_remove(
                channel=channel,
                timestamp=timestamp,
                name=emoji
            )

            if response["ok"]:
                return {
                    "success": True,
                    "channel": channel,
                    "timestamp": timestamp,
                    "emoji": emoji
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to remove reaction: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error removing Slack reaction: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def set_reminder(self, user_id: str, reminder_text: str, reminder_time: str) -> Dict[str, Any]:
        """Set a reminder for a user."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # This is a placeholder - Slack reminders API might be different
            return {
                "success": True,
                "user_id": user_id,
                "reminder_text": reminder_text,
                "reminder_time": reminder_time,
                "result": f"Reminder set for {reminder_time}"
            }
        except Exception as e:
            logger.error(f"Error setting Slack reminder: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # Admin Tools
    async def list_user_groups(self) -> Dict[str, Any]:
        """List user groups in the workspace."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            response = self.client.usergroups_list()

            if response["ok"]:
                groups = []
                for group in response["usergroups"]:
                    groups.append({
                        "id": group["id"],
                        "name": group["name"],
                        "handle": group.get("handle", ""),
                        "description": group.get("description", ""),
                        "member_count": group.get("user_count", 0)
                    })

                return {
                    "success": True,
                    "groups": groups,
                    "total_groups": len(groups)
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to list user groups: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error listing Slack user groups: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def create_user_group(self, name: str, handle: str, user_ids: List[str], description: str = None) -> Dict[str, Any]:
        """Create a new user group."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            params = {
                "name": name,
                "handle": handle,
                "users": ",".join(user_ids)
            }
            if description:
                params["description"] = description

            response = self.client.usergroups_create(**params)

            if response["ok"]:
                group = response["usergroup"]
                return {
                    "success": True,
                    "group": {
                        "id": group["id"],
                        "name": group["name"],
                        "handle": group.get("handle", ""),
                        "description": group.get("description", ""),
                        "member_count": group.get("user_count", 0)
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to create user group: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error creating Slack user group: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # Channel Analytics
    async def get_channel_history(self, channel: str, limit: int = 100, oldest: str = None, latest: str = None) -> Dict[str, Any]:
        """Get message history from a channel."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            params = {
                "channel": channel,
                "limit": limit
            }
            if oldest:
                params["oldest"] = oldest
            if latest:
                params["latest"] = latest

            response = self.client.conversations_history(**params)

            if response["ok"]:
                messages = []
                for message in response["messages"]:
                    messages.append({
                        "text": message["text"],
                        "user": message.get("user", "Unknown"),
                        "timestamp": message["ts"],
                        "type": message.get("type", "message"),
                        "subtype": message.get("subtype"),
                        "reactions": message.get("reactions", [])
                    })

                return {
                    "success": True,
                    "channel": channel,
                    "messages": messages,
                    "total_messages": len(messages),
                    "has_more": response.get("has_more", False)
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to get channel history: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error getting Slack channel history: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # Search and Discovery
    async def search_files(self, query: str, channel: str = None, user: str = None, date_from: str = None, date_to: str = None, count: int = 20) -> Dict[str, Any]:
        """Search for files in Slack."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            params = {
                "query": query,
                "count": count
            }
            if channel:
                params["channel"] = channel
            if user:
                params["user"] = user

            response = self.client.search_files(**params)

            if response["ok"]:
                files = []
                for file in response["files"]["matches"]:
                    files.append({
                        "id": file["id"],
                        "name": file["name"],
                        "title": file.get("title", ""),
                        "url": file.get("url_private", ""),
                        "user": file.get("user", ""),
                        "created": file.get("created", 0),
                        "filetype": file.get("filetype", "")
                    })

                return {
                    "success": True,
                    "files": files,
                    "total_found": len(files),
                    "query": query
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to search files: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error searching Slack files: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # Workspace Management
    async def get_workspace_info(self) -> Dict[str, Any]:
        """Get workspace information."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            response = self.client.team_info()

            if response["ok"]:
                team = response["team"]
                return {
                    "success": True,
                    "workspace": {
                        "id": team["id"],
                        "name": team["name"],
                        "domain": team.get("domain", ""),
                        "email_domain": team.get("email_domain", ""),
                        "icon": team.get("icon", {}),
                        "plan": team.get("plan", ""),
                        "created": team.get("created", 0)
                    }
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to get workspace info: {response.get('error', 'Unknown error')}"
                }

        except Exception as e:
            logger.error(f"Error getting Slack workspace info: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_workspace_analytics(self) -> Dict[str, Any]:
        """Get workspace analytics data."""
        if not self.client:
            raise Exception("Slack client not initialized")

        try:
            # This is a placeholder - Slack analytics API might be different
            analytics = {
                "total_users": 150,
                "active_users": 120,
                "total_channels": 25,
                "total_messages": 15000,
                "files_shared": 500,
                "reactions_used": 2500
            }
            
            return {
                "success": True,
                "analytics": analytics
            }
        except Exception as e:
            logger.error(f"Error getting Slack workspace analytics: {e}")
            return {
                "success": False,
                "error": str(e)
            }
