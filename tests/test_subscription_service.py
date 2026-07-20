"""Tests for subscription_plans and subscription_service."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from src.models import SubscriptionStatus, SubscriptionTier
from src.services.subscription_plans import (
    get_period_days,
    get_price,
    resolve_plan_slug,
    validate_amount,
)
from src.services.subscription_service import SubscriptionService, TRIAL_DAYS


def _user(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "subscription_tier": SubscriptionTier.FREE,
        "subscription_status": SubscriptionStatus.ACTIVE,
        "subscription_end_date": None,
        "billing_cycle": "monthly",
        "cancel_at_period_end": False,
        "auto_renew_enabled": True,
        "trial_started_at": None,
        "last_payment_at": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestSubscriptionPlans:
    def test_resolve_starter_from_display_name(self):
        assert resolve_plan_slug("Starter", 1500, "monthly") == "starter"

    def test_resolve_starter_from_lite_alias(self):
        assert resolve_plan_slug("lite", 1500, "monthly") == "starter"

    def test_resolve_starter_from_amount_not_lite(self):
        assert resolve_plan_slug(None, 1500, "monthly") == "starter"

    def test_resolve_business_from_amount(self):
        assert resolve_plan_slug(None, 5000, "monthly") == "business"

    def test_yearly_starter_price(self):
        assert get_price("starter", "yearly") == 14400
        assert validate_amount("starter", "yearly", 14400)

    def test_monthly_period_days(self):
        assert get_period_days("monthly") == 30
        assert get_period_days("yearly") == 365


class TestSubscriptionServiceEffectiveTier:
    def test_trial_returns_starter(self):
        now = datetime.now(timezone.utc)
        user = _user(
            subscription_tier=SubscriptionTier.STARTER,
            subscription_status=SubscriptionStatus.TRIAL,
            subscription_end_date=now + timedelta(days=3),
        )
        assert SubscriptionService.get_effective_tier(user, now) == SubscriptionTier.STARTER

    def test_expired_trial_returns_free(self):
        now = datetime.now(timezone.utc)
        user = _user(
            subscription_tier=SubscriptionTier.STARTER,
            subscription_status=SubscriptionStatus.TRIAL,
            subscription_end_date=now - timedelta(days=1),
        )
        assert SubscriptionService.get_effective_tier(user, now) == SubscriptionTier.FREE

    def test_active_paid_returns_tier(self):
        now = datetime.now(timezone.utc)
        user = _user(
            subscription_tier=SubscriptionTier.STARTER,
            subscription_status=SubscriptionStatus.ACTIVE,
            subscription_end_date=now + timedelta(days=20),
        )
        assert SubscriptionService.get_effective_tier(user, now) == SubscriptionTier.STARTER

    def test_expired_paid_returns_free(self):
        now = datetime.now(timezone.utc)
        user = _user(
            subscription_tier=SubscriptionTier.STARTER,
            subscription_status=SubscriptionStatus.ACTIVE,
            subscription_end_date=now - timedelta(days=1),
        )
        assert SubscriptionService.get_effective_tier(user, now) == SubscriptionTier.FREE

    def test_canceled_before_end_keeps_access(self):
        now = datetime.now(timezone.utc)
        user = _user(
            subscription_tier=SubscriptionTier.BUSINESS,
            subscription_status=SubscriptionStatus.CANCELED,
            subscription_end_date=now + timedelta(days=10),
        )
        assert SubscriptionService.get_effective_tier(user, now) == SubscriptionTier.BUSINESS


class TestSubscriptionServiceActivation:
    @pytest.mark.asyncio
    async def test_activate_monthly_starter(self):
        now = datetime.now(timezone.utc)
        user = _user(
            subscription_tier=SubscriptionTier.FREE,
            subscription_status=SubscriptionStatus.TRIAL,
            subscription_end_date=None,
        )
        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        from src.services.subscription_service import PaymentActivationData

        with patch.object(SubscriptionService, "_now", return_value=now):
            result = await SubscriptionService.activate_from_payment(
                user,
                SubscriptionTier.STARTER,
                "monthly",
                PaymentActivationData(
                    transaction_id="txn_123",
                    reference="ref_123",
                    amount_kes=1500,
                ),
                db,
            )

        assert result["success"] is True
        assert user.subscription_tier == SubscriptionTier.STARTER
        assert user.subscription_status == SubscriptionStatus.ACTIVE
        assert user.billing_cycle == "monthly"
        assert user.subscription_end_date == now + timedelta(days=30)

    @pytest.mark.asyncio
    async def test_idempotent_payment_skips_double_extend(self):
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=15)
        user = _user(
            subscription_tier=SubscriptionTier.STARTER,
            subscription_status=SubscriptionStatus.ACTIVE,
            subscription_end_date=end,
        )
        existing_payment = MagicMock()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing_payment)))

        from src.services.subscription_service import PaymentActivationData

        result = await SubscriptionService.activate_from_payment(
            user,
            SubscriptionTier.STARTER,
            "monthly",
            PaymentActivationData(
                transaction_id="txn_dup",
                reference="ref_dup",
                amount_kes=1500,
            ),
            db,
        )
        assert result["success"] is True
        assert "already processed" in result.get("message", "").lower()
        assert user.subscription_end_date == end

    @pytest.mark.asyncio
    async def test_yearly_activation_365_days(self):
        now = datetime.now(timezone.utc)
        user = _user(subscription_tier=SubscriptionTier.FREE)
        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        from src.services.subscription_service import PaymentActivationData

        with patch.object(SubscriptionService, "_now", return_value=now):
            result = await SubscriptionService.activate_from_payment(
                user,
                SubscriptionTier.STARTER,
                "yearly",
                PaymentActivationData(
                    transaction_id="txn_yr",
                    reference="ref_yr",
                    amount_kes=14400,
                ),
                db,
            )

        assert result["success"] is True
        assert user.subscription_end_date == now + timedelta(days=365)


class TestTrialDuration:
    def test_trial_days_constant(self):
        assert TRIAL_DAYS == 7
