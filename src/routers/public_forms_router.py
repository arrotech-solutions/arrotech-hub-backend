"""
Public Forms Router — Unauthenticated API endpoints for contact forms and newsletter subscriptions.

These endpoints serve ALL Arrotech frontends:
  - arrotechsolutions.com (company site)
  - hub.arrotechsolutions.com (Hub app)
  - blog.arrotechsolutions.com (blog)

Security:
  - IP-based rate limiting (built into main app middleware)
  - Honeypot field for bot detection
  - Input validation via Pydantic
  - CORS whitelist (only Arrotech domains)
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from ..database import get_db
from ..models import ContactSubmission, NewsletterSubscriber
from ..services.public_forms_service import public_forms_service

router = APIRouter(
    prefix="/api/public",
    tags=["public-forms"],
)

logger = logging.getLogger(__name__)


# =============================================================================
# Request / Response Schemas
# =============================================================================

class ContactFormRequest(BaseModel):
    """Contact form submission from any Arrotech website."""
    name: str = ""
    email: EmailStr
    phone: str = ""
    category: str = "general"  # general, sales, partnership, support, billing
    subject: str = ""
    message: str
    source_site: str = "arrotechsolutions.com"
    honeypot: str = ""  # Must be empty — bots fill this

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        allowed = {"general", "sales", "partnership", "support", "billing"}
        if v.lower() not in allowed:
            return "general"
        return v.lower()

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if len(v.strip()) < 10:
            raise ValueError("Message must be at least 10 characters")
        return v.strip()


class ContactFormResponse(BaseModel):
    success: bool
    message: str
    ticket_id: str = ""


class SubscribeRequest(BaseModel):
    """Newsletter subscription request."""
    email: EmailStr
    name: str = ""
    source_site: str = "arrotechsolutions.com"
    honeypot: str = ""  # Must be empty — bots fill this


class SubscribeResponse(BaseModel):
    success: bool
    message: str


class UnsubscribeResponse(BaseModel):
    success: bool
    message: str


# =============================================================================
# Contact Form Endpoint
# =============================================================================

@router.post("/contact", response_model=ContactFormResponse)
async def submit_contact_form(
    payload: ContactFormRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a contact form. Routes the email to the correct team based on `category`.

    Categories:
    - general → info@arrotechsolutions.com
    - sales / partnership → sales@arrotechsolutions.com
    - support → support@arrotechsolutions.com
    - billing → billing@arrotechsolutions.com
    """
    # Honeypot check — bots fill hidden fields
    if payload.honeypot:
        logger.warning(f"[ContactForm] Honeypot triggered from {request.client.host}")
        # Return fake success to not tip off the bot
        return ContactFormResponse(success=True, message="Message sent.", ticket_id="TKT-0000")

    # Get client IP
    ip_address = request.client.host if request.client else "unknown"

    # Duplicate detection — same email + message within 60 seconds
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
    dup_stmt = select(ContactSubmission).where(
        and_(
            ContactSubmission.email == payload.email,
            ContactSubmission.message == payload.message,
            ContactSubmission.created_at >= cutoff,
        )
    )
    dup_result = await db.execute(dup_stmt)
    if dup_result.scalar_one_or_none():
        return ContactFormResponse(
            success=True,
            message="Your message was already received. We'll respond within 24 hours.",
            ticket_id="",
        )

    # Generate ticket ID
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    ticket_id = f"TKT-{timestamp}"

    # Get routing info
    target_email, team_name = public_forms_service.get_route(payload.category)

    # Persist to database
    submission = ContactSubmission(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        category=payload.category,
        subject=payload.subject or f"{payload.category.capitalize()} Inquiry",
        message=payload.message,
        source_site=payload.source_site,
        routed_to=target_email,
        ip_address=ip_address,
    )
    db.add(submission)
    await db.commit()
    await db.refresh(submission)

    # Send emails asynchronously (don't block the response)
    loop = asyncio.get_event_loop()

    async def _send_emails():
        """Send notification + confirmation in the background."""
        try:
            # 1. Send internal notification to the appropriate team
            email_sent = await loop.run_in_executor(
                None,
                lambda: public_forms_service.send_contact_notification(
                    name=payload.name,
                    email=payload.email,
                    phone=payload.phone,
                    category=payload.category,
                    subject=payload.subject or f"{payload.category.capitalize()} Inquiry",
                    message=payload.message,
                    source_site=payload.source_site,
                    ticket_id=ticket_id,
                ),
            )

            # 2. Send confirmation to the sender
            confirmation_sent = await loop.run_in_executor(
                None,
                lambda: public_forms_service.send_contact_confirmation(
                    name=payload.name,
                    email=payload.email,
                    subject=payload.subject or f"{payload.category.capitalize()} Inquiry",
                    ticket_id=ticket_id,
                ),
            )

            # Update DB record
            submission.email_sent = email_sent
            submission.confirmation_sent = confirmation_sent
            db.add(submission)
            await db.commit()

        except Exception as e:
            logger.error(f"[ContactForm] Background email failed: {e}")

    task = asyncio.create_task(_send_emails())
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() and t.exception() else None)

    logger.info(f"[ContactForm] {ticket_id} — {payload.category} from {payload.email} → {target_email}")

    return ContactFormResponse(
        success=True,
        message="Your message has been sent successfully! We'll get back to you within 24 hours.",
        ticket_id=ticket_id,
    )


# =============================================================================
# Newsletter Subscribe Endpoint
# =============================================================================

@router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe_newsletter(
    payload: SubscribeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Subscribe to the Arrotech newsletter."""
    # Honeypot check
    if payload.honeypot:
        logger.warning(f"[Newsletter] Honeypot triggered from {request.client.host}")
        return SubscribeResponse(success=True, message="Subscribed successfully!")

    # Check if already subscribed
    existing_stmt = select(NewsletterSubscriber).where(
        NewsletterSubscriber.email == payload.email
    )
    result = await db.execute(existing_stmt)
    existing = result.scalar_one_or_none()

    if existing:
        if existing.is_active:
            return SubscribeResponse(
                success=True,
                message="You're already subscribed! 🎉",
            )
        else:
            # Re-subscribe
            existing.is_active = True
            existing.unsubscribed_at = None
            existing.source_site = payload.source_site
            if payload.name:
                existing.name = payload.name
            db.add(existing)
            await db.commit()

            return SubscribeResponse(
                success=True,
                message="Welcome back! You've been re-subscribed.",
            )

    # Create new subscriber
    token = public_forms_service.generate_unsubscribe_token()
    subscriber = NewsletterSubscriber(
        email=payload.email,
        name=payload.name or None,
        source_site=payload.source_site,
        unsubscribe_token=token,
    )
    db.add(subscriber)
    await db.commit()

    # Send welcome email + internal notification in background
    loop = asyncio.get_event_loop()

    async def _send_welcome():
        try:
            await loop.run_in_executor(
                None,
                lambda: public_forms_service.send_newsletter_welcome(payload.email, payload.name, token),
            )
            await loop.run_in_executor(
                None,
                lambda: public_forms_service.send_subscriber_notification(payload.email, payload.source_site),
            )
        except Exception as e:
            logger.error(f"[Newsletter] Welcome email failed: {e}")

    task = asyncio.create_task(_send_welcome())
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() and t.exception() else None)

    logger.info(f"[Newsletter] New subscriber: {payload.email} from {payload.source_site}")

    return SubscribeResponse(
        success=True,
        message="You've been subscribed successfully! Check your inbox for a welcome email. 🎉",
    )


# =============================================================================
# Unsubscribe Endpoint
# =============================================================================

@router.get("/unsubscribe", response_model=UnsubscribeResponse)
async def unsubscribe_newsletter(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Unsubscribe from the newsletter via one-click link (RFC 8058)."""
    if not token:
        raise HTTPException(status_code=400, detail="Missing unsubscribe token")

    stmt = select(NewsletterSubscriber).where(
        NewsletterSubscriber.unsubscribe_token == token
    )
    result = await db.execute(stmt)
    subscriber = result.scalar_one_or_none()

    if not subscriber:
        raise HTTPException(status_code=404, detail="Invalid unsubscribe token")

    if not subscriber.is_active:
        return UnsubscribeResponse(
            success=True,
            message="You're already unsubscribed.",
        )

    subscriber.is_active = False
    subscriber.unsubscribed_at = datetime.now(timezone.utc)
    db.add(subscriber)
    await db.commit()

    logger.info(f"[Newsletter] Unsubscribed: {subscriber.email}")

    return UnsubscribeResponse(
        success=True,
        message="You've been unsubscribed. We're sorry to see you go!",
    )


@router.post("/unsubscribe", response_model=UnsubscribeResponse)
async def unsubscribe_newsletter_post(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """POST endpoint for RFC 8058 List-Unsubscribe-Post one-click unsubscribe."""
    return await unsubscribe_newsletter(token=token, db=db)
