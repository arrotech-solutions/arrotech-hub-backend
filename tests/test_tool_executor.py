"""Tests for src/services/tool_executor.py"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

class TestToolExecutor:
    def test_import(self):
        from src.services.tool_executor import ToolExecutor
        svc = ToolExecutor()
        assert svc is not None

    def test_instantiate(self):
        from src.services.tool_executor import ToolExecutor
        svc = ToolExecutor()
        assert hasattr(svc, '__class__')

    @pytest.mark.asyncio
    async def test_get_platform_from_tool(self):
        from src.services.tool_executor import ToolExecutor
        svc = ToolExecutor()
        assert svc._get_platform_from_tool("slack_send_message") == "slack"
        assert svc._get_platform_from_tool("whatsapp_send") == None # Handled differently
        assert svc._get_platform_from_tool("kra_validate") == "kra_portal"
        assert svc._get_platform_from_tool("unknown_tool") == None

    def test_sanitize_chat_message(self):
        from src.services.tool_executor import ToolExecutor
        svc = ToolExecutor()
        raw = "```python\nprint('hello')\n```\n**Bold** and __Underline__"
        clean = svc._sanitize_chat_message_for_channel(raw, "whatsapp")
        assert "```" not in clean
        assert "*Bold*" in clean
        assert "*Underline*" in clean

    def test_parse_image_urls(self):
        from src.services.tool_executor import ToolExecutor
        svc = ToolExecutor()
        assert svc._parse_image_urls("['http://test.com/img.jpg']") == ["http://test.com/img.jpg"]
        assert svc._parse_image_urls('["http://test.com/img.jpg"]') == ["http://test.com/img.jpg"]
        assert svc._parse_image_urls("http://test.com/img.jpg") == ["http://test.com/img.jpg"]
        assert svc._parse_image_urls([]) == []

    @pytest.mark.asyncio
    async def test_execute_tool_unknown(self):
        from src.services.tool_executor import ToolExecutor
        svc = ToolExecutor()
        user_mock = MagicMock()
        user_mock.subscription_tier = "FREE"
        db_mock = AsyncMock()
        
        # Override connection check to pass
        with patch.object(svc, '_check_connection_access', return_value=True):
            result = await svc.execute_tool("unknown_random_tool", {}, user_mock, db_mock)
            assert result["success"] is False
            assert "Unknown tool" in result["error"]
