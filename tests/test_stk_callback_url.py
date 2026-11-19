"""STK ResultURL must hit Hub agent webhook, never the payments logger path."""

from src.services.order_stk_payment_service import (
    build_tenant_stk_callback_url,
    public_api_origin,
)


def test_public_api_origin_strips_payments_callback_path():
    assert (
        public_api_origin(
            "https://prod.api.arrotechsolutions.com/payments/api/mpesa/callback"
        )
        == "https://prod.api.arrotechsolutions.com"
    )


def test_build_tenant_stk_callback_url_from_clean_origin(monkeypatch):
    monkeypatch.setattr(
        "src.services.order_stk_payment_service.settings.API_BASE_URL",
        "https://prod.api.arrotechsolutions.com",
    )
    url = build_tenant_stk_callback_url("SECRET123")
    assert url == (
        "https://prod.api.arrotechsolutions.com/api/agents/daraja/callback/SECRET123"
    )


def test_build_tenant_stk_callback_url_recovers_from_payments_api_base(monkeypatch):
    monkeypatch.setattr(
        "src.services.order_stk_payment_service.settings.API_BASE_URL",
        "https://prod.api.arrotechsolutions.com/payments/api/mpesa/callback",
    )
    url = build_tenant_stk_callback_url("SECRET123")
    assert "/payments/" not in url
    assert url.endswith("/api/agents/daraja/callback/SECRET123")
