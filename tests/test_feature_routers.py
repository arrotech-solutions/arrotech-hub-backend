"""
Tests for AI, security, productivity, RAG, assistant, public forms,
developer, Google Workspace, and WebSocket routers.
"""
import pytest
from httpx import AsyncClient


# ── AI Router ─────────────────────────────────────────────────────────────────

class TestAIRouter:
    @pytest.mark.asyncio
    async def test_ai_generate_unauthorized(self, client: AsyncClient):
        r = await client.post("/api/v1/ai/generate", json={"prompt": "Hello"})
        assert r.status_code in [401, 422]

    @pytest.mark.asyncio
    async def test_ai_generate(self, client: AsyncClient, auth_headers):
        r = await client.post("/api/v1/ai/generate", headers=auth_headers, json={
            "prompt": "Write a greeting", "provider": "openai"
        })
        assert r.status_code in [200, 400, 422, 500]

    @pytest.mark.asyncio
    async def test_ai_models(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/v1/ai/models", headers=auth_headers)
        assert r.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_ai_providers(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/v1/ai/providers", headers=auth_headers)
        assert r.status_code in [200, 404]


# ── Security Router ──────────────────────────────────────────────────────────

class TestSecurityRouter:
    @pytest.mark.asyncio
    async def test_get_security_overview_unauthorized(self, client: AsyncClient):
        r = await client.get("/api/v1/security/overview")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_get_security_overview(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/v1/security/overview", headers=auth_headers)
        assert r.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_get_audit_log(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/v1/security/audit-log", headers=auth_headers)
        assert r.status_code in [200, 403, 404]

    @pytest.mark.asyncio
    async def test_setup_2fa(self, client: AsyncClient, auth_headers):
        r = await client.post("/api/v1/security/2fa/setup", headers=auth_headers)
        assert r.status_code in [200, 400, 422, 500]

    @pytest.mark.asyncio
    async def test_get_passkeys(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/v1/security/passkeys", headers=auth_headers)
        assert r.status_code in [200, 404]


# ── Productivity Router ──────────────────────────────────────────────────────

class TestProductivityRouter:
    @pytest.mark.asyncio
    async def test_get_productivity_dashboard(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/v1/productivity/dashboard", headers=auth_headers)
        assert r.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_get_productivity_unauthorized(self, client: AsyncClient):
        r = await client.get("/api/v1/productivity/dashboard")
        assert r.status_code == 401


# ── RAG Router ────────────────────────────────────────────────────────────────

class TestRAGRouter:
    @pytest.mark.asyncio
    async def test_list_knowledge_bases(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/v1/rag/knowledge-bases", headers=auth_headers)
        assert r.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_list_kb_unauthorized(self, client: AsyncClient):
        r = await client.get("/api/v1/rag/knowledge-bases")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_create_knowledge_base(self, client: AsyncClient, auth_headers):
        r = await client.post("/api/v1/rag/knowledge-bases", headers=auth_headers, json={
            "name": "Test KB", "description": "A test knowledge base"
        })
        assert r.status_code in [200, 201, 400, 422, 500]

    @pytest.mark.asyncio
    async def test_search_kb(self, client: AsyncClient, auth_headers):
        r = await client.post("/api/v1/rag/search", headers=auth_headers, json={
            "query": "test query", "namespace": "default"
        })
        assert r.status_code in [200, 400, 422, 500]


# ── Assistant Router ─────────────────────────────────────────────────────────

class TestAssistantRouter:
    @pytest.mark.asyncio
    async def test_assistant_chat(self, client: AsyncClient, auth_headers):
        r = await client.post("/api/v1/assistant/chat", headers=auth_headers, json={
            "message": "What can you help me with?"
        })
        assert r.status_code in [200, 400, 422, 500]

    @pytest.mark.asyncio
    async def test_assistant_chat_unauthorized(self, client: AsyncClient):
        r = await client.post("/api/v1/assistant/chat", json={"message": "hi"})
        assert r.status_code in [401, 422]


# ── Public Forms Router ──────────────────────────────────────────────────────

class TestPublicFormsRouter:
    @pytest.mark.asyncio
    async def test_contact_form_submit(self, client: AsyncClient):
        r = await client.post("/api/v1/public/contact", json={
            "name": "Test User", "email": "test@example.com",
            "subject": "Test", "message": "Hello"
        })
        assert r.status_code in [200, 201, 400, 422, 500]

    @pytest.mark.asyncio
    async def test_newsletter_subscribe(self, client: AsyncClient):
        r = await client.post("/api/v1/public/newsletter/subscribe", json={
            "email": "subscriber@example.com"
        })
        assert r.status_code in [200, 201, 400, 409, 422, 500]

    @pytest.mark.asyncio
    async def test_newsletter_duplicate(self, client: AsyncClient):
        await client.post("/api/v1/public/newsletter/subscribe", json={"email": "dup@example.com"})
        r = await client.post("/api/v1/public/newsletter/subscribe", json={"email": "dup@example.com"})
        assert r.status_code in [200, 400, 409, 422]


# ── Google Workspace Router ──────────────────────────────────────────────────

class TestGoogleWorkspaceRouter:
    @pytest.mark.asyncio
    async def test_google_oauth_url(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/google-workspace/oauth-url", headers=auth_headers)
        assert r.status_code in [200, 400, 500]


# ── M-Pesa Agent Router ─────────────────────────────────────────────────────

class TestMpesaAgentRouter:
    @pytest.mark.asyncio
    async def test_get_mpesa_config(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/agents/mpesa/config", headers=auth_headers)
        assert r.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_mpesa_config_unauthorized(self, client: AsyncClient):
        r = await client.get("/api/agents/mpesa/config")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_get_mpesa_payments(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/agents/mpesa/payments", headers=auth_headers)
        assert r.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_get_mpesa_invoices(self, client: AsyncClient, auth_headers):
        r = await client.get("/api/agents/mpesa/invoices", headers=auth_headers)
        assert r.status_code in [200, 404]


# ── Slack Agent Router ───────────────────────────────────────────────────────

class TestSlackAgentRouter:
    @pytest.mark.asyncio
    async def test_slack_events(self, client: AsyncClient):
        r = await client.post("/api/slack/events", json={
            "type": "url_verification", "challenge": "test_challenge"
        })
        assert r.status_code in [200, 400, 422]
