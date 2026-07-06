import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.conversational_agent_service import ConversationalAgentService


def test_business_name_falls_back_to_property_name():
    service = ConversationalAgentService()
    result = service._with_rent_landlord_fields(
        {"response_text": "hi"},
        order_notification="Payment received",
        payment_received=True,
    )
    assert result["notify_landlord"] is True
    assert result["landlord_notification"] == "Payment received"
    assert result["payment_received"] is True


def test_build_system_prompt_rent_includes_paybill():
    service = ConversationalAgentService()
    prompt = service._build_system_prompt(
        business_name="Sunset Apartments",
        order_type="rent_collection",
        currency="KES",
        delivery_methods=["pickup"],
        business_config={
            "paybill_number": "123456",
            "mpesa_stk_available": False,
        },
    )
    assert "Sunset Apartments" in prompt
    assert "123456" in prompt
    assert "initiate_rent_stk_payment" not in prompt


def test_build_system_prompt_rent_stk_mode():
    service = ConversationalAgentService()
    prompt = service._build_system_prompt(
        business_name="Sunset Apartments",
        order_type="rent_collection",
        currency="KES",
        delivery_methods=["pickup"],
        business_config={
            "paybill_number": "123456",
            "mpesa_stk_available": True,
        },
    )
    assert "initiate_rent_stk_payment" in prompt


@pytest.mark.asyncio
async def test_rent_template_has_business_name_mapping():
    from src.routers.templates_router import WORKFLOW_TEMPLATES

    rent = next(t for t in WORKFLOW_TEMPLATES if t["id"] == "whatsapp_rent_collection_agent")
    biz = rent["steps"][0]["tool_parameters"]["business_config"]
    assert biz.get("business_name") == "{{variables.property_name}}"
