"""
WhatsApp Broadcast & Template API endpoints.
Handles bulk messaging campaigns and template management.
"""

import logging
from datetime import datetime
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import (
    User, WhatsAppContact, WhatsAppBroadcast, WhatsAppBroadcastRecipient,
    WhatsAppTemplate, WhatsAppBroadcastStatus
)
from ..routers.auth_router import get_current_user
from ..services.whatsapp_service import WhatsAppService
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp-broadcast"])


# ============== Pydantic Schemas ==============

class TemplateResponse(BaseModel):
    id: uuid.UUID
    template_id: str
    name: str
    language: str
    category: Optional[str]
    status: Optional[str]
    components: Optional[dict]
    times_used: int
    created_at: datetime

    class Config:
        from_attributes = True


class BroadcastCreate(BaseModel):
    name: str
    description: Optional[str] = None
    message_type: str = "template"  # template or text
    template_id: Optional[uuid.UUID] = None
    template_variables: Optional[dict] = None
    text_content: Optional[str] = None
    target_type: str = "all"  # all, tag, selected
    target_tag: Optional[str] = None
    target_contact_ids: Optional[List[int]] = None
    scheduled_at: Optional[datetime] = None


class BroadcastResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    message_type: str
    template_id: Optional[uuid.UUID]
    target_type: str
    target_tag: Optional[str]
    status: str
    scheduled_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    total_recipients: int
    sent_count: int
    delivered_count: int
    read_count: int
    failed_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class BroadcastDetailResponse(BroadcastResponse):
    text_content: Optional[str]
    template_variables: Optional[dict]
    target_contact_ids: Optional[List[int]]


# ============== Template Endpoints ==============

@router.get("/templates", response_model=dict)
async def list_templates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all cached templates for the user."""
    result = await db.execute(
        select(WhatsAppTemplate)
        .where(WhatsAppTemplate.user_id == current_user.id)
        .order_by(WhatsAppTemplate.name)
    )
    templates = result.scalars().all()
    
    return {
        "success": True,
        "data": [TemplateResponse.model_validate(t).model_dump() for t in templates]
    }


@router.post("/templates/sync", response_model=dict)
async def sync_templates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Sync templates from Meta WhatsApp API."""
    try:
        # Get WhatsApp service
        wa_service = WhatsAppService(
            access_token=settings.WHATSAPP_TOKEN,
            phone_number_id=settings.WHATSAPP_PHONE_NUMBER_ID
        )
        
        # Fetch templates from Meta
        templates_data = await wa_service.list_templates()
        
        synced_count = 0
        for tmpl in templates_data.get("data", []):
            # Check if template exists
            existing = await db.execute(
                select(WhatsAppTemplate).where(
                    and_(
                        WhatsAppTemplate.user_id == current_user.id,
                        WhatsAppTemplate.template_id == tmpl["id"]
                    )
                )
            )
            template = existing.scalar_one_or_none()
            
            if template:
                # Update existing
                template.name = tmpl["name"]
                template.language = tmpl.get("language", "en")
                template.category = tmpl.get("category")
                template.status = tmpl.get("status")
                template.components = tmpl.get("components")
                template.synced_at = datetime.utcnow()
            else:
                # Create new
                template = WhatsAppTemplate(
                    user_id=current_user.id,
                    template_id=tmpl["id"],
                    name=tmpl["name"],
                    language=tmpl.get("language", "en"),
                    category=tmpl.get("category"),
                    status=tmpl.get("status"),
                    components=tmpl.get("components"),
                    synced_at=datetime.utcnow()
                )
                db.add(template)
            
            synced_count += 1
        
        await db.commit()
        
        return {
            "success": True,
            "message": f"Synced {synced_count} templates from Meta",
            "synced_count": synced_count
        }
        
    except Exception as e:
        logger.error(f"Error syncing templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============== Broadcast Endpoints ==============

@router.get("/broadcasts", response_model=dict)
async def list_broadcasts(
    status: Optional[str] = None,
    limit: int = Query(default=20, le=100),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all broadcast campaigns for the user."""
    query = select(WhatsAppBroadcast).where(
        WhatsAppBroadcast.user_id == current_user.id
    )
    
    if status:
        query = query.where(WhatsAppBroadcast.status == status)
    
    query = query.order_by(WhatsAppBroadcast.created_at.desc()).offset(offset).limit(limit)
    
    result = await db.execute(query)
    broadcasts = result.scalars().all()
    
    # Get total count
    count_query = select(func.count(WhatsAppBroadcast.id)).where(
        WhatsAppBroadcast.user_id == current_user.id
    )
    if status:
        count_query = count_query.where(WhatsAppBroadcast.status == status)
    total = (await db.execute(count_query)).scalar() or 0
    
    return {
        "success": True,
        "data": [BroadcastResponse.model_validate(b).model_dump() for b in broadcasts],
        "total": total
    }


@router.post("/broadcasts", response_model=dict)
async def create_broadcast(
    data: BroadcastCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new broadcast campaign."""
    # Validate template if using template message
    if data.message_type == "template" and data.template_id:
        template = await db.get(WhatsAppTemplate, data.template_id)
        if not template or template.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Template not found")
    
    # Create broadcast
    broadcast = WhatsAppBroadcast(
        user_id=current_user.id,
        name=data.name,
        description=data.description,
        message_type=data.message_type,
        template_id=data.template_id,
        template_variables=data.template_variables,
        text_content=data.text_content,
        target_type=data.target_type,
        target_tag=data.target_tag,
        target_contact_ids=data.target_contact_ids,
        status=WhatsAppBroadcastStatus.SCHEDULED if data.scheduled_at else WhatsAppBroadcastStatus.DRAFT,
        scheduled_at=data.scheduled_at
    )
    
    db.add(broadcast)
    await db.commit()
    await db.refresh(broadcast)
    
    # Count potential recipients
    recipient_count = await _count_broadcast_recipients(db, current_user.id, data)
    broadcast.total_recipients = recipient_count
    await db.commit()
    
    logger.info(f"[BROADCAST] Created campaign '{data.name}' targeting {recipient_count} recipients")
    
    return {
        "success": True,
        "data": BroadcastResponse.model_validate(broadcast).model_dump()
    }


@router.get("/broadcasts/{broadcast_id}", response_model=dict)
async def get_broadcast(
    broadcast_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get broadcast campaign details."""
    broadcast = await db.get(WhatsAppBroadcast, broadcast_id)
    
    if not broadcast or broadcast.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    
    return {
        "success": True,
        "data": BroadcastDetailResponse.model_validate(broadcast).model_dump()
    }


@router.post("/broadcasts/{broadcast_id}/send", response_model=dict)
async def send_broadcast(
    broadcast_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Start sending a broadcast campaign."""
    broadcast = await db.get(WhatsAppBroadcast, broadcast_id)
    
    if not broadcast or broadcast.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    
    if broadcast.status not in [WhatsAppBroadcastStatus.DRAFT, WhatsAppBroadcastStatus.SCHEDULED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot send broadcast with status '{broadcast.status}'"
        )
    
    # Update status
    broadcast.status = WhatsAppBroadcastStatus.SENDING
    broadcast.started_at = datetime.utcnow()
    await db.commit()
    
    # Add recipients and start sending in background
    background_tasks.add_task(
        _execute_broadcast,
        broadcast_id,
        current_user.id
    )
    
    return {
        "success": True,
        "message": "Broadcast sending started",
        "data": BroadcastResponse.model_validate(broadcast).model_dump()
    }


@router.post("/broadcasts/{broadcast_id}/cancel", response_model=dict)
async def cancel_broadcast(
    broadcast_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cancel a sending or scheduled broadcast."""
    broadcast = await db.get(WhatsAppBroadcast, broadcast_id)
    
    if not broadcast or broadcast.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    
    if broadcast.status not in [WhatsAppBroadcastStatus.SCHEDULED, WhatsAppBroadcastStatus.SENDING]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel broadcast with status '{broadcast.status}'"
        )
    
    broadcast.status = WhatsAppBroadcastStatus.CANCELLED
    await db.commit()
    
    return {
        "success": True,
        "message": "Broadcast cancelled",
        "data": BroadcastResponse.model_validate(broadcast).model_dump()
    }


@router.delete("/broadcasts/{broadcast_id}", response_model=dict)
async def delete_broadcast(
    broadcast_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a broadcast campaign (draft only)."""
    broadcast = await db.get(WhatsAppBroadcast, broadcast_id)
    
    if not broadcast or broadcast.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    
    if broadcast.status != WhatsAppBroadcastStatus.DRAFT:
        raise HTTPException(
            status_code=400,
            detail="Can only delete draft broadcasts"
        )
    
    await db.delete(broadcast)
    await db.commit()
    
    return {"success": True, "message": "Broadcast deleted"}


@router.get("/broadcasts/{broadcast_id}/recipients", response_model=dict)
async def get_broadcast_recipients(
    broadcast_id: uuid.UUID,
    status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get recipient status for a broadcast."""
    broadcast = await db.get(WhatsAppBroadcast, broadcast_id)
    
    if not broadcast or broadcast.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    
    query = select(WhatsAppBroadcastRecipient).where(
        WhatsAppBroadcastRecipient.broadcast_id == broadcast_id
    ).options(selectinload(WhatsAppBroadcastRecipient.contact))
    
    if status:
        query = query.where(WhatsAppBroadcastRecipient.status == status)
    
    query = query.offset(offset).limit(limit)
    
    result = await db.execute(query)
    recipients = result.scalars().all()
    
    return {
        "success": True,
        "data": [
            {
                "id": r.id,
                "contact_id": r.contact_id,
                "contact_name": r.contact.name or r.contact.profile_name or r.contact.phone_number,
                "phone_number": r.contact.phone_number,
                "status": r.status,
                "sent_at": r.sent_at,
                "delivered_at": r.delivered_at,
                "read_at": r.read_at,
                "error_message": r.error_message
            }
            for r in recipients
        ]
    }


# ============== Helper Functions ==============

async def _count_broadcast_recipients(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: BroadcastCreate
) -> int:
    """Count potential recipients for a broadcast."""
    query = select(func.count(WhatsAppContact.id)).where(
        and_(
            WhatsAppContact.user_id == user_id,
            WhatsAppContact.is_blocked == False
        )
    )
    
    if data.target_type == "tag" and data.target_tag:
        query = query.where(WhatsAppContact.tags.contains([data.target_tag]))
    elif data.target_type == "selected" and data.target_contact_ids:
        query = query.where(WhatsAppContact.id.in_(data.target_contact_ids))
    
    result = await db.execute(query)
    return result.scalar() or 0


async def _execute_broadcast(broadcast_id: uuid.UUID, user_id: uuid.UUID):
    """Background task to execute broadcast sending."""
    from ..database import get_session_maker
    
    session_maker = get_session_maker()
    async with session_maker() as db:
        try:
            broadcast = await db.get(WhatsAppBroadcast, broadcast_id)
            if not broadcast:
                return
            
            # Get recipients based on targeting
            query = select(WhatsAppContact).where(
                and_(
                    WhatsAppContact.user_id == user_id,
                    WhatsAppContact.is_blocked == False
                )
            )
            
            if broadcast.target_type == "tag" and broadcast.target_tag:
                query = query.where(WhatsAppContact.tags.contains([broadcast.target_tag]))
            elif broadcast.target_type == "selected" and broadcast.target_contact_ids:
                query = query.where(WhatsAppContact.id.in_(broadcast.target_contact_ids))
            
            result = await db.execute(query)
            contacts = result.scalars().all()
            
            # Create recipient records
            for contact in contacts:
                recipient = WhatsAppBroadcastRecipient(
                    broadcast_id=broadcast_id,
                    contact_id=contact.id,
                    status="pending"
                )
                db.add(recipient)
            
            await db.commit()
            
            # Initialize WhatsApp service
            wa_service = WhatsAppService(
                access_token=settings.WHATSAPP_TOKEN,
                phone_number_id=settings.WHATSAPP_PHONE_NUMBER_ID
            )
            
            # Send to each recipient
            sent = 0
            failed = 0
            
            for contact in contacts:
                try:
                    if broadcast.message_type == "template" and broadcast.template_id:
                        # Get template
                        template = await db.get(WhatsAppTemplate, broadcast.template_id)
                        if template:
                            response = await wa_service.send_template_message(
                                to=contact.phone_number,
                                template_name=template.name,
                                language_code=template.language,
                                components=broadcast.template_variables
                            )
                    else:
                        response = await wa_service.send_text_message(
                            to=contact.phone_number,
                            text=broadcast.text_content or ""
                        )
                    
                    # Update recipient status
                    recipient_result = await db.execute(
                        select(WhatsAppBroadcastRecipient).where(
                            and_(
                                WhatsAppBroadcastRecipient.broadcast_id == broadcast_id,
                                WhatsAppBroadcastRecipient.contact_id == contact.id
                            )
                        )
                    )
                    recipient = recipient_result.scalar_one_or_none()
                    if recipient:
                        recipient.status = "sent"
                        recipient.sent_at = datetime.utcnow()
                        recipient.whatsapp_message_id = response.get("messages", [{}])[0].get("id")
                    
                    sent += 1
                    
                except Exception as e:
                    logger.error(f"Failed to send to {contact.phone_number}: {e}")
                    recipient_result = await db.execute(
                        select(WhatsAppBroadcastRecipient).where(
                            and_(
                                WhatsAppBroadcastRecipient.broadcast_id == broadcast_id,
                                WhatsAppBroadcastRecipient.contact_id == contact.id
                            )
                        )
                    )
                    recipient = recipient_result.scalar_one_or_none()
                    if recipient:
                        recipient.status = "failed"
                        recipient.error_message = str(e)
                    
                    failed += 1
                
                await db.commit()
            
            # Update broadcast status
            broadcast.sent_count = sent
            broadcast.failed_count = failed
            broadcast.status = WhatsAppBroadcastStatus.COMPLETED
            broadcast.completed_at = datetime.utcnow()
            await db.commit()
            
            logger.info(f"[BROADCAST] Completed '{broadcast.name}': {sent} sent, {failed} failed")
            
        except Exception as e:
            logger.error(f"Error executing broadcast {broadcast_id}: {e}")
            if broadcast:
                broadcast.status = WhatsAppBroadcastStatus.FAILED
                await db.commit()
