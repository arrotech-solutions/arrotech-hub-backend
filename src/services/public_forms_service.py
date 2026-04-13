"""
Public Forms Service — Centralized contact form and newsletter handling for all Arrotech websites.

Handles:
- Contact form submissions with smart email routing
- Newsletter subscriptions with unsubscribe tokens
- Auto-confirmation emails to senders
- Branded HTML email templates
"""

import logging
import os
import secrets
import smtplib
import socket
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Email Routing Configuration
# =============================================================================

# Category → (target mailbox, reply-to address, team display name)
EMAIL_ROUTING: Dict[str, Tuple[str, str]] = {
    "general":     ("info@arrotechsolutions.com",    "General Inquiries"),
    "sales":       ("sales@arrotechsolutions.com",   "Sales Team"),
    "partnership": ("sales@arrotechsolutions.com",   "Partnerships"),
    "support":     ("support@arrotechsolutions.com", "Support Team"),
    "billing":     ("billing@arrotechsolutions.com", "Billing Team"),
}


class PublicFormsService:
    """Centralized service for handling public form submissions across all Arrotech websites."""

    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST", "smtppro.zoho.com")
        self.smtp_port = 465  # SSL

        # Per-account SMTP credentials
        self._smtp_passwords = {
            "noreply@arrotechsolutions.com": os.getenv("NOREPLY_SMTP_PASSWORD") or os.getenv("SMTP_PASSWORD", ""),
            "info@arrotechsolutions.com": os.getenv("INFO_SMTP_PASSWORD") or os.getenv("SMTP_PASSWORD", ""),
            "sales@arrotechsolutions.com": os.getenv("SALES_SMTP_PASSWORD") or os.getenv("SMTP_PASSWORD", ""),
            "billing@arrotechsolutions.com": os.getenv("BILLING_SMTP_PASSWORD") or os.getenv("SMTP_PASSWORD", ""),
            "support@arrotechsolutions.com": os.getenv("SUPPORT_EMAIL_PASSWORD") or os.getenv("SMTP_PASSWORD", ""),
        }

        self.noreply_email = "noreply@arrotechsolutions.com"
        self.frontend_url = os.getenv("FRONTEND_URL", "https://hub.arrotechsolutions.com")
        self.api_base_url = os.getenv("API_BASE_URL", "https://prod.api.arrotechsolutions.com")

        logger.info(
            f"[PublicFormsService] Initialized. SMTP={self.smtp_host}:{self.smtp_port}, "
            f"accounts configured: {sum(1 for v in self._smtp_passwords.values() if v)}/5"
        )

    # =========================================================================
    # Core Email Sending
    # =========================================================================

    def _send_smtp(self, from_email: str, msg: MIMEMultipart) -> None:
        """Send email via SMTP SSL. Blocking — call from thread pool."""
        password = self._smtp_passwords.get(from_email, "")
        if not password:
            logger.error(f"[SMTP] No password configured for {from_email}")
            raise ValueError(f"No SMTP password for {from_email}")

        # Resolve to IPv4 to avoid IPv6 issues on some hosts
        try:
            ipv4_addrs = socket.getaddrinfo(self.smtp_host, self.smtp_port, socket.AF_INET, socket.SOCK_STREAM)
            connect_host = ipv4_addrs[0][4][0] if ipv4_addrs else self.smtp_host
        except Exception:
            connect_host = self.smtp_host

        try:
            server = smtplib.SMTP_SSL(connect_host, self.smtp_port, timeout=15)
            try:
                server.ehlo()
                server.login(from_email, password)
                server.send_message(msg)
                logger.info(f"[SMTP] Message sent from {from_email}")
            finally:
                try:
                    server.quit()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[SMTP] Failed sending from {from_email}: {type(e).__name__}: {e}")
            raise

    def _build_message(
        self,
        from_email: str,
        from_name: str,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> MIMEMultipart:
        """Build a MIME email message."""
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        if reply_to:
            msg["Reply-To"] = reply_to

        if text_content:
            msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))
        return msg

    # =========================================================================
    # Smart Email Routing
    # =========================================================================

    def get_route(self, category: str) -> Tuple[str, str]:
        """Get the target mailbox and team name for a given category.

        Returns:
            (target_email, team_name)
        """
        return EMAIL_ROUTING.get(category, EMAIL_ROUTING["general"])

    # =========================================================================
    # Contact Form Handling
    # =========================================================================

    def send_contact_notification(
        self,
        name: str,
        email: str,
        phone: Optional[str],
        category: str,
        subject: str,
        message: str,
        source_site: str,
        ticket_id: str,
    ) -> bool:
        """Send internal notification email to the appropriate team mailbox."""
        target_email, team_name = self.get_route(category)

        html = self._contact_internal_template(
            name=name,
            email=email,
            phone=phone,
            category=category,
            subject=subject,
            message=message,
            source_site=source_site,
            ticket_id=ticket_id,
            team_name=team_name,
        )

        text = (
            f"New Contact Form Submission [{ticket_id}]\n"
            f"{'='*50}\n\n"
            f"From: {name or 'Not provided'}\n"
            f"Email: {email}\n"
            f"Phone: {phone or 'Not provided'}\n"
            f"Category: {category}\n"
            f"Subject: {subject}\n"
            f"Source: {source_site}\n\n"
            f"Message:\n{message}\n\n"
            f"---\nReply directly to respond to the customer."
        )

        msg = self._build_message(
            from_email=self.noreply_email,
            from_name="Arrotech Contact Form",
            to_email=target_email,
            subject=f"[{ticket_id}] {subject or 'New Contact Submission'}",
            html_content=html,
            text_content=text,
            reply_to=email,  # Staff can reply directly to the sender
        )

        try:
            self._send_smtp(self.noreply_email, msg)
            return True
        except Exception:
            return False

    def send_contact_confirmation(
        self,
        name: str,
        email: str,
        subject: str,
        ticket_id: str,
    ) -> bool:
        """Send auto-confirmation email to the person who submitted the contact form."""
        html = self._contact_confirmation_template(name=name, subject=subject, ticket_id=ticket_id)

        text = (
            f"Hi {name or 'there'},\n\n"
            f"We received your message and our team will get back to you within 24 hours.\n\n"
            f"Ticket ID: {ticket_id}\n"
            f"Subject: {subject}\n\n"
            f"Best regards,\nArrotech Solutions"
        )

        msg = self._build_message(
            from_email=self.noreply_email,
            from_name="Arrotech Solutions",
            to_email=email,
            subject=f"We received your message [{ticket_id}]",
            html_content=html,
            text_content=text,
            reply_to="support@arrotechsolutions.com",
        )

        try:
            self._send_smtp(self.noreply_email, msg)
            return True
        except Exception:
            return False

    # =========================================================================
    # Newsletter Handling
    # =========================================================================

    @staticmethod
    def generate_unsubscribe_token() -> str:
        """Generate a secure unsubscribe token."""
        return secrets.token_urlsafe(48)

    def send_newsletter_welcome(self, email: str, name: Optional[str], unsubscribe_token: str) -> bool:
        """Send welcome email to new newsletter subscriber."""
        unsubscribe_url = f"{self.api_base_url}/api/public/unsubscribe?token={unsubscribe_token}"

        html = self._newsletter_welcome_template(name=name, unsubscribe_url=unsubscribe_url)

        text = (
            f"Hi {name or 'there'},\n\n"
            f"Thanks for subscribing to the Arrotech newsletter! "
            f"You'll receive the latest insights on AI, automation, and productivity.\n\n"
            f"To unsubscribe: {unsubscribe_url}\n\n"
            f"Best regards,\nArrotech Solutions"
        )

        msg = self._build_message(
            from_email=self.noreply_email,
            from_name="Arrotech Solutions",
            to_email=email,
            subject="✉️ Welcome to the Arrotech Newsletter!",
            html_content=html,
            text_content=text,
        )
        # Add List-Unsubscribe header (RFC 8058)
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        try:
            self._send_smtp(self.noreply_email, msg)
            return True
        except Exception:
            return False

    def send_subscriber_notification(self, subscriber_email: str, source_site: str) -> bool:
        """Send internal notification to info@ that a new subscriber signed up."""
        html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #8B5CF6 0%, #3B82F6 100%); padding: 24px; border-radius: 12px 12px 0 0;">
                <h2 style="color: white; margin: 0; font-size: 20px;">📬 New Newsletter Subscriber</h2>
            </div>
            <div style="background: #ffffff; padding: 24px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 12px 12px;">
                <p style="margin: 0 0 8px;"><strong>Email:</strong> {subscriber_email}</p>
                <p style="margin: 0 0 8px;"><strong>Source:</strong> {source_site}</p>
                <p style="margin: 0;"><strong>Time:</strong> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
            </div>
        </div>
        """

        msg = self._build_message(
            from_email=self.noreply_email,
            from_name="Arrotech Newsletter",
            to_email="info@arrotechsolutions.com",
            subject=f"📬 New subscriber: {subscriber_email}",
            html_content=html,
            text_content=f"New subscriber: {subscriber_email} from {source_site}",
        )

        try:
            self._send_smtp(self.noreply_email, msg)
            return True
        except Exception:
            return False

    # =========================================================================
    # HTML Email Templates
    # =========================================================================

    def _base_template(self, content: str, title: str = "Arrotech Solutions") -> str:
        """Base HTML email wrapper with Arrotech branding."""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{title}</title>
        </head>
        <body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color: #f8fafc;">
                <tr>
                    <td align="center" style="padding: 40px 20px;">
                        <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width: 600px; width: 100%;">
                            <!-- Header -->
                            <tr>
                                <td style="background: linear-gradient(135deg, #7C3AED 0%, #4F46E5 50%, #2563EB 100%); padding: 32px; border-radius: 16px 16px 0 0; text-align: center;">
                                    <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 700; letter-spacing: -0.025em;">Arrotech Solutions</h1>
                                    <p style="color: rgba(255,255,255,0.8); margin: 8px 0 0; font-size: 13px;">Intelligent AI Solutions for Modern Businesses</p>
                                </td>
                            </tr>
                            <!-- Content -->
                            <tr>
                                <td style="background: #ffffff; padding: 32px; border: 1px solid #e2e8f0; border-top: none;">
                                    {content}
                                </td>
                            </tr>
                            <!-- Footer -->
                            <tr>
                                <td style="background: #f1f5f9; padding: 24px 32px; border-radius: 0 0 16px 16px; border: 1px solid #e2e8f0; border-top: none; text-align: center;">
                                    <p style="margin: 0 0 8px; color: #64748b; font-size: 12px;">
                                        &copy; {datetime.now().year} Arrotech Solutions. All rights reserved.
                                    </p>
                                    <p style="margin: 0; color: #94a3b8; font-size: 11px;">
                                        Nairobi, Kenya &middot; <a href="https://arrotechsolutions.com" style="color: #7C3AED; text-decoration: none;">arrotechsolutions.com</a>
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

    def _contact_internal_template(
        self, name: str, email: str, phone: Optional[str],
        category: str, subject: str, message: str,
        source_site: str, ticket_id: str, team_name: str,
    ) -> str:
        """HTML template for internal contact form notification."""
        category_colors = {
            "general": "#3B82F6",
            "sales": "#10B981",
            "partnership": "#F59E0B",
            "support": "#EF4444",
            "billing": "#8B5CF6",
        }
        color = category_colors.get(category, "#3B82F6")

        content = f"""
        <div style="margin-bottom: 24px;">
            <span style="display: inline-block; background: {color}15; color: {color}; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; border: 1px solid {color}30;">
                {category.upper()}
            </span>
            <span style="display: inline-block; background: #f1f5f9; color: #64748b; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 500; margin-left: 8px;">
                {ticket_id}
            </span>
        </div>

        <h2 style="margin: 0 0 20px; color: #1e293b; font-size: 20px; font-weight: 700;">
            New Contact Submission
        </h2>

        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background: #f8fafc; border-radius: 12px; padding: 20px; margin-bottom: 20px;">
            <tr><td style="padding: 8px 16px;"><strong style="color: #64748b; font-size: 13px;">From:</strong> <span style="color: #1e293b;">{name or 'Not provided'}</span></td></tr>
            <tr><td style="padding: 8px 16px;"><strong style="color: #64748b; font-size: 13px;">Email:</strong> <a href="mailto:{email}" style="color: #4F46E5;">{email}</a></td></tr>
            <tr><td style="padding: 8px 16px;"><strong style="color: #64748b; font-size: 13px;">Phone:</strong> <span style="color: #1e293b;">{phone or 'Not provided'}</span></td></tr>
            <tr><td style="padding: 8px 16px;"><strong style="color: #64748b; font-size: 13px;">Subject:</strong> <span style="color: #1e293b;">{subject}</span></td></tr>
            <tr><td style="padding: 8px 16px;"><strong style="color: #64748b; font-size: 13px;">Source:</strong> <span style="color: #1e293b;">{source_site}</span></td></tr>
            <tr><td style="padding: 8px 16px;"><strong style="color: #64748b; font-size: 13px;">Time:</strong> <span style="color: #1e293b;">{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</span></td></tr>
        </table>

        <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin-bottom: 20px;">
            <h3 style="margin: 0 0 12px; color: #374151; font-size: 14px; font-weight: 600;">Message:</h3>
            <p style="margin: 0; color: #374151; line-height: 1.6; white-space: pre-wrap;">{message}</p>
        </div>

        <p style="color: #94a3b8; font-size: 12px; margin: 0;">
            💡 Reply directly to this email to respond to the customer.
        </p>
        """
        return self._base_template(content, f"Contact: {ticket_id}")

    def _contact_confirmation_template(self, name: str, subject: str, ticket_id: str) -> str:
        """HTML template for auto-reply confirmation to the sender."""
        content = f"""
        <h2 style="margin: 0 0 16px; color: #1e293b; font-size: 22px; font-weight: 700;">
            Thanks for reaching out! 👋
        </h2>

        <p style="color: #475569; line-height: 1.7; margin: 0 0 20px;">
            Hi {name or 'there'}, we've received your message and our team will get back to you within <strong>24 hours</strong>.
        </p>

        <div style="background: #f8fafc; border-radius: 12px; padding: 20px; margin: 0 0 24px; border: 1px solid #e2e8f0;">
            <p style="margin: 0 0 8px;"><strong style="color: #64748b; font-size: 13px;">Ticket ID:</strong> <span style="color: #1e293b; font-family: monospace; font-weight: 600;">{ticket_id}</span></p>
            <p style="margin: 0;"><strong style="color: #64748b; font-size: 13px;">Subject:</strong> <span style="color: #1e293b;">{subject}</span></p>
        </div>

        <p style="color: #475569; line-height: 1.7; margin: 0 0 24px;">
            In the meantime, you might find answers in our <a href="https://hub.arrotechsolutions.com/help" style="color: #4F46E5; text-decoration: none; font-weight: 600;">Help Center</a>.
        </p>

        <table role="presentation" cellpadding="0" cellspacing="0">
            <tr>
                <td style="border-radius: 10px; background: linear-gradient(135deg, #7C3AED, #4F46E5);">
                    <a href="https://arrotechsolutions.com" style="display: inline-block; padding: 14px 28px; color: #ffffff; text-decoration: none; font-weight: 600; font-size: 14px;">
                        Visit Arrotech Solutions →
                    </a>
                </td>
            </tr>
        </table>

        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 32px 0 16px;">

        <p style="color: #94a3b8; font-size: 12px; margin: 0;">
            If you have additional information to add, simply reply to this email.
        </p>
        """
        return self._base_template(content, "We received your message")

    def _newsletter_welcome_template(self, name: Optional[str], unsubscribe_url: str) -> str:
        """HTML template for newsletter welcome email."""
        content = f"""
        <h2 style="margin: 0 0 16px; color: #1e293b; font-size: 22px; font-weight: 700;">
            You're subscribed! 🎉
        </h2>

        <p style="color: #475569; line-height: 1.7; margin: 0 0 20px;">
            Hi {name or 'there'}, thanks for subscribing to the Arrotech newsletter!
            You'll receive the latest insights on:
        </p>

        <ul style="color: #475569; line-height: 2; padding-left: 20px; margin: 0 0 24px;">
            <li>🤖 <strong>AI & Automation</strong> — Latest trends and practical guides</li>
            <li>🚀 <strong>Product Updates</strong> — New features from Arrotech Hub</li>
            <li>📊 <strong>Business Insights</strong> — Data-driven strategies that work</li>
            <li>💡 <strong>Tips & Tutorials</strong> — Get the most out of our tools</li>
        </ul>

        <table role="presentation" cellpadding="0" cellspacing="0" style="margin: 0 0 32px;">
            <tr>
                <td style="border-radius: 10px; background: linear-gradient(135deg, #7C3AED, #4F46E5);">
                    <a href="https://arrotechsolutions.com/blog" style="display: inline-block; padding: 14px 28px; color: #ffffff; text-decoration: none; font-weight: 600; font-size: 14px;">
                        Read Our Latest Articles →
                    </a>
                </td>
            </tr>
        </table>

        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 0 0 16px;">

        <p style="color: #94a3b8; font-size: 11px; margin: 0; text-align: center;">
            You can <a href="{unsubscribe_url}" style="color: #7C3AED; text-decoration: none;">unsubscribe</a> at any time. No spam, ever.
        </p>
        """
        return self._base_template(content, "Welcome to the Arrotech Newsletter")


# Singleton instance
public_forms_service = PublicFormsService()
