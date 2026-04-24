"""
Tests for src/config.py — configuration classes, environment selection, and get_config/get_settings.
"""
import os
from unittest.mock import patch

import pytest


class TestBaseConfig:
    """Tests for BaseConfig defaults and field declarations."""

    def test_base_config_instantiation(self):
        """BaseConfig can be instantiated with minimal env vars."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="test-secret")
        assert config.SECRET_KEY == "test-secret"
        assert config.ENVIRONMENT == "development"
        assert config.DATABASE_URL == "postgresql://user:pass@localhost/minihub"

    def test_base_config_defaults(self):
        """Validate important defaults."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.FREE_TIER_LIMIT == 10
        assert config.PRO_TIER_LIMIT == 10000
        assert config.JWT_ALGORITHM == "HS256"
        assert config.ACCESS_TOKEN_EXPIRE_MINUTES == 30
        assert config.DEFAULT_LLM_PROVIDER == "openai"
        assert config.LLM_TEMPERATURE == 0.7
        assert config.HOST == "0.0.0.0"
        assert config.DEBUG is False
        assert config.RELOAD is False

    def test_base_config_optional_fields_default_none(self):
        """Optional API keys should default to None."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.HUBSPOT_API_KEY is None
        assert config.OPENAI_API_KEY is None
        assert config.STRIPE_SECRET_KEY is None
        assert config.SLACK_BOT_TOKEN is None

    def test_base_config_cors_origins(self):
        """CORS origins should include localhost and production domains."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert "http://localhost:3000" in config.ALLOWED_ORIGINS
        assert "https://hub.arrotechsolutions.com" in config.ALLOWED_ORIGINS

    def test_base_config_ccm_defaults(self):
        """Conversation Context Manager defaults."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.CCM_MAX_MESSAGES == 20
        assert config.CCM_MAX_TOKENS == 2000
        assert config.CCM_SESSION_TTL == 7200
        assert config.CCM_ENABLE_SUMMARIZATION is False

    def test_base_config_redis_url(self):
        """Redis URL default value."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.REDIS_URL == "redis://localhost:6379"

    def test_base_config_pricing_defaults(self):
        """Pricing tier defaults."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.PRO_TIER_PRICE == 4900
        assert config.ENTERPRISE_SETUP_PRICE == 29900

    def test_base_config_mpesa_defaults(self):
        """M-Pesa defaults."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.MPESA_ENVIRONMENT == "sandbox"
        assert config.MPESA_CONSUMER_KEY is None

    def test_base_config_server_settings(self):
        """Server settings defaults."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.HOST == "0.0.0.0"
        assert isinstance(config.PORT, int)
        assert config.API_BASE_URL == "http://localhost:8000"
        assert config.FRONTEND_URL == "http://localhost:3000"

    def test_base_config_log_level(self):
        """Default log level."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.LOG_LEVEL == "INFO"

    def test_base_config_admin_defaults(self):
        """Admin defaults should be None."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.ADMIN_EMAIL is None
        assert config.ADMIN_PASSWORD is None

    def test_base_config_whatsapp_fields(self):
        """WhatsApp configuration fields."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.WHATSAPP_TOKEN is None
        assert config.WHATSAPP_PHONE_NUMBER_ID is None
        assert config.WHATSAPP_BUSINESS_ACCOUNT_ID is None

    def test_base_config_facebook_fields(self):
        """Facebook configuration fields."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.FACEBOOK_APP_ID is None
        assert config.FACEBOOK_APP_SECRET is None

    def test_base_config_twitter_fields(self):
        """Twitter configuration fields."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.TWITTER_CLIENT_ID is None
        assert config.TWITTER_CLIENT_SECRET is None

    def test_base_config_linkedin_fields(self):
        """LinkedIn configuration fields."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.LINKEDIN_CLIENT_ID is None
        assert config.LINKEDIN_CLIENT_SECRET is None

    def test_base_config_tiktok_fields(self):
        """TikTok configuration fields."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.TIKTOK_CLIENT_KEY is None
        assert config.TIKTOK_CLIENT_SECRET is None

    def test_base_config_kra_defaults(self):
        """KRA configuration defaults."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.KRA_ENV == "sandbox"

    def test_base_config_quickbooks_defaults(self):
        """QuickBooks configuration defaults."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.QUICKBOOKS_ENVIRONMENT == "sandbox"

    def test_base_config_openai_model_default(self):
        """OpenAI model default."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.OPENAI_MODEL == "gpt-4o"

    def test_base_config_anthropic_model_default(self):
        """Anthropic model default."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.ANTHROPIC_MODEL == "claude-3-5-sonnet-20240620"

    def test_base_config_ollama_defaults(self):
        """Ollama settings."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.OLLAMA_BASE_URL == "http://localhost:11434"
        assert config.OLLAMA_MODEL == "qwen3"

    def test_base_config_ccm_summary_threshold(self):
        """CCM summary threshold default."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.CCM_SUMMARY_THRESHOLD == 30

    def test_base_config_email_routing(self):
        """Email routing defaults."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.INFO_EMAIL == "info@arrotechsolutions.com"
        assert config.SALES_EMAIL == "sales@arrotechsolutions.com"
        assert config.BILLING_EMAIL == "billing@arrotechsolutions.com"
        assert config.NOREPLY_EMAIL == "noreply@arrotechsolutions.com"

    def test_base_config_gcp_defaults(self):
        """GCP project defaults."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.GCP_PROJECT_ID == "mini-hub-466619"
        assert "gmail-notifications" in config.GMAIL_PUBSUB_TOPIC

    def test_base_config_zoom_fields(self):
        """Zoom OAuth defaults."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.ZOOM_CLIENT_ID is None
        assert config.ZOOM_CLIENT_SECRET is None

    def test_base_config_teams_fields(self):
        """Teams fields."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.TEAMS_CLIENT_ID is None
        assert config.TEAMS_WEBHOOK_URL is None

    def test_base_config_notion_fields(self):
        """Notion fields."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.NOTION_CLIENT_ID is None

    def test_base_config_jira_fields(self):
        """Jira fields."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.JIRA_CLIENT_ID is None

    def test_base_config_trello_fields(self):
        """Trello fields."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.TRELLO_CLIENT_ID is None

    def test_base_config_xero_fields(self):
        """Xero fields."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.XERO_CLIENT_ID is None

    def test_base_config_zoho_fields(self):
        """Zoho fields."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.ZOHO_CLIENT_ID is None

    def test_base_config_airtable_fields(self):
        """Airtable fields."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.AIRTABLE_CLIENT_ID is None

    def test_base_config_resend_field(self):
        """Resend API key."""
        from src.config import BaseConfig
        config = BaseConfig(SECRET_KEY="s")
        assert config.RESEND_API_KEY is None


class TestEnvironmentConfigs:
    """Tests for environment-specific configuration classes."""

    def test_development_config(self):
        """DevelopmentConfig should enable debug and reload."""
        from src.config import DevelopmentConfig
        config = DevelopmentConfig(SECRET_KEY="s")
        assert config.DEBUG is True
        assert config.RELOAD is True
        assert config.LOG_LEVEL == "DEBUG"

    def test_development_config_database(self):
        """DevelopmentConfig should have dev database URL."""
        from src.config import DevelopmentConfig
        config = DevelopmentConfig(SECRET_KEY="s")
        assert "minihub_dev" in config.DATABASE_URL

    def test_development_config_redis(self):
        """DevelopmentConfig should have dev redis URL."""
        from src.config import DevelopmentConfig
        config = DevelopmentConfig(SECRET_KEY="s")
        assert "/1" in config.REDIS_URL

    def test_testing_config(self):
        """TestingConfig should have test-specific settings."""
        from src.config import TestingConfig
        config = TestingConfig()
        assert config.DEBUG is True
        assert config.RELOAD is False
        assert config.SECRET_KEY == "test-secret-key"

    def test_testing_config_database(self):
        """TestingConfig should have test database URL."""
        from src.config import TestingConfig
        config = TestingConfig()
        assert "minihub_test" in config.DATABASE_URL

    def test_testing_config_redis(self):
        """TestingConfig should have test redis URL."""
        from src.config import TestingConfig
        config = TestingConfig()
        assert "/2" in config.REDIS_URL

    def test_staging_config(self):
        """StagingConfig should have staging settings."""
        from src.config import StagingConfig
        config = StagingConfig(SECRET_KEY="s")
        assert config.DEBUG is False
        assert config.ENVIRONMENT == "staging"
        assert "https://staging.minihub.com" in config.ALLOWED_ORIGINS

    def test_staging_config_reload_false(self):
        """StagingConfig reload should be False."""
        from src.config import StagingConfig
        config = StagingConfig(SECRET_KEY="s")
        assert config.RELOAD is False

    def test_production_config(self):
        """ProductionConfig should have production settings."""
        from src.config import ProductionConfig
        config = ProductionConfig(SECRET_KEY="s")
        assert config.DEBUG is False
        assert config.RELOAD is False
        assert config.LOG_LEVEL == "WARNING"
        assert config.ENVIRONMENT == "production"
        assert "https://hub.arrotechsolutions.com" in config.ALLOWED_ORIGINS

    def test_production_config_cors(self):
        """ProductionConfig should have multiple production CORS origins."""
        from src.config import ProductionConfig
        config = ProductionConfig(SECRET_KEY="s")
        assert "https://arrotechsolutions.com" in config.ALLOWED_ORIGINS
        assert "https://www.arrotechsolutions.com" in config.ALLOWED_ORIGINS
        assert "https://mini-hub.fly.dev" in config.ALLOWED_ORIGINS

    def test_release_config(self):
        """ReleaseConfig should have release settings."""
        from src.config import ReleaseConfig
        config = ReleaseConfig(SECRET_KEY="s")
        assert config.DEBUG is False
        assert config.ENVIRONMENT == "release"

    def test_release_config_log_level(self):
        """ReleaseConfig log level."""
        from src.config import ReleaseConfig
        config = ReleaseConfig(SECRET_KEY="s")
        assert config.LOG_LEVEL == "INFO"

    def test_release_config_cors(self):
        """ReleaseConfig CORS origins."""
        from src.config import ReleaseConfig
        config = ReleaseConfig(SECRET_KEY="s")
        assert "https://release.minihub.com" in config.ALLOWED_ORIGINS


class TestGetConfig:
    """Tests for get_config() environment dispatch."""

    @patch.dict(os.environ, {"ENVIRONMENT": "development"})
    def test_get_config_development(self):
        from src.config import get_config, DevelopmentConfig
        config = get_config()
        assert isinstance(config, DevelopmentConfig)

    @patch.dict(os.environ, {"ENVIRONMENT": "testing"})
    def test_get_config_testing(self):
        from src.config import get_config, TestingConfig
        config = get_config()
        assert isinstance(config, TestingConfig)

    @patch.dict(os.environ, {"ENVIRONMENT": "staging", "SECRET_KEY": "s"})
    def test_get_config_staging(self):
        from src.config import get_config, StagingConfig
        config = get_config()
        assert isinstance(config, StagingConfig)

    @patch.dict(os.environ, {"ENVIRONMENT": "production", "SECRET_KEY": "s"})
    def test_get_config_production(self):
        from src.config import get_config, ProductionConfig
        config = get_config()
        assert isinstance(config, ProductionConfig)

    @patch.dict(os.environ, {"ENVIRONMENT": "release", "SECRET_KEY": "s"})
    def test_get_config_release(self):
        from src.config import get_config, ReleaseConfig
        config = get_config()
        assert isinstance(config, ReleaseConfig)

    @patch.dict(os.environ, {"ENVIRONMENT": "unknown_env"})
    def test_get_config_unknown_falls_back_to_development(self):
        from src.config import get_config, DevelopmentConfig
        config = get_config()
        assert isinstance(config, DevelopmentConfig)

    @patch.dict(os.environ, {"ENVIRONMENT": ""})
    def test_get_config_empty_env(self):
        from src.config import get_config, DevelopmentConfig
        config = get_config()
        assert isinstance(config, DevelopmentConfig)

    @patch.dict(os.environ, {"ENVIRONMENT": "PRODUCTION", "SECRET_KEY": "s"})
    def test_get_config_case_insensitive(self):
        from src.config import get_config, ProductionConfig
        config = get_config()
        assert isinstance(config, ProductionConfig)

    def test_get_settings_returns_config(self):
        from src.config import get_settings
        config = get_settings()
        assert config is not None
        assert hasattr(config, "SECRET_KEY")

    def test_get_settings_returns_base_config_subclass(self):
        from src.config import get_settings, BaseConfig
        config = get_settings()
        assert isinstance(config, BaseConfig)

    def test_global_settings_instance(self):
        from src.config import settings
        assert settings is not None
        assert hasattr(settings, "SECRET_KEY")
        assert hasattr(settings, "ENVIRONMENT")
        assert hasattr(settings, "DATABASE_URL")
