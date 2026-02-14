"""
WhatsApp Workflow Trigger Service.
Fires workflows based on WhatsApp events (new message, new contact, keyword match).
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models import (
    Workflow, WorkflowStatus, WorkflowTriggerType,
    WhatsAppContact, WhatsAppMessage, WhatsAppMessageDirection
)
from ..services.workflow_builder_service import WorkflowBuilderService

logger = logging.getLogger(__name__)


class WhatsAppWorkflowTrigger:
    """Service to trigger workflows based on WhatsApp events."""
    
    TRIGGER_EVENTS = [
        "whatsapp_message_received",
        "whatsapp_new_contact",
        "whatsapp_keyword_detected",
    ]
    
    @classmethod
    async def on_message_received(
        cls,
        user_id: int,
        contact: WhatsAppContact,
        message: WhatsAppMessage
    ):
        """
        Called when a new WhatsApp message is received.
        Checks for matching workflows and triggers them.
        """
        async with AsyncSessionLocal() as db:
            try:
                # Find workflows with WhatsApp triggers
                result = await db.execute(
                    select(Workflow).where(
                        and_(
                            Workflow.user_id == user_id,
                            Workflow.status == WorkflowStatus.ACTIVE,
                            Workflow.trigger_type == WorkflowTriggerType.EVENT.value
                        )
                    )
                )
                workflows = result.scalars().all()
                
                for workflow in workflows:
                    trigger_config = workflow.trigger_config or {}
                    event_type = trigger_config.get("event_type", "")
                    
                    # Check if this workflow should trigger
                    should_trigger = False
                    
                    if event_type == "whatsapp_message_received":
                        should_trigger = True
                        
                    elif event_type == "whatsapp_new_contact":
                        # Only trigger if first message from contact
                        if contact.message_count == 1:
                            should_trigger = True
                            
                    elif event_type == "whatsapp_keyword_detected":
                        keywords = trigger_config.get("keywords", [])
                        content = (message.content or "").lower()
                        for keyword in keywords:
                            if keyword.lower() in content:
                                should_trigger = True
                                break
                    
                    if should_trigger:
                        # Build input variables for workflow
                        input_vars = {
                            "whatsapp_contact_id": contact.id,
                            "whatsapp_contact_phone": contact.phone_number,
                            "whatsapp_contact_name": contact.name or contact.profile_name or "Customer",
                            "whatsapp_message_id": message.id,
                            "whatsapp_message_content": message.content or "",
                            "whatsapp_message_type": message.message_type,
                            "timestamp": datetime.utcnow().isoformat()
                        }
                        
                        # Execute workflow
                        logger.info(f"[WA_TRIGGER] Firing workflow '{workflow.name}' for contact {contact.phone_number}")
                        
                        try:
                            builder = WorkflowBuilderService()
                            await builder.execute_workflow(
                                db=db,
                                workflow_id=workflow.id,
                                input_variables=input_vars
                            )
                        except Exception as e:
                            logger.error(f"[WA_TRIGGER] Failed to execute workflow {workflow.id}: {e}")
                            
            except Exception as e:
                logger.error(f"[WA_TRIGGER] Error checking workflows: {e}")


async def register_whatsapp_workflow_actions():
    """
    Register WhatsApp actions that can be used in workflows.
    These are added to the MCP tools registry.
    """
    # This is called at startup to register WhatsApp as workflow actions
    workflow_actions = {
        "whatsapp_send_message": {
            "description": "Send a WhatsApp message to a contact",
            "parameters": {
                "contact_id": {"type": "integer", "description": "Contact ID to send to"},
                "message": {"type": "string", "description": "Message content"}
            }
        },
        "whatsapp_send_template": {
            "description": "Send a WhatsApp template message",
            "parameters": {
                "contact_id": {"type": "integer", "description": "Contact ID to send to"},
                "template_name": {"type": "string", "description": "Template name"},
                "variables": {"type": "object", "description": "Template variables"}
            }
        },
        "whatsapp_add_tag": {
            "description": "Add a tag to a WhatsApp contact",
            "parameters": {
                "contact_id": {"type": "integer", "description": "Contact ID"},
                "tag": {"type": "string", "description": "Tag to add"}
            }
        }
    }
    
    return workflow_actions


async def execute_whatsapp_action(
    action_name: str,
    user_id: int,
    parameters: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Execute a WhatsApp workflow action.
    Called by the workflow executor when a workflow step uses a WhatsApp action.
    """
    from ..services import WhatsAppService
    from ..config import settings
    
    async with AsyncSessionLocal() as db:
        try:
            if action_name == "whatsapp_send_message":
                contact_id = parameters.get("contact_id")
                message_content = parameters.get("message")
                
                # Get contact
                result = await db.execute(
                    select(WhatsAppContact).where(
                        and_(
                            WhatsAppContact.id == contact_id,
                            WhatsAppContact.user_id == user_id
                        )
                    )
                )
                contact = result.scalar_one_or_none()
                
                if not contact:
                    return {"success": False, "error": "Contact not found"}
                
                # Send message
                wa_service = WhatsAppService()
                result = await wa_service.send_message(
                    to_number=contact.phone_number,
                    message=message_content,
                    message_type="text",
                    config={"access_token": settings.WHATSAPP_TOKEN, "phone_number_id": settings.WHATSAPP_PHONE_NUMBER_ID}
                )
                
                return {"success": True, "message_id": result.get("message_id")}
                
            elif action_name == "whatsapp_add_tag":
                contact_id = parameters.get("contact_id")
                tag = parameters.get("tag")
                
                result = await db.execute(
                    select(WhatsAppContact).where(
                        and_(
                            WhatsAppContact.id == contact_id,
                            WhatsAppContact.user_id == user_id
                        )
                    )
                )
                contact = result.scalar_one_or_none()
                
                if not contact:
                    return {"success": False, "error": "Contact not found"}
                
                # Add tag
                current_tags = contact.tags or []
                if tag not in current_tags:
                    current_tags.append(tag)
                    contact.tags = current_tags
                    await db.commit()
                
                return {"success": True, "tags": contact.tags}
                
            else:
                return {"success": False, "error": f"Unknown action: {action_name}"}
                
        except Exception as e:
            logger.error(f"[WA_ACTION] Error executing {action_name}: {e}")
            return {"success": False, "error": str(e)}
