"""
Celery tasks for subscription expiry, reminders, and auto-renewal.
"""

import logging
from datetime import datetime, timedelta, timezone

from src.celery_app import app
from .utils import run_async as _run_async

logger = logging.getLogger(__name__)


@app.task(
    name="src.tasks.subscription_tasks.process_subscription_expiry_task",
    bind=True,
    max_retries=1,
    acks_late=True,
    ignore_result=True,
)
def process_subscription_expiry_task(self):
    """Daily: grace period, expiry, trial end, workflow pause."""
    _run_async(_process_subscription_expiry())


@app.task(
    name="src.tasks.subscription_tasks.send_subscription_reminders_task",
    bind=True,
    max_retries=1,
    acks_late=True,
    ignore_result=True,
)
def send_subscription_reminders_task(self):
    """Daily: email reminders 7 days and 1 day before expiry."""
    _run_async(_send_subscription_reminders())


@app.task(
    name="src.tasks.subscription_tasks.attempt_subscription_renewal_task",
    bind=True,
    max_retries=1,
    acks_late=True,
    ignore_result=True,
)
def attempt_subscription_renewal_task(self):
    """Daily: auto-charge Paystack authorization ~3 days before expiry."""
    _run_async(_attempt_subscription_renewal())


async def _process_subscription_expiry():
    from src.config import settings
    from src.database import get_session_maker
    from src.models import SubscriptionStatus, SubscriptionTier, User
    from src.services.subscription_service import subscription_service
    from sqlalchemy import and_, select

    now = datetime.now(timezone.utc)
    grace_days = getattr(settings, "SUBSCRIPTION_GRACE_DAYS", 3) or 0
    session_maker = get_session_maker()

    async with session_maker() as db:
        result = await db.execute(
            select(User).where(
                and_(
                    User.subscription_tier != SubscriptionTier.FREE,
                    User.subscription_end_date.isnot(None),
                    User.subscription_end_date < now,
                    User.subscription_status != SubscriptionStatus.EXPIRED,
                    User.subscription_status != SubscriptionStatus.TRIAL,
                )
            )
        )
        users = result.scalars().all()

        for user in users:
            end_date = user.subscription_end_date
            if end_date and end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)

            if grace_days > 0 and user.subscription_status not in (
                SubscriptionStatus.GRACE_PERIOD,
                SubscriptionStatus.PAST_DUE,
            ):
                grace_end = end_date + timedelta(days=grace_days)
                if now <= grace_end:
                    await subscription_service.enter_grace_period(user, db)
                    logger.info("User %s entered grace period", user.id)
                    continue

            await subscription_service.expire_user(user, db)
            try:
                from src.services.email_service import email_service
                await email_service.send_email(
                    to_email=user.email,
                    subject="Your Arrotech Hub subscription has expired",
                    html_content=(
                        f"<p>Hi {user.name},</p>"
                        "<p>Your subscription has ended and your account has been moved to the Free plan. "
                        "Renew anytime at <a href=\"https://hub.arrotechsolutions.com/pricing\">Pricing</a>.</p>"
                        "<p>— Arrotech Hub</p>"
                    ),
                    text_content=(
                        f"Hi {user.name},\n\n"
                        "Your subscription has ended and your account has been moved to the Free plan. "
                        "Renew anytime at https://hub.arrotechsolutions.com/pricing\n\n"
                        "— Arrotech Hub"
                    ),
                )
            except Exception as e:
                logger.error("Failed to send expiry email to %s: %s", user.email, e)

        trial_result = await db.execute(
            select(User).where(
                and_(
                    User.subscription_status == SubscriptionStatus.TRIAL,
                    User.subscription_end_date.isnot(None),
                    User.subscription_end_date < now,
                )
            )
        )
        for user in trial_result.scalars().all():
            user.subscription_status = SubscriptionStatus.EXPIRED
            user.subscription_tier = SubscriptionTier.FREE
            db.add(user)
        await db.commit()


async def _send_subscription_reminders():
    from src.database import get_session_maker
    from src.models import SubscriptionStatus, SubscriptionTier, User
    from src.services.subscription_service import subscription_service
    from sqlalchemy import and_, select

    now = datetime.now(timezone.utc)
    windows = [(7, "7 days"), (1, "1 day")]
    session_maker = get_session_maker()

    async with session_maker() as db:
        for days, label in windows:
            target_start = now + timedelta(days=days)
            target_end = target_start + timedelta(days=1)
            result = await db.execute(
                select(User).where(
                    and_(
                        User.subscription_status == SubscriptionStatus.ACTIVE,
                        User.subscription_tier != SubscriptionTier.FREE,
                        User.subscription_end_date >= target_start,
                        User.subscription_end_date < target_end,
                    )
                )
            )
            for user in result.scalars().all():
                try:
                    from src.services.email_service import email_service
                    snap = subscription_service.build_status_snapshot(user, now)
                    await email_service.send_email(
                        to_email=user.email,
                        subject=f"Your Arrotech Hub plan renews in {label}",
                        html_content=(
                            f"<p>Hi {user.name},</p>"
                            f"<p>Your {snap['tier']} plan expires on {snap['end_date']}. "
                            "Visit Payments in your dashboard to renew or manage auto-renew.</p>"
                            "<p>— Arrotech Hub</p>"
                        ),
                        text_content=(
                            f"Hi {user.name},\n\n"
                            f"Your {snap['tier']} plan expires on {snap['end_date']}. "
                            "Visit Payments in your dashboard to renew or manage auto-renew.\n\n"
                            "— Arrotech Hub"
                        ),
                    )
                except Exception as e:
                    logger.error("Reminder email failed for %s: %s", user.email, e)


async def _attempt_subscription_renewal():
    import requests
    from src.config import settings
    from src.database import get_session_maker
    from src.models import SubscriptionStatus, SubscriptionTier, User
    from src.services.payment_service import PaymentService
    from src.services.subscription_plans import get_price
    from sqlalchemy import and_, select

    if not settings.PAYSTACK_SECRET_KEY:
        return

    now = datetime.now(timezone.utc)
    renewal_window_start = now + timedelta(days=3)
    renewal_window_end = now + timedelta(days=4)
    payment_service = PaymentService()
    session_maker = get_session_maker()

    async with session_maker() as db:
        result = await db.execute(
            select(User).where(
                and_(
                    User.subscription_status == SubscriptionStatus.ACTIVE,
                    User.auto_renew_enabled.is_(True),
                    User.paystack_authorization_code.isnot(None),
                    User.subscription_tier.in_([
                        SubscriptionTier.STARTER,
                        SubscriptionTier.BUSINESS,
                        SubscriptionTier.PRO,
                    ]),
                    User.subscription_end_date >= renewal_window_start,
                    User.subscription_end_date < renewal_window_end,
                )
            )
        )
        users = result.scalars().all()

        for user in users:
            billing_cycle = getattr(user, "billing_cycle", None) or "monthly"
            amount = get_price(user.subscription_tier, billing_cycle)
            if not amount:
                continue

            try:
                response = requests.post(
                    "https://api.paystack.co/transaction/charge_authorization",
                    headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
                    json={
                        "authorization_code": user.paystack_authorization_code,
                        "email": user.email,
                        "amount": amount * 100,
                        "currency": "KES",
                        "metadata": {
                            "user_id": str(user.id),
                            "plan_id": user.subscription_tier,
                            "billing_cycle": billing_cycle,
                            "auto_renew": True,
                        },
                    },
                    timeout=30,
                )
                body = response.json()
                if not body.get("status") or body.get("data", {}).get("status") != "success":
                    from src.services.subscription_service import subscription_service
                    await subscription_service.set_past_due(user, db)
                    logger.warning("Auto-renew failed for user %s: %s", user.id, body)
                    continue

                data = body["data"]
                metadata = data.get("metadata") or {
                    "user_id": str(user.id),
                    "plan_id": user.subscription_tier,
                    "billing_cycle": billing_cycle,
                }
                await payment_service._activate_paystack_charge(
                    user=user,
                    data=data,
                    reference=data.get("reference", ""),
                    amount_kes=(data.get("amount") or 0) / 100,
                    metadata=metadata,
                    db=db,
                )
                logger.info("Auto-renewed subscription for user %s", user.id)
            except Exception as e:
                from src.services.subscription_service import subscription_service
                logger.error("Auto-renew error for user %s: %s", user.id, e)
                await subscription_service.set_past_due(user, db)
