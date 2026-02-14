"""
Support ticket routes - handles user support requests via email.
"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..config import settings

router = APIRouter(
    prefix="/api/support",
    tags=["support"]
)

logger = logging.getLogger(__name__)


class SupportTicketRequest(BaseModel):
    name: str = ""
    email: EmailStr
    subject: str = "Support Request"
    message: str


class SupportTicketResponse(BaseModel):
    message: str
    ticket_id: str


# Email configuration (using environment variables in production)
SUPPORT_EMAIL = "support@arrotechsolutions.com"
IMAP_SERVER = "mail.privateemail.com"
SMTP_SERVER = "mail.privateemail.com"
SMTP_PORT = 465  # SSL
# Note: Password should be stored in environment variables, not in code


@router.post("/ticket", response_model=SupportTicketResponse)
async def create_support_ticket(
    request: SupportTicketRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a support ticket by sending an email to the support team.
    Returns a ticket ID for reference.
    """
    # Generate a simple ticket ID
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    ticket_id = f"TKT-{timestamp}"
    
    try:
        # Get SMTP credentials from environment/settings
        smtp_password = getattr(settings, 'SUPPORT_EMAIL_PASSWORD', None)
        
        if smtp_password:
            # Create email message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"[{ticket_id}] {request.subject}"
            msg['From'] = SUPPORT_EMAIL
            msg['To'] = SUPPORT_EMAIL
            msg['Reply-To'] = request.email
            
            # HTML email body
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #4F46E5; border-bottom: 2px solid #4F46E5; padding-bottom: 10px;">
                        New Support Ticket: {ticket_id}
                    </h2>
                    
                    <div style="background: #F3F4F6; padding: 15px; border-radius: 8px; margin: 20px 0;">
                        <p><strong>From:</strong> {request.name or 'Not provided'}</p>
                        <p><strong>Email:</strong> <a href="mailto:{request.email}">{request.email}</a></p>
                        <p><strong>Subject:</strong> {request.subject}</p>
                        <p><strong>Time:</strong> {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}</p>
                    </div>
                    
                    <div style="background: #FFFFFF; padding: 20px; border: 1px solid #E5E7EB; border-radius: 8px;">
                        <h3 style="margin-top: 0; color: #374151;">Message:</h3>
                        <p style="white-space: pre-wrap;">{request.message}</p>
                    </div>
                    
                    <p style="color: #6B7280; font-size: 12px; margin-top: 20px;">
                        Reply directly to this email to respond to the customer.
                    </p>
                </div>
            </body>
            </html>
            """
            
            # Plain text fallback
            text_body = f"""
New Support Ticket: {ticket_id}
================================

From: {request.name or 'Not provided'}
Email: {request.email}
Subject: {request.subject}
Time: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}

Message:
{request.message}

---
Reply directly to this email to respond to the customer.
            """
            
            msg.attach(MIMEText(text_body, 'plain'))
            msg.attach(MIMEText(html_body, 'html'))
            
            # Send email via SMTP SSL
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                server.login(SUPPORT_EMAIL, smtp_password)
                server.send_message(msg)
            
            logger.info(f"Support ticket {ticket_id} created and email sent")
            
            # Also send confirmation to user
            try:
                user_msg = MIMEMultipart('alternative')
                user_msg['Subject'] = f"We received your support request [{ticket_id}]"
                user_msg['From'] = SUPPORT_EMAIL
                user_msg['To'] = request.email
                
                user_html = f"""
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                        <h2 style="color: #4F46E5;">Thanks for reaching out!</h2>
                        
                        <p>Hi{' ' + request.name if request.name else ''},</p>
                        
                        <p>We've received your support request and our team will get back to you within 24 hours.</p>
                        
                        <div style="background: #F3F4F6; padding: 15px; border-radius: 8px; margin: 20px 0;">
                            <p><strong>Ticket ID:</strong> {ticket_id}</p>
                            <p><strong>Subject:</strong> {request.subject}</p>
                        </div>
                        
                        <p>In the meantime, you might find answers in our <a href="https://hub.arrotechsolutions.com/help" style="color: #4F46E5;">Help Center</a>.</p>
                        
                        <p style="margin-top: 30px;">
                            Best regards,<br>
                            <strong>Arrotech Hub Support Team</strong>
                        </p>
                        
                        <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 30px 0;">
                        
                        <p style="color: #6B7280; font-size: 12px;">
                            If you have additional information to add, simply reply to this email.
                        </p>
                    </div>
                </body>
                </html>
                """
                
                user_msg.attach(MIMEText(user_html, 'html'))
                
                with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
                    server.login(SUPPORT_EMAIL, smtp_password)
                    server.send_message(user_msg)
                    
                logger.info(f"Confirmation email sent to {request.email}")
            except Exception as e:
                logger.warning(f"Failed to send user confirmation: {e}")
                # Don't fail the request if user confirmation fails
        else:
            # No SMTP configured - just log the ticket
            logger.warning("SMTP not configured, ticket logged but email not sent")
            logger.info(f"Support ticket {ticket_id}: {request.email} - {request.subject}")
        
        return SupportTicketResponse(
            message="Support request submitted successfully. We'll get back to you within 24 hours.",
            ticket_id=ticket_id
        )
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP authentication failed: {e}")
        # Still return success - we don't want to leak auth errors to users
        return SupportTicketResponse(
            message="Support request received. We'll get back to you soon.",
            ticket_id=ticket_id
        )
    except Exception as e:
        logger.error(f"Failed to create support ticket: {e}")
        raise HTTPException(status_code=500, detail="Failed to submit support request. Please try again or email support@arrotechsolutions.com directly.")
