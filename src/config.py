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
    GA4_PROPERTY_ID: Optional[str] = None
    GA4_CREDENTIALS_FILE: Optional[str] = None
    SLACK_BOT_TOKEN: Optional[str] = None
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

    # Asana API Configuration
    ASANA_ACCESS_TOKEN: Optional[str] = None
    ASANA_WORKSPACE_ID: Optional[str] = None

    # Power BI Configuration
    POWERBI_CLIENT_ID: Optional[str] = None
    POWERBI_CLIENT_SECRET: Optional[str] = None
    POWERBI_TENANT_ID: Optional[str] = None

    # LLM API Keys
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    HUGGINGFACE_API_KEY: Optional[str] = None
    TOGETHER_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None

    # LLM Settings
    DEFAULT_LLM_PROVIDER: str = "ollama"
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

    # Stripe
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    STRIPE_PUBLISHABLE_KEY: Optional[str] = None

    # App Settings
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ENVIRONMENT: str = "development"

    # Rate Limits
    FREE_TIER_LIMIT: int = 100  # requests per day
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

    # Server Settings
    HOST: str = "0.0.0.0"
    PORT: int = os.getenv("PORT")
    DEBUG: bool = True
    RELOAD: bool = True

    # CORS - Allow Railway and local development
    ALLOWED_ORIGINS: list = [
        "http://localhost:3000",
        "http://localhost:5173",
        "https://*.railway.app",
        "https://*.up.railway.app"
    ]

    # JWT Settings
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Logging
    LOG_LEVEL: str = "INFO"

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

    # Production-specific overrides - includes Railway domains
    ALLOWED_ORIGINS: list = [
        "https://minihub.com",
        "https://app.minihub.com",
        "https://*.railway.app",
        "https://*.up.railway.app"
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
