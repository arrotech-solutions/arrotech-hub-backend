"""Tests for WhatsApp ordering UX helpers."""

import pytest

from src.services.whatsapp_ordering_helpers import (
    is_order_confirmation_message,
    match_cart_command,
    normalize_search_query,
    parse_product_button_id,
    parse_remove_item_name,
    parse_set_quantity_message,
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


def test_match_cart_command():
    assert match_cart_command("clear cart") == "clear"
    assert match_cart_command("my cart") == "view"
    assert match_cart_command("checkout") == "checkout"
    assert match_cart_command("remove chicken stew") == "remove"
    assert match_cart_command("change pilau to 2") == "set_quantity"


def test_parse_remove_and_quantity():
    assert parse_remove_item_name("remove Chicken Stew") == "Chicken Stew"
    name, qty = parse_set_quantity_message("change pilau to 3")
    assert name == "pilau"
    assert qty == 3.0
    name, qty = parse_set_quantity_message("2 chicken stew")
    assert "chicken" in name
    assert qty == 2.0


def test_webhook_signature():
    secret = "test_secret"
    body = b'{"entry":[]}'
    import hashlib
    import hmac

    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_whatsapp_signature(body, sig, secret)
    assert not verify_whatsapp_signature(body, "sha256=bad", secret)
