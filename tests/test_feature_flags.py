"""
Tests for src/services/feature_flags.py and src/services/tier_gate.py —
FeatureGate, PLAN_LIMITS, PLAN_PRICING, tier checking, and tier gate functions.
"""
import pytest
from unittest.mock import MagicMock


class TestPlanLimits:
    def test_plan_limits_has_all_tiers(self):
        from src.services.feature_flags import PLAN_LIMITS
        from src.models import SubscriptionTier
        assert SubscriptionTier.FREE in PLAN_LIMITS
        assert SubscriptionTier.STARTER in PLAN_LIMITS
        assert SubscriptionTier.BUSINESS in PLAN_LIMITS
        assert SubscriptionTier.PRO in PLAN_LIMITS
        assert SubscriptionTier.ENTERPRISE in PLAN_LIMITS

    def test_free_tier_limits(self):
        from src.services.feature_flags import PLAN_LIMITS
        from src.models import SubscriptionTier
        free = PLAN_LIMITS[SubscriptionTier.FREE]
        assert free["ai_actions_monthly"] == 100
        assert free["max_active_workflows"] == 3
        assert free["team_members"] == 1
        assert free["inbox_send"] is False
        assert free["inbox_read"] is True

    def test_starter_tier_limits(self):
        from src.services.feature_flags import PLAN_LIMITS
        from src.models import SubscriptionTier
        starter = PLAN_LIMITS[SubscriptionTier.STARTER]
        assert starter["ai_actions_monthly"] == 500
        assert starter["inbox_send"] is True
        assert starter["calendar_create_edit"] is True
        assert starter["tasks_create_update"] is True

    def test_business_tier_limits(self):
        from src.services.feature_flags import PLAN_LIMITS
        from src.models import SubscriptionTier
        biz = PLAN_LIMITS[SubscriptionTier.BUSINESS]
        assert biz["ai_actions_monthly"] == 2000
        assert biz["inbox_ai_reply"] is True
        assert biz["smart_scheduler"] is True
        assert biz["api_access"] is True

    def test_pro_tier_limits(self):
        from src.services.feature_flags import PLAN_LIMITS
        from src.models import SubscriptionTier
        pro = PLAN_LIMITS[SubscriptionTier.PRO]
        assert pro["ai_actions_monthly"] == 5000
        assert pro["inbox_multi_client"] is True
        assert pro["allowed_connections"] == ["*"]

    def test_enterprise_tier_limits(self):
        from src.services.feature_flags import PLAN_LIMITS
        from src.models import SubscriptionTier
        ent = PLAN_LIMITS[SubscriptionTier.ENTERPRISE]
        assert ent["white_label"] is True
        assert ent["sso"] is True
        assert ent["allowed_connections"] == ["*"]

    def test_tier_limits_monotonically_increase(self):
        from src.services.feature_flags import PLAN_LIMITS
        from src.models import SubscriptionTier
        tiers = [SubscriptionTier.FREE, SubscriptionTier.STARTER,
                 SubscriptionTier.BUSINESS, SubscriptionTier.PRO,
                 SubscriptionTier.ENTERPRISE]
        prev = 0
        for t in tiers:
            curr = PLAN_LIMITS[t]["ai_actions_monthly"]
            assert curr >= prev
            prev = curr


class TestPlanPricing:
    def test_pricing_has_all_tiers(self):
        from src.services.feature_flags import PLAN_PRICING
        from src.models import SubscriptionTier
        for t in SubscriptionTier:
            assert t in PLAN_PRICING

    def test_free_tier_price_is_zero(self):
        from src.services.feature_flags import PLAN_PRICING
        from src.models import SubscriptionTier
        assert PLAN_PRICING[SubscriptionTier.FREE]["price_monthly"] == 0

    def test_enterprise_price_is_custom(self):
        from src.services.feature_flags import PLAN_PRICING
        from src.models import SubscriptionTier
        assert PLAN_PRICING[SubscriptionTier.ENTERPRISE]["price_monthly"] is None

    def test_all_tiers_have_currency(self):
        from src.services.feature_flags import PLAN_PRICING
        for _, info in PLAN_PRICING.items():
            assert info["currency"] == "KES"


class TestAddonPricing:
    def test_addon_pricing_exists(self):
        from src.services.feature_flags import ADDON_PRICING
        assert "automation_runs_1000" in ADDON_PRICING
        assert "automation_runs_5000" in ADDON_PRICING

    def test_addon_pricing_values(self):
        from src.services.feature_flags import ADDON_PRICING
        assert ADDON_PRICING["automation_runs_1000"]["price"] == 500
        assert ADDON_PRICING["automation_runs_5000"]["runs"] == 5000


class TestFeatureGate:
    def _mock_user(self, tier="free"):
        user = MagicMock()
        user.subscription_tier = tier
        user.subscription_status = "active"
        user.subscription_end_date = None
        return user

    def test_get_limits_free(self):
        from src.services.feature_flags import FeatureGate
        limits = FeatureGate.get_limits("free")
        assert limits["ai_actions_monthly"] == 100
        assert limits["max_active_workflows"] == 3

    def test_get_limits_pro(self):
        from src.services.feature_flags import FeatureGate
        limits = FeatureGate.get_limits("pro")
        assert limits["ai_actions_monthly"] == 5000

    def test_get_limits_unknown_falls_back_to_free(self):
        from src.services.feature_flags import FeatureGate
        limits = FeatureGate.get_limits("nonexistent_tier")
        assert limits["ai_actions_monthly"] == 100

    def test_get_pricing_free(self):
        from src.services.feature_flags import FeatureGate
        pricing = FeatureGate.get_pricing("free")
        assert pricing["price_monthly"] == 0
        assert pricing["name"] == "Free"

    def test_get_pricing_business(self):
        from src.services.feature_flags import FeatureGate
        pricing = FeatureGate.get_pricing("business")
        assert pricing["price_monthly"] == 5000

    def test_can_activate_workflow_under_limit(self):
        from src.services.feature_flags import FeatureGate
        user = self._mock_user("free")
        assert FeatureGate.can_activate_workflow(user, 2) is True

    def test_can_activate_workflow_at_limit(self):
        from src.services.feature_flags import FeatureGate
        user = self._mock_user("free")
        assert FeatureGate.can_activate_workflow(user, 3) is False

    def test_can_use_ai_action_under_limit(self):
        from src.services.feature_flags import FeatureGate
        user = self._mock_user("free")
        assert FeatureGate.can_use_ai_action(user, 50) is True

    def test_can_use_ai_action_at_limit(self):
        from src.services.feature_flags import FeatureGate
        user = self._mock_user("free")
        assert FeatureGate.can_use_ai_action(user, 100) is False

    def test_can_use_automation_run(self):
        from src.services.feature_flags import FeatureGate
        user = self._mock_user("free")
        assert FeatureGate.can_use_automation_run(user, 0) is True
        assert FeatureGate.can_use_automation_run(user, 500) is False

    def test_has_connection_access_free_slack(self):
        from src.services.feature_flags import FeatureGate
        user = self._mock_user("free")
        assert FeatureGate.has_connection_access(user, "slack") is True

    def test_has_connection_access_free_hubspot_denied(self):
        from src.services.feature_flags import FeatureGate
        user = self._mock_user("free")
        assert FeatureGate.has_connection_access(user, "hubspot") is False

    def test_has_connection_access_pro_wildcard(self):
        from src.services.feature_flags import FeatureGate
        from unittest.mock import patch
        user = self._mock_user("pro")
        with patch.object(FeatureGate, "get_effective_tier", return_value="pro"):
            assert FeatureGate.has_connection_access(user, "anything") is True

    def test_has_feature_free_inbox_read(self):
        from src.services.feature_flags import FeatureGate
        user = self._mock_user("free")
        assert FeatureGate.has_feature(user, "inbox_read") is True

    def test_has_feature_free_inbox_send(self):
        from src.services.feature_flags import FeatureGate
        user = self._mock_user("free")
        assert FeatureGate.has_feature(user, "inbox_send") is False

    def test_get_provider_limit_free(self):
        from src.services.feature_flags import FeatureGate
        user = self._mock_user("free")
        assert FeatureGate.get_provider_limit(user, "email") == 1

    def test_get_provider_limit_business(self):
        from src.services.feature_flags import FeatureGate
        from unittest.mock import patch
        user = self._mock_user("business")
        with patch.object(FeatureGate, "get_effective_tier", return_value="business"):
            assert FeatureGate.get_provider_limit(user, "email") == 5

    def test_get_usage_percentage(self):
        from src.services.feature_flags import FeatureGate
        assert FeatureGate.get_usage_percentage(50, 100) == 50.0
        assert FeatureGate.get_usage_percentage(0, 100) == 0.0

    def test_get_usage_percentage_unlimited(self):
        from src.services.feature_flags import FeatureGate
        assert FeatureGate.get_usage_percentage(5000, 999999) == 0.0

    def test_get_usage_percentage_zero_limit(self):
        from src.services.feature_flags import FeatureGate
        assert FeatureGate.get_usage_percentage(5, 0) == 0.0

    def test_should_show_warning_at_80(self):
        from src.services.feature_flags import FeatureGate
        assert FeatureGate.should_show_warning(80, 100) is True
        assert FeatureGate.should_show_warning(79, 100) is False

    def test_should_show_warning_unlimited(self):
        from src.services.feature_flags import FeatureGate
        assert FeatureGate.should_show_warning(500, 999999) is False

    def test_is_at_limit(self):
        from src.services.feature_flags import FeatureGate
        assert FeatureGate.is_at_limit(100, 100) is True
        assert FeatureGate.is_at_limit(99, 100) is False

    def test_is_at_limit_unlimited(self):
        from src.services.feature_flags import FeatureGate
        assert FeatureGate.is_at_limit(99999, 999999) is False

    def test_get_upgrade_message_known(self):
        from src.services.feature_flags import FeatureGate
        msg = FeatureGate.get_upgrade_message("free", "inbox_send")
        assert "Starter" in msg

    def test_get_upgrade_message_unknown(self):
        from src.services.feature_flags import FeatureGate
        msg = FeatureGate.get_upgrade_message("free", "some_feature")
        assert "some_feature" in msg


class TestFeatureFlagService:
    def test_import(self):
        from src.services.feature_flags import FeatureGate
        assert FeatureGate is not None


class TestTierGateFunctions:
    def test_format_tier_name_all(self):
        from src.services.tier_gate import format_tier_name
        assert format_tier_name("free") == "Free"
        assert format_tier_name("starter") == "Starter"
        assert format_tier_name("business") == "Business"
        assert format_tier_name("pro") == "Pro"
        assert format_tier_name("enterprise") == "Enterprise"

    def test_format_platform_name_special(self):
        from src.services.tier_gate import format_platform_name
        assert format_platform_name("google_workspace") == "Google Workspace"
        assert format_platform_name("mpesa") == "M-Pesa"
        assert format_platform_name("ga4") == "Google Analytics 4"
        assert format_platform_name("power_bi") == "Power BI"

    def test_format_platform_name_generic(self):
        from src.services.tier_gate import format_platform_name
        result = format_platform_name("my_custom_platform")
        assert result == "My Custom Platform"

    def test_get_tier_for_platform_free_platforms(self):
        from src.services.tier_gate import get_tier_for_platform
        assert get_tier_for_platform("slack") == "Free"
        assert get_tier_for_platform("whatsapp") == "Free"
        assert get_tier_for_platform("jira") == "Free"
        assert get_tier_for_platform("trello") == "Free"
        assert get_tier_for_platform("asana") == "Free"

    def test_get_tier_for_platform_business_platforms(self):
        from src.services.tier_gate import get_tier_for_platform
        assert get_tier_for_platform("hubspot") == "Business"
        assert get_tier_for_platform("salesforce") == "Business"
        assert get_tier_for_platform("facebook") == "Business"

    def test_get_next_tier(self):
        from src.services.tier_gate import get_next_tier
        assert get_next_tier("free") == "starter"

    def test_get_next_tier_unknown(self):
        from src.services.tier_gate import get_next_tier
        assert get_next_tier("xyz") == "starter"

    def test_tier_gate_error_status_code(self):
        from src.services.tier_gate import TierGateError
        err = TierGateError(
            feature="test_feature",
            required_tier="business",
            current_tier="free"
        )
        assert err.status_code == 402
        assert err.detail["error"] == "upgrade_required"
        assert err.detail["feature"] == "test_feature"
        assert err.detail["required_tier"] == "business"
        assert err.detail["current_tier"] == "free"

    def test_tier_gate_error_custom_url(self):
        from src.services.tier_gate import TierGateError
        err = TierGateError(
            feature="test", required_tier="pro",
            current_tier="free", upgrade_url="/custom"
        )
        assert err.detail["upgrade_url"] == "/custom"
