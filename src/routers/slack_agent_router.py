"""
Slack Agent Router
Handles Slack Events API events and routes messages to appropriate agents
"""
import asyncio
import hmac
import hashlib
import json
import logging
from typing import Any, Dict, Optional
import uuid

import aiohttp
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import settings
from ..database import get_db
from ..models import Connection, ConnectionPlatform, ConnectionStatus, User
from ..services.agents.mpesa_agent import MpesaReconciliationAgent

router = APIRouter(prefix="/api/slack", tags=["slack-agents"])
logger = logging.getLogger(__name__)


def verify_slack_signature(request_body: bytes, timestamp: str, signature: str) -> bool:
    """Verify Slack request signature."""
    signing_secret = getattr(settings, 'SLACK_SIGNING_SECRET', None)
    if not signing_secret:
        logger.warning("SLACK_SIGNING_SECRET not configured, skipping signature verification")
        return True  # Skip verification if not configured
    
    sig_basestring = f"v0:{timestamp}:{request_body.decode()}"
    computed_signature = 'v0=' + hmac.new(
        signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(computed_signature, signature)


async def get_user_from_slack_team(
    team_id: str,
    db: AsyncSession
) -> Optional[User]:
    """
    Get user from Slack team ID.
    For now, returns the first user with an active Slack connection.
    TODO: Implement proper team_id to user mapping.
    """
    stmt = select(Connection).options(
        selectinload(Connection.user)
    ).where(
        Connection.platform == ConnectionPlatform.SLACK,
        Connection.status == ConnectionStatus.ACTIVE
    ).limit(1)
    
    result = await db.execute(stmt)
    connection = result.scalar_one_or_none()
    
    if connection:
        return connection.user
    
    return None


async def get_bot_user_id(connection: Connection) -> Optional[str]:
    """Get bot user ID from Slack connection."""
    try:
        from slack_sdk.web import WebClient
        
        bot_token = connection.config.get("bot_token")
        if not bot_token:
            return None
        
        # Check if bot_user_id is cached in config
        if "bot_user_id" in connection.config:
            return connection.config["bot_user_id"]
        
        # Fetch bot user ID from Slack API
        client = WebClient(token=bot_token)
        auth_response = client.auth_test()
        
        if auth_response.get("ok"):
            bot_user_id = auth_response.get("user_id")
            # Cache it in config for future use
            if bot_user_id:
                connection.config["bot_user_id"] = bot_user_id
                # Note: We're not saving to DB here to avoid async issues
                # The cache will be lost on restart, but that's acceptable
            return bot_user_id
        
        return None
    except Exception as e:
        logger.error(f"Error getting bot user ID: {e}", exc_info=True)
        return None


def is_bot_mentioned(text: str, bot_user_id: Optional[str]) -> bool:
    """Check if the bot is mentioned in the message text."""
    if not bot_user_id or not text:
        return False
    
    # Check for mention format: <@BOT_USER_ID> or @bot_name
    return f"<@{bot_user_id}>" in text or f"<@!{bot_user_id}>" in text


async def check_channel_is_dm(connection: Connection, channel_id: str) -> bool:
    """Check if a channel is a DM by querying Slack API."""
    try:
        from slack_sdk.web import WebClient
        
        bot_token = connection.config.get("bot_token")
        if not bot_token:
            return False
        
        client = WebClient(token=bot_token)
        # Use conversations.info to get channel details
        response = client.conversations_info(channel=channel_id)
        
        if response.get("ok"):
            channel_info = response.get("channel", {})
            is_im = channel_info.get("is_im", False)
            is_private = channel_info.get("is_private", False)
            # DMs are both IM and private
            return is_im and is_private
        
        return False
    except Exception as e:
        logger.error(f"Error checking if channel is DM: {e}", exc_info=True)
        return False


@router.post("/events")
async def slack_events(
    request: Request,
    background_tasks: BackgroundTasks,
    x_slack_request_timestamp: Optional[str] = Header(None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: Optional[str] = Header(None, alias="X-Slack-Signature"),
    db: AsyncSession = Depends(get_db)
):
    """Handle Slack Events API events."""
    body = await request.body()
    
    # Verify signature
    if x_slack_signature and x_slack_request_timestamp:
        if not verify_slack_signature(body, x_slack_request_timestamp, x_slack_signature):
            logger.warning("Invalid Slack signature")
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    # Handle URL verification challenge
    if data.get("type") == "url_verification":
        return {"challenge": data.get("challenge")}
    
    # Handle event callbacks
    if data.get("type") == "event_callback":
        event = data.get("event", {})
        event_type = event.get("type")
        team_id = data.get("team_id")
        
        # Handle message events
        if event_type == "message":
            # Skip bot messages and message edits
            if event.get("subtype") in ["bot_message", "message_changed", "message_deleted"]:
                return {"status": "ok"}
            
            channel = event.get("channel")
            channel_type = event.get("channel_type")
            text = event.get("text", "")
            slack_user_id = event.get("user")
            
            # Skip if missing required fields
            if not channel or not text or not slack_user_id:
                return {"status": "ok"}
            
            # Get user and connection
            user = await get_user_from_slack_team(team_id or "", db)
            if not user:
                logger.warning(f"No user found for team {team_id}")
                return {"status": "ok"}
            
            # Get connection to check bot user ID
            stmt = select(Connection).where(
                Connection.user_id == user.id,
                Connection.platform == ConnectionPlatform.SLACK,
                Connection.status == ConnectionStatus.ACTIVE
            ).order_by(Connection.created_at.desc()).limit(1)
            result = await db.execute(stmt)
            connection = result.scalar_one_or_none()
            
            if not connection:
                logger.warning(f"No active Slack connection for user {user.id}")
                return {"status": "ok"}
            
            # Get bot user ID for mention detection
            bot_user_id = await get_bot_user_id(connection)
            
            # Detect DMs: Check channel ID format (DMs start with 'D') or channel_type
            is_dm = False
            if channel and channel.startswith("D"):
                is_dm = True
            elif channel_type == "im":
                is_dm = True
            elif not channel_type or channel_type not in ["channel", "group"]:
                # Fallback: Use Slack API to check channel type if unclear
                is_dm = await check_channel_is_dm(connection, channel)
            
            # Check if bot is mentioned
            bot_mentioned = is_bot_mentioned(text, bot_user_id) if bot_user_id else False
            
            # Process if DM or bot is mentioned
            if is_dm or bot_mentioned:
                logger.info(f"Processing message: DM={is_dm}, Mentioned={bot_mentioned}, Channel={channel}")
                background_tasks.add_task(
                    process_message_async,
                    user_id=user.id,
                    channel=channel,
                    message=text,
                    slack_user_id=slack_user_id,
                    is_mention=bot_mentioned
                )
        
        return {"status": "ok"}
    
    return {"status": "ok"}


async def route_message_to_agent(
    channel: str,
    message: str,
    slack_user_id: str,
    team_id: Optional[str],
    db: AsyncSession
):
    """Route message to appropriate agent based on channel."""
    try:
        # Get user (simplified - in production, map Slack user/team to your user)
        user = await get_user_from_slack_team(team_id or "", db)
        
        if not user:
            logger.warning(f"No user found for team {team_id}")
            return
        
        # Determine which agent to use based on channel
        # For now, route all to M-Pesa agent
        # TODO: Implement channel-to-agent mapping
        agent = MpesaReconciliationAgent(user, db)
        response = await agent.process_message(message, channel, slack_user_id)
        
        # Send response back to Slack if successful
        if response.get("success") and response.get("response"):
            from ..services.slack_service import SlackService
            from slack_sdk.web import WebClient
            from sqlalchemy import select
            from ..models import Connection, ConnectionPlatform, ConnectionStatus
            
            slack_service = SlackService()
            
            # Get user's Slack connection (get most recent if multiple)
            stmt = select(Connection).where(
                Connection.user_id == user.id,
                Connection.platform == ConnectionPlatform.SLACK,
                Connection.status == ConnectionStatus.ACTIVE
            ).order_by(Connection.created_at.desc()).limit(1)
            result = await db.execute(stmt)
            connection = result.scalar_one_or_none()
            
            if connection:
                bot_token = connection.config.get("bot_token")
                if bot_token:
                    slack_service.client = WebClient(token=bot_token)
                    try:
                        await slack_service.send_message(
                            channel=channel,
                            message=response["response"]
                        )
                    except Exception as e:
                        logger.error(f"Error sending Slack response: {e}")
    
    except Exception as e:
        logger.error(f"Error routing message to agent: {e}", exc_info=True)


@router.post("/commands/mpesa")
async def slack_mpesa_command(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Handle /mpesa Slack slash command."""
    try:
        form_data = await request.form()
        text = form_data.get("text", "")
        channel = form_data.get("channel_id")
        user_id_slack = form_data.get("user_id")
        team_id = form_data.get("team_id")
        response_url = form_data.get("response_url")  # Slack provides this for delayed responses
        
        # Get user
        user = await get_user_from_slack_team(team_id or "", db)
        
        if not user:
            return {
                "response_type": "ephemeral",
                "text": "❌ No active Slack connection found. Please connect your Slack account first."
            }
        
        # Store user_id and other data for background task (can't pass db session directly)
        user_id = user.id
        
        # Return immediate acknowledgment to Slack (must be within 3 seconds)
        # Process the request asynchronously in background
        logger.info(f"Processing /mpesa command for user {user_id}: '{text}'")
        background_tasks.add_task(
            process_mpesa_command_async,
            user_id=user_id,
            text=text or "",
            channel=channel or "",
            slack_user_id=user_id_slack or "",
            response_url=response_url
        )
        
        # Return immediate response
        return {
            "response_type": "ephemeral",
            "text": "⏳ Processing your request..."
        }
    
    except Exception as e:
        logger.error(f"Error handling /mpesa command: {e}", exc_info=True)
        return {
            "response_type": "ephemeral",
            "text": f"❌ Error: {str(e)}"
        }


async def process_mpesa_command_async(
    user_id: uuid.UUID,
    text: str,
    channel: str,
    slack_user_id: str,
    response_url: Optional[str]
):
    """Process M-Pesa command asynchronously and send response."""
    from ..database import get_session_maker
    
    session_maker = get_session_maker()
    async with session_maker() as db:
        try:
            # Get user
            stmt = select(User).where(User.id == user_id)
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()
            
            if not user:
                if response_url:
                    await send_slack_response(response_url, {
                        "response_type": "ephemeral",
                        "text": "❌ User not found"
                    })
                return
            
            # Process with M-Pesa agent
            agent = MpesaReconciliationAgent(user, db)
            response = await agent.process_message(text, channel, slack_user_id)
        
            # Send response via response_url (for slash commands)
            if response_url:
                response_data = {
                    "response_type": "in_channel" if response.get("success") else "ephemeral",
                    "text": response.get("response") or response.get("error") or "Sorry, I couldn't process your request."
                }
                await send_slack_response(response_url, response_data)
        
        except Exception as e:
            logger.error(f"Error processing M-Pesa command: {e}", exc_info=True)
            if response_url:
                await send_slack_response(response_url, {
                    "response_type": "ephemeral",
                    "text": f"❌ Error processing request: {str(e)}"
                })


async def process_message_async(
    user_id: uuid.UUID,
    channel: str,
    message: str,
    slack_user_id: str,
    is_mention: bool = False
):
    """Process regular message (not slash command) asynchronously and send response."""
    from ..database import get_session_maker
    
    session_maker = get_session_maker()
    async with session_maker() as db:
        try:
            # Get user
            stmt = select(User).where(User.id == user_id)
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()
            
            if not user:
                logger.error(f"User {user_id} not found")
                return
            
            # Delegate entirely to the generic workflow engine
            from ..services.slack_workflow_trigger import SlackWorkflowTrigger
            await SlackWorkflowTrigger.on_message_received(
                user_id=user.id,
                channel=channel,
                message=message,
                slack_user_id=slack_user_id,
                is_mention=is_mention
            )
        
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)


async def send_slack_response(response_url: str, response_data: Dict[str, Any]):
    """Helper function to send response to Slack response_url."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                response_url,
                json=response_data,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    response_text = await resp.text()
                    logger.error(f"Failed to send Slack response: {resp.status} - {response_text}")
                else:
                    logger.info("Successfully sent delayed Slack response")
    except Exception as e:
        logger.error(f"Error sending Slack response: {e}", exc_info=True)

