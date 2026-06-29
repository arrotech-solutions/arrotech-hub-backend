"""
WhatsApp Broadcast & Template API endpoints.
Handles bulk messaging campaigns and template management.
"""

import logging
from datetime import datetime
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
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
from ..services.whatsapp_config_helper import get_whatsapp_config_for_user
from ..services.llm_service import llm_service
from ..services.tier_gate import check_broadcast_access
from ..tasks.broadcast_tasks import execute_broadcast_campaign_task

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
    target_contact_ids: Optional[List[uuid.UUID]] = None
    scheduled_at: Optional[datetime] = None
    send_rate: Optional[int] = 10


class GenerateCopyRequest(BaseModel):
    campaign_goal: str
    audience_description: Optional[str] = None
    tone: Optional[str] = "professional"


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
    target_contact_ids: Optional[List[uuid.UUID]]


def _parse_meta_templates(templates_data: dict) -> List[dict]:
    """Extract template list from WhatsAppService.list_templates response."""
    if not templates_data.get("success"):
        return []
    payload = templates_data.get("data") or {}
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("data") or []
    return []


def _template_language_code(tmpl: dict) -> str:
    lang = tmpl.get("language")
    if isinstance(lang, dict):
        return lang.get("code") or "en_US"
    return lang or "en_US"


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
    check_broadcast_access(current_user)
    try:
        wa_config = await get_whatsapp_config_for_user(db, current_user)
        wa_service = WhatsAppService()
        templates_data = await wa_service.list_templates(config=wa_config)
        if not templates_data.get("success"):
            raise HTTPException(
                status_code=400,
                detail=templates_data.get("error", "Failed to fetch templates from Meta"),
            )

        synced_count = 0
        for tmpl in _parse_meta_templates(templates_data):
            template_id = str(tmpl.get("id") or tmpl.get("name", ""))
            if not template_id:
                continue
            existing = await db.execute(
                select(WhatsAppTemplate).where(
                    and_(
                        WhatsAppTemplate.user_id == current_user.id,
                        WhatsAppTemplate.template_id == template_id,
                    )
                )
            )
            template = existing.scalar_one_or_none()
            lang = _template_language_code(tmpl)

            if template:
                template.name = tmpl.get("name", template.name)
                template.language = lang
                template.category = tmpl.get("category")
                template.status = tmpl.get("status")
                template.components = tmpl.get("components")
                template.synced_at = datetime.utcnow()
            else:
                template = WhatsAppTemplate(
                    user_id=current_user.id,
                    template_id=template_id,
                    name=tmpl.get("name", template_id),
                    language=lang,
                    category=tmpl.get("category"),
                    status=tmpl.get("status"),
                    components=tmpl.get("components"),
                    synced_at=datetime.utcnow(),
                )
                db.add(template)

            synced_count += 1

        await db.commit()

        return {
            "success": True,
            "message": f"Synced {synced_count} templates from Meta",
            "synced_count": synced_count,
        }

    except HTTPException:
        raise
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
    check_broadcast_access(current_user)
    await get_whatsapp_config_for_user(db, current_user)

    if data.message_type == "template":
        if not data.template_id:
            raise HTTPException(status_code=400, detail="template_id is required for template broadcasts")
        template = await db.get(WhatsAppTemplate, data.template_id)
        if not template or template.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Template not found")
        if (template.status or "").upper() not in ("APPROVED", "ACTIVE"):
            raise HTTPException(
                status_code=400,
                detail=f"Template '{template.name}' is not approved (status: {template.status})",
            )
    elif data.message_type == "text":
        if not (data.text_content or "").strip():
            raise HTTPException(status_code=400, detail="text_content is required for text broadcasts")
    else:
        raise HTTPException(status_code=400, detail="message_type must be 'template' or 'text'")

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
        target_contact_ids=[str(cid) for cid in data.target_contact_ids] if data.target_contact_ids else None,
        send_rate=data.send_rate or 10,
        status=WhatsAppBroadcastStatus.SCHEDULED if data.scheduled_at else WhatsAppBroadcastStatus.DRAFT,
        scheduled_at=data.scheduled_at,
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


@router.get("/broadcasts/dashboard/stats", response_model=dict)
async def get_broadcast_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get aggregate stats across all broadcast campaigns."""
    result = await db.execute(
        select(
            func.count(WhatsAppBroadcast.id).label('total_campaigns'),
            func.sum(WhatsAppBroadcast.sent_count).label('total_sent'),
            func.sum(WhatsAppBroadcast.delivered_count).label('total_delivered'),
            func.sum(WhatsAppBroadcast.read_count).label('total_read'),
            func.sum(WhatsAppBroadcast.failed_count).label('total_failed')
        ).where(WhatsAppBroadcast.user_id == current_user.id)
    )
    stats = result.first()

    total_campaigns = stats.total_campaigns or 0
    total_sent = stats.total_sent or 0
    total_delivered = stats.total_delivered or 0
    total_read = stats.total_read or 0
    total_failed = stats.total_failed or 0

    delivery_rate = round((total_delivered / total_sent * 100), 2) if total_sent > 0 else 0
    read_rate = round((total_read / total_sent * 100), 2) if total_sent > 0 else 0

    return {
        "success": True,
        "data": {
            "total_campaigns": total_campaigns,
            "total_sent": total_sent,
            "total_delivered": total_delivered,
            "total_read": total_read,
            "total_failed": total_failed,
            "delivery_rate": delivery_rate,
            "read_rate": read_rate,
        },
    }


@router.post("/broadcasts/generate-copy", response_model=dict)
async def generate_broadcast_copy(
    data: GenerateCopyRequest,
    current_user: User = Depends(get_current_user)
):
    """Generate campaign copy variations using AI."""
    check_broadcast_access(current_user)
    prompt = (
        f"You are an expert copywriter for WhatsApp marketing campaigns.\n"
        f"Goal: {data.campaign_goal}\n"
        f"Audience: {data.audience_description or 'General audience'}\n"
        f"Tone: {data.tone}\n\n"
        "Generate 3 short, engaging variations of WhatsApp message copy. "
        "Each variation should be less than 400 characters, include emojis, "
        "and have a clear call to action. Use variables like {{name}} if appropriate."
    )

    try:
        response = await llm_service.generate_text(prompt, model="gpt-4o")
        variations = [v.strip() for v in response.split('\n\n') if len(v.strip()) > 10]
        variations = variations[:3]

        return {
            "success": True,
            "variations": variations,
        }
    except Exception as e:
        logger.error(f"Error generating broadcast copy: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate AI copy")


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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Start sending a broadcast campaign."""
    check_broadcast_access(current_user)
    await get_whatsapp_config_for_user(db, current_user)

    broadcast = await db.get(WhatsAppBroadcast, broadcast_id)

    if not broadcast or broadcast.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    if broadcast.status == WhatsAppBroadcastStatus.SENDING:
        raise HTTPException(status_code=400, detail="Broadcast is already sending")

    if broadcast.status not in [WhatsAppBroadcastStatus.DRAFT, WhatsAppBroadcastStatus.SCHEDULED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot send broadcast with status '{broadcast.status}'"
        )

    if broadcast.message_type == "template" and broadcast.template_id:
        template = await db.get(WhatsAppTemplate, broadcast.template_id)
        if not template or (template.status or "").upper() not in ("APPROVED", "ACTIVE"):
            raise HTTPException(status_code=400, detail="Broadcast template is not approved")

    broadcast.status = WhatsAppBroadcastStatus.SENDING
    broadcast.started_at = datetime.utcnow()
    await db.commit()
    
    # Delegate to Celery task
    execute_broadcast_campaign_task.delay(
        str(broadcast_id),
        str(current_user.id)
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
            WhatsAppContact.is_blocked == False,
            WhatsAppContact.opted_out == False
        )
    )
    
    if data.target_type == "tag" and data.target_tag:
        query = query.where(WhatsAppContact.tags.contains([data.target_tag]))
    elif data.target_type == "selected" and data.target_contact_ids:
        query = query.where(WhatsAppContact.id.in_(data.target_contact_ids))
    
    result = await db.execute(query)
    return result.scalar() or 0


@router.post("/broadcasts/{broadcast_id}/duplicate", response_model=dict)
async def duplicate_broadcast(
    broadcast_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Duplicate an existing broadcast campaign."""
    broadcast = await db.get(WhatsAppBroadcast, broadcast_id)
    
    if not broadcast or broadcast.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Broadcast not found")
        
    new_broadcast = WhatsAppBroadcast(
        user_id=current_user.id,
        name=f"{broadcast.name} (Copy)",
        description=broadcast.description,
        message_type=broadcast.message_type,
        template_id=broadcast.template_id,
        template_variables=broadcast.template_variables,
        text_content=broadcast.text_content,
        media_url=broadcast.media_url,
        media_type=broadcast.media_type,
        send_rate=broadcast.send_rate,
        target_type=broadcast.target_type,
        target_tag=broadcast.target_tag,
        target_contact_ids=broadcast.target_contact_ids,
        status=WhatsAppBroadcastStatus.DRAFT
    )
    
    db.add(new_broadcast)
    await db.commit()
    await db.refresh(new_broadcast)
    
    # Recalculate recipient count
    create_data = BroadcastCreate(
        name=new_broadcast.name,
        target_type=new_broadcast.target_type,
        target_tag=new_broadcast.target_tag,
        target_contact_ids=[
            uuid.UUID(str(cid)) for cid in (new_broadcast.target_contact_ids or [])
        ] or None,
        message_type=new_broadcast.message_type,
    )
    recipient_count = await _count_broadcast_recipients(db, current_user.id, create_data)
    new_broadcast.total_recipients = recipient_count
    await db.commit()
    
    return {
        "success": True,
        "message": "Broadcast duplicated",
        "data": BroadcastResponse.model_validate(new_broadcast).model_dump()
    }
