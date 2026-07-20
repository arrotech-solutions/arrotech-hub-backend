"""Tests for WhatsApp ordering template storage wiring."""

from src.routers.templates_router import WORKFLOW_TEMPLATES
from src.services.whatsapp_workflow_trigger import _merge_workflow_storage_into_config


def _whatsapp_template():
    return next(t for t in WORKFLOW_TEMPLATES if t["id"] == "whatsapp_ordering_agent")


def test_whatsapp_template_exposes_transactions_sheet_variable():
    variables = _whatsapp_template()["variables"]
    assert "storage_transactions_sheet_name" in variables
    assert variables["storage_transactions_sheet_name"]["default"] == "Transactions"
    assert "storage_airtable_transactions_table" in variables


def test_whatsapp_template_wires_storage_into_business_config():
    step = _whatsapp_template()["steps"][0]
    business_config = step["tool_parameters"]["business_config"]
    assert business_config["storage_orders_sheet_name"] == "{{variables.storage_orders_sheet_name}}"
    assert business_config["storage_customers_sheet_name"] == "{{variables.storage_customers_sheet_name}}"
    assert business_config["storage_transactions_sheet_name"] == "{{variables.storage_transactions_sheet_name}}"
    assert business_config["storage_airtable_transactions_table"] == (
        "{{variables.storage_airtable_transactions_table}}"
    )


def test_merge_workflow_storage_into_config_backfills_top_level_variables():
    merged = _merge_workflow_storage_into_config(
        {},
        {
            "storage_orders_sheet_name": "Sheet1",
            "storage_transactions_sheet_name": "Transactions",
        },
    )
    assert merged["storage_orders_sheet_name"] == "Sheet1"
    assert merged["storage_transactions_sheet_name"] == "Transactions"


def test_merge_workflow_storage_into_config_prefers_existing_config():
    merged = _merge_workflow_storage_into_config(
        {"storage_orders_sheet_name": "Orders"},
        {"storage_orders_sheet_name": "Sheet1"},
    )
    assert merged["storage_orders_sheet_name"] == "Orders"
