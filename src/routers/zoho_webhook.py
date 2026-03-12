"""
Zoho Webhook Handler for receiving real-time events.
This enables autonomous triggers for workflows (e.g., KB Autopilot).
"""

import logging
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import datetime

from ..database import get_db
from ..models import Connection, Workflow, WorkflowStatus, WorkflowTriggerType
from ..services.workflow_builder_service import WorkflowBuilderService

router = APIRouter(
    prefix="/api/zoho/webhook",
    tags=["zoho-webhook"]
)

logger = logging.getLogger(__name__)

@router.get("/desk/{user_id}")
async def validate_desk_webhook(user_id: int):
    """Zoho sends a GET request to validate the webhook URL before saving."""
    return {"status": "ok", "message": "Arrotech KB Autopilot webhook is active."}

@router.post("/desk/{user_id}")
async def receive_desk_webhook(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Receive incoming webhooks from Zoho Desk.
    """
    try:
        payload = await request.json()
        logger.info(f"[ZOHO WEBHOOK] Received payload for user {user_id}: {payload}")
        
        # Zoho Desk often sends a list of events rather than a single object
        if isinstance(payload, list) and len(payload) > 0:
            payload = payload[0]
            
        # Determine the event type based on payload structure or headers
        # Zoho might send specific headers or payload formats.
        # Assuming typical Zoho Desk structure:
        event = payload.get("event") # Or extract from payload structure if Zoho sends different format
        
        # Trigger workflows for this user
        await _trigger_zoho_workflows(user_id, payload, db)
        
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"[ZOHO WEBHOOK] Error processing webhook: {e}")
        # Return 200 to acknowledge receipt and prevent Zoho from spamming retries
        return {"status": "error", "message": str(e)}

async def _trigger_zoho_workflows(user_id: int, payload: dict, db: AsyncSession):
    """
    Find and execute workflows triggered by this webhook.
    """
    # Look for active workflows triggering on Zoho Desk events
    stmt = select(Workflow).where(
        and_(
            Workflow.user_id == user_id,
            Workflow.status == WorkflowStatus.ACTIVE,
            Workflow.trigger_type == WorkflowTriggerType.EVENT 
        )
    )
    result = await db.execute(stmt)
    workflows = result.scalars().all()
    
    logger.info(f"[ZOHO WEBHOOK] Found {len(workflows)} active workflows for user {user_id}")
    
    # Determine the event type from the Zoho payload
    event_type = payload.get("eventType", "").lower()  # e.g. "ticket_add", "ticket_update"
    ticket_data = payload.get("payload", payload.get("entity", payload))
    ticket_status = ""
    if isinstance(ticket_data, dict):
        ticket_status = (ticket_data.get("status") or ticket_data.get("statusType") or "").lower()
    
    is_ticket_created = event_type == "ticket_add"
    is_ticket_updated = event_type == "ticket_update"
    is_closed_or_resolved = ticket_status in ("closed", "resolved")
    
    logger.info(f"[ZOHO WEBHOOK] Event: {event_type}, Status: {ticket_status}, "
                f"isCreated={is_ticket_created}, isUpdated={is_ticket_updated}, isClosed={is_closed_or_resolved}")
    
    workflow_service = WorkflowBuilderService()
    
    for workflow in workflows:
        trigger_config = workflow.trigger_config or {}
        
        platform = trigger_config.get("platform", "").lower()
        # Frontend saves as "event_type", fallback to "trigger" for backwards compat
        trigger_event = trigger_config.get("event_type", trigger_config.get("trigger", "")).lower()
        
        should_trigger = False
        
        if platform == "zoho":
            # "Ticket Created" workflows fire on Ticket_Add events
            if "ticket created" in trigger_event and is_ticket_created:
                should_trigger = True
            # "Status Updated" / "KB Draft" workflows fire on Ticket_Update with closed/resolved status
            elif "status updated" in trigger_event and is_ticket_updated and is_closed_or_resolved:
                should_trigger = True
        
        # Fallback: if no platform, match based on name/description BUT only for the right event type
        if not platform:
            wf_text = f"{workflow.name} {workflow.description}".lower()
            if "zoho" in wf_text or "ticket" in wf_text:
                # Try to match by workflow purpose
                if ("resolver" in wf_text or "auto-reply" in wf_text or "auto resolve" in wf_text) and is_ticket_created:
                    should_trigger = True
                elif ("ingester" in wf_text or "draft" in wf_text or "article" in wf_text) and is_ticket_updated and is_closed_or_resolved:
                    should_trigger = True
                elif is_ticket_created:
                    # Default fallback for unrecognized workflows: trigger on new tickets only
                    should_trigger = True
                
        if should_trigger:
            logger.info(f"[ZOHO WEBHOOK] Mapped to Workflow '{workflow.name}'. Executing...")
            
            # Map Zoho payload to Arrotech standardized "Trigger" variables
            input_vars = {
                "Trigger": {
                    "id": ticket_data.get("id", ticket_data.get("ticketId", payload.get("id"))),
                    "subject": ticket_data.get("subject", payload.get("subject")),
                    "description": ticket_data.get("description", payload.get("description")),
                    "status": ticket_data.get("status", payload.get("status")),
                    "contactId": ticket_data.get("contactId", payload.get("contactId")),
                    "raw_payload": payload
                },
                "timestamp": datetime.utcnow().isoformat()
            }
            
            try:
                await workflow_service.execute_workflow(
                    workflow_id=workflow.id,
                    user_id=user_id,
                    db=db,
                    input_data=input_vars
                )
                logger.info(f"[ZOHO WEBHOOK] Successfully triggered Workflow {workflow.id}")
            except Exception as e:
                logger.error(f"[ZOHO WEBHOOK] Failed to execute Workflow {workflow.id}: {e}")
        else:
            logger.info(f"[ZOHO WEBHOOK] Skipped Workflow '{workflow.name}' (event doesn't match trigger)")
