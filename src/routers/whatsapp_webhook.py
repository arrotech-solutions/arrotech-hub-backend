"""
WhatsApp Webhook Handler for receiving incoming messages.
This is the critical piece for enabling auto-reply and chatbot features.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks
from fastapi.responses import PlainTextResponse
import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import Optional
import uuid

from ..database import get_db, get_session_maker
from ..models import (
    User, Connection, WhatsAppContact, WhatsAppMessage,
    WhatsAppMessageDirection, WhatsAppMessageStatus
)
from ..config import settings
from ..services import WhatsAppService

router = APIRouter(
    prefix="/api/whatsapp",
    tags=["whatsapp-webhook"]
)

logger = logging.getLogger(__name__)

# Initialize WhatsApp service
whatsapp_service = WhatsAppService()


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge")
):
    """
    Verify webhook for Meta/WhatsApp.
    Meta sends a GET request to verify the webhook endpoint.
    """
    logger.info(f"[WHATSAPP WEBHOOK] Verification request received")
    logger.info(f"[WHATSAPP WEBHOOK] Mode: {hub_mode}, Token: {hub_verify_token}")
    
    # Check verification token
    verify_token = settings.WHATSAPP_VERIFY_TOKEN or "arrotech_whatsapp_webhook_2024"
    
    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        logger.info("[WHATSAPP WEBHOOK] Verification successful!")
        return PlainTextResponse(content=hub_challenge, status_code=200)
    else:
        logger.warning(f"[WHATSAPP WEBHOOK] Verification failed! Expected: {verify_token}, Got: {hub_verify_token}")
        raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Receive incoming WhatsApp messages and status updates.
    This is where all the magic happens for auto-reply!
    """
    try:
        body = await request.json()
        logger.info(f"[WHATSAPP WEBHOOK] Received webhook payload: {body}")
        
        # Extract the entry array
        entries = body.get("entry", [])
        
        for entry in entries:
            # Each entry has changes
            changes = entry.get("changes", [])
            
            for change in changes:
                value = change.get("value", {})
                
                # Handle different types of updates
                if "messages" in value:
                    # Incoming message
                    await process_incoming_messages(value, db, background_tasks)
                    
                if "statuses" in value:
                    # Message status update (sent, delivered, read)
                    await process_status_updates(value, db)
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"[WHATSAPP WEBHOOK] Error processing webhook: {e}")
        # Always return 200 to prevent Meta from retrying
        return {"status": "error", "message": str(e)}


async def process_incoming_messages(value: dict, db: AsyncSession, background_tasks: BackgroundTasks):
    """Process incoming WhatsApp messages."""
    
    messages = value.get("messages", [])
    metadata = value.get("metadata", {})
    contacts = value.get("contacts", [])
    
    # Get the phone number ID that received this message
    phone_number_id = metadata.get("phone_number_id")
    
    logger.info(f"[WHATSAPP WEBHOOK] Processing {len(messages)} incoming message(s)")
    
    for msg in messages:
        try:
            # Extract message details
            msg_id = msg.get("id")
            
            # Check if message already exists (prevent duplicate inserts on Meta retries)
            existing_msg = await db.execute(
                select(WhatsAppMessage).filter(WhatsAppMessage.whatsapp_message_id == msg_id)
            )
            if existing_msg.scalar_one_or_none():
                logger.info(f"[WHATSAPP WEBHOOK] Message {msg_id} already exists, skipping duplicate.")
                continue

            from_number = msg.get("from")  # Sender's phone number
            msg_type = msg.get("type", "text")
            timestamp = msg.get("timestamp")
            
            # Get contact info
            contact_info = next((c for c in contacts if c.get("wa_id") == from_number), {})
            profile_name = contact_info.get("profile", {}).get("name", "")
            
            # Extract content based on message type
            content = ""
            media_url = None
            media_mime_type = None
            
            if msg_type == "text":
                content = msg.get("text", {}).get("body", "")
            elif msg_type == "image":
                image = msg.get("image", {})
                content = image.get("caption", "")
                media_url = image.get("id")  # This is media ID, need to download
                media_mime_type = image.get("mime_type", "image/jpeg")
            elif msg_type == "document":
                doc = msg.get("document", {})
                content = doc.get("caption", "") or doc.get("filename", "")
                media_url = doc.get("id")
                media_mime_type = doc.get("mime_type", "application/pdf")
            elif msg_type == "location":
                loc = msg.get("location", {})
                content = f"Location: {loc.get('latitude')}, {loc.get('longitude')}"
            elif msg_type == "button":
                content = msg.get("button", {}).get("text", "")
            elif msg_type == "interactive":
                interactive = msg.get("interactive", {})
                if interactive.get("type") == "button_reply":
                    title = interactive.get("button_reply", {}).get("title", "")
                    btn_id = interactive.get("button_reply", {}).get("id", "")

                    # Parse product card button clicks into actionable messages
                    # Look up product details from Redis cache (stored when card was sent)
                    if btn_id.startswith("add_to_cart_") or btn_id.startswith("view_details_"):
                        is_add_to_cart = btn_id.startswith("add_to_cart_")
                        product_id = btn_id.replace("add_to_cart_", "").replace("view_details_", "")

                        # Resolve product name from cache
                        product_name = product_id  # fallback
                        product_price = ""
                        try:
                            from ..services.cache_service import cache_service
                            cached = cache_service.get(f"product_card:{phone_number_id}:{product_id}")
                            if cached and isinstance(cached, dict):
                                product_name = cached.get("name", product_id)
                                price = cached.get("price", 0)
                                currency = cached.get("currency", "KES")
                                if price:
                                    product_price = f" ({currency} {price:,.0f})"
                        except Exception as cache_err:
                            logger.warning(f"[WHATSAPP WEBHOOK] Product cache lookup failed: {cache_err}")

                        if is_add_to_cart:
                            content = (
                                f"I want to add {product_name}{product_price} to my cart. "
                                f"Please proceed with my order."
                            )
                        else:
                            content = (
                                f"I want to see more details about {product_name}{product_price}. "
                                f"Please show me the full description, availability, and options."
                            )
                        msg_type = "text"  # Treat as text so workflows process it normally
                    else:
                        # Generic interactive button
                        content = f"{title}" if title else f"Button clicked: {btn_id}"
                        msg_type = "text"

                elif interactive.get("type") == "list_reply":
                    title = interactive.get("list_reply", {}).get("title", "")
                    list_id = interactive.get("list_reply", {}).get("id", "")
                    content = f"{title}" if title else f"Selected: {list_id}"
                    msg_type = "text"
            
            logger.info(f"[WHATSAPP WEBHOOK] Message from {from_number}: {content[:50]}...")
            
            # Find the user who owns this phone number ID
            # Look up by their WhatsApp connection config
            result = await db.execute(
                select(Connection).filter(
                    Connection.platform == "whatsapp",
                    Connection.status == "active"
                )
            )
            connections = result.scalars().all()
            
            logger.info(f"[WHATSAPP WEBHOOK] Found {len(connections)} active WhatsApp connection(s)")
            for c in connections:
                logger.info(f"[WHATSAPP WEBHOOK] Connection {c.id}: user_id={c.user_id}, config={c.config}")
            
            owner_user_id = None
            for conn in connections:
                config = conn.config or {}
                if config.get("phone_number_id") == phone_number_id:
                    owner_user_id = conn.user_id
                    break
            
            if not owner_user_id:
                logger.error(
                    f"[WHATSAPP WEBHOOK] No connection found for phone_number_id={phone_number_id}. "
                    f"Checked {len(connections)} active connection(s). Message from {from_number} will be skipped. "
                    f"Ensure the customer's connection config has the correct phone_number_id."
                )
                continue
            
            # Find or create contact
            contact = await get_or_create_contact(
                db, owner_user_id, from_number, profile_name
            )
            
            # Save the message
            message = WhatsAppMessage(
                user_id=owner_user_id,
                contact_id=contact.id,
                direction=WhatsAppMessageDirection.INCOMING,
                message_type=msg_type,
                content=content,
                media_url=media_url,
                media_mime_type=media_mime_type,
                whatsapp_message_id=msg_id,
                status=WhatsAppMessageStatus.DELIVERED
            )
            db.add(message)
            
            # Update contact's last message timestamp and count
            contact.last_message_at = datetime.utcnow()
            contact.message_count = (contact.message_count or 0) + 1
            if not contact.first_message_at:
                contact.first_message_at = datetime.utcnow()
            
            await db.commit()
            await db.refresh(message)
            
            logger.info(f"[WHATSAPP WEBHOOK] Saved message {msg_id} from {from_number}")
            
            # Trigger background processing
            background_tasks.add_task(
                background_process_message,
                owner_user_id,
                contact.id,
                message.id
            )
            
        except Exception as e:
            logger.error(f"[WHATSAPP WEBHOOK] Error processing message: {e}")
            continue

async def background_process_message(user_id: uuid.UUID, contact_id: uuid.UUID, message_id: uuid.UUID):
    """Process auto-reply and workflow triggers in the background with a fresh DB session."""
    session_maker = get_session_maker()
    async with session_maker() as db:
        try:
            # Fetch contact and message freshly
            contact_res = await db.execute(select(WhatsAppContact).filter(WhatsAppContact.id == contact_id))
            contact = contact_res.scalar_one_or_none()
            
            message_res = await db.execute(select(WhatsAppMessage).filter(WhatsAppMessage.id == message_id))
            message = message_res.scalar_one_or_none()
            
            if not contact or not message:
                logger.error(f"[WHATSAPP WEBHOOK BG] Contact or message not found")
                return

            # Mark message as read and show typing indicator
            try:
                from ..models import Connection
                from sqlalchemy import and_
                conn_res = await db.execute(
                    select(Connection).where(
                        and_(
                            Connection.user_id == user_id,
                            Connection.platform == "whatsapp",
                            Connection.status == "active"
                        )
                    )
                )
                connection = conn_res.scalar_one_or_none()
                wa_config = connection.config if connection else None

                if message.whatsapp_message_id:
                    from ..services.whatsapp_service import WhatsAppService
                    wa_svc = WhatsAppService()
                    await wa_svc.mark_message_read(
                        message.whatsapp_message_id,
                        show_typing=True,
                        config=wa_config
                    )
            except Exception as e:
                logger.error(f"[WHATSAPP WEBHOOK BG] Failed to send typing indicator: {e}")


            # Trigger auto-reply processing
            try:
                from ..services.whatsapp_auto_reply import auto_reply_engine
                await auto_reply_engine.process_incoming_message(
                    db, user_id, contact, message
                )
            except Exception as e:
                logger.error(f"[WHATSAPP WEBHOOK BG] Auto-reply error: {e}")
            
            # Trigger workflow automation
            try:
                from ..services.whatsapp_workflow_trigger import WhatsAppWorkflowTrigger
                await WhatsAppWorkflowTrigger.on_message_received(
                    user_id, contact, message
                )
            except Exception as e:
                logger.error(f"[WHATSAPP WEBHOOK BG] Workflow trigger error: {e}")
                
        except Exception as e:
            logger.error(f"[WHATSAPP WEBHOOK BG] Error in background processing: {e}")


async def process_status_updates(value: dict, db: AsyncSession):
    """Process message status updates (sent, delivered, read)."""
    
    statuses = value.get("statuses", [])
    
    for status in statuses:
        try:
            msg_id = status.get("id")
            status_value = status.get("status")  # sent, delivered, read, failed
            timestamp = status.get("timestamp")
            
            logger.info(f"[WHATSAPP WEBHOOK] Status update: {msg_id} -> {status_value}")
            
            # Map status to our enum
            status_map = {
                "sent": WhatsAppMessageStatus.SENT,
                "delivered": WhatsAppMessageStatus.DELIVERED,
                "read": WhatsAppMessageStatus.READ,
                "failed": WhatsAppMessageStatus.FAILED
            }
            
            new_status = status_map.get(status_value)
            if not new_status:
                continue
            
            # Update the message status
            result = await db.execute(
                select(WhatsAppMessage).filter(
                    WhatsAppMessage.whatsapp_message_id == msg_id
                )
            )
            message = result.scalar_one_or_none()
            
            if message:
                message.status = new_status
                if status_value == "delivered":
                    message.delivered_at = datetime.utcnow()
                elif status_value == "read":
                    message.read_at = datetime.utcnow()
                elif status_value == "failed":
                    errors = status.get("errors", [])
                    if errors:
                        message.error_message = errors[0].get("message", "Unknown error")
                
                await db.commit()
                logger.info(f"[WHATSAPP WEBHOOK] Updated message {msg_id} status to {status_value}")
            
        except Exception as e:
            logger.error(f"[WHATSAPP WEBHOOK] Error processing status update: {e}")
            continue


async def get_or_create_contact(
    db: AsyncSession,
    user_id: uuid.UUID,
    phone_number: str,
    profile_name: str = None
) -> WhatsAppContact:
    """Get existing contact or create a new one."""
    
    # Clean phone number
    phone_number = phone_number.replace("+", "").replace(" ", "").replace("-", "")
    
    # Try to find existing contact
    result = await db.execute(
        select(WhatsAppContact).filter(
            WhatsAppContact.user_id == user_id,
            WhatsAppContact.phone_number == phone_number
        )
    )
    contact = result.scalar_one_or_none()
    
    if contact:
        # Update profile name if we have a new one
        if profile_name and not contact.profile_name:
            contact.profile_name = profile_name
            await db.commit()
        return contact
    
    # Create new contact
    contact = WhatsAppContact(
        user_id=user_id,
        phone_number=phone_number,
        profile_name=profile_name,
        name=profile_name,  # Use profile name as initial name
        tags=[],
        message_count=0
    )
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    
    logger.info(f"[WHATSAPP WEBHOOK] Created new contact: {phone_number} for user {user_id}")
    
    return contact
