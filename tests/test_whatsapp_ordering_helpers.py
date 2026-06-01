"""Tests for WhatsApp ordering UX helpers."""

import pytest

from src.services.whatsapp_ordering_helpers import (
    is_order_confirmation_message,
    normalize_search_query,
    parse_product_button_id,
    sanitize_product_button_id,
    verify_whatsapp_signature,
)


def test_is_order_confirmation():
    assert is_order_confirmation_message("yes")
    assert is_order_confirmation_message("Ndio please")
    assert is_order_confirmation_message("CONFIRM")
    assert not is_order_confirmation_message("I want chicken")


def test_normalize_search_query():
    assert "chicken" in normalize_search_query("chiken stew")


def test_product_button_id_stable():
    assert sanitize_product_button_id("TG-0218: Special!") == "TG-0218__Special_"


def test_parse_product_button_new_format():
    action, pid = parse_product_button_id("cart:TG-0218")
    assert action == "cart"
    assert pid == "TG-0218"


def test_parse_product_button_legacy():
    action, pid = parse_product_button_id("cart:Chicken Stew:400")
    assert action == "cart"
    assert pid is None


def test_webhook_signature():
    secret = "test_secret"
    body = b'{"entry":[]}'
    import hashlib
    import hmac

    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_whatsapp_signature(body, sig, secret)
    assert not verify_whatsapp_signature(body, "sha256=bad", secret)
