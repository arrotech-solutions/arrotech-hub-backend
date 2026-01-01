"""
Settings router for Mini-Hub MCP Server.
Comprehensive settings management with proper API response format.
"""

from typing import Any, Dict, Optional

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


class NotificationSettings(BaseModel):
    """Notification settings model."""
    email_notifications: bool = Field(default=True, description="Enable email notifications")
    slack_notifications: bool = Field(default=False, description="Enable Slack notifications")
    webhook_notifications: bool = Field(default=False, description="Enable webhook notifications")
    notification_webhook_url: Optional[str] = Field(None, description="Webhook URL for notifications")


class APISettings(BaseModel):
    """API settings model."""
    api_rate_limit: int = Field(default=1000, description="API rate limit per hour")
    api_timeout: int = Field(default=30, description="API timeout in seconds")
    auto_refresh_tokens: bool = Field(default=True, description="Auto refresh tokens")


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
    id: int
    user_id: int
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

async def get_or_create_user_settings(db: AsyncSession, user_id: int) -> UserSettings:
    """Get or create user settings."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        settings = UserSettings(user_id=user_id)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

    return settings


def format_settings_response(settings: UserSettings) -> dict:
    """Format settings into response dictionary."""
    return {
        "id": settings.id,
        "user_id": settings.user_id,
        "notification_settings": {
            "email_notifications": settings.email_notifications,
            "slack_notifications": settings.slack_notifications,
            "webhook_notifications": settings.webhook_notifications,
            "notification_webhook_url": settings.notification_webhook_url
        },
        "api_settings": {
            "api_rate_limit": settings.api_rate_limit,
            "api_timeout": settings.api_timeout,
            "auto_refresh_tokens": settings.auto_refresh_tokens
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

        # Update API settings
        if settings_update.api_settings:
            api = settings_update.api_settings
            settings.api_rate_limit = api.api_rate_limit
            settings.api_timeout = api.api_timeout
            settings.auto_refresh_tokens = api.auto_refresh_tokens

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
        data={
            "email_notifications": settings.email_notifications,
            "slack_notifications": settings.slack_notifications,
            "webhook_notifications": settings.webhook_notifications,
            "notification_webhook_url": settings.notification_webhook_url
        }
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

        await db.commit()
        await db.refresh(settings)

        return ApiResponse(
            success=True,
            data={
                "email_notifications": settings.email_notifications,
                "slack_notifications": settings.slack_notifications,
                "webhook_notifications": settings.webhook_notifications,
                "notification_webhook_url": settings.notification_webhook_url
            },
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

        await db.commit()
        await db.refresh(settings)

        return ApiResponse(
            success=True,
            data={
                "api_rate_limit": settings.api_rate_limit,
                "api_timeout": settings.api_timeout,
                "auto_refresh_tokens": settings.auto_refresh_tokens
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
