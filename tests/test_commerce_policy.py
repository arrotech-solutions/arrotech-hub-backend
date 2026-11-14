"""Merchant commerce policy service and HTTP API."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User
from src.services.commerce_policy import (
    DEFAULT_COMMERCE_POLICY,
    CommercePolicyValidationError,
    get_policy,
    upsert_policy,
)


def _policy_body(data: dict) -> dict:
    inner = data.get("data")
    return inner if isinstance(inner, dict) else {}


@pytest.mark.asyncio
async def test_get_policy_merges_defaults_when_no_row(
    db_session: AsyncSession,
    test_user: User,
):
    """get_policy returns every DEFAULT_COMMERCE_POLICY key with default values."""
    policy = await get_policy(db_session, test_user.id)
    assert set(policy.keys()) == set(DEFAULT_COMMERCE_POLICY.keys())
    assert policy["cancel_until_status"] == "preparing"
    assert policy["commerce_rails_enabled"] is True
    assert policy["auto_approve_enabled"] is False


@pytest.mark.asyncio
async def test_upsert_policy_rejects_negative_auto_approve_max(
    db_session: AsyncSession,
    test_user: User,
):
    with pytest.raises(CommercePolicyValidationError):
        await upsert_policy(
            db_session,
            test_user.id,
            {"auto_approve_max_amount_kes": -100},
        )


@pytest.mark.asyncio
async def test_put_policy_round_trip(
    client: AsyncClient,
    auth_headers,
    test_user: User,
):
    """PUT /api/commerce/policy persists overrides; GET returns merged policy."""
    get_resp = await client.get("/api/commerce/policy", headers=auth_headers)
    assert get_resp.status_code == 200, get_resp.text
    baseline = _policy_body(get_resp.json())
    assert baseline.get("return_window_days") == DEFAULT_COMMERCE_POLICY["return_window_days"]

    patch = {
        "return_window_days": 14,
        "auto_approve_enabled": True,
        "auto_approve_max_amount_kes": 2500,
        "delivery_methods": ["delivery", "pickup"],
    }
    put_resp = await client.put(
        "/api/commerce/policy",
        headers=auth_headers,
        json=patch,
    )
    assert put_resp.status_code == 200, put_resp.text
    body = put_resp.json()
    assert body.get("success") is True
    saved = _policy_body(body)
    assert saved["return_window_days"] == 14
    assert saved["auto_approve_enabled"] is True
    assert saved["auto_approve_max_amount_kes"] == 2500
    assert saved["delivery_methods"] == ["delivery", "pickup"]
    assert saved["cancel_until_status"] == "preparing"

    get_again = await client.get("/api/commerce/policy", headers=auth_headers)
    assert get_again.status_code == 200
    again = _policy_body(get_again.json())
    assert again["return_window_days"] == 14
    assert again["auto_approve_enabled"] is True