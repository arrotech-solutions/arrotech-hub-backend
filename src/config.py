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

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_TIME_LIMIT: int = 300
    CELERY_TASK_SOFT_TIME_LIMIT: int = 240
    CELERY_WORKER_MAX_TASKS_PER_CHILD: int = 100
    CELERY_WORKER_CONCURRENCY: int = 4
    CELERY_FLOWER_PORT: int = 5555
    CELERY_FLOWER_BASIC_AUTH: Optional[str] = None  # "user:password"

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

    # Telegram Configuration
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_BOT_NAME: Optional[str] = None

    # WhatsApp API Configuration
    WHATSAPP_TOKEN: Optional[str] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_BUSINESS_ACCOUNT_ID: Optional[str] = None
    WHATSAPP_BASE_URL: Optional[str] = None
    WHATSAPP_APP_ID: Optional[str] = None
    WHATSAPP_APP_SECRET: Optional[str] = None
    WHATSAPP_VERIFY_TOKEN: Optional[str] = None
    # Inbound webhook flood control (per business owner + customer phone)
    WHATSAPP_WEBHOOK_RATE_LIMIT: int = 15
    WHATSAPP_WEBHOOK_RATE_WINDOW: int = 60
    # Require X-Hub-Signature-256 when app secret is set
    WHATSAPP_WEBHOOK_REQUIRE_SIGNATURE: bool = True
    # Queue webhook messages to Celery (set False to process in API process — good for local dev)
    WHATSAPP_USE_CELERY_WEBHOOK: bool = True
    # If Celery queue fails, fall back to FastAPI BackgroundTasks
    WHATSAPP_WEBHOOK_INLINE_FALLBACK: bool = True
    
    # Facebook (Pages) Configuration
    FACEBOOK_APP_ID: Optional[str] = None
    FACEBOOK_APP_SECRET: Optional[str] = None
    INSTAGRAM_WEBHOOK_VERIFY_TOKEN: Optional[str] = None

    # Telegram Configuration
    TELEGRAM_BOT_TOKEN: Optional[str] = None

    # Twitter (X) Configuration
    TWITTER_CLIENT_ID: Optional[str] = None
    TWITTER_CLIENT_SECRET: Optional[str] = None

    # LinkedIn Configuration
    LINKEDIN_CLIENT_ID: Optional[str] = None
    LINKEDIN_CLIENT_SECRET: Optional[str] = None
    LINKEDIN_REDIRECT_URI: Optional[str] = None

    # GitHub Configuration
    GITHUB_CLIENT_ID: Optional[str] = None
    GITHUB_CLIENT_SECRET: Optional[str] = None
    GITHUB_REDIRECT_URI: Optional[str] = None
    GITHUB_WEBHOOK_SECRET: Optional[str] = None

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

    # WhatsApp Business Configuration — defined above in lines 50-57

    # LLM & RAG API Keys
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    HUGGINGFACE_API_KEY: Optional[str] = None
    TOGETHER_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    TAVILY_API_KEY: Optional[str] = None
    PINECONE_API_KEY: Optional[str] = None
    PINECONE_INDEX_HOST: Optional[str] = None
    FIRECRAWL_API_KEY: Optional[str] = None
    COHERE_API_KEY: Optional[str] = None
    LLAMA_CLOUD_API_KEY: Optional[str] = None
    UNSTRUCTURED_API_KEY: Optional[str] = None
    UNSTRUCTURED_API_URL: str = "https://api.unstructured.io/general/v0/general"
    GOOGLE_MAPS_API_KEY: Optional[str] = None

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

    # Subscription lifecycle
    SUBSCRIPTION_GRACE_DAYS: int = 3
    SUBSCRIPTION_TRIAL_DAYS: int = 7

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
    SUPPORT_SMTP_USER: Optional[str] = "support@arrotechsolutions.com"

    # Centralized Email Routing — all Arrotech mailboxes
    INFO_EMAIL: str = "info@arrotechsolutions.com"
    SALES_EMAIL: str = "sales@arrotechsolutions.com"
    BILLING_EMAIL: str = "billing@arrotechsolutions.com"
    NOREPLY_EMAIL: str = "noreply@arrotechsolutions.com"
    NOREPLY_SMTP_PASSWORD: Optional[str] = None
    INFO_SMTP_PASSWORD: Optional[str] = None
    SALES_SMTP_PASSWORD: Optional[str] = None
    BILLING_SMTP_PASSWORD: Optional[str] = None

    # Resend (transactional email API — backup transport, uncomment in .env if SMTP is blocked)
    RESEND_API_KEY: Optional[str] = None

    # Server Settings
    HOST: str = "0.0.0.0"
    PORT: int = int(os.getenv("PORT", "8000"))
    DEBUG: bool = False  # Secure default
    RELOAD: bool = False  # Secure default
    
    # URLs
    API_BASE_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:3000"
    # Google Drive push notifications (must be public HTTPS in production)
    GOOGLE_DRIVE_WEBHOOK_URL: Optional[str] = None  # defaults to {API_BASE_URL}/api/google-drive/events
    GOOGLE_DRIVE_USE_CELERY_WEBHOOK: bool = True

    # CORS - Allow Railway, local development, and production domain
    ALLOWED_ORIGINS: list = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
        "http://localhost:5177",
        "https://hub.arrotechsolutions.com",
        "https://admin.arrotechsolutions.com",
        "https://arrotechsolutions.com",
        "https://www.arrotechsolutions.com",
        "https://blog.arrotechsolutions.com"
    ]

    ADMIN_FRONTEND_URL: str = "http://localhost:5177"

    # Conversation Context Manager (CCM) — WhatsApp/Telegram memory
    CCM_MAX_MESSAGES: int = 20             # Sliding window: max messages to keep
    CCM_MAX_TOKENS: int = 2000             # Token budget for context window
    CCM_SESSION_TTL: int = 7200            # Redis TTL in seconds (default: 2 hours)
    CCM_ENABLE_SUMMARIZATION: bool = False  # Auto-summarize old messages via LLM
    CCM_SUMMARY_THRESHOLD: int = 30        # Trigger summarization above this count

    # Conversational agent — escalation & multilingual
    AGENT_AUTO_ESCALATION_ENABLED: bool = True
    AGENT_FRUSTRATION_ESCALATION_THRESHOLD: float = 0.65
    AGENT_HUMAN_HANDOFF_TTL_HOURS: int = 24  # 0 = no auto-resume; else bot resumes after TTL
    AGENT_DEFAULT_SUPPORTED_LANGUAGES: str = "en,sw,fr,ar,es"  # comma-separated ISO codes

    # Voice notes — transcription (OpenAI Whisper). Billed per audio minute.
    VOICE_TRANSCRIBE_MODEL: str = "whisper-1"

    # WhatsApp ordering — location & automated tracking
    ORDER_TRACKING_ENABLED: bool = True  # confirmation, receipts, status push via WhatsApp

    # Coding Agent Configuration
    GITHUB_TOKEN: Optional[str] = None
    CODING_AGENT_DOCKER_IMAGE: str = "node:20-alpine"
    CODING_AGENT_SESSION_TIMEOUT: int = 1800  # 30 minutes idle timeout
    CODING_AGENT_MAX_SESSIONS_PER_USER: int = 1
    CODING_AGENT_CPU_LIMIT: str = "2"
    CODING_AGENT_MEMORY_LIMIT: str = "2g"
    CODING_AGENT_SESSIONS_DIR: str = "/tmp/agent-sessions"

    # Governed Runtime Configuration
    AUDIT_STORE_BACKEND: str = "memory"  # "memory" or "postgres"

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
        "https://www.arrotechsolutions.com",
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
