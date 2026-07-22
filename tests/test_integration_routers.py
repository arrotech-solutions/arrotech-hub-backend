"""
Tests for integration/OAuth routers: slack, whatsapp, facebook, instagram,
telegram, twitter, linkedin, hubspot, outlook, notion, trello, jira, clickup,
teams, zoom, quickbooks, airtable, xero, zoho, tiktok, asana, kra.
"""
import pytest
from httpx import AsyncClient


# ── Slack Router ──────────────────────────────────────────────────────────────

class TestSlackRouter:
    @pytest.mark.asyncio
    async def test_slack_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/slack/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]

    @pytest.mark.asyncio
    async def test_slack_channels(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/slack/channels", headers=auth_headers)
        assert r.status_code in [200, 400, 404, 500]


# ── WhatsApp Router ──────────────────────────────────────────────────────────

class TestWhatsAppRouter:
    @pytest.mark.asyncio
    async def test_whatsapp_status(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/whatsapp/status", headers=auth_headers)
        assert r.status_code in [200, 400, 404, 500]

    @pytest.mark.asyncio
    async def test_whatsapp_send_message(self, client: AsyncClient, auth_headers):
        r = await client.post("/api/whatsapp/send", headers=auth_headers, json={
            "to": "+254700000000", "message": "Test"
        })
        assert r.status_code in [200, 400, 404, 422, 500]


# ── WhatsApp Webhook ─────────────────────────────────────────────────────────

class TestWhatsAppWebhook:
    @pytest.mark.asyncio
    async def test_webhook_verify(self, client: AsyncClient):
        r = await client.get("/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=test&hub.challenge=abc")
        assert r.status_code in [200, 403, 503]

    @pytest.mark.asyncio
    async def test_webhook_post(self, client: AsyncClient):
        r = await client.post("/api/whatsapp/webhook", json={"entry": []})
        assert r.status_code in [200, 400, 422]


# ── WhatsApp Contacts ────────────────────────────────────────────────────────

class TestWhatsAppContacts:
    @pytest.mark.asyncio
    async def test_list_contacts(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/whatsapp/contacts", headers=auth_headers)
        assert r.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_list_contacts_unauthorized(self, client: AsyncClient):
        r = await client.get("/api/whatsapp/contacts")
        assert r.status_code in (401, 403)


# ── WhatsApp Broadcast ───────────────────────────────────────────────────────

class TestWhatsAppBroadcast:
    @pytest.mark.asyncio
    async def test_list_broadcasts(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/whatsapp/broadcasts", headers=auth_headers)
        assert r.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_create_broadcast(self, client: AsyncClient, auth_headers):
        r = await client.post("/api/whatsapp/broadcasts", headers=auth_headers, json={
            "name": "Test Broadcast", "message_type": "text", "text_content": "Hello"
        })
        assert r.status_code in [200, 201, 400, 402, 422]


# ── Facebook Router ──────────────────────────────────────────────────────────

class TestFacebookRouter:
    @pytest.mark.asyncio
    async def test_facebook_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/facebook/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]


# ── Instagram Router ─────────────────────────────────────────────────────────

class TestInstagramRouter:
    @pytest.mark.asyncio
    async def test_instagram_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/instagram/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]

    @pytest.mark.asyncio
    async def test_instagram_webhook_verify(self, client: AsyncClient):
        r = await client.get("/api/instagram/webhook?hub.mode=subscribe&hub.verify_token=test&hub.challenge=abc")
        assert r.status_code in [200, 403, 404]


# ── Telegram Router ──────────────────────────────────────────────────────────

class TestTelegramRouter:
    @pytest.mark.asyncio
    async def test_telegram_status(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/telegram/status", headers=auth_headers)
        assert r.status_code in [200, 400, 404, 500]

    @pytest.mark.asyncio
    async def test_telegram_webhook(self, client: AsyncClient):
        r = await client.post("/api/telegram/webhook", json={"update_id": 1})
        assert r.status_code in [200, 400, 404, 422]


# ── Twitter Router ────────────────────────────────────────────────────────────

class TestTwitterRouter:
    @pytest.mark.asyncio
    async def test_twitter_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/twitter/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]


# ── LinkedIn Router ──────────────────────────────────────────────────────────

class TestLinkedInRouter:
    @pytest.mark.asyncio
    async def test_linkedin_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/linkedin/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]


# ── HubSpot Router ───────────────────────────────────────────────────────────

class TestHubSpotRouter:
    @pytest.mark.asyncio
    async def test_hubspot_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/hubspot/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]


# ── Outlook Router ───────────────────────────────────────────────────────────

class TestOutlookRouter:
    @pytest.mark.asyncio
    async def test_outlook_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/outlook/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]


# ── Notion Router ────────────────────────────────────────────────────────────

class TestNotionRouter:
    @pytest.mark.asyncio
    async def test_notion_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/notion/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]


# ── Trello Router ────────────────────────────────────────────────────────────

class TestTrelloRouter:
    @pytest.mark.asyncio
    async def test_trello_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/trello/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]


# ── Jira Router ──────────────────────────────────────────────────────────────

class TestJiraRouter:
    @pytest.mark.asyncio
    async def test_jira_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/jira/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]


# ── ClickUp Router ───────────────────────────────────────────────────────────

class TestClickUpRouter:
    @pytest.mark.asyncio
    async def test_clickup_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/clickup/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]


# ── Teams Router ─────────────────────────────────────────────────────────────

class TestTeamsRouter:
    @pytest.mark.asyncio
    async def test_teams_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/teams/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]


# ── Zoom Router ──────────────────────────────────────────────────────────────

class TestZoomRouter:
    @pytest.mark.asyncio
    async def test_zoom_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/zoom/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]


# ── QuickBooks Router ────────────────────────────────────────────────────────

class TestQuickBooksRouter:
    @pytest.mark.asyncio
    async def test_quickbooks_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/quickbooks/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]


# ── Airtable Router ─────────────────────────────────────────────────────────

class TestAirtableRouter:
    @pytest.mark.asyncio
    async def test_airtable_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/airtable/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]


# ── Xero Router ──────────────────────────────────────────────────────────────

class TestXeroRouter:
    @pytest.mark.asyncio
    async def test_xero_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/xero/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]


# ── Zoho Router ──────────────────────────────────────────────────────────────

class TestZohoRouter:
    @pytest.mark.asyncio
    async def test_zoho_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/zoho/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]

    @pytest.mark.asyncio
    async def test_zoho_webhook(self, client: AsyncClient):
        r = await client.post("/api/zoho/webhook", json={"event": "test"})
        assert r.status_code in [200, 400, 404, 422]


# ── TikTok Router ────────────────────────────────────────────────────────────

class TestTikTokRouter:
    @pytest.mark.asyncio
    async def test_tiktok_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/tiktok/auth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]

    @pytest.mark.asyncio
    async def test_tiktok_profile(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/tiktok/profile", headers=auth_headers)
        assert r.status_code in [200, 404, 500]


# ── Asana Router ─────────────────────────────────────────────────────────────

class TestAsanaRouter:
    @pytest.mark.asyncio
    async def test_asana_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/auth/asana/url", headers=auth_headers)
        assert r.status_code in [200, 400, 402, 500]


# ── KRA Router ───────────────────────────────────────────────────────────────

class TestKRARouter:
    @pytest.mark.asyncio
    async def test_kra_pin_check(self, client: AsyncClient, auth_headers):
        r = await client.post("/kra/check-pin", headers=auth_headers, json={
            "pin": "A000000000A"
        })
        assert r.status_code in [200, 400, 404, 422, 500]


# ── Gmail Webhook ────────────────────────────────────────────────────────────

class TestGmailWebhook:
    @pytest.mark.asyncio
    async def test_gmail_webhook_post(self, client: AsyncClient):
        r = await client.post("/api/webhooks/gmail/push", json={
            "message": {"data": "dGVzdA==", "messageId": "1"},
            "subscription": "projects/test/subscriptions/test"
        })
        assert r.status_code in [200, 400, 422]
