import pytest
from src.services.workflow_templates import AGENT_TEMPLATES
from src.routers.templates_router import WORKFLOW_TEMPLATES

def test_workflow_templates_exist():
    # Check that rent_collection is in AGENT_TEMPLATES
    assert "whatsapp_rent_collection_agent" in AGENT_TEMPLATES
    template = AGENT_TEMPLATES["whatsapp_rent_collection_agent"]
    
    assert template["name"] == "WhatsApp Rent Collection Agent"
    assert template["platform"] == "whatsapp"
    assert "rent_collection" in template["industry_tags"]
    
    # Check required config
    config = template["required_config"]
    assert "property_name" in config
    assert "paybill_number" in config
    assert "water_billing_enabled" in config
    assert "storage_provider" in config

def test_router_templates_exist():
    # Check that rent_collection is in WORKFLOW_TEMPLATES for the router
    found = False
    for template in WORKFLOW_TEMPLATES:
        if template["id"] == "whatsapp_rent_collection_agent":
            found = True
            assert template["name"] == "WhatsApp Rent Collection Agent"
            assert template["category"] == "Real Estate"
            assert "conversational_agent" in [step["tool_name"] for step in template["steps"]]
            
            # Verify the conversational_agent step has rent_collection order_type
            agent_step = next(step for step in template["steps"] if step["tool_name"] == "conversational_agent")
            assert agent_step["tool_parameters"]["business_config"]["order_type"] == "rent_collection"
            break
            
    assert found, "whatsapp_rent_collection_agent template not found in router"
