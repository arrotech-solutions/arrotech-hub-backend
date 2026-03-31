"""
Configuration settings for Mini-Hub MCP Server.
"""

import os
from typing import Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


class BaseConfig(BaseSettings):
    """Base configuration class."""

    # Database
    DATABASE_URL: str = "postgresql://user:pass@localhost/minihub"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # API Keys
    HUBSPOT_API_KEY: Optional[str] = None
    HUBSPOT_CLIENT_ID: Optional[str] = None
    HUBSPOT_CLIENT_SECRET: Optional[str] = None
    HUBSPOT_REDIRECT_URI: str = "https://mini-hub.fly.dev/connections"
    GA4_PROPERTY_ID: Optional[str] = None
    GA4_CREDENTIALS_FILE: Optional[str] = None
    SLACK_BOT_TOKEN: Optional[str] = None
    SLACK_SIGNING_SECRET: Optional[str] = None
    SLACK_CLIENT_ID: Optional[str] = None
    SLACK_CLIENT_SECRET: Optional[str] = None
    TEAMS_WEBHOOK_URL: Optional[str] = None
    TEAMS_ACCESS_TOKEN: Optional[str] = None
    TEAMS_TENANT_ID: Optional[str] = None
    TEAMS_CLIENT_ID: Optional[str] = None
    TEAMS_CLIENT_SECRET: Optional[str] = None

    # Zoom OAuth Configuration
    ZOOM_CLIENT_ID: Optional[str] = None
    ZOOM_CLIENT_SECRET: Optional[str] = None
    ZOOM_ACCOUNT_ID: Optional[str] = None

    # WhatsApp API Configuration
    WHATSAPP_TOKEN: Optional[str] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_BUSINESS_ACCOUNT_ID: Optional[str] = None
    WHATSAPP_BASE_URL: Optional[str] = None
    WHATSAPP_APP_ID: Optional[str] = None
    WHATSAPP_APP_SECRET: Optional[str] = None
    WHATSAPP_VERIFY_TOKEN: Optional[str] = None
    
    # Facebook (Pages) Configuration
    FACEBOOK_APP_ID: Optional[str] = None
    FACEBOOK_APP_SECRET: Optional[str] = None

    # Twitter (X) Configuration
    TWITTER_CLIENT_ID: Optional[str] = None
    TWITTER_CLIENT_SECRET: Optional[str] = None

    # LinkedIn Configuration
    LINKEDIN_CLIENT_ID: Optional[str] = None
    LINKEDIN_CLIENT_SECRET: Optional[str] = None
    LINKEDIN_REDIRECT_URI: Optional[str] = None

    # TikTok Configuration
    TIKTOK_CLIENT_KEY: Optional[str] = None
    TIKTOK_CLIENT_SECRET: Optional[str] = None

    # KRA GavaConnect Configuration (Multi-App)
    KRA_ENV: str = "sandbox"  # sandbox or production
    
    # App 1a: Identity - PIN Checker (By PIN)
    KRA_IDENTITY_PIN_KEY: Optional[str] = None
    KRA_IDENTITY_PIN_SECRET: Optional[str] = None

    # App 1b: Identity - ID Checker (By National ID)
    KRA_IDENTITY_ID_KEY: Optional[str] = None
    KRA_IDENTITY_ID_SECRET: Optional[str] = None
    
    # App 2: Filing (NIL Returns, Tax Returns)
    KRA_NIL_FILING_KEY: Optional[str] = None
    KRA_NIL_FILING_SECRET: Optional[str] = None
    
    # App 3: eTIMS (Device Init, eSlips)
    KRA_ETIMS_KEY: str = "wHMPOgfwO6..."
    KRA_ETIMS_SECRET: str = "2GMNiibyAA..."

    KRA_INDIVIDUAL_PIN_REGISTRATION_KEY: str = "wHMPOgfwO6..." 
    KRA_INDIVIDUAL_PIN_REGISTRATION_SECRET: str = "2GMNiibyAA..."

    # Asana API Configuration
    ASANA_ACCESS_TOKEN: Optional[str] = None
    ASANA_WORKSPACE_ID: Optional[str] = None
    ASANA_CLIENT_ID: Optional[str] = None
    ASANA_CLIENT_SECRET: Optional[str] = None

    # Power BI Configuration
    POWERBI_CLIENT_ID: Optional[str] = None
    POWERBI_CLIENT_SECRET: Optional[str] = None
    POWERBI_TENANT_ID: Optional[str] = None

    # Outlook Configuration
    OUTLOOK_CLIENT_ID: Optional[str] = None
    OUTLOOK_CLIENT_SECRET: Optional[str] = None
    
    # Notion Configuration
    NOTION_CLIENT_ID: Optional[str] = None
    NOTION_CLIENT_SECRET: Optional[str] = None

    # Trello Configuration
    TRELLO_CLIENT_ID: Optional[str] = None
    TRELLO_CLIENT_SECRET: Optional[str] = None

    # Jira Configuration
    JIRA_CLIENT_ID: Optional[str] = None
    JIRA_CLIENT_SECRET: Optional[str] = None

    # QuickBooks Online Configuration
    QUICKBOOKS_CLIENT_ID: Optional[str] = None
    QUICKBOOKS_CLIENT_SECRET: Optional[str] = None
    QUICKBOOKS_REDIRECT_URI: Optional[str] = None
    QUICKBOOKS_ENVIRONMENT: str = "sandbox"  # "sandbox" or "production"

    # Airtable Configuration
    AIRTABLE_CLIENT_ID: Optional[str] = None
    AIRTABLE_CLIENT_SECRET: Optional[str] = None
    AIRTABLE_REDIRECT_URI: Optional[str] = None

    # Xero Configuration
    XERO_CLIENT_ID: Optional[str] = None
    XERO_CLIENT_SECRET: Optional[str] = None
    XERO_REDIRECT_URI: Optional[str] = None

    # WhatsApp Business Configuration
    WHATSAPP_VERIFY_TOKEN: Optional[str] = None
    WHATSAPP_TOKEN: Optional[str] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_BUSINESS_ACCOUNT_ID: Optional[str] = None
    WHATSAPP_APP_ID: Optional[str] = None
    WHATSAPP_APP_SECRET: Optional[str] = None

    # LLM API Keys
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    HUGGINGFACE_API_KEY: Optional[str] = None
    TOGETHER_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    TAVILY_API_KEY: Optional[str] = None

    # Zoho Configuration
    ZOHO_CLIENT_ID: Optional[str] = None
    ZOHO_CLIENT_SECRET: Optional[str] = None
    ZOHO_REDIRECT_URI: Optional[str] = None

    # LLM Settings
    DEFAULT_LLM_PROVIDER: str = "openai"
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: Optional[int] = None

    # OpenAI Settings
    OPENAI_MODEL: str = "gpt-4o"  # gpt-4o, gpt-4-turbo, gpt-3.5-turbo

    # Ollama Settings (Local LLM)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3"

    # Hugging Face Settings
    HUGGINGFACE_MODEL: str = "meta-llama/Llama-2-7b-chat-hf"

    # Together AI Settings
    TOGETHER_MODEL: str = "togethercomputer/llama-2-7b-chat"

    # Anthropic Settings
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20240620"

    # Paystack
    PAYSTACK_SECRET_KEY: Optional[str] = None
    PAYSTACK_PUBLIC_KEY: Optional[str] = None

    # Stripe
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    STRIPE_PUBLISHABLE_KEY: Optional[str] = None

    # App Settings
    SECRET_KEY: str  # Must be set in environment
    ENVIRONMENT: str = "development"

    # Rate Limits
    FREE_TIER_LIMIT: int = 10  # requests per day
    PRO_TIER_LIMIT: int = 10000  # requests per day

    # Pricing
    PRO_TIER_PRICE: int = 4900  # $49.00 in cents
    ENTERPRISE_SETUP_PRICE: int = 29900  # $299.00 in cents

    # M-Pesa
    MPESA_CONSUMER_KEY: Optional[str] = None
    MPESA_CONSUMER_SECRET: Optional[str] = None
    MPESA_PASSKEY: Optional[str] = None
    MPESA_BUSINESS_SHORT_CODE: Optional[str] = None
    MPESA_CALLBACK_URL: Optional[str] = None
    MPESA_ENVIRONMENT: str = "sandbox"  # sandbox or live

    # Support Email Configuration
    SUPPORT_EMAIL_PASSWORD: Optional[str] = None

    # Server Settings
    HOST: str = "0.0.0.0"
    PORT: int = int(os.getenv("PORT", "8000"))
    DEBUG: bool = False  # Secure default
    RELOAD: bool = False  # Secure default
    
    # URLs
    API_BASE_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:3000"

    # CORS - Allow Railway, local development, and production domain
    ALLOWED_ORIGINS: list = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
        "https://hub.arrotechsolutions.com",
        "https://arrotechsolutions.com",
        "https://blog.arrotechsolutions.com"
    ]

    # JWT Settings
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Logging
    LOG_LEVEL: str = "INFO"

    # Admin Configuration
    ADMIN_EMAIL: Optional[str] = None
    ADMIN_PASSWORD: Optional[str] = None

    # Google OAuth Configuration
    GOOGLE_CLIENT_ID: Optional[str] = None

    # Google Cloud / Gmail Pub/Sub Configuration
    GCP_PROJECT_ID: str = "mini-hub-466619"
    GMAIL_PUBSUB_TOPIC: str = "projects/mini-hub-466619/topics/gmail-notifications"

    # Microsoft OAuth Configuration
    MICROSOFT_CLIENT_ID: Optional[str] = None

    class Config:
        env_file = ".env"
        case_sensitive = True
        env_file_encoding = "utf-8"


class DevelopmentConfig(BaseConfig):
    """Development environment configuration."""

    DEBUG: bool = True
    RELOAD: bool = True
    LOG_LEVEL: str = "DEBUG"

    # Development-specific overrides
    DATABASE_URL: str = "postgresql://user:pass@localhost/minihub_dev"
    REDIS_URL: str = "redis://localhost:6379/1"

    class Config:
        env_file = ".env.development"
        case_sensitive = True


class TestingConfig(BaseConfig):
    """Testing environment configuration."""

    DEBUG: bool = True
    RELOAD: bool = False
    LOG_LEVEL: str = "DEBUG"

    # Testing-specific overrides
    DATABASE_URL: str = "postgresql://user:pass@localhost/minihub_test"
    REDIS_URL: str = "redis://localhost:6379/2"
    SECRET_KEY: str = "test-secret-key"

    class Config:
        env_file = ".env.testing"
        case_sensitive = True


class StagingConfig(BaseConfig):
    """Staging environment configuration."""

    DEBUG: bool = False
    RELOAD: bool = False
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "staging"

    # Staging-specific overrides
    ALLOWED_ORIGINS: list = [
        "https://staging.minihub.com",
        "https://staging-frontend.minihub.com"
    ]

    class Config:
        env_file = ".env.staging"
        case_sensitive = True


class ProductionConfig(BaseConfig):
    """Production environment configuration."""

    DEBUG: bool = False
    RELOAD: bool = False
    LOG_LEVEL: str = "WARNING"
    ENVIRONMENT: str = "production"

    # Production-specific overrides
    ALLOWED_ORIGINS: list = [
        "https://hub.arrotechsolutions.com",
        "https://arrotechsolutions.com",
        "https://mini-hub.fly.dev",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
        "https://blog.arrotechsolutions.com"
    ]

    class Config:
        env_file = ".env.production"
        case_sensitive = True


class ReleaseConfig(BaseConfig):
    """Release environment configuration."""

    DEBUG: bool = False
    RELOAD: bool = False
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "release"

    # Release-specific overrides
    ALLOWED_ORIGINS: list = [
        "https://release.minihub.com",
        "https://release-frontend.minihub.com"
    ]

    class Config:
        env_file = ".env.release"
        case_sensitive = True


def get_config() -> BaseConfig:
    """Get configuration based on environment."""
    environment = os.getenv("ENVIRONMENT", "development").lower()

    config_map = {
        "development": DevelopmentConfig,
        "testing": TestingConfig,
        "staging": StagingConfig,
        "production": ProductionConfig,
        "release": ReleaseConfig,
    }

    config_class = config_map.get(environment, DevelopmentConfig)
    return config_class()


def get_settings() -> BaseConfig:
    """Get settings instance."""
    return get_config()


# Global settings instance
settings = get_settings()
