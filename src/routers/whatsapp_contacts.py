"""
WhatsApp Contacts & Messages API.
CRUD operations for contacts and conversation history.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, or_
from sqlalchemy.orm import selectinload
from typing import Optional, List, Dict
import uuid
from pydantic import BaseModel, Field
from datetime import datetime
from pathlib import Path
import aiofiles

from ..database import get_db
from ..models import (
    User, WhatsAppContact, WhatsAppMessage, WhatsAppMessageDirection,
    WhatsAppMessageStatus, WhatsAppAutoReply, WhatsAppBusinessProfile,
    WhatsAppQuickReply, Connection,
)
from ..services.whatsapp_contact_service import (
    ALLOWED_AVATAR_MIME,
    MAX_AVATAR_BYTES,
    avatar_storage_path,
    bulk_delete_contacts,
    contact_has_tag,
    delete_contact_and_related,
    resolve_avatar_full_path,
    _remove_avatar_file,
)
from ..services.file_management_service import file_management_service
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
    assigned_to_id: Optional[str] = None
    status: Optional[str] = None  # open, pending, resolved, closed
    is_starred: Optional[bool] = None

class ContactResponse(BaseModel):
    id: uuid.UUID
    phone_number: str
    name: Optional[str]
    profile_name: Optional[str]
    avatar_url: Optional[str] = None
    tags: Optional[List[str]]
    notes: Optional[str]
    assigned_to_id: Optional[uuid.UUID] = None
    status: Optional[str] = "open"
    is_starred: Optional[bool] = False
    message_count: int
    unread_count: int = 0
    first_message_at: Optional[datetime]
    last_message_at: Optional[datetime]
    last_message_preview: Optional[str] = None
    is_blocked: bool
    opted_out: bool = False
    snoozed_until: Optional[datetime] = None
    first_inbound_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class BulkDeleteRequest(BaseModel):
    contact_ids: List[uuid.UUID] = Field(..., min_length=1)


def _contact_to_response(
    contact: WhatsAppContact,
    last_message_preview: Optional[str] = None,
) -> ContactResponse:
    data = ContactResponse.model_validate(contact)
    updates: Dict[str, object] = {}
    if contact.avatar_url:
        updates["avatar_url"] = f"/api/whatsapp/contacts/{contact.id}/avatar"
    if last_message_preview is not None:
        updates["last_message_preview"] = last_message_preview
    if updates:
        return data.model_copy(update=updates)
    return data


async def _fetch_last_message_previews(
    db: AsyncSession,
    contact_ids: List[uuid.UUID],
) -> Dict[uuid.UUID, str]:
    """Latest non-empty message content per contact (batch, max 50)."""
    previews: Dict[uuid.UUID, str] = {}
    for cid in contact_ids:
        result = await db.execute(
            select(WhatsAppMessage.content)
            .where(
                WhatsAppMessage.contact_id == cid,
                WhatsAppMessage.content.isnot(None),
                WhatsAppMessage.content != "",
            )
            .order_by(desc(WhatsAppMessage.created_at))
            .limit(1)
        )
        content = result.scalar_one_or_none()
        if content:
            previews[cid] = content
    return previews

class MessageCreate(BaseModel):
    content: str
    message_type: str = "text"
    is_internal_note: bool = False

class MessageResponse(BaseModel):
    id: uuid.UUID
    direction: str
    message_type: str
    content: Optional[str]
    media_url: Optional[str]
    status: str
    is_auto_reply: bool
    is_agent: bool = False
    is_internal_note: bool = False
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
    status: Optional[str] = Query(None, description="Filter by status: open, pending, resolved, closed"),
    assigned_to: Optional[str] = Query(None, description="Filter by assigned agent ID"),
    is_starred: Optional[bool] = Query(None, description="Filter starred conversations"),
    has_unread: Optional[bool] = Query(None, description="Filter conversations with unread messages"),
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
    
    # Tag filter (JSON array column — cast to JSONB for @> containment)
    if tag:
        query = query.filter(contact_has_tag(WhatsAppContact.tags, tag))
    
    # Status filter
    if status:
        query = query.filter(WhatsAppContact.status == status)
    
    # Assigned agent filter
    if assigned_to:
        if assigned_to == "unassigned":
            query = query.filter(WhatsAppContact.assigned_to_id.is_(None))
        else:
            query = query.filter(WhatsAppContact.assigned_to_id == assigned_to)
    
    # Starred filter
    if is_starred is not None:
        query = query.filter(WhatsAppContact.is_starred == is_starred)
    
    # Unread filter
    if has_unread is not None:
        if has_unread:
            query = query.filter(WhatsAppContact.unread_count > 0)
        else:
            query = query.filter(WhatsAppContact.unread_count == 0)

    # Hide snoozed conversations until snooze expires
    now = datetime.utcnow()
    query = query.filter(
        or_(
            WhatsAppContact.snoozed_until.is_(None),
            WhatsAppContact.snoozed_until <= now,
        )
    )
    
    # Order: starred first, then by last message (most recent first)
    query = query.order_by(
        desc(WhatsAppContact.is_starred),
        desc(WhatsAppContact.last_message_at)
    )
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    result = await db.execute(count_query)
    total = result.scalar()
    
    # Apply pagination
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    contacts = result.scalars().all()

    previews = await _fetch_last_message_previews(db, [c.id for c in contacts])
    
    return {
        "success": True,
        "data": [
            _contact_to_response(c, previews.get(c.id))
            for c in contacts
        ],
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
        "data": _contact_to_response(contact),
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
        "data": _contact_to_response(contact),
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
    if data.assigned_to_id is not None:
        contact.assigned_to_id = uuid.UUID(data.assigned_to_id) if data.assigned_to_id else None
    if data.status is not None:
        if data.status not in ("open", "pending", "resolved", "closed"):
            raise HTTPException(status_code=400, detail="Invalid status. Must be: open, pending, resolved, closed")
        contact.status = data.status
    if data.is_starred is not None:
        contact.is_starred = data.is_starred
    
    await db.commit()
    await db.refresh(contact)
    
    return {
        "success": True,
        "data": _contact_to_response(contact),
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
    
    await delete_contact_and_related(db, contact)
    await db.commit()
    
    return {"success": True, "message": "Contact deleted"}


@router.post("/contacts/bulk-delete")
async def bulk_delete_contact_list(
    data: BulkDeleteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple contacts and their messages."""
    check_connection_access(user, "whatsapp_business")

    try:
        deleted, failed = await bulk_delete_contacts(
            db,
            user_id=user.id,
            contact_ids=data.contact_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await db.commit()

    return {
        "success": True,
        "deleted": deleted,
        "failed": failed,
    }


_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


@router.post("/contacts/{contact_id}/avatar")
async def upload_contact_avatar(
    contact_id: uuid.UUID,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a custom avatar image for a contact."""
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

    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_AVATAR_MIME:
        raise HTTPException(
            status_code=400,
            detail="Invalid image type. Use JPEG, PNG, WebP, or GIF.",
        )

    content = await file.read()
    if len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="Image must be 2MB or smaller.")

    ext = _MIME_EXT.get(content_type, ".jpg")
    storage_key = avatar_storage_path(user.id, contact_id, ext)
    full_path = resolve_avatar_full_path(file_management_service.upload_dir, storage_key)
    full_path.parent.mkdir(parents=True, exist_ok=True)

    if contact.avatar_url:
        _remove_avatar_file(contact.avatar_url)

    async with aiofiles.open(full_path, "wb") as f:
        await f.write(content)

    contact.avatar_url = str(full_path)
    await db.commit()
    await db.refresh(contact)

    return {
        "success": True,
        "data": _contact_to_response(contact),
    }


@router.get("/contacts/{contact_id}/avatar")
async def get_contact_avatar(
    contact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve the contact's custom avatar image."""
    check_connection_access(user, "whatsapp_business")

    result = await db.execute(
        select(WhatsAppContact).filter(
            WhatsAppContact.id == contact_id,
            WhatsAppContact.user_id == user.id,
        )
    )
    contact = result.scalar_one_or_none()
    if not contact or not contact.avatar_url:
        raise HTTPException(status_code=404, detail="Avatar not found")

    path = Path(contact.avatar_url)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Avatar file missing")

    media_type = "image/jpeg"
    suffix = path.suffix.lower()
    if suffix == ".png":
        media_type = "image/png"
    elif suffix == ".webp":
        media_type = "image/webp"
    elif suffix == ".gif":
        media_type = "image/gif"

    return FileResponse(path, media_type=media_type)


@router.delete("/contacts/{contact_id}/avatar")
async def delete_contact_avatar(
    contact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove custom avatar and revert to initials."""
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

    if contact.avatar_url:
        _remove_avatar_file(contact.avatar_url)
        contact.avatar_url = None
        await db.commit()
        await db.refresh(contact)

    return {
        "success": True,
        "data": _contact_to_response(contact),
    }


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

    from ..services.whatsapp_inbox_service import (
        merge_ccm_assistant_messages,
        merge_message_rows_for_api,
    )

    ccm_synthetics = await merge_ccm_assistant_messages(
        db,
        user_id=user.id,
        contact=contact,
        persisted_messages=messages,
    )
    merged = merge_message_rows_for_api(messages, ccm_synthetics)
    
    return {
        "success": True,
        "data": [MessageResponse.model_validate(m) for m in merged],
        "contact": _contact_to_response(contact)
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
    
    # Internal notes: store locally without sending to WhatsApp
    if data.is_internal_note:
        message = WhatsAppMessage(
            user_id=user.id,
            contact_id=contact.id,
            direction=WhatsAppMessageDirection.OUTGOING,
            message_type="text",
            content=data.content,
            status=WhatsAppMessageStatus.SENT,
            is_internal_note=True
        )
        db.add(message)
        contact.last_message_at = datetime.utcnow()
        contact.message_count = (contact.message_count or 0) + 1
        await db.commit()
        await db.refresh(message)
        return {
            "success": True,
            "data": MessageResponse.model_validate(message)
        }
    
    # Get user's WhatsApp connection config
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
        status=WhatsAppMessageStatus.SENT,
        is_agent=False,
    )
    db.add(message)
    
    # Update contact
    contact.last_message_at = datetime.utcnow()
    contact.message_count = (contact.message_count or 0) + 1
    contact.first_inbound_at = None
    
    await db.commit()
    await db.refresh(message)

    try:
        from ..services.whatsapp_inbox_events import emit_to_org_members
        payload = {
            "contact_id": str(contact.id),
            "message_id": str(message.id),
            "direction": "outgoing",
        }
        await emit_to_org_members(user.id, "whatsapp_new_message", payload, db=db)
        await emit_to_org_members(
            user.id,
            "whatsapp_contact_updated",
            {"contact_id": str(contact.id)},
            db=db,
        )
    except Exception:
        pass

    return {
        "success": True,
        "data": MessageResponse.model_validate(message)
    }


@router.post("/contacts/{contact_id}/messages/template")
async def send_template_message_to_contact(
    contact_id: uuid.UUID,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send an approved WhatsApp template (outside 24h window)."""
    check_connection_access(user, "whatsapp_business")
    template_name = body.get("template_name")
    language_code = body.get("language_code", "en")
    components = body.get("components")
    if not template_name:
        raise HTTPException(status_code=400, detail="template_name is required")

    result = await db.execute(
        select(WhatsAppContact).filter(
            WhatsAppContact.id == contact_id,
            WhatsAppContact.user_id == user.id,
        )
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    conn_result = await db.execute(
        select(Connection).filter(
            Connection.user_id == user.id,
            Connection.platform == "whatsapp",
            Connection.status == "active",
        )
    )
    connection = conn_result.scalar_one_or_none()
    if not connection:
        raise HTTPException(status_code=400, detail="WhatsApp not connected")

    send_result = await whatsapp_service.send_template_message(
        to_number=contact.phone_number,
        template_name=template_name,
        language_code=language_code,
        components=components,
        config=connection.config or {},
    )
    if not send_result.get("success"):
        raise HTTPException(status_code=500, detail=send_result.get("error", "Template send failed"))

    message = WhatsAppMessage(
        user_id=user.id,
        contact_id=contact.id,
        direction=WhatsAppMessageDirection.OUTGOING,
        message_type="template",
        content=f"[Template: {template_name}]",
        whatsapp_message_id=send_result.get("message_id"),
        status=WhatsAppMessageStatus.SENT,
    )
    db.add(message)
    contact.last_message_at = datetime.utcnow()
    contact.message_count = (contact.message_count or 0) + 1
    await db.commit()
    await db.refresh(message)
    return {"success": True, "data": MessageResponse.model_validate(message)}


@router.post("/contacts/{contact_id}/media-upload")
async def upload_and_send_chat_media(
    contact_id: uuid.UUID,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload file to Meta and send as WhatsApp media message."""
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

    conn_result = await db.execute(
        select(Connection).filter(
            Connection.user_id == user.id,
            Connection.platform == "whatsapp",
            Connection.status == "active",
        )
    )
    connection = conn_result.scalar_one_or_none()
    if not connection:
        raise HTTPException(status_code=400, detail="WhatsApp not connected")

    content = await file.read()
    mime = (file.content_type or "application/octet-stream").lower()
    filename = file.filename or "file"
    config = connection.config or {}
    msg_type = "image" if mime.startswith("image/") else "document"

    send_result = await whatsapp_service.upload_and_send_document(
        contact.phone_number,
        content,
        filename,
        mime_type=mime,
        caption=caption,
        config=config,
    )
    if not send_result.get("success"):
        raise HTTPException(status_code=500, detail=send_result.get("error", "Send failed"))

    message = WhatsAppMessage(
        user_id=user.id,
        contact_id=contact.id,
        direction=WhatsAppMessageDirection.OUTGOING,
        message_type=msg_type,
        content=caption or filename,
        status=WhatsAppMessageStatus.SENT,
        whatsapp_message_id=send_result.get("message_id"),
    )
    db.add(message)
    contact.last_message_at = datetime.utcnow()
    contact.message_count = (contact.message_count or 0) + 1
    await db.commit()
    await db.refresh(message)
    return {"success": True, "data": MessageResponse.model_validate(message)}


@router.post("/contacts/{contact_id}/media")
async def send_media_message(
    contact_id: uuid.UUID,
    media_url: str = Query(...),
    media_type: str = Query(...),
    caption: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Send a media message to a contact."""
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
    if contact.is_blocked:
        raise HTTPException(status_code=400, detail="Cannot send message to blocked contact")
        
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
        
    config = connection.config or {}
    send_result = await whatsapp_service.send_media_message(
        to_number=contact.phone_number,
        media_url=media_url,
        media_type=media_type,
        caption=caption,
        config=config
    )
    
    if not send_result.get("success"):
        raise HTTPException(status_code=500, detail=send_result.get("error", "Failed to send media"))
        
    message = WhatsAppMessage(
        user_id=user.id,
        contact_id=contact.id,
        direction=WhatsAppMessageDirection.OUTGOING,
        message_type=media_type,
        content=caption or "",
        media_url=media_url,
        whatsapp_message_id=send_result.get("message_id"),
        status=WhatsAppMessageStatus.SENT
    )
    db.add(message)
    
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


class SnoozeRequest(BaseModel):
    until: datetime


@router.post("/contacts/{contact_id}/snooze")
async def snooze_contact(
    contact_id: uuid.UUID,
    data: SnoozeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Snooze a conversation until a given time."""
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
    contact.snoozed_until = data.until
    await db.commit()
    await db.refresh(contact)
    return {"success": True, "data": _contact_to_response(contact)}


@router.delete("/contacts/{contact_id}/snooze")
async def unsnooze_contact(
    contact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
    contact.snoozed_until = None
    await db.commit()
    await db.refresh(contact)
    return {"success": True, "data": _contact_to_response(contact)}


@router.get("/contacts/{contact_id}/commerce-context")
async def get_commerce_context(
    contact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cart, order, and payment context for inbox sidebar."""
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

    from ..services.whatsapp_commerce_context import get_contact_commerce_context

    ctx = await get_contact_commerce_context(db, user_id=user.id, contact=contact)
    return {"success": True, "data": ctx}


class InboxSettingsUpdate(BaseModel):
    round_robin_enabled: Optional[bool] = None
    round_robin_agent_ids: Optional[List[str]] = None
    sla_first_response_minutes: Optional[int] = None


@router.get("/inbox-settings")
async def get_whatsapp_inbox_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    check_connection_access(user, "whatsapp_business")
    from ..services.whatsapp_inbox_settings import get_inbox_settings

    return {"success": True, "data": await get_inbox_settings(db, user.id)}


@router.put("/inbox-settings")
async def update_whatsapp_inbox_settings(
    data: InboxSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    check_connection_access(user, "whatsapp_business")
    from ..services.whatsapp_inbox_settings import get_inbox_settings, merge_inbox_settings

    result = await db.execute(
        select(WhatsAppBusinessProfile).where(WhatsAppBusinessProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        profile = WhatsAppBusinessProfile(user_id=user.id)
        db.add(profile)

    current = merge_inbox_settings(profile.inbox_settings)
    if data.round_robin_enabled is not None:
        current["round_robin_enabled"] = data.round_robin_enabled
    if data.round_robin_agent_ids is not None:
        current["round_robin_agent_ids"] = data.round_robin_agent_ids
    if data.sla_first_response_minutes is not None:
        current["sla_first_response_minutes"] = data.sla_first_response_minutes
    profile.inbox_settings = current
    await db.commit()
    return {"success": True, "data": current}


@router.get("/contacts/export")
async def export_contacts_csv(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export contacts as CSV."""
    check_connection_access(user, "whatsapp_business")
    import csv
    import io
    from fastapi.responses import StreamingResponse

    result = await db.execute(
        select(WhatsAppContact).where(WhatsAppContact.user_id == user.id)
    )
    contacts = result.scalars().all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["phone_number", "name", "profile_name", "tags", "status", "notes"])
    for c in contacts:
        writer.writerow([
            c.phone_number,
            c.name or "",
            c.profile_name or "",
            ",".join(c.tags or []),
            c.status or "open",
            (c.notes or "").replace("\n", " "),
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=whatsapp-contacts.csv"},
    )


@router.post("/contacts/import")
async def import_contacts_csv(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Import contacts from CSV (phone_number, name, tags)."""
    check_connection_access(user, "whatsapp_business")
    import csv
    import io

    content = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    created = 0
    skipped = 0
    for row in reader:
        phone = (row.get("phone_number") or row.get("phone") or "").strip().replace("+", "").replace(" ", "")
        if not phone:
            skipped += 1
            continue
        existing = await db.execute(
            select(WhatsAppContact).where(
                WhatsAppContact.user_id == user.id,
                WhatsAppContact.phone_number == phone,
            )
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue
        tags_raw = row.get("tags") or ""
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        contact = WhatsAppContact(
            user_id=user.id,
            phone_number=phone,
            name=row.get("name") or None,
            tags=tags,
            notes=row.get("notes") or None,
            message_count=0,
        )
        db.add(contact)
        created += 1
    await db.commit()
    return {"success": True, "created": created, "skipped": skipped}


class OrderStatusUpdate(BaseModel):
    """Update order status and notify the customer on WhatsApp."""

    status: str = Field(..., description="New order status (confirmed, preparing, shipped, etc.)")
    customer_phone: Optional[str] = Field(
        None,
        description="Customer WhatsApp number; uses tracking registry if omitted",
    )
    notes: Optional[str] = Field(None, description="Optional note included in the customer alert")
    business_name: Optional[str] = None
    currency: Optional[str] = "KES"
    notify_customer: bool = True


@router.post("/orders/{order_id}/status")
async def update_order_status_and_notify(
    order_id: str,
    body: OrderStatusUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Push an order status update to the customer via WhatsApp (shipping alerts, etc.).

    Orders are registered in Redis when placed through the conversational ordering agent.
    """
    check_connection_access(user, "whatsapp_business")

    if not getattr(settings, "ORDER_TRACKING_ENABLED", True):
        raise HTTPException(
            status_code=503,
            detail="Order tracking notifications are disabled",
        )

    from ..services.order_service import ORDER_STATUSES
    from ..services.order_tracking_service import order_tracking_service

    new_status = (body.status or "").lower().replace(" ", "_")
    if new_status not in ORDER_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Allowed: {', '.join(ORDER_STATUSES)}",
        )

    registry = order_tracking_service.get_registered_order(str(user.id), order_id)
    if not registry and not body.customer_phone:
        raise HTTPException(
            status_code=404,
            detail="Order not found in tracking registry. Provide customer_phone.",
        )

    result: dict = {"success": True, "order_id": order_id, "status": new_status}

    if body.notify_customer:
        notify_result = await order_tracking_service.notify_status_change(
            user=user,
            db=db,
            order_id=order_id,
            new_status=new_status,
            customer_phone=body.customer_phone or "",
            business_name=body.business_name or "",
            currency=body.currency or "KES",
            notes=body.notes or "",
            previous_status=(registry or {}).get("status", ""),
        )
        result["notification"] = notify_result
        if not notify_result.get("success") and not notify_result.get("skipped"):
            raise HTTPException(
                status_code=502,
                detail=notify_result.get("error", "Failed to notify customer"),
            )
    else:
        if registry:
            registry["status"] = new_status
            from ..services.cache_service import cache_service

            cache_service.set(
                order_tracking_service._tracking_key(str(user.id), order_id),
                registry,
                expire_seconds=60 * 60 * 24 * 45,
            )

    return result


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
    def _dir_key(d) -> str:
        return d.value if hasattr(d, "value") else str(d)

    message_trends = {}
    for row in daily_messages:
        day_str = str(row.msg_date)
        if day_str not in message_trends:
            message_trends[day_str] = {"incoming": 0, "outgoing": 0}
        message_trends[day_str][_dir_key(row.direction)] = row.count
    
    # Total incoming vs outgoing
    result = await db.execute(
        select(
            WhatsAppMessage.direction,
            func.count(WhatsAppMessage.id).label("count")
        ).filter(
            WhatsAppMessage.user_id == user.id
        ).group_by(WhatsAppMessage.direction)
    )
    direction_counts = {_dir_key(row.direction): row.count for row in result.fetchall()}
    
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


# ============================================================================
# Conversation Lifecycle
# ============================================================================

@router.patch("/contacts/{contact_id}/read")
async def mark_conversation_read(
    contact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Mark all unread messages in a conversation as read and reset unread count."""
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
    
    # Reset unread count
    contact.unread_count = 0
    await db.commit()
    
    return {"success": True, "message": "Conversation marked as read"}


# ============================================================================
# Quick Replies API
# ============================================================================

class QuickReplyCreate(BaseModel):
    title: str
    shortcut: str
    content: str
    category: Optional[str] = None

class QuickReplyResponse(BaseModel):
    id: uuid.UUID
    title: str
    shortcut: str
    content: str
    category: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/quick-replies")
async def list_quick_replies(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all quick reply templates."""
    check_connection_access(user, "whatsapp_business")
    
    result = await db.execute(
        select(WhatsAppQuickReply).filter(
            WhatsAppQuickReply.user_id == user.id
        ).order_by(WhatsAppQuickReply.title)
    )
    replies = result.scalars().all()
    
    return {
        "success": True,
        "data": [QuickReplyResponse.model_validate(r) for r in replies]
    }


@router.post("/quick-replies")
async def create_quick_reply(
    data: QuickReplyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new quick reply template."""
    check_connection_access(user, "whatsapp_business")
    
    # Ensure shortcut starts with /
    shortcut = data.shortcut if data.shortcut.startswith("/") else f"/{data.shortcut}"
    
    # Check for duplicate shortcut
    result = await db.execute(
        select(WhatsAppQuickReply).filter(
            WhatsAppQuickReply.user_id == user.id,
            WhatsAppQuickReply.shortcut == shortcut
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Shortcut '{shortcut}' already exists")
    
    reply = WhatsAppQuickReply(
        user_id=user.id,
        title=data.title,
        shortcut=shortcut,
        content=data.content,
        category=data.category
    )
    db.add(reply)
    await db.commit()
    await db.refresh(reply)
    
    return {
        "success": True,
        "data": QuickReplyResponse.model_validate(reply)
    }


@router.put("/quick-replies/{reply_id}")
async def update_quick_reply(
    reply_id: uuid.UUID,
    data: QuickReplyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a quick reply template."""
    check_connection_access(user, "whatsapp_business")
    
    result = await db.execute(
        select(WhatsAppQuickReply).filter(
            WhatsAppQuickReply.id == reply_id,
            WhatsAppQuickReply.user_id == user.id
        )
    )
    reply = result.scalar_one_or_none()
    
    if not reply:
        raise HTTPException(status_code=404, detail="Quick reply not found")
    
    shortcut = data.shortcut if data.shortcut.startswith("/") else f"/{data.shortcut}"
    reply.title = data.title
    reply.shortcut = shortcut
    reply.content = data.content
    reply.category = data.category
    
    await db.commit()
    await db.refresh(reply)
    
    return {
        "success": True,
        "data": QuickReplyResponse.model_validate(reply)
    }


@router.delete("/quick-replies/{reply_id}")
async def delete_quick_reply(
    reply_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a quick reply template."""
    check_connection_access(user, "whatsapp_business")
    
    result = await db.execute(
        select(WhatsAppQuickReply).filter(
            WhatsAppQuickReply.id == reply_id,
            WhatsAppQuickReply.user_id == user.id
        )
    )
    reply = result.scalar_one_or_none()
    
    if not reply:
        raise HTTPException(status_code=404, detail="Quick reply not found")
    
    await db.delete(reply)
    await db.commit()
    
    return {"success": True, "message": "Quick reply deleted"}


# ============================================================================
# Team Members API
# ============================================================================

@router.get("/team-members")
async def get_team_members(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get team members for agent assignment (from organization membership)."""
    from ..models import OrganizationMember, Organization

    # Find organizations the user belongs to
    result = await db.execute(
        select(OrganizationMember).filter(
            OrganizationMember.user_id == user.id
        )
    )
    memberships = result.scalars().all()
    
    members = []
    if memberships:
        # Get all members from the user's organizations
        org_ids = [m.org_id for m in memberships]
        result = await db.execute(
            select(OrganizationMember, User).join(
                User, OrganizationMember.user_id == User.id
            ).filter(
                OrganizationMember.org_id.in_(org_ids)
            )
        )
        for member, member_user in result.fetchall():
            members.append({
                "id": str(member_user.id),
                "name": member_user.name,
                "email": member_user.email,
                "role": member.role
            })
    else:
        # Solo user — just return themselves
        members.append({
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": "owner"
        })
    
    return {"success": True, "data": members}
