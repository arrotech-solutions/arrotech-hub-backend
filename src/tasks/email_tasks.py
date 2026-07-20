"""
Email Tasks — Celery wrappers around EmailService.

Provides reliable, retryable email delivery. All email-sending call sites
should use these tasks instead of asyncio.create_task() fire-and-forget.

Queue: default
Retry: 3 attempts with exponential backoff (60s, 120s, 240s)
"""

import logging
from src.celery_app import app
from .utils import run_async as _run_async

logger = logging.getLogger(__name__)


@app.task(
    name="src.tasks.email_tasks.send_email_task",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    acks_late=True,
)
def send_email_task(self, to_email: str, subject: str, html_content: str, text_content: str = None):
    """Send a generic email with retry guarantees."""
    import asyncio
    from src.services.email_service import email_service

    logger.info(f"[CeleryEmail] Sending email to {to_email}: {subject[:50]}")

    result = _run_async(email_service.send_email(to_email, subject, html_content, text_content))
    if not result:
        raise RuntimeError(f"Email send returned False for {to_email}")
    return {"status": "sent", "to": to_email}


@app.task(
    name="src.tasks.email_tasks.send_welcome_email_task",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def send_welcome_email_task(self, to_email: str, user_name: str):
    """Send welcome email to new users."""
    from src.services.email_service import email_service

    result = _run_async(email_service.send_welcome_email(to_email, user_name))
    return {"status": "sent" if result else "failed", "to": to_email}


@app.task(
    name="src.tasks.email_tasks.send_password_reset_email_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def send_password_reset_email_task(self, to_email: str, reset_token: str, reset_url: str):
    """Send password reset email."""
    from src.services.email_service import email_service

    result = _run_async(email_service.send_password_reset_email(to_email, reset_token, reset_url))
    return {"status": "sent" if result else "failed", "to": to_email}


@app.task(
    name="src.tasks.email_tasks.send_2fa_otp_email_task",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def send_2fa_otp_email_task(self, to_email: str, otp: str):
    """Send 2FA OTP code via email. Lower retry delay since OTPs are time-sensitive."""
    from src.services.email_service import email_service

    result = _run_async(email_service.send_2fa_otp_email(to_email, otp))
    return {"status": "sent" if result else "failed", "to": to_email}


@app.task(
    name="src.tasks.email_tasks.send_email_verification_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def send_email_verification_task(self, to_email: str, user_name: str, otp: str):
    """Send email verification OTP to newly registered users."""
    from src.services.email_service import email_service

    result = _run_async(email_service.send_email_verification(to_email, user_name, otp))
    return {"status": "sent" if result else "failed", "to": to_email}


@app.task(
    name="src.tasks.email_tasks.send_org_invitation_email_task",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def send_org_invitation_email_task(
    self, to_email: str, org_name: str, inviter_name: str, role: str, invite_url: str
):
    """Send organization invitation email."""
    from src.services.email_service import email_service

    result = _run_async(email_service.send_org_invitation_email(to_email, org_name, inviter_name, role, invite_url))
    return {"status": "sent" if result else "failed", "to": to_email}


@app.task(
    name="src.tasks.email_tasks.send_payment_notification_task",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def send_payment_notification_task(
    self, to_email: str, user_name: str, amount: float,
    currency: str, payment_method: str, item_name: str
):
    """Send payment confirmation email."""
    from src.services.email_service import email_service

    result = _run_async(email_service.send_payment_received_notification(
                to_email, user_name, amount, currency, payment_method, item_name)
        )
    return {"status": "sent" if result else "failed", "to": to_email}
