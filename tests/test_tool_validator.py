"""
Tests for src/services/tool_validator.py — ToolArgumentValidator type checking and validation.
"""
import pytest


SAMPLE_TOOLS = [
    {"function": {"name": "send_email", "parameters": {
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "count": {"type": "integer"},
            "urgent": {"type": "boolean"},
            "tags": {"type": "array"},
            "metadata": {"type": "object"},
            "score": {"type": "number"},
        },
        "required": ["to", "subject"]
    }}},
    {"function": {"name": "no_required", "parameters": {
        "type": "object",
        "properties": {"optional_field": {"type": "string"}},
        "required": []
    }}},
]


class TestToolArgumentValidator:
    def test_valid_args(self):
        from src.services.tool_validator import ToolArgumentValidator
        valid, msg = ToolArgumentValidator.validate(
            "send_email", {"to": "a@b.com", "subject": "Hi"}, SAMPLE_TOOLS
        )
        assert valid is True
        assert msg is None

    def test_missing_required_param(self):
        from src.services.tool_validator import ToolArgumentValidator
        valid, msg = ToolArgumentValidator.validate(
            "send_email", {"to": "a@b.com"}, SAMPLE_TOOLS
        )
        assert valid is False
        assert "subject" in msg

    def test_missing_all_required(self):
        from src.services.tool_validator import ToolArgumentValidator
        valid, msg = ToolArgumentValidator.validate(
            "send_email", {}, SAMPLE_TOOLS
        )
        assert valid is False

    def test_unknown_tool(self):
        from src.services.tool_validator import ToolArgumentValidator
        valid, msg = ToolArgumentValidator.validate("nonexistent", {}, SAMPLE_TOOLS)
        assert valid is False
        assert "not in the list" in msg

    def test_wrong_type_string(self):
        from src.services.tool_validator import ToolArgumentValidator
        valid, msg = ToolArgumentValidator.validate(
            "send_email", {"to": 123, "subject": "Hi"}, SAMPLE_TOOLS
        )
        assert valid is False
        assert "string" in msg

    def test_wrong_type_integer(self):
        from src.services.tool_validator import ToolArgumentValidator
        valid, msg = ToolArgumentValidator.validate(
            "send_email", {"to": "a", "subject": "b", "count": "five"}, SAMPLE_TOOLS
        )
        assert valid is False
        assert "integer" in msg

    def test_boolean_not_integer(self):
        from src.services.tool_validator import ToolArgumentValidator
        # bool is subclass of int in Python — validator should reject bool for integer
        valid, msg = ToolArgumentValidator.validate(
            "send_email", {"to": "a", "subject": "b", "count": True}, SAMPLE_TOOLS
        )
        assert valid is False

    def test_wrong_type_boolean(self):
        from src.services.tool_validator import ToolArgumentValidator
        valid, msg = ToolArgumentValidator.validate(
            "send_email", {"to": "a", "subject": "b", "urgent": "yes"}, SAMPLE_TOOLS
        )
        assert valid is False
        assert "boolean" in msg

    def test_wrong_type_array(self):
        from src.services.tool_validator import ToolArgumentValidator
        valid, msg = ToolArgumentValidator.validate(
            "send_email", {"to": "a", "subject": "b", "tags": "not_a_list"}, SAMPLE_TOOLS
        )
        assert valid is False
        assert "list" in msg or "array" in msg

    def test_wrong_type_object(self):
        from src.services.tool_validator import ToolArgumentValidator
        valid, msg = ToolArgumentValidator.validate(
            "send_email", {"to": "a", "subject": "b", "metadata": "string"}, SAMPLE_TOOLS
        )
        assert valid is False
        assert "dictionary" in msg or "object" in msg

    def test_wrong_type_number(self):
        from src.services.tool_validator import ToolArgumentValidator
        valid, msg = ToolArgumentValidator.validate(
            "send_email", {"to": "a", "subject": "b", "score": "nope"}, SAMPLE_TOOLS
        )
        assert valid is False
        assert "number" in msg

    def test_valid_number_as_float(self):
        from src.services.tool_validator import ToolArgumentValidator
        valid, msg = ToolArgumentValidator.validate(
            "send_email", {"to": "a", "subject": "b", "score": 3.14}, SAMPLE_TOOLS
        )
        assert valid is True

    def test_valid_number_as_int(self):
        from src.services.tool_validator import ToolArgumentValidator
        valid, msg = ToolArgumentValidator.validate(
            "send_email", {"to": "a", "subject": "b", "score": 5}, SAMPLE_TOOLS
        )
        assert valid is True

    def test_extra_args_allowed(self):
        from src.services.tool_validator import ToolArgumentValidator
        valid, msg = ToolArgumentValidator.validate(
            "send_email", {"to": "a", "subject": "b", "extra": "value"}, SAMPLE_TOOLS
        )
        assert valid is True

    def test_no_required_params(self):
        from src.services.tool_validator import ToolArgumentValidator
        valid, msg = ToolArgumentValidator.validate(
            "no_required", {}, SAMPLE_TOOLS
        )
        assert valid is True

    def test_flat_tool_format(self):
        """Test tool definitions without nested 'function' key."""
        from src.services.tool_validator import ToolArgumentValidator
        flat_tools = [{"name": "simple_tool", "parameters": {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"]
        }}]
        valid, msg = ToolArgumentValidator.validate(
            "simple_tool", {"x": "val"}, flat_tools
        )
        assert valid is True

    def test_empty_tool_list(self):
        from src.services.tool_validator import ToolArgumentValidator
        valid, msg = ToolArgumentValidator.validate("anything", {}, [])
        assert valid is False


class TestCheckType:
    def test_check_type_string_valid(self):
        from src.services.tool_validator import ToolArgumentValidator
        result = ToolArgumentValidator._check_type("f", "hello", "string")
        assert result is None

    def test_check_type_string_invalid(self):
        from src.services.tool_validator import ToolArgumentValidator
        result = ToolArgumentValidator._check_type("f", 123, "string")
        assert result is not None

    def test_check_type_integer_valid(self):
        from src.services.tool_validator import ToolArgumentValidator
        result = ToolArgumentValidator._check_type("f", 42, "integer")
        assert result is None

    def test_check_type_integer_rejects_bool(self):
        from src.services.tool_validator import ToolArgumentValidator
        result = ToolArgumentValidator._check_type("f", True, "integer")
        assert result is not None

    def test_check_type_boolean_valid(self):
        from src.services.tool_validator import ToolArgumentValidator
        result = ToolArgumentValidator._check_type("f", True, "boolean")
        assert result is None

    def test_check_type_array_valid(self):
        from src.services.tool_validator import ToolArgumentValidator
        result = ToolArgumentValidator._check_type("f", [1, 2], "array")
        assert result is None

    def test_check_type_object_valid(self):
        from src.services.tool_validator import ToolArgumentValidator
        result = ToolArgumentValidator._check_type("f", {"k": "v"}, "object")
        assert result is None

    def test_check_type_number_accepts_float(self):
        from src.services.tool_validator import ToolArgumentValidator
        result = ToolArgumentValidator._check_type("f", 3.14, "number")
        assert result is None

    def test_check_type_number_rejects_bool(self):
        from src.services.tool_validator import ToolArgumentValidator
        result = ToolArgumentValidator._check_type("f", False, "number")
        assert result is not None

    def test_check_type_unknown_type_passes(self):
        from src.services.tool_validator import ToolArgumentValidator
        result = ToolArgumentValidator._check_type("f", "any", "custom")
        assert result is None
