"""Tests for WhatsApp ordering UX helpers."""

import pytest

from src.services.whatsapp_ordering_helpers import (
    format_checkout_confirmation,
    is_order_confirmation_message,
    match_cart_command,
    normalize_search_query,
    parse_checkout_details,
    parse_table_number,
    clean_checkout_customer_name,
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
    assert not is_order_confirmation_message("ok")
    assert not is_order_confirmation_message("sure")
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


def test_parse_checkout_detects_dine_in():
    assert parse_checkout_details("dine in").get("delivery_method") == "dine_in"
    assert parse_checkout_details("I'll eat in").get("delivery_method") == "dine_in"
    assert parse_checkout_details("kula hapa").get("delivery_method") == "dine_in"


def test_parse_table_number_variants():
    assert parse_table_number("table 12") == "12"
    assert parse_table_number("Table No. 7") == "7"
    assert parse_table_number("meza 5") == "5"
    assert parse_table_number("A3") == "A3"
    assert parse_table_number("15") == "15"
    assert parse_table_number("#9") == "9"


def test_parse_table_number_skip_returns_empty():
    assert parse_table_number("skip") == ""
    assert parse_table_number("I don't know") == ""
    assert parse_table_number("sina") == ""
    assert parse_table_number("") == ""


def test_format_checkout_confirmation_dine_in_shows_table():
    cart = [{"name": "Pilau", "quantity": 1, "unit_price": 400}]
    msg = format_checkout_confirmation(
        cart=cart,
        currency="KES",
        customer_name="Asha",
        customer_phone="254700000000",
        delivery_method="dine_in",
        table_number="12",
    )
    assert "🍽️" in msg
    assert "Table: 12" in msg


def test_format_checkout_confirmation_dine_in_without_table():
    cart = [{"name": "Pilau", "quantity": 1, "unit_price": 400}]
    msg = format_checkout_confirmation(
        cart=cart,
        currency="KES",
        customer_name="Asha",
        customer_phone="254700000000",
        delivery_method="dine_in",
        table_number="",
    )
    assert "🍽️" in msg
    assert "Table:" not in msg


def test_webhook_signature():
    secret = "test_secret"
    body = b'{"entry":[]}'
    import hashlib
    import hmac

    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_whatsapp_signature(body, sig, secret)
    assert not verify_whatsapp_signature(body, "sha256=bad", secret)


@pytest.mark.parametrize(
    "message,expected_name,expected_delivery",
    [
        ("Name: Harun Gitundu\nPickup", "Harun Gitundu", "pickup"),
        ("Harun Gitundu\nPickup", "Harun Gitundu", "pickup"),
        ("Name: Harun Gitundu Pickup", "Harun Gitundu", "pickup"),
        ("Harun Gitundu Pickup", "Harun Gitundu", "pickup"),
        ("Name: Harun Gitundu\nDelivery", "Harun Gitundu", "delivery"),
    ],
)
def test_parse_checkout_details_splits_name_and_delivery(message, expected_name, expected_delivery):
    parsed = parse_checkout_details(message)
    assert parsed["name"] == expected_name
    assert parsed["delivery_method"] == expected_delivery


def test_merge_sheet_records_fills_empty_cells():
    from src.services.conversational_agent_service import (
        _ORDERS_SHEET_HEADERS,
        _merge_sheet_records,
    )

    headers = list(_ORDERS_SHEET_HEADERS)
    sparse_row = [
        "ORD-1", "paid", "", "", "", "", "", "", "", "KES", "", "", "", "", "",
    ]
    full_record = {
        "Order ID": "ORD-1",
        "Status": "paid",
        "Customer Name": "Harun Gitundu",
        "Customer Phone": "254711371265",
        "Items": "Tea x1",
        "Item Count": "1",
        "Subtotal": "2",
        "Delivery Method": "pickup",
        "Order Type": "food",
        "Created At": "2026-06-30T12:00:00",
    }
    merged = _merge_sheet_records(headers, sparse_row, full_record, force_status="paid")
    assert merged["Customer Name"] == "Harun Gitundu"
    assert merged["Items"] == "Tea x1"
    assert merged["Item Count"] == "1"
    assert merged["Subtotal"] == "2"
    assert merged["Delivery Method"] == "pickup"
    assert merged["Order Type"] == "food"
    assert merged["Created At"] == "2026-06-30T12:00:00"
    assert merged["Status"] == "paid"


def test_clean_checkout_customer_name_strips_multiline_delivery():
    assert clean_checkout_customer_name("Harun Gitundu\nPickup") == "Harun Gitundu"
    assert clean_checkout_customer_name("Name: Harun Gitundu\nPickup") == "Harun Gitundu"
