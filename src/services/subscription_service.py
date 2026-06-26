"""
Central subscription lifecycle service.
All activation, expiry, trial, and tier resolution flows through here.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import (
    Payment,
    Subscription,
    SubscriptionStatus,
    SubscriptionTier,
    User,
    Workflow,
    WorkflowStatus,
)
from .feature_flags import PLAN_LIMITS
from .subscription_plans import (
    get_period_days,
    normalize_billing_cycle,
    normalize_plan_slug,
    resolve_plan_slug,
    validate_amount,
)

logger = logging.getLogger(__name__)

TRIAL_DAYS = 7
PAID_ACCESS_STATUSES = {
    SubscriptionStatus.ACTIVE,
    SubscriptionStatus.CANCELED,
    SubscriptionStatus.GRACE_PERIOD,
    SubscriptionStatus.PAST_DUE,
}


@dataclass
class PaymentActivationData:
    transaction_id: str
    reference: str
    amount_kes: float
    currency: str = "KES"
    plan_id: Optional[str] = None
    billing_cycle: str = "monthly"
    metadata: Optional[Dict[str, Any]] = None
    paystack_customer_code: Optional[str] = None
    paystack_authorization_code: Optional[str] = None


class SubscriptionService:
    """Authoritative subscription state machine."""

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _ensure_aware(dt: Optional[datetime]) -> Optional[datetime]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @classmethod
    def get_effective_tier(cls, user: User, now: Optional[datetime] = None) -> str:
        now = now or cls._now()
        end_date = cls._ensure_aware(user.subscription_end_date)
        status = user.subscription_status or SubscriptionStatus.ACTIVE

        if status == SubscriptionStatus.TRIAL:
            if end_date and end_date > now:
                return SubscriptionTier.STARTER
            return SubscriptionTier.FREE

        tier = (user.subscription_tier or SubscriptionTier.FREE).lower()
        if tier == SubscriptionTier.FREE:
            return SubscriptionTier.FREE

        if end_date and end_date > now and status in PAID_ACCESS_STATUSES:
            return tier

        return SubscriptionTier.FREE

    @classmethod
    def is_subscription_active(cls, user: User, now: Optional[datetime] = None) -> bool:
        return cls.get_effective_tier(user, now) != SubscriptionTier.FREE

    @classmethod
    def days_remaining(cls, user: User, now: Optional[datetime] = None) -> Optional[int]:
        now = now or cls._now()
        end_date = cls._ensure_aware(user.subscription_end_date)
        if not end_date:
            return None
        delta = end_date - now
        return max(0, delta.days)

    @classmethod
    def build_status_snapshot(cls, user: User, now: Optional[datetime] = None) -> Dict[str, Any]:
        now = now or cls._now()
        effective = cls.get_effective_tier(user, now)
        status = user.subscription_status or SubscriptionStatus.ACTIVE
        return {
            "tier": user.subscription_tier,
            "effective_tier": effective,
            "status": status,
            "billing_cycle": getattr(user, "billing_cycle", None) or "monthly",
            "end_date": user.subscription_end_date.isoformat() if user.subscription_end_date else None,
            "days_remaining": cls.days_remaining(user, now),
            "is_trial": status == SubscriptionStatus.TRIAL,
            "is_active": cls.is_subscription_active(user, now),
            "cancel_at_period_end": bool(getattr(user, "cancel_at_period_end", False)),
            "auto_renew_enabled": bool(getattr(user, "auto_renew_enabled", True)),
            "trial_started_at": (
                user.trial_started_at.isoformat()
                if getattr(user, "trial_started_at", None)
                else None
            ),
            "last_payment_at": (
                user.last_payment_at.isoformat()
                if getattr(user, "last_payment_at", None)
                else None
            ),
        }

    @classmethod
    def extend_period(
        cls,
        user: User,
        days: int,
        from_date: Optional[datetime] = None,
    ) -> datetime:
        now = from_date or cls._now()
        current_end = cls._ensure_aware(user.subscription_end_date)
        status = user.subscription_status or SubscriptionStatus.ACTIVE
        # Trial or lapsed: start fresh from now; active paid: stack
        if (
            current_end
            and current_end > now
            and status in PAID_ACCESS_STATUSES
            and status != SubscriptionStatus.TRIAL
        ):
            new_end = current_end + timedelta(days=days)
        else:
            new_end = now + timedelta(days=days)
        user.subscription_end_date = new_end
        return new_end

    @classmethod
    async def start_trial(cls, user: User, db: AsyncSession) -> None:
        now = cls._now()
        user.subscription_tier = SubscriptionTier.STARTER
        user.subscription_status = SubscriptionStatus.TRIAL
        user.subscription_end_date = now + timedelta(days=TRIAL_DAYS)
        user.trial_started_at = now
        user.billing_cycle = "monthly"
        user.cancel_at_period_end = False
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info("Started %d-day trial for user %s", TRIAL_DAYS, user.id)

    @classmethod
    async def activate_from_payment(
        cls,
        user: User,
        plan_id: str,
        billing_cycle: str,
        payment_data: PaymentActivationData,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Idempotent subscription activation from a successful payment."""
        billing_cycle = normalize_billing_cycle(billing_cycle)
        plan_id = normalize_plan_slug(plan_id) or plan_id

        if plan_id not in (
            SubscriptionTier.STARTER,
            SubscriptionTier.BUSINESS,
            SubscriptionTier.PRO,
        ):
            return {"success": False, "error": f"Invalid plan: {plan_id}"}

        if not validate_amount(plan_id, billing_cycle, payment_data.amount_kes):
            logger.warning(
                "Amount mismatch for user %s: plan=%s cycle=%s amount=%s",
                user.id,
                plan_id,
                billing_cycle,
                payment_data.amount_kes,
            )
            return {
                "success": False,
                "error": "Payment amount does not match selected plan",
            }

        # Idempotency: skip if payment already recorded
        existing = await db.execute(
            select(Payment).where(Payment.transaction_id == payment_data.transaction_id)
        )
        existing_payment = existing.scalar_one_or_none()
        if existing_payment:
            logger.info("Payment %s already processed", payment_data.transaction_id)
            return {
                "success": True,
                "message": "Payment already processed",
                "subscription": cls.build_status_snapshot(user),
            }

        now = cls._now()
        period_days = get_period_days(billing_cycle)
        period_start = now
        new_end = cls.extend_period(user, period_days, now)

        user.subscription_tier = plan_id
        user.subscription_status = SubscriptionStatus.ACTIVE
        user.billing_cycle = billing_cycle
        user.cancel_at_period_end = False
        user.last_payment_at = now

        if payment_data.paystack_customer_code:
            user.paystack_customer_code = payment_data.paystack_customer_code
        if payment_data.paystack_authorization_code:
            user.paystack_authorization_code = payment_data.paystack_authorization_code

        payment = Payment(
            user_id=user.id,
            payment_method="paystack",
            amount=int(round(payment_data.amount_kes)),
            currency=payment_data.currency,
            status="completed",
            transaction_id=payment_data.transaction_id,
            reference=payment_data.reference,
            payment_metadata={
                "plan_id": plan_id,
                "billing_cycle": billing_cycle,
                "reference": payment_data.reference,
                "raw_metadata": payment_data.metadata or {},
            },
        )
        db.add(payment)
        await db.flush()

        sub_record = Subscription(
            user_id=user.id,
            tier=plan_id,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=period_start,
            current_period_end=new_end,
            billing_cycle=billing_cycle,
            payment_id=payment.id,
            paystack_reference=payment_data.reference,
        )
        db.add(sub_record)
        await db.commit()
        await db.refresh(user)

        logger.info(
            "Activated subscription user=%s tier=%s cycle=%s end=%s",
            user.id,
            plan_id,
            billing_cycle,
            new_end,
        )
        return {
            "success": True,
            "subscription": cls.build_status_snapshot(user),
            "new_end_date": new_end.isoformat(),
            "tier": plan_id,
        }

    @classmethod
    async def cancel_at_period_end(cls, user: User, db: AsyncSession) -> Dict[str, Any]:
        if user.subscription_tier == SubscriptionTier.FREE:
            return {"success": False, "error": "No active paid subscription"}
        if user.subscription_status == SubscriptionStatus.CANCELED:
            return {"success": False, "error": "Already canceled"}

        user.subscription_status = SubscriptionStatus.CANCELED
        user.cancel_at_period_end = True
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return {"success": True, "subscription": cls.build_status_snapshot(user)}

    @classmethod
    async def reactivate(cls, user: User, db: AsyncSession) -> Dict[str, Any]:
        now = cls._now()
        end_date = cls._ensure_aware(user.subscription_end_date)
        if user.subscription_status != SubscriptionStatus.CANCELED:
            return {"success": False, "error": "Subscription is not canceled"}
        if not end_date or end_date <= now:
            return {"success": False, "error": "Subscription has expired"}

        user.subscription_status = SubscriptionStatus.ACTIVE
        user.cancel_at_period_end = False
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return {"success": True, "subscription": cls.build_status_snapshot(user)}

    @classmethod
    async def expire_user(cls, user: User, db: AsyncSession) -> None:
        """Downgrade expired user to free and pause excess workflows."""
        user.subscription_tier = SubscriptionTier.FREE
        user.subscription_status = SubscriptionStatus.EXPIRED
        user.cancel_at_period_end = False
        db.add(user)

        free_limits = PLAN_LIMITS[SubscriptionTier.FREE]
        max_workflows = free_limits.get("max_active_workflows", 3)

        result = await db.execute(
            select(Workflow)
            .where(
                Workflow.user_id == user.id,
                Workflow.status == WorkflowStatus.ACTIVE,
            )
            .order_by(Workflow.created_at.desc())
        )
        active_workflows = result.scalars().all()
        for i, wf in enumerate(active_workflows):
            if i >= max_workflows:
                wf.status = WorkflowStatus.INACTIVE
                db.add(wf)

        await db.commit()
        logger.info("Expired subscription for user %s", user.id)

    @classmethod
    async def enter_grace_period(cls, user: User, db: AsyncSession) -> None:
        user.subscription_status = SubscriptionStatus.GRACE_PERIOD
        db.add(user)
        await db.commit()

    @classmethod
    async def set_past_due(cls, user: User, db: AsyncSession) -> None:
        user.subscription_status = SubscriptionStatus.PAST_DUE
        db.add(user)
        await db.commit()

    @classmethod
    async def admin_set_subscription(
        cls,
        user: User,
        tier: str,
        status: str,
        end_date: datetime,
        billing_cycle: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        user.subscription_tier = tier
        user.subscription_status = status
        user.subscription_end_date = end_date
        user.billing_cycle = normalize_billing_cycle(billing_cycle)
        user.cancel_at_period_end = status == SubscriptionStatus.CANCELED
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info(
            "Admin set subscription user=%s tier=%s status=%s end=%s",
            user.id,
            tier,
            status,
            end_date,
        )
        return {"success": True, "subscription": cls.build_status_snapshot(user)}

    @classmethod
    def resolve_plan_from_paystack_metadata(
        cls,
        metadata: Dict[str, Any],
        amount_kes: float,
    ) -> tuple[Optional[str], str]:
        billing_cycle = normalize_billing_cycle(metadata.get("billing_cycle"))
        plan_id = metadata.get("plan_id")

        if not plan_id and "custom_fields" in metadata:
            for field in metadata["custom_fields"]:
                var = field.get("variable_name", "")
                if var in ("plan_id", "plan"):
                    plan_id = field.get("value")
                    break

        if not plan_id:
            plan_id = metadata.get("plan")

        resolved = resolve_plan_slug(plan_id, amount_kes, billing_cycle)
        return resolved, billing_cycle


subscription_service = SubscriptionService()
