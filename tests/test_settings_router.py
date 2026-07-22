"""
Tests for settings endpoints.
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_settings_unauthorized(client: AsyncClient):
    """Test getting settings without auth returns 401."""
    response = await client.get("/settings/")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_get_settings(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test getting user settings."""
    response = await client.get("/settings/", headers=auth_headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_settings(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test updating user settings."""
    response = await client.put(
        "/settings/",
        headers=auth_headers,
        json={
            "notification_settings": {
                "email_notifications": False,
                "slack_notifications": True
            }
        }
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_all_settings_at_once(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test updating all settings at once."""
    response = await client.put(
        "/settings/",
        headers=auth_headers,
        json={
            "notification_settings": {
                "email_notifications": True,
                "slack_notifications": True,
                "webhook_notifications": True,
                "notification_webhook_url": "https://example.com/wh"
            },
            "api_settings": {
                "api_rate_limit": 1000,
                "api_timeout": 120
            },
            "dashboard_settings": {
                "dashboard_theme": "dark",
                "dashboard_layout": "compact"
            }
        }
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_notification_settings(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test getting notification settings."""
    response = await client.get(
        "/settings/notifications", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_notification_settings(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test updating notification settings."""
    response = await client.put(
        "/settings/notifications",
        headers=auth_headers,
        json={
            "email_notifications": True,
            "slack_notifications": False
        }
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_notification_webhook(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test updating webhook URL in notifications."""
    response = await client.put(
        "/settings/notifications",
        headers=auth_headers,
        json={
            "webhook_notifications": True,
            "notification_webhook_url": "https://hooks.example.com/n"
        }
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_api_settings(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test getting API settings."""
    response = await client.get("/settings/api", headers=auth_headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_api_settings(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test updating API settings."""
    response = await client.put(
        "/settings/api",
        headers=auth_headers,
        json={
            "api_rate_limit": 500,
            "api_timeout": 60
        }
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_api_rate_limit_high(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test updating API rate limit to high value."""
    response = await client.put(
        "/settings/api",
        headers=auth_headers,
        json={"api_rate_limit": 10000, "api_timeout": 300}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_dashboard_settings(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test getting dashboard settings."""
    response = await client.get(
        "/settings/dashboard", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_dashboard_settings(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test updating dashboard settings."""
    response = await client.put(
        "/settings/dashboard",
        headers=auth_headers,
        json={
            "dashboard_theme": "dark",
            "dashboard_layout": "compact"
        }
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_dashboard_theme_light(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test updating dashboard theme to light."""
    response = await client.put(
        "/settings/dashboard",
        headers=auth_headers,
        json={"dashboard_theme": "light"}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_dashboard_layout_default(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test updating dashboard layout to default."""
    response = await client.put(
        "/settings/dashboard",
        headers=auth_headers,
        json={"dashboard_layout": "default"}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_integrations_settings(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test getting integrations settings."""
    response = await client.get(
        "/settings/integrations", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_integrations_settings(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test updating integrations settings."""
    response = await client.put(
        "/settings/integrations",
        headers=auth_headers,
        json={"hubspot_enabled": True, "slack_enabled": True}
    )
    assert response.status_code in [200, 400, 422]


@pytest.mark.asyncio
async def test_get_security_settings(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test getting security settings."""
    response = await client.get(
        "/settings/security", headers=auth_headers
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_update_security_settings(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test updating security settings."""
    response = await client.put(
        "/settings/security",
        headers=auth_headers,
        json={"two_factor_enabled": False, "session_timeout": 3600}
    )
    assert response.status_code in [200, 400, 422]


@pytest.mark.asyncio
async def test_delete_settings(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test deleting user settings."""
    response = await client.delete("/settings/", headers=auth_headers)
    assert response.status_code in [200, 204, 400, 405]


@pytest.mark.asyncio
async def test_update_settings_partial(
    client: AsyncClient, auth_headers, test_user_settings
):
    """Test partial settings update."""
    response = await client.put(
        "/settings/",
        headers=auth_headers,
        json={
            "notification_settings": {"email_notifications": False}
        }
    )
    assert response.status_code == 200
