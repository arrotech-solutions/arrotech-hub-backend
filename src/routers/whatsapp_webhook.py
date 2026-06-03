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
    
    # Check verification token (required in production)
    verify_token = settings.WHATSAPP_VERIFY_TOKEN
    env = getattr(settings, "ENVIRONMENT", "development").lower()
    if not verify_token and env in ("development", "testing"):
        verify_token = "arrotech_whatsapp_webhook_2024"
    if not verify_token:
        logger.error("[WHATSAPP WEBHOOK] WHATSAPP_VERIFY_TOKEN is not configured")
        raise HTTPException(status_code=503, detail="Webhook verify token not configured")
    
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
        raw_body = await request.body()
        signature_header = request.headers.get("X-Hub-Signature-256", "")
        app_secret = settings.WHATSAPP_APP_SECRET or settings.FACEBOOK_APP_SECRET
        require_sig = getattr(settings, "WHATSAPP_WEBHOOK_REQUIRE_SIGNATURE", False)

        if app_secret and require_sig:
            from ..services.whatsapp_ordering_helpers import verify_whatsapp_signature
            if not verify_whatsapp_signature(raw_body, signature_header, app_secret):
                logger.warning("[WHATSAPP WEBHOOK] Invalid or missing signature")
                raise HTTPException(status_code=403, detail="Invalid signature")
        elif require_sig and not app_secret:
            logger.warning(
                "[WHATSAPP WEBHOOK] WHATSAPP_APP_SECRET not set — skipping signature check"
            )

        import json as _json
        body = _json.loads(raw_body.decode("utf-8") if raw_body else "{}")
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
                    # Primary path: Celery worker (original behaviour).
                    # Fallback: inline only if queue dispatch fails (no worker / local dev).
                    _dispatch_whatsapp_incoming(value, background_tasks)
                    
                if "statuses" in value:
                    # Message status update (sent, delivered, read)
                    await process_status_updates(value, db)
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"[WHATSAPP WEBHOOK] Error processing webhook: {e}")
        # Always return 200 to prevent Meta from retrying
        return {"status": "error", "message": str(e)}


def _dispatch_whatsapp_incoming(value: dict, background_tasks: Optional[BackgroundTasks]) -> None:
    """Queue to Celery, or process inline when broker/worker unavailable."""
    use_celery = getattr(settings, "WHATSAPP_USE_CELERY_WEBHOOK", True)
    inline_fallback = getattr(settings, "WHATSAPP_WEBHOOK_INLINE_FALLBACK", True)
    queued = False

    if use_celery:
        try:
            from ..tasks.webhook_tasks import process_whatsapp_message_task
            process_whatsapp_message_task.delay(value)
            queued = True
            logger.info("[WHATSAPP WEBHOOK] Message queued to Celery")
        except Exception as e:
            logger.warning(
                f"[WHATSAPP WEBHOOK] Celery dispatch failed, will use inline fallback: {e}"
            )

    if not queued and inline_fallback:
        if background_tasks is not None:
            background_tasks.add_task(_process_whatsapp_payload_inline, value)
            logger.info("[WHATSAPP WEBHOOK] Message scheduled for inline background processing")
        else:
            logger.warning(
                "[WHATSAPP WEBHOOK] No Celery and no BackgroundTasks — message may not be processed"
            )


async def _process_whatsapp_payload_inline(value: dict) -> None:
    """Process webhook payload in-process (when Celery is not running)."""
    session_maker = get_session_maker()
    async with session_maker() as db:
        try:
            await process_incoming_messages(value, db, background_tasks=None)
        except Exception as e:
            logger.error(f"[WHATSAPP WEBHOOK] Inline processing error: {e}", exc_info=True)


async def process_incoming_messages(value: dict, db: AsyncSession, background_tasks: Optional[BackgroundTasks] = None):
    """Process incoming WhatsApp messages."""
    
    messages = value.get("messages", [])
    metadata = value.get("metadata", {})
    contacts = value.get("contacts", [])
    
    # Get the phone number ID that received this message
    phone_number_id = metadata.get("phone_number_id")
    
    logger.info(f"[WHATSAPP WEBHOOK] Processing {len(messages)} incoming message(s)")
    
    for msg in messages:
        pending_cart_item = None
        pending_delivery_location = None
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
                from ..services.whatsapp_location_service import (
                    normalize_whatsapp_location_payload,
                    enrich_location_with_reverse_geocode,
                    build_location_agent_message,
                )

                loc = msg.get("location", {})
                location_data = normalize_whatsapp_location_payload(loc)
                if location_data:
                    location_data = await enrich_location_with_reverse_geocode(
                        location_data
                    )
                    pending_delivery_location = location_data
                    content = build_location_agent_message(location_data)
                else:
                    content = "I shared my location but it could not be read."
            elif msg_type == "button":
                content = msg.get("button", {}).get("text", "")
            elif msg_type == "interactive":
                interactive = msg.get("interactive", {})
                if interactive.get("type") == "button_reply":
                    title = interactive.get("button_reply", {}).get("title", "")
                    btn_id = interactive.get("button_reply", {}).get("id", "")
                    # ── Parse order card action button clicks ──
                    # Format: "cancel_order:{order_id}", "order_details:{order_id}",
                    #          "confirm_cancel:{order_id}", "keep_order:{order_id}"
                    order_action = None
                    order_id_from_btn = None

                    if btn_id.startswith("cancel_order:"):
                        order_action = "cancel"
                        order_id_from_btn = btn_id.split(":", 1)[1]
                    elif btn_id.startswith("order_details:"):
                        order_action = "details"
                        order_id_from_btn = btn_id.split(":", 1)[1]
                    elif btn_id.startswith("confirm_cancel:"):
                        order_action = "confirm_cancel"
                        order_id_from_btn = btn_id.split(":", 1)[1]
                    elif btn_id.startswith("keep_order:"):
                        order_action = "keep"
                        order_id_from_btn = btn_id.split(":", 1)[1]

                    if order_action and order_id_from_btn:
                        if order_action == "cancel":
                            content = (
                                f"I want to cancel order {order_id_from_btn}. "
                                f"Please proceed with the cancellation."
                            )
                        elif order_action == "details":
                            content = (
                                f"Show me the full details of order {order_id_from_btn}."
                            )
                        elif order_action == "confirm_cancel":
                            content = (
                                f"Yes, please confirm the cancellation of order {order_id_from_btn}."
                            )
                        elif order_action == "keep":
                            content = (
                                f"No, I changed my mind. Please keep order {order_id_from_btn} active."
                            )
                        msg_type = "text"

                    # ── Staff ↔ AI assistant toggle buttons ──
                    elif btn_id in ("agent:human", "agent:staff"):
                        content = "I'd like to speak with a person, please."
                        msg_type = "text"
                    elif btn_id == "agent:ai":
                        content = "/bot"
                        msg_type = "text"

                    # ── Welcome / menu quick-reply buttons ──
                    elif btn_id.startswith("menu:"):
                        menu_action = btn_id.split(":", 1)[1] if ":" in btn_id else ""
                        menu_messages = {
                            "browse": "I'd like to browse the menu. Please show me what you have.",
                            "add_more": "I'd like to browse the menu and add more items to my cart.",
                            "cart": "view my cart",
                            "clear_cart": "clear cart",
                            "checkout": "checkout",
                            "orders": "I'd like to see my order history and status.",
                            "human": "I'd like to speak with a person, please.",
                            "reset": "reset",
                        }
                        content = menu_messages.get(
                            menu_action,
                            title or "Hello, I need help with my order.",
                        )
                        msg_type = "text"

                    # ── Parse product card button clicks ──
                    # New format: cart:{product_id} / details:{product_id}
                    # Legacy: cart:Chicken Stew:400
                    elif btn_id.startswith("cart:") or btn_id.startswith("details:"):
                        from ..services.whatsapp_ordering_helpers import parse_product_button_id

                        is_add_to_cart = btn_id.startswith("cart:")
                        _action, product_id = parse_product_button_id(btn_id)
                        product_name = None
                        product_price = ""
                        price_val = 0.0
                        cache_key_id = product_id

                        if product_id:
                            try:
                                from ..services.cache_service import cache_service
                                cached = cache_service.get(
                                    f"product_card:{phone_number_id}:{product_id}"
                                )
                                if cached and isinstance(cached, dict):
                                    product_name = cached.get("name", product_id)
                                    price_val = float(cached.get("price", 0) or 0)
                                    if price_val:
                                        product_price = f" (KES {price_val:,.0f})"
                            except Exception as cache_err:
                                logger.warning(
                                    f"[WHATSAPP WEBHOOK] Product cache lookup failed: {cache_err}"
                                )
                            if not product_name:
                                product_name = product_id
                        else:
                            # Legacy name:price format
                            parts = btn_id.split(":", 2)
                            product_name = parts[1] if len(parts) >= 2 else None
                            if len(parts) >= 3:
                                try:
                                    price_val = float(parts[2])
                                    product_price = f" (KES {price_val:,.0f})"
                                except (ValueError, TypeError):
                                    pass
                            cache_key_id = product_name

                        if product_name:
                            if is_add_to_cart:
                                content = (
                                    f"I want to add {product_name}{product_price} to my cart. "
                                    f"Please show my cart and help me complete the order."
                                )
                                pending_cart_item = {
                                    "id": cache_key_id or product_name,
                                    "name": product_name,
                                    "unit_price": price_val,
                                    "quantity": 1,
                                }
                            else:
                                content = (
                                    f"I want to see more details about {product_name}{product_price}. "
                                    f"Please show me the full description, availability, and options."
                                )
                        else:
                            content = f"{title}" if title else f"Button clicked: {btn_id}"
                        msg_type = "text"

                    elif btn_id.startswith("add_to_cart_") or btn_id.startswith("view_details_"):
                        # Old format — try Redis cache for product name
                        is_add_to_cart = btn_id.startswith("add_to_cart_")
                        product_id = btn_id.replace("add_to_cart_", "").replace("view_details_", "")
                        product_name = product_id  # fallback to opaque ID
                        legacy_price = 0.0
                        try:
                            from ..services.cache_service import cache_service
                            cached = cache_service.get(f"product_card:{phone_number_id}:{product_id}")
                            if cached and isinstance(cached, dict):
                                product_name = cached.get("name", product_id)
                                legacy_price = float(cached.get("price", 0) or 0)
                                currency = cached.get("currency", "KES")
                                if legacy_price:
                                    product_price = f" ({currency} {legacy_price:,.0f})"
                        except Exception as cache_err:
                            logger.warning(f"[WHATSAPP WEBHOOK] Product cache lookup failed: {cache_err}")

                        if is_add_to_cart:
                            content = (
                                f"I want to add {product_name}{product_price} to my cart. "
                                f"Please show my cart and help me complete the order."
                            )
                            pending_cart_item = {
                                "id": product_id or product_name,
                                "name": product_name,
                                "unit_price": legacy_price,
                                "quantity": 1,
                            }
                        else:
                            content = (
                                f"I want to see more details about {product_name}{product_price}. "
                                f"Please show me the full description, availability, and options."
                            )
                        msg_type = "text"

                    else:
                        # Generic interactive button
                        content = f"{title}" if title else f"Button clicked: {btn_id}"
                        msg_type = "text"

                elif interactive.get("type") == "list_reply":
                    title = interactive.get("list_reply", {}).get("title", "")
                    list_id = interactive.get("list_reply", {}).get("id", "")
                    if list_id.startswith("cart_rm:"):
                        product_ref = list_id.split(":", 1)[1]
                        remove_label = title or product_ref
                        content = f"remove {remove_label}"
                        msg_type = "text"
                    else:
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

            if pending_cart_item:
                try:
                    from ..services.conversation_context_manager import (
                        context_manager,
                        _build_session_key,
                    )
                    sk = _build_session_key("whatsapp", str(owner_user_id), from_number)
                    await context_manager.add_cart_item(sk, pending_cart_item)
                except Exception as cart_err:
                    logger.warning(f"[WHATSAPP WEBHOOK] Cart update failed: {cart_err}")

            if pending_delivery_location:
                try:
                    from ..services.conversation_context_manager import (
                        context_manager,
                        _build_session_key,
                    )

                    sk = _build_session_key(
                        "whatsapp", str(owner_user_id), from_number
                    )
                    await context_manager.set_delivery_location(
                        sk, pending_delivery_location
                    )
                except Exception as loc_err:
                    logger.warning(
                        f"[WHATSAPP WEBHOOK] Delivery location save failed: {loc_err}"
                    )

            # Trigger processing
            if background_tasks:
                background_tasks.add_task(
                    background_process_message,
                    owner_user_id,
                    contact.id,
                    message.id
                )
            else:
                # If no background_tasks (e.g. running inside Celery), await directly
                await background_process_message(owner_user_id, contact.id, message.id)
            
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

            wa_config = None

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
                if not connection:
                    logger.warning(f"[WHATSAPP WEBHOOK BG] No active WhatsApp connection found for user {user_id}")
                wa_config = connection.config if connection else None
                if wa_config:
                    logger.info(f"[WHATSAPP WEBHOOK BG] Found connection config, phone_id: {wa_config.get('phone_number_id')}")

                if message.whatsapp_message_id:
                    from ..services.whatsapp_service import WhatsAppService
                    wa_svc = WhatsAppService()
                    await wa_svc.mark_message_read(
                        message.whatsapp_message_id,
                        show_typing=True,
                        to_number=contact.phone_number,
                        config=wa_config
                    )
            except Exception as e:
                logger.error(f"[WHATSAPP WEBHOOK BG] Failed to send typing indicator: {e}")

            # Per-sender rate limit
            try:
                from ..services.cache_service import cache_service
                from ..services.whatsapp_ordering_helpers import (
                    check_whatsapp_rate_limit,
                    rate_limit_message,
                )
                limit = getattr(settings, "WHATSAPP_WEBHOOK_RATE_LIMIT", 15)
                window = getattr(settings, "WHATSAPP_WEBHOOK_RATE_WINDOW", 60)
                allowed, count = check_whatsapp_rate_limit(
                    cache_service.redis_client,
                    str(user_id),
                    contact.phone_number,
                    limit=limit,
                    window_seconds=window,
                )
                if not allowed:
                    logger.warning(
                        f"[WHATSAPP WEBHOOK BG] Rate limit exceeded for {contact.phone_number} ({count})"
                    )
                    if wa_config:
                        from ..services.whatsapp_service import WhatsAppService
                        biz_phone = (wa_config or {}).get("business_phone", "")
                        await WhatsAppService().send_message(
                            contact.phone_number,
                            rate_limit_message(biz_phone),
                            config=wa_config,
                        )
                    return
            except Exception as e:
                logger.error(f"[WHATSAPP WEBHOOK BG] Rate limit check error: {e}")

            has_agent_workflow = False
            try:
                from ..services.whatsapp_workflow_trigger import WhatsAppWorkflowTrigger
                has_agent_workflow = await WhatsAppWorkflowTrigger.has_active_conversational_agent(
                    user_id, db
                )
            except Exception as e:
                logger.warning(f"[WHATSAPP WEBHOOK BG] Agent workflow check failed: {e}")

            # Skip auto-reply when a conversational ordering workflow is active
            if not has_agent_workflow:
                try:
                    from ..services.whatsapp_auto_reply import auto_reply_engine
                    await auto_reply_engine.process_incoming_message(
                        db, user_id, contact, message
                    )
                except Exception as e:
                    logger.error(f"[WHATSAPP WEBHOOK BG] Auto-reply error: {e}")
            else:
                logger.info(
                    "[WHATSAPP WEBHOOK BG] Skipping auto-reply — conversational agent workflow active"
                )

            # Trigger workflow automation (always — cart commands handled inside agent)
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
