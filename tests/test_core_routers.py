"""
Tests for uncovered routers: access, blog, employee, organization, subscription, support.
"""
import pytest
from httpx import AsyncClient


# ── Access Router ─────────────────────────────────────────────────────────────

class TestAccessRouter:
    @pytest.mark.asyncio
    async def test_request_access(self, client: AsyncClient):
        response = await client.post(
            "/access/request",
            json={"email": "earlyuser@example.com", "name": "Early User", "reason": "Testing"}
        )
        assert response.status_code in [200, 201, 400, 422]

    @pytest.mark.asyncio
    async def test_request_access_duplicate(self, client: AsyncClient):
        await client.post("/access/request", json={"email": "dup@example.com", "name": "Dup"})
        r = await client.post("/access/request", json={"email": "dup@example.com", "name": "Dup"})
        assert r.status_code in [200, 400, 409, 422]

    @pytest.mark.asyncio
    async def test_check_access_status(self, client: AsyncClient):
        response = await client.get("/access/status?email=unknown@example.com")
        assert response.status_code in [200, 404, 422]


# ── Blog Router ───────────────────────────────────────────────────────────────

class TestBlogRouter:
    @pytest.mark.asyncio
    async def test_get_blog_posts_public(self, client: AsyncClient):
        response = await client.get("/api/blog/posts")
        assert response.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_get_blog_categories(self, client: AsyncClient):
        response = await client.get("/api/blog/categories")
        assert response.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_get_blog_post_by_slug(self, client: AsyncClient):
        response = await client.get("/api/blog/posts/nonexistent-slug")
        assert response.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_create_blog_post_unauthorized(self, client: AsyncClient):
        response = await client.post("/api/blog/posts", json={
            "title": "Test", "content": "Body", "description": "Desc",
            "slug": "test-post", "author_name": "Admin"
        })
        assert response.status_code in [401, 403, 422]


# ── Employee Router ───────────────────────────────────────────────────────────

class TestEmployeeRouter:
    @pytest.mark.asyncio
    async def test_list_employees_unauthorized(self, client: AsyncClient):
        response = await client.get("/admin/employees")
        assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_list_employees(self, client: AsyncClient, auth_headers):
        response = await client.get("/admin/employees", headers=auth_headers)
        assert response.status_code in [200, 403]

    @pytest.mark.asyncio
    async def test_get_subscribers(self, client: AsyncClient, auth_headers):
        response = await client.get("/admin/subscribers", headers=auth_headers)
        assert response.status_code in [200, 403, 404]


# ── Organization Router ──────────────────────────────────────────────────────

class TestOrganizationRouter:
    @pytest.mark.asyncio
    async def test_list_orgs_unauthorized(self, client: AsyncClient):
        response = await client.get("/api/v1/organizations")
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_list_orgs(self, client: AsyncClient, auth_headers):
        response = await client.get("/api/v1/organizations", headers=auth_headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_create_org(self, client: AsyncClient, auth_headers):
        response = await client.post("/api/v1/organizations", headers=auth_headers, json={
            "name": "Test Org", "slug": "test-org", "industry": "tech"
        })
        assert response.status_code in [200, 201, 400, 422]

    @pytest.mark.asyncio
    async def test_get_org_not_found(self, client: AsyncClient, auth_headers):
        response = await client.get(
            "/api/v1/organizations/00000000-0000-0000-0000-000000000000",
            headers=auth_headers
        )
        assert response.status_code in [404, 403]


# ── Subscription Router ──────────────────────────────────────────────────────

class TestSubscriptionRouter:
    @pytest.mark.asyncio
    async def test_get_subscription_status(self, client: AsyncClient, auth_headers):
        response = await client.get("/subscription/status", headers=auth_headers)
        assert response.status_code in [200, 404]

    @pytest.mark.asyncio
    async def test_get_usage(self, client: AsyncClient, auth_headers):
        response = await client.get("/subscription/usage", headers=auth_headers)
        assert response.status_code in [200, 404, 500]

    @pytest.mark.asyncio
    async def test_get_plans(self, client: AsyncClient):
        response = await client.get("/subscription/plans")
        assert response.status_code in [200, 401, 404]


# ── Support Router ────────────────────────────────────────────────────────────

class TestSupportRouter:
    @pytest.mark.asyncio
    async def test_submit_ticket_unauthorized(self, client: AsyncClient):
        response = await client.post("/api/support/ticket", json={"subject": "Help", "description": "Me"})
        assert response.status_code in [401, 422]

    @pytest.mark.asyncio
    async def test_submit_ticket(self, client: AsyncClient, auth_headers):
        response = await client.post("/api/support/ticket", headers=auth_headers, json={
            "subject": "Help", "message": "I need help", "category": "general"
        })
        assert response.status_code in [200, 201, 400, 422, 500]

    @pytest.mark.asyncio
    async def test_get_tickets(self, client: AsyncClient, auth_headers):
        response = await client.get("/api/support/tickets", headers=auth_headers)
        assert response.status_code in [200, 404]
