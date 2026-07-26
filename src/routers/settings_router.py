"""
Settings router for Mini-Hub MCP Server.
Comprehensive settings management with proper API response format.
"""

from typing import Any, Dict, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, UserSettings
from ..routers.auth_router import get_current_user

router = APIRouter(tags=["settings"])


# ================== Response Models ==================

class ApiResponse(BaseModel):
    """Standard API response format."""
    success: bool
    data: Optional[Any] = None
    message: Optional[str] = None
    error: Optional[str] = None


class QuietHours(BaseModel):
    """Quiet hours window (local time)."""
    start: Optional[str] = Field(None, description="HH:MM start")
    end: Optional[str] = Field(None, description="HH:MM end")
    timezone: Optional[str] = Field("UTC", description="IANA timezone")


class ChannelRule(BaseModel):
    in_app: bool = True
    email: bool = False
    slack: bool = False
    webhook: bool = False


class NotificationSettings(BaseModel):
    """Notification settings model."""
    email_notifications: bool = Field(default=True, description="Enable email notifications")
    slack_notifications: bool = Field(default=False, description="Enable Slack notifications")
    webhook_notifications: bool = Field(default=False, description="Enable webhook notifications")
    notification_webhook_url: Optional[str] = Field(None, description="Webhook URL for notifications")
    notification_rules: Optional[Dict[str, Dict[str, bool]]] = Field(
        None, description="Category × channel matrix"
    )
    quiet_hours: Optional[QuietHours] = Field(None, description="Suppress push channels in window")
    digest_email_daily: bool = Field(default=False, description="Batch info emails into daily digest")


class APISettings(BaseModel):
    """API settings model."""
    api_rate_limit: int = Field(default=1000, description="API rate limit per hour")
    api_timeout: int = Field(default=30, description="API timeout in seconds")
    auto_refresh_tokens: bool = Field(default=True, description="Auto refresh tokens")
    openai_api_key: Optional[str] = Field(None, description="OpenAI API Key")
    anthropic_api_key: Optional[str] = Field(None, description="Anthropic API Key")
    gemini_api_key: Optional[str] = Field(None, description="Gemini API Key")
    huggingface_api_key: Optional[str] = Field(None, description="Hugging Face API Key")
    together_api_key: Optional[str] = Field(None, description="Together AI API Key")


class DashboardSettings(BaseModel):
    """Dashboard settings model."""
    dashboard_theme: str = Field(default="light", description="Dashboard theme (light/dark/auto)")
    dashboard_layout: str = Field(default="default", description="Dashboard layout")
    show_analytics: bool = Field(default=True, description="Show analytics on dashboard")
    show_usage_stats: bool = Field(default=True, description="Show usage statistics")


class IntegrationSettings(BaseModel):
    """Integration settings model."""
    auto_sync_connections: bool = Field(default=True, description="Auto sync connections")
    sync_frequency: str = Field(default="hourly", description="Sync frequency")
    backup_connections: bool = Field(default=True, description="Backup connections")


class SecuritySettings(BaseModel):
    """Security settings model."""
    two_factor_enabled: bool = Field(default=False, description="Enable 2FA")
    session_timeout: int = Field(default=30, description="Session timeout in minutes")
    ip_whitelist: Optional[list] = Field(None, description="IP whitelist")


class UserSettingsUpdate(BaseModel):
    """User settings update model."""
    notification_settings: Optional[NotificationSettings] = None
    api_settings: Optional[APISettings] = None
    dashboard_settings: Optional[DashboardSettings] = None
    integration_settings: Optional[IntegrationSettings] = None
    security_settings: Optional[SecuritySettings] = None
    custom_settings: Optional[Dict[str, Any]] = None


class UserSettingsResponse(BaseModel):
    """User settings response model."""
    id: uuid.UUID
    user_id: uuid.UUID
    notification_settings: NotificationSettings
    api_settings: APISettings
    dashboard_settings: DashboardSettings
    integration_settings: IntegrationSettings
    security_settings: SecuritySettings
    custom_settings: Optional[Dict[str, Any]] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ================== Helper Functions ==================

async def get_or_create_user_settings(db: AsyncSession, user_id: uuid.UUID) -> UserSettings:
    """Get or create user settings."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        from ..services.notification_events import DEFAULT_CATEGORY_RULES
        settings = UserSettings(
            user_id=user_id,
            notification_rules={k: dict(v) for k, v in DEFAULT_CATEGORY_RULES.items()},
        )
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    elif not getattr(settings, "notification_rules", None):
        from ..services.notification_events import DEFAULT_CATEGORY_RULES
        settings.notification_rules = {k: dict(v) for k, v in DEFAULT_CATEGORY_RULES.items()}
        await db.commit()
        await db.refresh(settings)

    return settings


def _notification_settings_dict(settings: UserSettings) -> dict:
    from ..services.notification_events import merge_rules, list_categories_for_ui

    return {
        "email_notifications": settings.email_notifications,
        "slack_notifications": settings.slack_notifications,
        "webhook_notifications": settings.webhook_notifications,
        "notification_webhook_url": settings.notification_webhook_url,
        "notification_rules": merge_rules(getattr(settings, "notification_rules", None)),
        "quiet_hours": getattr(settings, "quiet_hours", None),
        "digest_email_daily": bool(getattr(settings, "digest_email_daily", False)),
        "categories": list_categories_for_ui(),
    }


def format_settings_response(settings: UserSettings) -> dict:
    """Format settings into response dictionary."""
    return {
        "id": settings.id,
        "user_id": settings.user_id,
        "notification_settings": _notification_settings_dict(settings),

        "api_settings": {
            "api_rate_limit": settings.api_rate_limit,
            "api_timeout": settings.api_timeout,
            "auto_refresh_tokens": settings.auto_refresh_tokens,
            "openai_api_key": settings.openai_api_key,
            "anthropic_api_key": settings.anthropic_api_key,
            "gemini_api_key": settings.gemini_api_key,
            "huggingface_api_key": settings.huggingface_api_key,
            "together_api_key": settings.together_api_key
        },
        "dashboard_settings": {
            "dashboard_theme": settings.dashboard_theme,
            "dashboard_layout": settings.dashboard_layout,
            "show_analytics": settings.show_analytics,
            "show_usage_stats": settings.show_usage_stats
        },
        "integration_settings": {
            "auto_sync_connections": settings.auto_sync_connections,
            "sync_frequency": settings.sync_frequency,
            "backup_connections": settings.backup_connections
        },
        "security_settings": {
            "two_factor_enabled": settings.two_factor_enabled,
            "session_timeout": settings.session_timeout,
            "ip_whitelist": settings.ip_whitelist
        },
        "custom_settings": settings.custom_settings,
        "created_at": settings.created_at.isoformat() if settings.created_at else None,
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else (
            settings.created_at.isoformat() if settings.created_at else None
        )
    }


# ================== Main Settings Endpoints ==================

@router.get("/", response_model=ApiResponse)
async def get_user_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all user settings."""
    try:
        settings = await get_or_create_user_settings(db, current_user.id)
        return ApiResponse(
            success=True,
            data=format_settings_response(settings)
        )
    except Exception as e:
        return ApiResponse(
            success=False,
            error=str(e)
        )


@router.put("/", response_model=ApiResponse)
async def update_user_settings(
    settings_update: UserSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user settings."""
    try:
        settings = await get_or_create_user_settings(db, current_user.id)

        # Update notification settings
        if settings_update.notification_settings:
            ns = settings_update.notification_settings
            settings.email_notifications = ns.email_notifications
            settings.slack_notifications = ns.slack_notifications
            settings.webhook_notifications = ns.webhook_notifications
            settings.notification_webhook_url = ns.notification_webhook_url
            if ns.notification_rules is not None:
                from ..services.notification_events import merge_rules
                settings.notification_rules = merge_rules(ns.notification_rules)
            if ns.quiet_hours is not None:
                settings.quiet_hours = ns.quiet_hours.model_dump() if hasattr(ns.quiet_hours, "model_dump") else ns.quiet_hours
            settings.digest_email_daily = ns.digest_email_daily

        # Update API settings
        if settings_update.api_settings:
            api = settings_update.api_settings
            settings.api_rate_limit = api.api_rate_limit
            settings.api_timeout = api.api_timeout
            settings.auto_refresh_tokens = api.auto_refresh_tokens
            settings.openai_api_key = api.openai_api_key
            settings.anthropic_api_key = api.anthropic_api_key
            settings.gemini_api_key = api.gemini_api_key
            settings.huggingface_api_key = api.huggingface_api_key
            settings.together_api_key = api.together_api_key

        # Update dashboard settings
        if settings_update.dashboard_settings:
            dash = settings_update.dashboard_settings
            settings.dashboard_theme = dash.dashboard_theme
            settings.dashboard_layout = dash.dashboard_layout
            settings.show_analytics = dash.show_analytics
            settings.show_usage_stats = dash.show_usage_stats

        # Update integration settings
        if settings_update.integration_settings:
            integ = settings_update.integration_settings
            settings.auto_sync_connections = integ.auto_sync_connections
            settings.sync_frequency = integ.sync_frequency
            settings.backup_connections = integ.backup_connections

        # Update security settings
        if settings_update.security_settings:
            sec = settings_update.security_settings
            settings.two_factor_enabled = sec.two_factor_enabled
            settings.session_timeout = sec.session_timeout
            settings.ip_whitelist = sec.ip_whitelist

        # Update custom settings
        if settings_update.custom_settings is not None:
            settings.custom_settings = settings_update.custom_settings

        await db.commit()
        await db.refresh(settings)

        return ApiResponse(
            success=True,
            data=format_settings_response(settings),
            message="Settings updated successfully"
        )
    except Exception as e:
        await db.rollback()
        return ApiResponse(
            success=False,
            error=str(e)
        )


@router.delete("/", response_model=ApiResponse)
async def reset_user_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Reset user settings to defaults."""
    try:
        result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == current_user.id)
        )
        settings = result.scalar_one_or_none()

        if settings:
            await db.delete(settings)
            await db.commit()

        # Recreate with defaults
        new_settings = await get_or_create_user_settings(db, current_user.id)

        return ApiResponse(
            success=True,
            data=format_settings_response(new_settings),
            message="Settings reset to defaults"
        )
    except Exception as e:
        await db.rollback()
        return ApiResponse(
            success=False,
            error=str(e)
        )


# ================== Section-Specific Endpoints ==================

@router.get("/notifications", response_model=ApiResponse)
async def get_notification_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get notification settings."""
    settings = await get_or_create_user_settings(db, current_user.id)
    return ApiResponse(
        success=True,
        data=_notification_settings_dict(settings)
    )


@router.put("/notifications", response_model=ApiResponse)
async def update_notification_settings(
    notification_settings: NotificationSettings,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update notification settings."""
    try:
        settings = await get_or_create_user_settings(db, current_user.id)

        settings.email_notifications = notification_settings.email_notifications
        settings.slack_notifications = notification_settings.slack_notifications
        settings.webhook_notifications = notification_settings.webhook_notifications
        settings.notification_webhook_url = notification_settings.notification_webhook_url
        if notification_settings.notification_rules is not None:
            from ..services.notification_events import merge_rules
            settings.notification_rules = merge_rules(notification_settings.notification_rules)
        if notification_settings.quiet_hours is not None:
            qh = notification_settings.quiet_hours
            settings.quiet_hours = qh.model_dump() if hasattr(qh, "model_dump") else qh
        settings.digest_email_daily = notification_settings.digest_email_daily

        await db.commit()
        await db.refresh(settings)

        return ApiResponse(
            success=True,
            data=_notification_settings_dict(settings),
            message="Notification settings updated"
        )
    except Exception as e:
        await db.rollback()
        return ApiResponse(success=False, error=str(e))


@router.get("/api", response_model=ApiResponse)
async def get_api_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get API settings."""
    settings = await get_or_create_user_settings(db, current_user.id)
    return ApiResponse(
        success=True,
        data={
            "api_rate_limit": settings.api_rate_limit,
            "api_timeout": settings.api_timeout,
            "auto_refresh_tokens": settings.auto_refresh_tokens
        }
    )


@router.put("/api", response_model=ApiResponse)
async def update_api_settings(
    api_settings: APISettings,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update API settings."""
    try:
        settings = await get_or_create_user_settings(db, current_user.id)

        settings.api_rate_limit = api_settings.api_rate_limit
        settings.api_timeout = api_settings.api_timeout
        settings.auto_refresh_tokens = api_settings.auto_refresh_tokens
        settings.openai_api_key = api_settings.openai_api_key
        settings.anthropic_api_key = api_settings.anthropic_api_key
        settings.gemini_api_key = api_settings.gemini_api_key
        settings.huggingface_api_key = api_settings.huggingface_api_key
        settings.together_api_key = api_settings.together_api_key

        await db.commit()
        await db.refresh(settings)

        return ApiResponse(
            success=True,
            data={
                "api_rate_limit": settings.api_rate_limit,
                "api_timeout": settings.api_timeout,
                "auto_refresh_tokens": settings.auto_refresh_tokens,
                "openai_api_key": settings.openai_api_key,
                "anthropic_api_key": settings.anthropic_api_key,
                "gemini_api_key": settings.gemini_api_key,
                "huggingface_api_key": settings.huggingface_api_key,
                "together_api_key": settings.together_api_key
            },
            message="API settings updated"
        )
    except Exception as e:
        await db.rollback()
        return ApiResponse(success=False, error=str(e))


@router.get("/dashboard", response_model=ApiResponse)
async def get_dashboard_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get dashboard settings."""
    settings = await get_or_create_user_settings(db, current_user.id)
    return ApiResponse(
        success=True,
        data={
            "dashboard_theme": settings.dashboard_theme,
            "dashboard_layout": settings.dashboard_layout,
            "show_analytics": settings.show_analytics,
            "show_usage_stats": settings.show_usage_stats
        }
    )


@router.put("/dashboard", response_model=ApiResponse)
async def update_dashboard_settings(
    dashboard_settings: DashboardSettings,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update dashboard settings."""
    try:
        settings = await get_or_create_user_settings(db, current_user.id)

        settings.dashboard_theme = dashboard_settings.dashboard_theme
        settings.dashboard_layout = dashboard_settings.dashboard_layout
        settings.show_analytics = dashboard_settings.show_analytics
        settings.show_usage_stats = dashboard_settings.show_usage_stats

        await db.commit()
        await db.refresh(settings)

        return ApiResponse(
            success=True,
            data={
                "dashboard_theme": settings.dashboard_theme,
                "dashboard_layout": settings.dashboard_layout,
                "show_analytics": settings.show_analytics,
                "show_usage_stats": settings.show_usage_stats
            },
            message="Dashboard settings updated"
        )
    except Exception as e:
        await db.rollback()
        return ApiResponse(success=False, error=str(e))


@router.get("/integrations", response_model=ApiResponse)
async def get_integration_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get integration settings."""
    settings = await get_or_create_user_settings(db, current_user.id)
    return ApiResponse(
        success=True,
        data={
            "auto_sync_connections": settings.auto_sync_connections,
            "sync_frequency": settings.sync_frequency,
            "backup_connections": settings.backup_connections
        }
    )


@router.put("/integrations", response_model=ApiResponse)
async def update_integration_settings(
    integration_settings: IntegrationSettings,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update integration settings."""
    try:
        settings = await get_or_create_user_settings(db, current_user.id)

        settings.auto_sync_connections = integration_settings.auto_sync_connections
        settings.sync_frequency = integration_settings.sync_frequency
        settings.backup_connections = integration_settings.backup_connections

        await db.commit()
        await db.refresh(settings)

        return ApiResponse(
            success=True,
            data={
                "auto_sync_connections": settings.auto_sync_connections,
                "sync_frequency": settings.sync_frequency,
                "backup_connections": settings.backup_connections
            },
            message="Integration settings updated"
        )
    except Exception as e:
        await db.rollback()
        return ApiResponse(success=False, error=str(e))


@router.get("/security", response_model=ApiResponse)
async def get_security_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get security settings."""
    settings = await get_or_create_user_settings(db, current_user.id)
    return ApiResponse(
        success=True,
        data={
            "two_factor_enabled": settings.two_factor_enabled,
            "session_timeout": settings.session_timeout,
            "ip_whitelist": settings.ip_whitelist
        }
    )


@router.put("/security", response_model=ApiResponse)
async def update_security_settings(
    security_settings: SecuritySettings,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update security settings."""
    try:
        settings = await get_or_create_user_settings(db, current_user.id)

        settings.two_factor_enabled = security_settings.two_factor_enabled
        settings.session_timeout = security_settings.session_timeout
        settings.ip_whitelist = security_settings.ip_whitelist

        await db.commit()
        await db.refresh(settings)

        return ApiResponse(
            success=True,
            data={
                "two_factor_enabled": settings.two_factor_enabled,
                "session_timeout": settings.session_timeout,
                "ip_whitelist": settings.ip_whitelist
            },
            message="Security settings updated"
        )
    except Exception as e:
        await db.rollback()
        return ApiResponse(success=False, error=str(e))
