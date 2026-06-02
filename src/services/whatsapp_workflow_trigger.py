"""
WhatsApp Workflow Trigger Service.
Fires workflows based on WhatsApp events (new message, new contact, keyword match).
Includes real estate specific triggers for property inquiries, maintenance, and payments.
"""

import logging
import re
from datetime import datetime
from typing import Optional, Dict, Any, List
import uuid

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session_maker
from ..models import (
    Workflow, WorkflowStatus, WorkflowTriggerType,
    WhatsAppContact, WhatsAppMessage, WhatsAppMessageDirection
)
from ..services.workflow_builder_service import WorkflowBuilderService

logger = logging.getLogger(__name__)


# Real estate keyword groups for trigger matching
RE_KEYWORDS = {
    "property_inquiry": [
        "rent", "kodi", "buy", "nunua", "apartment", "flat", "house", "nyumba",
        "bedsitter", "bedsitta", "plot", "shamba", "land", "2br", "3br", "1br",
        "bedroom", "studio", "office", "shop", "duka", "godown", "commercial",
        "for sale", "for rent", "available", "vacancy", "vacant"
    ],
    "viewing_request": [
        "view", "visit", "see the", "tazama", "viewing", "angalia", "come see",
        "can i see", "schedule", "book viewing", "show me"
    ],
    "maintenance_request": [
        "broken", "leak", "repair", "fix", "maintenance", "plumbing", "pipe",
        "electrical", "water", "maji", "stima", "haribika", "vunja", "blocked",
        "not working", "damaged", "crack", "flood", "toilet", "sink"
    ],
    "payment_confirmation": [
        "confirmed", "paid", "mpesa", "m-pesa", "transaction", "receipt",
        "nimelipa", "payment sent", "sent payment"
    ],
    "lease_inquiry": [
        "lease", "contract", "renew", "renewal", "extend", "move out",
        "vacate", "notice", "leaving"
    ],
}


class WhatsAppWorkflowTrigger:
    """Service to trigger workflows based on WhatsApp events."""

    @classmethod
    async def has_active_conversational_agent(
        cls,
        user_id: uuid.UUID,
        db: AsyncSession,
    ) -> bool:
        """True if user has an active WhatsApp workflow with a conversational_agent step."""
        from ..models import WorkflowStep

        result = await db.execute(
            select(Workflow).where(
                and_(
                    Workflow.user_id == user_id,
                    Workflow.status == WorkflowStatus.ACTIVE,
                    Workflow.trigger_type == WorkflowTriggerType.EVENT.value,
                )
            )
        )
        workflows = result.scalars().all()
        for workflow in workflows:
            trigger_config = workflow.trigger_config or {}
            if trigger_config.get("event_type") != "whatsapp_message_received":
                continue
            step_result = await db.execute(
                select(WorkflowStep).where(
                    and_(
                        WorkflowStep.workflow_id == workflow.id,
                        WorkflowStep.tool_name == "conversational_agent",
                    )
                )
            )
            if step_result.scalar_one_or_none():
                return True
        return False
    
    TRIGGER_EVENTS = [
        "whatsapp_message_received",
        "whatsapp_new_contact",
        "whatsapp_keyword_detected",
        # Real estate specific triggers
        "whatsapp_property_inquiry",
        "whatsapp_viewing_request",
        "whatsapp_maintenance_request",
        "whatsapp_payment_confirmation",
        "whatsapp_lease_inquiry",
    ]
    
    @classmethod
    def _detect_real_estate_intent(cls, message_content: str) -> Optional[str]:
        """Detect real estate intent from message content."""
        if not message_content:
            return None
        
        content_lower = message_content.lower()
        
        for intent, keywords in RE_KEYWORDS.items():
            for keyword in keywords:
                if keyword in content_lower:
                    return intent
        
        return None
    
    @classmethod
    async def on_message_received(
        cls,
        user_id: uuid.UUID,
        contact: WhatsAppContact,
        message: WhatsAppMessage
    ):
        """
        Called when a new WhatsApp message is received.
        Checks for matching workflows and triggers them.
        Includes real estate intent detection.
        """
        session_maker = get_session_maker()
        async with session_maker() as db:
            try:
                # Detect real estate intent from message
                re_intent = cls._detect_real_estate_intent(message.content)
                re_event_type = f"whatsapp_{re_intent}" if re_intent else None
                
                # ── CCM: Persist incoming message to conversation session ──
                session_key = ""
                try:
                    from .conversation_context_manager import context_manager

                    session = await context_manager.get_or_create_session(
                        platform="whatsapp",
                        owner_user_id=str(user_id),
                        sender_id=contact.phone_number,
                        metadata={
                            "contact_name": contact.name or contact.profile_name or "",
                            "contact_phone": contact.phone_number,
                        }
                    )
                    session_key = session.session_key

                    # Add incoming message to history
                    await context_manager.add_message(
                        session, "user", message.content or ""
                    )
                except Exception as ccm_err:
                    logger.warning(f"[WA_TRIGGER] CCM session init failed (non-blocking): {ccm_err}")

                if session_key:
                    try:
                        from ..config import settings

                        ttl_hours = int(
                            getattr(settings, "AGENT_HUMAN_HANDOFF_TTL_HOURS", 24) or 0
                        )
                        if ttl_hours > 0:
                            expired = await context_manager.maybe_expire_human_handoff(
                                session_key, ttl_hours * 3600
                            )
                            if expired:
                                logger.info(
                                    "[WA_TRIGGER] Handoff TTL expired for %s — AI resumed",
                                    contact.phone_number,
                                )
                    except Exception as handoff_err:
                        logger.warning(
                            f"[WA_TRIGGER] Handoff TTL check failed (continuing): {handoff_err}"
                        )

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
                    
                    # Real estate specific triggers
                    elif re_event_type and event_type == re_event_type:
                        should_trigger = True
                    
                    if should_trigger:
                        wf_config = dict((workflow.variables or {}).get("config", {}) or {})
                        wf_config.setdefault("customer_phone", contact.phone_number)
                        wf_config.setdefault(
                            "customer_name",
                            contact.name or contact.profile_name or "Customer",
                        )
                        wf_config.setdefault("platform", "whatsapp")

                        # Build input variables for workflow
                        input_vars = {
                            "whatsapp_contact_id": str(contact.id) if contact.id else None,
                            "whatsapp_contact_phone": contact.phone_number,
                            "whatsapp_contact_name": contact.name or contact.profile_name or "Customer",
                            "whatsapp_message_id": str(message.id) if message.id else None,
                            "whatsapp_message_content": message.content or "",
                            "whatsapp_message_type": message.message_type,
                            "timestamp": datetime.utcnow().isoformat(),
                            # ── CCM: Inject session key for context-aware tools ──
                            "session_key": session_key,
                            "platform": "whatsapp",
                            # ── Inject workflow-level config for agent tools ──
                            "config": wf_config,
                        }
                        
                        # Add real estate context if detected
                        if re_intent:
                            input_vars["real_estate_intent"] = re_intent
                            input_vars["real_estate_event"] = re_event_type
                        
                        # Execute workflow
                        logger.info(f"[WA_TRIGGER] Firing workflow '{workflow.name}' for contact {contact.phone_number}" +
                                   (f" (RE intent: {re_intent})" if re_intent else ""))
                        
                        try:
                            builder = WorkflowBuilderService()
                            await builder.execute_workflow(
                                workflow_id=workflow.id,
                                user_id=user_id,
                                db=db,
                                input_data=input_vars,
                                trigger_type="whatsapp_message_received"
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
        },
        # Real estate specific actions
        "whatsapp_send_rent_reminder": {
            "description": "Send a formatted rent reminder via WhatsApp",
            "parameters": {
                "contact_id": {"type": "integer", "description": "Tenant contact ID"},
                "amount": {"type": "number", "description": "Rent amount in KES"},
                "due_date": {"type": "string", "description": "Payment due date"},
                "reminder_level": {"type": "string", "enum": ["first", "second", "final"]}
            }
        },
        "whatsapp_send_maintenance_ack": {
            "description": "Send a maintenance request acknowledgement via WhatsApp",
            "parameters": {
                "contact_id": {"type": "integer", "description": "Tenant contact ID"},
                "category": {"type": "string", "description": "Maintenance category"},
                "priority": {"type": "string", "description": "Priority level"}
            }
        },
        "whatsapp_send_viewing_slots": {
            "description": "Send available property viewing slots via WhatsApp",
            "parameters": {
                "contact_id": {"type": "integer", "description": "Prospect contact ID"},
                "property_description": {"type": "string"},
                "slots": {"type": "array", "items": {"type": "string"}}
            }
        },
    }
    
    return workflow_actions


async def execute_whatsapp_action(
    action_name: str,
    user_id: uuid.UUID,
    parameters: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Execute a WhatsApp workflow action.
    Called by the workflow executor when a workflow step uses a WhatsApp action.
    """
    from ..services import WhatsAppService
    from ..config import settings
    from ..models import Connection
    
    session_maker = get_session_maker()
    async with session_maker() as db:
        try:
            # Get user's WhatsApp connection config
            conn_result = await db.execute(
                select(Connection).where(
                    and_(
                        Connection.user_id == user_id,
                        Connection.platform == "whatsapp",
                        Connection.status == "active"
                    )
                )
            )
            connection = conn_result.scalar_one_or_none()
            wa_config = connection.config if connection and connection.config else {
                "access_token": settings.WHATSAPP_TOKEN,
                "phone_number_id": settings.WHATSAPP_PHONE_NUMBER_ID
            }

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
                    config=wa_config
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
            
            elif action_name == "whatsapp_send_rent_reminder":
                # Use real estate tools to format, then send via WhatsApp
                from .real_estate_service import RealEstateService
                re_service = RealEstateService()
                
                formatted = await re_service.format_rent_reminder(
                    tenant_name=parameters.get("tenant_name", "Tenant"),
                    amount=parameters.get("amount", 0),
                    due_date=parameters.get("due_date", ""),
                    reminder_level=parameters.get("reminder_level", "first"),
                    paybill=parameters.get("paybill", ""),
                    account_number=parameters.get("account_number", ""),
                )
                
                if not formatted.get("success"):
                    return formatted
                
                contact_id = parameters.get("contact_id")
                result_contact = await db.execute(
                    select(WhatsAppContact).where(
                        and_(WhatsAppContact.id == contact_id, WhatsAppContact.user_id == user_id)
                    )
                )
                contact = result_contact.scalar_one_or_none()
                
                if not contact:
                    return {"success": False, "error": "Contact not found"}
                
                wa_service = WhatsAppService()
                send_result = await wa_service.send_message(
                    to_number=contact.phone_number,
                    message=formatted["message"],
                    message_type="text",
                    config=wa_config
                )
                
                return {"success": True, "message_id": send_result.get("message_id"), "formatted_message": formatted["message"]}
            
            elif action_name == "whatsapp_send_maintenance_ack":
                from .real_estate_service import RealEstateService
                re_service = RealEstateService()
                
                formatted = await re_service.format_maintenance_response(
                    tenant_name=parameters.get("tenant_name", "Tenant"),
                    category=parameters.get("category", "general"),
                    priority=parameters.get("priority", "normal"),
                )
                
                if not formatted.get("success"):
                    return formatted
                
                contact_id = parameters.get("contact_id")
                result_contact = await db.execute(
                    select(WhatsAppContact).where(
                        and_(WhatsAppContact.id == contact_id, WhatsAppContact.user_id == user_id)
                    )
                )
                contact = result_contact.scalar_one_or_none()
                
                if not contact:
                    return {"success": False, "error": "Contact not found"}
                
                wa_service = WhatsAppService()
                send_result = await wa_service.send_message(
                    to_number=contact.phone_number,
                    message=formatted["message"],
                    message_type="text",
                    config=wa_config
                )
                
                return {"success": True, "message_id": send_result.get("message_id"), "ticket_id": formatted.get("ticket_id")}
            
            elif action_name == "whatsapp_send_viewing_slots":
                from .real_estate_service import RealEstateService
                re_service = RealEstateService()
                
                formatted = await re_service.format_viewing_slots(
                    property_description=parameters.get("property_description", "the property"),
                    slots=parameters.get("slots"),
                    location=parameters.get("location", ""),
                    agent_name=parameters.get("agent_name", ""),
                )
                
                if not formatted.get("success"):
                    return formatted
                
                contact_id = parameters.get("contact_id")
                result_contact = await db.execute(
                    select(WhatsAppContact).where(
                        and_(WhatsAppContact.id == contact_id, WhatsAppContact.user_id == user_id)
                    )
                )
                contact = result_contact.scalar_one_or_none()
                
                if not contact:
                    return {"success": False, "error": "Contact not found"}
                
                wa_service = WhatsAppService()
                send_result = await wa_service.send_message(
                    to_number=contact.phone_number,
                    message=formatted["message"],
                    message_type="text",
                    config=wa_config
                )
                
                return {"success": True, "message_id": send_result.get("message_id"), "slots": formatted.get("available_slots")}
                
            else:
                return {"success": False, "error": f"Unknown action: {action_name}"}
                
        except Exception as e:
            logger.error(f"[WA_ACTION] Error executing {action_name}: {e}")
            return {"success": False, "error": str(e)}

