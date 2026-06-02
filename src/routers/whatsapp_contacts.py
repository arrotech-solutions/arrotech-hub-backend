"""
WhatsApp Contacts & Messages API.
CRUD operations for contacts and conversation history.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, or_
from sqlalchemy.orm import selectinload
from typing import Optional, List
import uuid
from pydantic import BaseModel
from datetime import datetime

from ..database import get_db
from ..models import (
    User, WhatsAppContact, WhatsAppMessage, WhatsAppMessageDirection,
    WhatsAppMessageStatus, WhatsAppAutoReply, WhatsAppBusinessProfile
)
from ..routers.auth_router import get_current_user
from ..services import WhatsAppService
from ..services.tier_gate import check_connection_access
from ..config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/whatsapp",
    tags=["whatsapp-contacts"]
)

whatsapp_service = WhatsAppService()


@router.get("/debug-credentials")
async def debug_whatsapp_credentials(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Debug endpoint to check WhatsApp credentials (admin only)."""
    # Get connection config
    from ..models import Connection
    result = await db.execute(
        select(Connection).filter(
            Connection.user_id == user.id,
            Connection.platform == "whatsapp",
            Connection.status == "active"
        )
    )
    connection = result.scalar_one_or_none()
    
    conn_config = connection.config if connection else {}
    
    return {
        "env_credentials": {
            "WHATSAPP_VERIFY_TOKEN": settings.WHATSAPP_VERIFY_TOKEN[:10] + "..." if settings.WHATSAPP_VERIFY_TOKEN else None,
            "WHATSAPP_TOKEN": settings.WHATSAPP_TOKEN[:20] + "..." if settings.WHATSAPP_TOKEN else None,
            "WHATSAPP_PHONE_NUMBER_ID": settings.WHATSAPP_PHONE_NUMBER_ID,
            "WHATSAPP_BUSINESS_ACCOUNT_ID": settings.WHATSAPP_BUSINESS_ACCOUNT_ID,
            "WHATSAPP_APP_ID": settings.WHATSAPP_APP_ID,
            "WHATSAPP_APP_SECRET": settings.WHATSAPP_APP_SECRET[:10] + "..." if settings.WHATSAPP_APP_SECRET else None,
        },
        "connection_config": {
            "has_connection": connection is not None,
            "phone_number_id": conn_config.get("phone_number_id"),
            "business_account_id": conn_config.get("business_account_id"),
            "access_token": conn_config.get("access_token", "")[:20] + "..." if conn_config.get("access_token") else None,
            "setup_needed": conn_config.get("setup_needed"),
        }
    }


# ============================================================================
# Pydantic Schemas
# ============================================================================

class ContactCreate(BaseModel):
    phone_number: str
    name: Optional[str] = None
    tags: Optional[List[str]] = []
    notes: Optional[str] = None

class ContactUpdate(BaseModel):
    name: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    is_blocked: Optional[bool] = None

class ContactResponse(BaseModel):
    id: uuid.UUID
    phone_number: str
    name: Optional[str]
    profile_name: Optional[str]
    tags: Optional[List[str]]
    notes: Optional[str]
    message_count: int
    first_message_at: Optional[datetime]
    last_message_at: Optional[datetime]
    is_blocked: bool
    created_at: datetime

    class Config:
        from_attributes = True

class MessageCreate(BaseModel):
    content: str
    message_type: str = "text"

class MessageResponse(BaseModel):
    id: uuid.UUID
    direction: str
    message_type: str
    content: Optional[str]
    media_url: Optional[str]
    status: str
    is_auto_reply: bool
    created_at: datetime
    delivered_at: Optional[datetime]
    read_at: Optional[datetime]

    class Config:
        from_attributes = True

class AutoReplyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    trigger_type: str  # first_message, keyword, business_hours, all
    trigger_value: Optional[str] = None
    response_type: str = "text"  # text, template, ai
    response_content: Optional[str] = None
    is_active: bool = True
    priority: int = 0

class AutoReplyResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    trigger_type: str
    trigger_value: Optional[str]
    response_type: str
    response_content: Optional[str]
    is_active: bool
    priority: int
    times_triggered: int
    last_triggered_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True

class BusinessProfileUpdate(BaseModel):
    business_name: Optional[str] = None
    description: Optional[str] = None
    industry: Optional[str] = None
    products: Optional[List[dict]] = None
    services: Optional[List[dict]] = None
    faqs: Optional[List[dict]] = None
    greeting_message: Optional[str] = None
    away_message: Optional[str] = None
    business_hours: Optional[dict] = None
    timezone: Optional[str] = None


# ============================================================================
# Contacts API
# ============================================================================

@router.get("/contacts")
async def list_contacts(
    search: Optional[str] = Query(None, description="Search by name or phone"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    limit: int = Query(50, le=100),
    offset: int = Query(0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all WhatsApp contacts for the current user."""
    check_connection_access(user, "whatsapp_business")
    
    query = select(WhatsAppContact).filter(
        WhatsAppContact.user_id == user.id
    )
    
    # Search filter
    if search:
        query = query.filter(
            or_(
                WhatsAppContact.name.ilike(f"%{search}%"),
                WhatsAppContact.phone_number.ilike(f"%{search}%"),
                WhatsAppContact.profile_name.ilike(f"%{search}%")
            )
        )
    
    # Tag filter
    if tag:
        query = query.filter(WhatsAppContact.tags.contains([tag]))
    
    # Order by last message (most recent first)
    query = query.order_by(desc(WhatsAppContact.last_message_at))
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    result = await db.execute(count_query)
    total = result.scalar()
    
    # Apply pagination
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    contacts = result.scalars().all()
    
    return {
        "success": True,
        "data": [ContactResponse.model_validate(c) for c in contacts],
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/contacts/{contact_id}")
async def get_contact(
    contact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a single contact by ID."""
    check_connection_access(user, "whatsapp_business")
    
    result = await db.execute(
        select(WhatsAppContact).filter(
            WhatsAppContact.id == contact_id,
            WhatsAppContact.user_id == user.id
        )
    )
    contact = result.scalar_one_or_none()
    
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    return {
        "success": True,
        "data": ContactResponse.model_validate(contact)
    }


@router.post("/contacts")
async def create_contact(
    data: ContactCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new contact."""
    check_connection_access(user, "whatsapp_business")
    
    # Clean phone number
    phone = data.phone_number.replace("+", "").replace(" ", "").replace("-", "")
    
    # Check if contact already exists
    result = await db.execute(
        select(WhatsAppContact).filter(
            WhatsAppContact.user_id == user.id,
            WhatsAppContact.phone_number == phone
        )
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        raise HTTPException(status_code=400, detail="Contact with this phone number already exists")
    
    contact = WhatsAppContact(
        user_id=user.id,
        phone_number=phone,
        name=data.name,
        tags=data.tags or [],
        notes=data.notes,
        message_count=0
    )
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    
    return {
        "success": True,
        "data": ContactResponse.model_validate(contact)
    }


@router.put("/contacts/{contact_id}")
async def update_contact(
    contact_id: uuid.UUID,
    data: ContactUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a contact."""
    check_connection_access(user, "whatsapp_business")
    
    result = await db.execute(
        select(WhatsAppContact).filter(
            WhatsAppContact.id == contact_id,
            WhatsAppContact.user_id == user.id
        )
    )
    contact = result.scalar_one_or_none()
    
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    # Update fields
    if data.name is not None:
        contact.name = data.name
    if data.tags is not None:
        contact.tags = data.tags
    if data.notes is not None:
        contact.notes = data.notes
    if data.is_blocked is not None:
        contact.is_blocked = data.is_blocked
    
    await db.commit()
    await db.refresh(contact)
    
    return {
        "success": True,
        "data": ContactResponse.model_validate(contact)
    }


@router.delete("/contacts/{contact_id}")
async def delete_contact(
    contact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a contact and all their messages."""
    check_connection_access(user, "whatsapp_business")
    
    result = await db.execute(
        select(WhatsAppContact).filter(
            WhatsAppContact.id == contact_id,
            WhatsAppContact.user_id == user.id
        )
    )
    contact = result.scalar_one_or_none()
    
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    await db.delete(contact)
    await db.commit()
    
    return {"success": True, "message": "Contact deleted"}


# ============================================================================
# Messages API
# ============================================================================

@router.get("/contacts/{contact_id}/messages")
async def get_messages(
    contact_id: uuid.UUID,
    limit: int = Query(50, le=100),
    before_id: Optional[uuid.UUID] = Query(None, description="Load messages before this ID"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get conversation history with a contact."""
    check_connection_access(user, "whatsapp_business")
    
    # Verify contact belongs to user
    result = await db.execute(
        select(WhatsAppContact).filter(
            WhatsAppContact.id == contact_id,
            WhatsAppContact.user_id == user.id
        )
    )
    contact = result.scalar_one_or_none()
    
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    query = select(WhatsAppMessage).filter(
        WhatsAppMessage.contact_id == contact_id
    )
    
    # Pagination by ID
    if before_id:
        query = query.filter(WhatsAppMessage.id < before_id)
    
    query = query.order_by(desc(WhatsAppMessage.created_at)).limit(limit)
    
    result = await db.execute(query)
    messages = result.scalars().all()
    
    # Reverse to get chronological order
    messages = list(reversed(messages))
    
    return {
        "success": True,
        "data": [MessageResponse.model_validate(m) for m in messages],
        "contact": ContactResponse.model_validate(contact)
    }


@router.post("/contacts/{contact_id}/messages")
async def send_message(
    contact_id: uuid.UUID,
    data: MessageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Send a message to a contact."""
    check_connection_access(user, "whatsapp_business")
    
    # Verify contact belongs to user
    result = await db.execute(
        select(WhatsAppContact).filter(
            WhatsAppContact.id == contact_id,
            WhatsAppContact.user_id == user.id
        )
    )
    contact = result.scalar_one_or_none()
    
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    if contact.is_blocked:
        raise HTTPException(status_code=400, detail="Cannot send message to blocked contact")
    
    # Get user's WhatsApp connection config
    from ..models import Connection
    result = await db.execute(
        select(Connection).filter(
            Connection.user_id == user.id,
            Connection.platform == "whatsapp",
            Connection.status == "active"
        )
    )
    connection = result.scalar_one_or_none()
    
    if not connection:
        raise HTTPException(status_code=400, detail="WhatsApp not connected")
    
    # Send via WhatsApp API
    config = connection.config or {}
    send_result = await whatsapp_service.send_message(
        to_number=contact.phone_number,
        message=data.content,
        message_type=data.message_type,
        config=config
    )
    
    if not send_result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=send_result.get("error", "Failed to send message")
        )
    
    # Save outgoing message
    message = WhatsAppMessage(
        user_id=user.id,
        contact_id=contact.id,
        direction=WhatsAppMessageDirection.OUTGOING,
        message_type=data.message_type,
        content=data.content,
        whatsapp_message_id=send_result.get("message_id"),
        status=WhatsAppMessageStatus.SENT
    )
    db.add(message)
    
    # Update contact
    contact.last_message_at = datetime.utcnow()
    contact.message_count = (contact.message_count or 0) + 1
    
    await db.commit()
    await db.refresh(message)

    return {
        "success": True,
        "data": MessageResponse.model_validate(message)
    }


@router.post("/contacts/{contact_id}/release-agent")
async def release_agent_for_contact(
    contact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a contact conversation to the AI agent after human handoff."""
    check_connection_access(user, "whatsapp_business")

    result = await db.execute(
        select(WhatsAppContact).filter(
            WhatsAppContact.id == contact_id,
            WhatsAppContact.user_id == user.id,
        )
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    from ..services.conversation_context_manager import (
        context_manager,
        _build_session_key,
    )

    sk = _build_session_key("whatsapp", str(user.id), contact.phone_number)
    cleared = await context_manager.clear_human_handoff(sk)

    tags = [t for t in (contact.tags or []) if t not in ("human_handoff", "needs_attention")]
    contact.tags = tags
    await db.commit()

    return {
        "success": True,
        "released": cleared,
        "session_key": sk,
        "message": "AI agent resumed for this contact. Customer can continue ordering via chat.",
    }


# ============================================================================
# Auto-Reply Rules API
# ============================================================================

@router.get("/auto-replies")
async def list_auto_replies(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all auto-reply rules."""
    check_connection_access(user, "whatsapp_business")
    
    result = await db.execute(
        select(WhatsAppAutoReply).filter(
            WhatsAppAutoReply.user_id == user.id
        ).order_by(desc(WhatsAppAutoReply.priority))
    )
    rules = result.scalars().all()
    
    return {
        "success": True,
        "data": [AutoReplyResponse.model_validate(r) for r in rules]
    }


@router.post("/auto-replies")
async def create_auto_reply(
    data: AutoReplyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new auto-reply rule."""
    check_connection_access(user, "whatsapp_business")
    
    rule = WhatsAppAutoReply(
        user_id=user.id,
        name=data.name,
        description=data.description,
        trigger_type=data.trigger_type,
        trigger_value=data.trigger_value,
        response_type=data.response_type,
        response_content=data.response_content,
        is_active=data.is_active,
        priority=data.priority,
        times_triggered=0
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    
    return {
        "success": True,
        "data": AutoReplyResponse.model_validate(rule)
    }


@router.put("/auto-replies/{rule_id}")
async def update_auto_reply(
    rule_id: uuid.UUID,
    data: AutoReplyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update an auto-reply rule."""
    check_connection_access(user, "whatsapp_business")
    
    result = await db.execute(
        select(WhatsAppAutoReply).filter(
            WhatsAppAutoReply.id == rule_id,
            WhatsAppAutoReply.user_id == user.id
        )
    )
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    # Update all fields
    rule.name = data.name
    rule.description = data.description
    rule.trigger_type = data.trigger_type
    rule.trigger_value = data.trigger_value
    rule.response_type = data.response_type
    rule.response_content = data.response_content
    rule.is_active = data.is_active
    rule.priority = data.priority
    
    await db.commit()
    await db.refresh(rule)
    
    return {
        "success": True,
        "data": AutoReplyResponse.model_validate(rule)
    }


@router.delete("/auto-replies/{rule_id}")
async def delete_auto_reply(
    rule_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete an auto-reply rule."""
    check_connection_access(user, "whatsapp_business")
    
    result = await db.execute(
        select(WhatsAppAutoReply).filter(
            WhatsAppAutoReply.id == rule_id,
            WhatsAppAutoReply.user_id == user.id
        )
    )
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    await db.delete(rule)
    await db.commit()
    
    return {"success": True, "message": "Rule deleted"}


@router.patch("/auto-replies/{rule_id}/toggle")
async def toggle_auto_reply(
    rule_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Toggle an auto-reply rule on/off."""
    check_connection_access(user, "whatsapp_business")
    
    result = await db.execute(
        select(WhatsAppAutoReply).filter(
            WhatsAppAutoReply.id == rule_id,
            WhatsAppAutoReply.user_id == user.id
        )
    )
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    rule.is_active = not rule.is_active
    await db.commit()
    
    return {
        "success": True,
        "data": {"is_active": rule.is_active}
    }


# ============================================================================
# Business Profile API
# ============================================================================

@router.get("/business-profile")
async def get_business_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the user's WhatsApp business profile."""
    check_connection_access(user, "whatsapp_business")
    
    result = await db.execute(
        select(WhatsAppBusinessProfile).filter(
            WhatsAppBusinessProfile.user_id == user.id
        )
    )
    profile = result.scalar_one_or_none()
    
    if not profile:
        # Create default profile
        profile = WhatsAppBusinessProfile(
            user_id=user.id,
            timezone="Africa/Nairobi"
        )
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
    
    return {
        "success": True,
        "data": {
            "business_name": profile.business_name,
            "description": profile.description,
            "industry": profile.industry,
            "products": profile.products or [],
            "services": profile.services or [],
            "faqs": profile.faqs or [],
            "greeting_message": profile.greeting_message,
            "away_message": profile.away_message,
            "business_hours": profile.business_hours,
            "timezone": profile.timezone
        }
    }


@router.put("/business-profile")
async def update_business_profile(
    data: BusinessProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update the user's WhatsApp business profile."""
    check_connection_access(user, "whatsapp_business")
    
    result = await db.execute(
        select(WhatsAppBusinessProfile).filter(
            WhatsAppBusinessProfile.user_id == user.id
        )
    )
    profile = result.scalar_one_or_none()
    
    if not profile:
        profile = WhatsAppBusinessProfile(user_id=user.id)
        db.add(profile)
    
    # Update fields
    if data.business_name is not None:
        profile.business_name = data.business_name
    if data.description is not None:
        profile.description = data.description
    if data.industry is not None:
        profile.industry = data.industry
    if data.products is not None:
        profile.products = data.products
    if data.services is not None:
        profile.services = data.services
    if data.faqs is not None:
        profile.faqs = data.faqs
    if data.greeting_message is not None:
        profile.greeting_message = data.greeting_message
    if data.away_message is not None:
        profile.away_message = data.away_message
    if data.business_hours is not None:
        profile.business_hours = data.business_hours
    if data.timezone is not None:
        profile.timezone = data.timezone
    
    await db.commit()
    await db.refresh(profile)
    
    return {
        "success": True,
        "message": "Business profile updated"
    }


# ============================================================================
# Dashboard Stats API
# ============================================================================

@router.get("/stats")
async def get_whatsapp_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get WhatsApp statistics for dashboard."""
    check_connection_access(user, "whatsapp_business")
    
    # Total contacts
    result = await db.execute(
        select(func.count()).select_from(WhatsAppContact).filter(
            WhatsAppContact.user_id == user.id
        )
    )
    total_contacts = result.scalar()
    
    # Total messages (incoming + outgoing)
    result = await db.execute(
        select(func.count()).select_from(WhatsAppMessage).filter(
            WhatsAppMessage.user_id == user.id
        )
    )
    total_messages = result.scalar()
    
    # Messages today
    from datetime import date
    result = await db.execute(
        select(func.count()).select_from(WhatsAppMessage).filter(
            WhatsAppMessage.user_id == user.id,
            func.date(WhatsAppMessage.created_at) == date.today()
        )
    )
    messages_today = result.scalar()
    
    # Active auto-reply rules
    result = await db.execute(
        select(func.count()).select_from(WhatsAppAutoReply).filter(
            WhatsAppAutoReply.user_id == user.id,
            WhatsAppAutoReply.is_active == True
        )
    )
    active_rules = result.scalar()
    
    return {
        "success": True,
        "data": {
            "total_contacts": total_contacts,
            "total_messages": total_messages,
            "messages_today": messages_today,
            "active_auto_replies": active_rules
        }
    }


@router.get("/analytics")
async def get_whatsapp_analytics(
    days: int = Query(7, le=30, description="Number of days to analyze"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed WhatsApp analytics for the dashboard."""
    check_connection_access(user, "whatsapp_business")
    
    from datetime import date, timedelta
    from collections import Counter
    
    # Date range
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    
    # Messages per day (incoming vs outgoing)
    result = await db.execute(
        select(
            func.date(WhatsAppMessage.created_at).label("msg_date"),
            WhatsAppMessage.direction,
            func.count(WhatsAppMessage.id).label("count")
        ).filter(
            WhatsAppMessage.user_id == user.id,
            func.date(WhatsAppMessage.created_at) >= start_date
        ).group_by(
            func.date(WhatsAppMessage.created_at),
            WhatsAppMessage.direction
        ).order_by(func.date(WhatsAppMessage.created_at))
    )
    daily_messages = result.fetchall()
    
    # Format daily data
    message_trends = {}
    for row in daily_messages:
        day_str = str(row.msg_date)
        if day_str not in message_trends:
            message_trends[day_str] = {"incoming": 0, "outgoing": 0}
        message_trends[day_str][row.direction.value] = row.count
    
    # Total incoming vs outgoing
    result = await db.execute(
        select(
            WhatsAppMessage.direction,
            func.count(WhatsAppMessage.id).label("count")
        ).filter(
            WhatsAppMessage.user_id == user.id
        ).group_by(WhatsAppMessage.direction)
    )
    direction_counts = {row.direction.value: row.count for row in result.fetchall()}
    
    # Auto-reply stats
    result = await db.execute(
        select(func.sum(WhatsAppAutoReply.times_triggered)).filter(
            WhatsAppAutoReply.user_id == user.id
        )
    )
    total_auto_replies_sent = result.scalar() or 0
    
    # New contacts this period
    result = await db.execute(
        select(func.count(WhatsAppContact.id)).filter(
            WhatsAppContact.user_id == user.id,
            func.date(WhatsAppContact.created_at) >= start_date
        )
    )
    new_contacts = result.scalar() or 0
    
    # Response rate (outgoing / incoming ratio)
    incoming = direction_counts.get("incoming", 0)
    outgoing = direction_counts.get("outgoing", 0)
    response_rate = round((outgoing / incoming * 100) if incoming > 0 else 0, 1)
    
    # Busiest hours (when most messages are received)
    result = await db.execute(
        select(
            func.extract('hour', WhatsAppMessage.created_at).label("hour"),
            func.count(WhatsAppMessage.id).label("count")
        ).filter(
            WhatsAppMessage.user_id == user.id,
            WhatsAppMessage.direction == WhatsAppMessageDirection.INCOMING
        ).group_by(
            func.extract('hour', WhatsAppMessage.created_at)
        ).order_by(desc("count")).limit(5)
    )
    busiest_hours = [{"hour": int(row.hour), "count": row.count} for row in result.fetchall()]
    
    return {
        "success": True,
        "data": {
            "period_days": days,
            "message_trends": message_trends,
            "total_incoming": incoming,
            "total_outgoing": outgoing,
            "response_rate": response_rate,
            "auto_replies_sent": total_auto_replies_sent,
            "new_contacts": new_contacts,
            "busiest_hours": busiest_hours
        }
    }
