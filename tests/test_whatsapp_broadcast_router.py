"""Tests for WhatsApp broadcast production fixes."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestWhatsAppConfigHelper:
    @pytest.mark.asyncio
    async def test_get_whatsapp_config_from_connection(self):
        from src.services.whatsapp_config_helper import get_whatsapp_config

        conn = MagicMock()
        conn.config = {
            "phone_number_id": "pn_123",
            "access_token": "token_abc",
            "business_account_id": "waba_456",
        }
        conn.id = uuid.uuid4()

        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=conn))))
        )

        config = await get_whatsapp_config(db, uuid.uuid4())
        assert config["phone_number_id"] == "pn_123"
        assert config["access_token"] == "token_abc"
        assert config["business_account_id"] == "waba_456"


class TestBroadcastRouterHelpers:
    def test_parse_meta_templates_nested(self):
        from src.routers.whatsapp_broadcast import _parse_meta_templates

        items = _parse_meta_templates({
            "success": True,
            "data": {"data": [{"id": "1", "name": "hello_world"}]},
        })
        assert len(items) == 1
        assert items[0]["name"] == "hello_world"

    def test_template_language_code_object(self):
        from src.routers.whatsapp_broadcast import _template_language_code

        assert _template_language_code({"language": {"code": "en_US"}}) == "en_US"
        assert _template_language_code({"language": "en"}) == "en"


class TestBroadcastTasksHelpers:
    def test_template_components_list(self):
        from src.tasks.broadcast_tasks import _template_components

        raw = [{"type": "body", "parameters": []}]
        assert _template_components(raw) == raw

    def test_template_components_wrapped(self):
        from src.tasks.broadcast_tasks import _template_components

        assert _template_components({"components": [{"type": "body"}]}) == [{"type": "body"}]

    def test_is_rate_limit_error(self):
        from src.tasks.broadcast_tasks import _is_rate_limit_error

        assert _is_rate_limit_error({"error": "HTTP 429 too many requests"}) is True
        assert _is_rate_limit_error({"error": "invalid number"}) is False

    def test_execute_broadcast_task_signature(self):
        from src.tasks.broadcast_tasks import execute_broadcast_campaign_task

        with patch("src.tasks.broadcast_tasks._run_async") as mock_run:
            mock_run.return_value = {"sent": 1, "failed": 0}
            result = execute_broadcast_campaign_task("broadcast-id", "user-id")
            assert result == {"sent": 1, "failed": 0}
            mock_run.assert_called_once()


class TestTierGateBroadcast:
    def test_check_broadcast_access_requires_subscription(self):
        from src.services.tier_gate import check_broadcast_access, TierGateError
        from src.models import User, SubscriptionTier

        user = User(email="free@test.com", subscription_tier=SubscriptionTier.FREE)
        user.subscription_status = "inactive"

        with patch("src.services.subscription_service.SubscriptionService.is_subscription_active", return_value=False):
            with pytest.raises(TierGateError):
                check_broadcast_access(user)
