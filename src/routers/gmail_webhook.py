"""
Gmail Webhook Router for receiving Google Pub/Sub push notifications.
Handles Gmail inbox changes (new emails) and triggers the auto-responder workflow.

End-to-end flow:
1. Google Pub/Sub pushes a notification when a new email arrives
2. We decode the notification and find the user's Google Workspace connection
3. Fetch unread emails from the inbox
4. Classify each email by category (billing, support, sales, etc.)
5. Render the appropriate auto-reply template
6. SEND the auto-reply via Gmail
7. Mark the email as read so it's not re-processed
8. Log the sender as a contact in HubSpot CRM (if connected)
9. Record a workflow execution so it appears in the Executions tab
"""

import base64
import json
import logging
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db, get_session_maker
from ..models import (
    Connection, ConnectionStatus, User, Workflow, WorkflowExecution,
    WorkflowExecutionStatus, WorkflowStatus, WorkflowTriggerType
)
from ..services.google_workspace.base_client import GoogleWorkspaceBaseClient
from ..services.google_workspace.gmail_service import GmailService
from ..services.email_template_service import email_template_service
from ..services.hubspot_service import HubSpotService

router = APIRouter(
    prefix="/api/webhooks/gmail",
    tags=["gmail-webhook"]
)

logger = logging.getLogger(__name__)

# Simple in-memory deduplication cache to prevent Pub/Sub retry storms.
# Maps message_id -> timestamp. Entries expire after 5 minutes.
_processed_messages: dict = {}
_DEDUP_TTL_SECONDS = 300  # 5 minutes
_DEDUP_MAX_SIZE = 200


@router.post("/push")
async def gmail_push_notification(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    Receive Gmail push notifications from Google Cloud Pub/Sub.
    
    When a user has set up watch_inbox(), Gmail sends notifications here
    whenever new emails arrive. We fast-ack the webhook and process the emails
    in a background task.
    """
    try:
        body = await request.json()
        
        # Pub/Sub sends the message in this format
        message = body.get("message", {})
        if not message:
            logger.warning("Gmail webhook received empty message")
            return {"status": "ignored", "reason": "empty message"}
        
        # Deduplication: Pub/Sub may deliver the same message multiple times.
        # Always return 200 to acknowledge — returning 500 causes exponential retry storms.
        msg_id = message.get("message_id") or message.get("messageId", "")
        now = time.time()
        
        # Clean expired entries
        expired = [k for k, v in _processed_messages.items() if now - v > _DEDUP_TTL_SECONDS]
        for k in expired:
            _processed_messages.pop(k, None)
        
        if msg_id and msg_id in _processed_messages:
            logger.info(f"Duplicate Pub/Sub message {msg_id} — skipping")
            return {"status": "duplicate", "message_id": msg_id}
        
        if msg_id:
            _processed_messages[msg_id] = now
            # Cap cache size
            if len(_processed_messages) > _DEDUP_MAX_SIZE:
                oldest = min(_processed_messages, key=_processed_messages.get)
                _processed_messages.pop(oldest, None)
        
        # Decode the Pub/Sub data
        data_raw = message.get("data", "")
        if data_raw:
            decoded_data = base64.b64decode(data_raw).decode("utf-8")
            notification = json.loads(decoded_data)
        else:
            notification = {}
        
        email_address = notification.get("emailAddress")
        history_id = notification.get("historyId")
        
        if not email_address:
            logger.warning("Gmail webhook: no emailAddress in notification")
            return {"status": "ignored", "reason": "no email address"}
        
        logger.info(f"Gmail push notification received for {email_address} — queuing background task")
        
        # Queue the actual processing in the background
        background_tasks.add_task(_process_gmail_notification_bg, email_address, history_id)
        
        return {"status": "accepted"}
    
    except Exception as e:
        # ALWAYS return 200 to Pub/Sub — returning 500 causes retry storms
        # that exhaust the DB connection pool.
        logger.error(f"Error queuing Gmail push notification: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


async def _process_gmail_notification_bg(email_address: str, history_id: Optional[str]):
    """Background task that actually processes the incoming Gmail notification without holding DB connections."""
    session_maker = get_session_maker()
    
    try:
        logger.info(f"Background task starting for {email_address}, historyId: {history_id}")
        
        # --- PART 1: Fetch Credentials & Check Workflow Status (Short DB Transaction) ---
        connection = None
        user_id = None
        credentials_data = None
        company_name = "Our Team"
        has_active_workflow = False
        
        async with session_maker() as db:
            result = await db.execute(
                select(Connection)
                .filter(
                    Connection.platform == "google_workspace",
                    Connection.status == ConnectionStatus.ACTIVE
                )
            )
            all_gw_connections = result.scalars().all()
            
            for conn in all_gw_connections:
                conn_email = (conn.config or {}).get("email", "")
                if conn_email.lower() == email_address.lower():
                    connection = conn
                    user_id = conn.user_id
                    credentials_data = {
                        "client_id": conn.config.get("client_id"),
                        "client_secret": conn.config.get("client_secret"),
                        "refresh_token": conn.config.get("refresh_token"),
                        "access_token": conn.config.get("access_token"),
                        "scopes": conn.config.get("scopes")
                    }
                    company_name = conn.config.get("company_name", company_name)
                    break
            
            # Check if the user has an ACTIVE email auto-responder workflow
            if user_id:
                wf_result = await db.execute(
                    select(Workflow)
                    .filter(
                        Workflow.user_id == user_id,
                        Workflow.status == WorkflowStatus.ACTIVE
                    )
                    .options(selectinload(Workflow.steps))
                )
                active_workflows = wf_result.scalars().all()
                
                for wf in active_workflows:
                    name_lower = (wf.name or "").lower()
                    desc_lower = (wf.description or "").lower()
                    if any(kw in name_lower or kw in desc_lower
                           for kw in ["email auto", "auto-respond", "auto respond", "email respond"]):
                        has_active_workflow = True
                        break
                    # Fallback: check webhook trigger with Gmail/email steps
                    if wf.trigger_type == WorkflowTriggerType.WEBHOOK:
                        for step in (wf.steps or []):
                            if "gmail" in (step.tool_name or "").lower() or "email" in (step.tool_name or "").lower():
                                has_active_workflow = True
                                break
                        if has_active_workflow:
                            break
        
        if not credentials_data:
            logger.warning(f"No active Google Workspace connection found for {email_address}")
            return
        
        if not has_active_workflow:
            logger.info(f"Email auto-responder workflow is not active for user {user_id} — skipping auto-replies")
            return
            
        # --- PART 2: Network IO (No DB Connection Held!) ---
        base_client = GoogleWorkspaceBaseClient(credentials_data)
        gmail_service = GmailService(base_client)
        
        # Fetch recent unread emails
        unread_emails = await gmail_service.read_emails(
            max_results=5,
            query="is:unread",
            label_ids=["INBOX"]
        )
        
        if not unread_emails.get("success") or not unread_emails.get("emails"):
            return
        
        processed = []
        processed_ids = []
        
        for email_data in unread_emails.get("emails", []):
            email_id = email_data.get("id")
            subject = email_data.get("subject", "")
            sender = email_data.get("from", "")
            snippet = email_data.get("snippet", "")
            
            # Skip emails we should NOT auto-reply to
            sender_email = _extract_sender_email(sender)
            skip_reason = _should_skip_sender(sender_email, sender, subject, email_address)
            if skip_reason:
                logger.info(f"Skipping email {email_id}: {skip_reason}")
                # Still mark as read so we don't re-process
                processed_ids.append(email_id)
                continue
            
            # Classify the email
            category = _classify_email(subject, snippet)
            sender_name = _extract_sender_name(sender)
            
            logger.info(
                f"Processing email {email_id}: category={category}, "
                f"from={sender}, subject={subject}"
            )
            
            # Render the appropriate template
            rendered = await email_template_service.render_template(
                category=category,
                variables={
                    "sender_name": sender_name,
                    "original_subject": subject,
                    "company_name": company_name
                }
            )
            
            if not rendered.get("success"):
                # Missing template is expected if the user hasn't configured one for this category
                logger.info(f"Skipping auto-reply for {email_id}: {rendered.get('error', 'No template')}")
                continue
            
            reply_subject = f"{rendered.get('subject_prefix', 'Re: ')}{subject}"
            reply_body = rendered.get("rendered_body", "")
            
            # SEND the auto-reply
            send_result = await gmail_service.send_email(
                to=sender_email,
                subject=reply_subject,
                body=reply_body
            )
            
            if send_result.get("success"):
                logger.info(f"✅ Auto-reply sent for email {email_id} to {sender_email}")
            else:
                logger.error(f"❌ Failed to send auto-reply for email {email_id}: {send_result.get('error')}")
            
            processed_ids.append(email_id)
            processed.append({
                "email_id": email_id,
                "from": sender,
                "sender_email": sender_email,
                "subject": subject,
                "category": category,
                "reply_sent": send_result.get("success", False),
                "reply_message_id": send_result.get("message_id"),
                "priority": rendered.get("priority")
            })
        
        # Mark all processed emails as read
        if processed_ids:
            mark_result = await gmail_service.mark_as_read(processed_ids)
            if mark_result.get("success"):
                logger.info(f"✅ Marked {len(processed_ids)} emails as read")
            else:
                logger.error(f"❌ Failed to mark emails as read: {mark_result.get('error')}")
        
        # --- PART 3: Save Results (Short DB Transaction) ---
        if processed:
            # First, do HubSpot logging which does slow Network IO
            await _log_contacts_to_hubspot(user_id, processed)
            
            # Then, separately record the purely internal execution in a tight DB transaction
            async with session_maker() as db:
                try:
                    await _record_workflow_execution(db, user_id, processed)
                except Exception as inner_e:
                    logger.error(f"Error recording workflow execution: {inner_e}", exc_info=True)
                
    except Exception as e:
        logger.error(f"Error in background processing for {email_address}: {e}", exc_info=True)


@router.get("/health")
async def gmail_webhook_health():
    """Health check for the Gmail webhook endpoint."""
    return {"status": "healthy", "service": "gmail-webhook"}


# ─── Helper Functions ────────────────────────────────────────────────────────


def _should_skip_sender(sender_email: str, from_header: str, subject: str, own_email: str) -> str:
    """
    Check if we should skip auto-replying to this sender.
    Returns the reason string if we should skip, or empty string if OK to reply.
    """
    email_lower = sender_email.lower()
    from_lower = from_header.lower()
    subject_lower = subject.lower()
    
    # 1. Skip self-sent emails (reply loop prevention)
    if own_email.lower() in email_lower:
        return "self-sent email"
    
    # 2. Skip no-reply / system addresses (by local part before @)
    local_part = email_lower.split("@")[0] if "@" in email_lower else email_lower
    noreply_prefixes = [
        "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply",
        "notifications", "notification", "alert", "alerts",
        "newsletters-noreply", "newsletter", "news",
        "mailer-daemon", "postmaster", "mail-daemon",
        "bounce", "bounces", "return",
        "auto", "autoresponder", "auto-reply",
    ]
    if local_part in noreply_prefixes or any(local_part.startswith(p + "-") or local_part.startswith(p + "_") for p in ["noreply", "no-reply", "newsletter", "security-noreply", "jobs-noreply", "messaging-digest-noreply", "jobalerts-noreply"]):
        return f"no-reply/system address: {sender_email}"
    
    # Also catch compound noreply patterns like "jobs-noreply", "security-noreply"
    if "-noreply" in local_part or "_noreply" in local_part or "noreply" in local_part:
        return f"no-reply address: {sender_email}"
    
    # 3. Skip common marketing/automated email prefixes
    marketing_prefixes = [
        "marketing", "sales", "team", "hello", "hi", "info",
        "promo", "promotions", "offers", "deals",
        "feedback", "survey", "announce", "announcements",
        "engage", "outreach", "campaigns", "digest",
        "updates", "billing", "support", "help",
    ]
    if local_part in marketing_prefixes:
        return f"marketing prefix: {sender_email}"
    
    # 4. Skip known automated/marketing domains (uses endswith to catch subdomains)
    blocked_domains = [
        "linkedin.com", "facebookmail.com", "twitter.com", "x.com",
        "github.com", "gitlab.com", "bitbucket.org",
        "googlemail.com", "google.com",
        "amazonses.com", "sendgrid.net", "mailchimp.com", "mailgun.org",
        "hubspot.com", "intercom.io", "zendesk.com",
        "grammarly.com", "alibaba.com", "jobcopilot.com",
        "canva.com", "fiverr.com", "slack.com", "discord.com",
        "microsoft.com", "apple.com", "amazon.com",
        "remax-kenya.com", "jobleads.com", "remotejobs.io",
        "skool.com", "circleci.com", "vercel.com", "snyk.io",
        "fly.io", "glovoapp.com", "autodesk.com", "autodeskcommunications.com",
    ]
    sender_domain = email_lower.split("@")[-1] if "@" in email_lower else ""
    # Use endswith to catch subdomains like mail.grammarly.com, em.linkedin.com
    if any(sender_domain == d or sender_domain.endswith("." + d) for d in blocked_domains):
        return f"blocked domain: {sender_domain}"
    
    # 5. Skip delivery failure notifications
    if "delivery status notification" in subject_lower:
        return "delivery status notification"
    
    # 6. Skip if "via LinkedIn" or similar forwarded newsletters
    if "via linkedin" in from_lower:
        return "LinkedIn newsletter"
    
    # 7. Skip if subject looks like an unsubscribe/marketing blast
    marketing_subjects = [
        "unsubscribe", "% off", "limited time", "act now",
        "exclusive offer", "don't miss", "last chance",
    ]
    if any(kw in subject_lower for kw in marketing_subjects):
        return f"marketing subject: {subject[:50]}"
    
    return ""  # OK to reply


def _classify_email(subject: str, snippet: str) -> str:
    """
    Simple keyword-based email classifier.
    Returns a template category based on the email content.
    """
    text = f"{subject} {snippet}".lower()
    
    # Priority order matters: more specific matches first
    if any(kw in text for kw in ["invoice", "billing", "payment", "charge", "receipt", "refund"]):
        return "billing"
    if any(kw in text for kw in ["bug", "issue", "error", "help", "support", "broken", "not working", "problem"]):
        return "support"
    if any(kw in text for kw in ["price", "pricing", "quote", "demo", "trial", "buy", "purchase", "interested"]):
        return "sales"
    if any(kw in text for kw in ["partner", "partnership", "collaborate", "sponsor", "affiliate"]):
        return "partnership"
    if any(kw in text for kw in ["feedback", "suggestion", "review", "opinion", "recommend"]):
        return "feedback"
    
    return "general"


def _extract_sender_name(from_header: str) -> str:
    """Extract the sender's display name from a 'From' header like 'John Doe <john@example.com>'."""
    if "<" in from_header:
        name = from_header.split("<")[0].strip().strip('"')
        return name if name else "there"
    return "there"


def _extract_sender_email(from_header: str) -> str:
    """Extract the email address from a 'From' header like 'John Doe <john@example.com>'."""
    if "<" in from_header and ">" in from_header:
        return from_header.split("<")[1].split(">")[0].strip()
    # If no angle brackets, the whole thing might be just an email
    return from_header.strip()


async def _log_contacts_to_hubspot(
    user_id: int, processed_emails: list
):
    """
    Log each sender as a contact in HubSpot CRM. Best-effort: if no HubSpot
    connection exists or it fails, we log the error and continue.
    """
    try:
        session_maker = get_session_maker()
        access_token = None
        
        # 1. Fetch credentials (short DB transaction)
        async with session_maker() as db:
            result = await db.execute(
                select(Connection)
                .filter(
                    Connection.user_id == user_id,
                    Connection.platform == "hubspot",
                    Connection.status == ConnectionStatus.ACTIVE
                )
            )
            hubspot_connection = result.scalars().first()
            
            if hubspot_connection:
                access_token = hubspot_connection.config.get("api_key") or hubspot_connection.config.get("access_token")
        
        # 2. Network IO outside DB transaction
        if not access_token:
            logger.info("No active HubSpot connection / token — skipping CRM logging")
            return
            
        # Initialize HubSpot service with user's token
        hubspot_service = HubSpotService()
        hubspot_service.api_key = access_token
        hubspot_service.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        for email_info in processed_emails:
            sender_email = email_info.get("sender_email")
            if not sender_email:
                continue
            
            sender_name = _extract_sender_name(email_info.get("from", ""))
            first_name = sender_name if sender_name != "there" else None
            
            contact_result = await hubspot_service.create_contact(
                email=sender_email,
                first_name=first_name
            )
            
            if contact_result.get("success"):
                logger.info(f"✅ HubSpot: Created/updated contact for {sender_email}")
            else:
                # Contact may already exist — that's OK
                error = contact_result.get("error", "")
                if "409" in str(error) or "conflict" in str(error).lower() or "already" in str(error).lower():
                    logger.info(f"HubSpot: Contact {sender_email} already exists")
                else:
                    logger.warning(f"HubSpot: Failed to create contact for {sender_email}: {error}")
    
    except Exception as e:
        logger.error(f"HubSpot CRM logging failed (non-blocking): {e}")


async def _record_workflow_execution(
    db: AsyncSession, user_id: int, processed_emails: list
):
    """
    Record a workflow execution so it shows up in the Executions tab.
    Looks for an active 'email auto-responder' workflow for this user.
    Best-effort — if no matching workflow exists, we skip.
    """
    try:
        # Find the user's active auto-responder workflow
        result = await db.execute(
            select(Workflow)
            .filter(
                Workflow.user_id == user_id,
                Workflow.status == WorkflowStatus.ACTIVE
            )
            .options(selectinload(Workflow.steps))
        )
        workflows = result.scalars().all()
        
        # Find workflow that looks like an email auto-responder
        target_workflow = None
        for wf in workflows:
            name_lower = (wf.name or "").lower()
            desc_lower = (wf.description or "").lower()
            if any(kw in name_lower or kw in desc_lower 
                   for kw in ["email auto", "auto-respond", "auto respond", "email respond"]):
                target_workflow = wf
                break
            # Also check if trigger_type is webhook
            if wf.trigger_type == WorkflowTriggerType.WEBHOOK:
                # Check if steps mention Gmail/email
                for step in (wf.steps or []):
                    if "gmail" in (step.tool_name or "").lower() or "email" in (step.tool_name or "").lower():
                        target_workflow = wf
                        break
                if target_workflow:
                    break
        
        if not target_workflow:
            logger.info("No matching email auto-responder workflow found — skipping execution recording")
            return
        
        # Create execution record
        execution = WorkflowExecution(
            workflow_id=target_workflow.id,
            user_id=user_id,
            status=WorkflowExecutionStatus.COMPLETED,
            trigger_type=WorkflowTriggerType.WEBHOOK,
            trigger_data={"source": "gmail_push_notification"},
            input_data={
                "emails_received": len(processed_emails),
                "emails": [
                    {
                        "from": e.get("from"),
                        "subject": e.get("subject"),
                        "category": e.get("category")
                    }
                    for e in processed_emails
                ]
            },
            output_data={
                "replies_sent": sum(1 for e in processed_emails if e.get("reply_sent")),
                "categories": {e.get("category"): 1 for e in processed_emails},
                "processed_emails": processed_emails
            },
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow()
        )
        
        db.add(execution)
        await db.commit()
        
        logger.info(
            f"✅ Recorded workflow execution #{execution.id} for workflow '{target_workflow.name}' "
            f"({len(processed_emails)} emails processed)"
        )
    
    except Exception as e:
        logger.error(f"Workflow execution recording failed (non-blocking): {e}")
