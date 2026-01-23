import asyncio
import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.services.tool_validator import ToolArgumentValidator
from src.services.dynamic_tool_registry import dynamic_tool_registry

def test_validator():
    print("\n--- Testing ToolArgumentValidator ---")
    
    tools = [
        {
            "function": {
                "name": "send_email",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "count": {"type": "integer"}
                    },
                    "required": ["to"]
                }
            }
        }
    ]
    
    # Valid case
    valid, msg = ToolArgumentValidator.validate("send_email", {"to": "test@example.com", "count": 5}, tools)
    print(f"Valid case: {valid} (Msg: {msg}) - {'PASS' if valid else 'FAIL'}")
    
    # Missing required
    valid, msg = ToolArgumentValidator.validate("send_email", {"count": 5}, tools)
    print(f"Missing required: {not valid} (Msg: {msg}) - {'PASS' if not valid else 'FAIL'}")
    
    # Wrong type
    valid, msg = ToolArgumentValidator.validate("send_email", {"to": "test", "count": "five"}, tools)
    print(f"Wrong type: {not valid} (Msg: {msg}) - {'PASS' if not valid else 'FAIL'}")
    
    # Unknown tool
    valid, msg = ToolArgumentValidator.validate("unknown_tool", {}, tools)
    print(f"Unknown tool: {not valid} (Msg: {msg}) - {'PASS' if not valid else 'FAIL'}")

def test_semantic_examples():
    print("\n--- Testing Semantic Example Injection ---")
    
    tools = [
        {
            "function": {
                "name": "slack_send_message",
                "description": "Send a message to Slack",
                "few_shot_examples": [
                    {"user": "msg slack", "tool_call": "slack_call"}
                ]
            }
        },
        {
            "function": {
                "name": "create_invoice",
                "description": "Create a financial invoice",
                "few_shot_examples": [
                    {"user": "invoice please", "tool_call": "invoice_call"}
                ]
            }
        }
    ]
    
    # Test Slack query
    ex_slack = dynamic_tool_registry.get_relevant_examples("Send a message to team", tools)
    print(f"Query 'Send a message': Found Slack? {'slack_call' in ex_slack} - {'PASS' if 'slack_call' in ex_slack else 'FAIL'}")
    
    # Test Invoice query
    ex_invoice = dynamic_tool_registry.get_relevant_examples("Create an invoice for $50", tools)
    print(f"Query 'Create invoice': Found Invoice? {'invoice_call' in ex_invoice} - {'PASS' if 'invoice_call' in ex_invoice else 'FAIL'}")
    
    # Test Irrelevant
    ex_none = dynamic_tool_registry.get_relevant_examples("Dance for me", tools)
    print(f"Query 'Dance': {'Found result' if ex_none else 'Empty result'}")

if __name__ == "__main__":
    test_validator()
    test_semantic_examples()
