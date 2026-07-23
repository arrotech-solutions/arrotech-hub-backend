"""Tests for WhatsApp ordering UX helpers."""

import pytest

from src.services.whatsapp_ordering_helpers import (
    detect_reservation_intent,
    format_checkout_confirmation,
    format_reservation_summary_line,
    is_order_confirmation_message,
    is_reservation_cancel,
    match_cart_command,
    normalize_search_query,
    parse_checkout_details,
    parse_party_size,
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


def test_coerce_delivery_methods_from_jinja_string():
    from src.services.whatsapp_ordering_helpers import (
        apply_food_only_fulfillment,
        coerce_delivery_methods,
        is_food_business,
    )

    assert coerce_delivery_methods(["delivery", "pickup", "dine_in"]) == [
        "delivery", "pickup", "dine_in"
    ]
    assert coerce_delivery_methods("['delivery', 'pickup', 'dine_in']") == [
        "delivery", "pickup", "dine_in"
    ]
    assert coerce_delivery_methods("delivery, pickup") == ["delivery", "pickup"]


def test_apply_food_only_fulfillment_strips_dine_in_and_reservations():
    from src.services.whatsapp_ordering_helpers import apply_food_only_fulfillment

    methods, res = apply_food_only_fulfillment(
        "retail", ["delivery", "pickup", "dine_in"], True
    )
    assert methods == ["delivery", "pickup"]
    assert res is False

    methods, res = apply_food_only_fulfillment(
        "food", ["delivery", "dine_in"], True
    )
    assert "dine_in" in methods
    assert res is True


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


# ── Reservation flow helpers ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "I wanna book a reservation for two",
        "I would like to make a reservation",
        "can you reserve a table",
        "book a table for us tonight",
        "nataka kuweka meza",
    ],
)
def test_detect_reservation_intent_true(message):
    assert detect_reservation_intent(message)


@pytest.mark.parametrize(
    "message",
    [
        "I want to order pizza",
        "show me the menu",
        "add chicken to cart",
        "how much is a soda",
        "",
    ],
)
def test_detect_reservation_intent_false(message):
    assert not detect_reservation_intent(message)


@pytest.mark.parametrize(
    "message,expected",
    [
        ("book a reservation for two", 2),
        ("party of 4", 4),
        ("table for 3", 3),
        ("we are 5 people", 5),
        ("reservation for six", 6),
    ],
)
def test_parse_party_size_explicit(message, expected):
    assert parse_party_size(message) == expected


def test_parse_party_size_ignores_dates_and_times_without_bare():
    # A date or time number must never be read as a head count.
    assert parse_party_size("24th July 2026") is None
    assert parse_party_size("10 p.m") is None


@pytest.mark.parametrize(
    "message,expected",
    [
        ("2", 2),
        ("two", 2),
        ("the number of guests is two", 2),
        ("just 3 of us", 3),
    ],
)
def test_parse_party_size_bare(message, expected):
    assert parse_party_size(message, bare=True) == expected


@pytest.mark.parametrize(
    "message",
    ["cancel", "stop", "never mind", "cancel booking", "acha"],
)
def test_is_reservation_cancel_true(message):
    assert is_reservation_cancel(message)


@pytest.mark.parametrize(
    "message",
    ["10 p.m", "Harun Gitundu", "24th July 2026", "yes"],
)
def test_is_reservation_cancel_false(message):
    assert not is_reservation_cancel(message)


def test_format_reservation_summary_uses_exact_values():
    summary = format_reservation_summary_line(
        customer_name="Harun Gitundu",
        customer_phone="254711371265",
        reservation_date="24th July 2026",
        reservation_time="10 p.m",
        party_size=2,
        business_name="Tians Grill",
    )
    # Exactly what the customer supplied — never a hallucinated/normalised value.
    assert "Harun Gitundu" in summary
    assert "24th July 2026" in summary
    assert "10 p.m" in summary
    assert "Party size: 2" in summary
    assert "YES" in summary
