"""Tests for Google Sheets order upsert on payment."""

from src.services.conversational_agent_service import (
    ConversationalAgentService,
    _ORDERS_SHEET_HEADERS,
    _merge_sheet_records,
)


def test_build_order_sheet_record_from_order_data():
    svc = ConversationalAgentService()
    record = svc._build_order_sheet_record(
        order_data={
            "order_id": "ORD-20260630-ABC123",
            "order_type": "food",
            "item_count": 2,
            "subtotal": 500,
            "currency": "KES",
            "delivery_method": "pickup",
            "delivery_address": "",
            "notes": "",
            "created_at": "2026-06-30T14:00:00",
            "customer": {"name": "Harun Gitundu", "phone": "254711371265", "email": ""},
            "items": [{"name": "Tea", "quantity": 1}, {"name": "Coffee", "quantity": 1}],
        },
        customer={"name": "Harun Gitundu", "phone": "254711371265", "email": ""},
        items_summary="Tea x1; Coffee x1",
        created_at="2026-06-30T14:00:00",
        status="paid",
    )
    assert record["Customer Name"] == "Harun Gitundu"
    assert record["Items"] == "Tea x1; Coffee x1"
    assert record["Item Count"] == "2"
    assert record["Subtotal"] == "500"
    assert record["Delivery Method"] == "pickup"
    assert record["Table Number"] == ""
    assert record["Order Type"] == "food"
    assert record["Created At"] == "2026-06-30T14:00:00"
    assert record["Status"] == "paid"


def test_build_order_sheet_record_includes_table_number_for_dine_in():
    svc = ConversationalAgentService()
    record = svc._build_order_sheet_record(
        order_data={
            "order_id": "ORD-20260722-DINE01",
            "order_type": "food",
            "delivery_method": "dine_in",
            "table_number": "12",
            "customer": {"name": "Asha", "phone": "254700000000"},
        },
        customer={"name": "Asha", "phone": "254700000000"},
        items_summary="Pilau x1",
        created_at="2026-07-22T14:00:00",
        status="pending",
    )
    assert record["Delivery Method"] == "dine_in"
    assert record["Table Number"] == "12"


def test_merge_preserves_existing_nonempty_values():
    headers = list(_ORDERS_SHEET_HEADERS)
    existing = [
        "ORD-1", "pending", "Old Name", "254700000000", "", "", "Old items", "1", "10",
        "KES", "delivery", "", "", "", "retail", "2026-01-01",
    ]
    patch = {"Order ID": "ORD-1", "Status": "paid", "Customer Name": "New Name"}
    merged = _merge_sheet_records(headers, existing, patch, force_status="paid")
    assert merged["Status"] == "paid"
    assert merged["Customer Name"] == "New Name"
    assert merged["Items"] == "Old items"


def test_build_order_sheet_record_separates_whatsapp_and_mpesa_phone():
    svc = ConversationalAgentService()
    record = svc._build_order_sheet_record(
        order_data={
            "order_id": "ORD-1",
            "whatsapp_sender": "254711371265",
            "mpesa_phone": "254797568564",
            "customer": {"name": "Harun", "phone": "254797568564"},
        },
        customer={"name": "Harun", "phone": "254797568564"},
        items_summary="Tea x1",
        created_at="2026-06-30T14:00:00",
        status="paid",
        mpesa_phone="254797568564",
    )
    assert record["Customer Phone"] == "'254711371265"
    assert record["M-Pesa Phone"] == "'254797568564"


def test_orders_sheet_tab_candidates_prefers_orders_after_sheet1_rename():
    from src.services.conversational_agent_service import _orders_sheet_tab_candidates

    assert _orders_sheet_tab_candidates("Sheet1") == ["Orders", "Sheet1"]
    assert _orders_sheet_tab_candidates("Orders") == ["Orders", "Sheet1"]
    assert _orders_sheet_tab_candidates("") == ["Orders", "Sheet1"]


def test_merge_preserves_whatsapp_customer_phone_on_paid_update():
    headers = list(_ORDERS_SHEET_HEADERS)
    existing = [
        "ORD-1", "pending", "Harun", "254711371265", "", "", "Tea x1", "1", "2",
        "KES", "pickup", "", "", "", "food", "2026-06-30T12:00:00",
    ]
    patch = {
        "Order ID": "ORD-1",
        "Status": "paid",
        "Customer Phone": "254797568564",
        "M-Pesa Phone": "254797568564",
    }
    merged = _merge_sheet_records(headers, existing, patch, force_status="paid")
    assert merged["Customer Phone"] == "254711371265"
    assert merged["M-Pesa Phone"] == "254797568564"
    assert merged["Status"] == "paid"
