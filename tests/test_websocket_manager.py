"""Tests for src/services/websocket_manager.py"""
import pytest
from unittest.mock import AsyncMock

class TestConnectionManager:
    def test_import(self):
        from src.services.websocket_manager import ConnectionManager
        manager = ConnectionManager()
        assert manager is not None

    def test_initial_state(self):
        from src.services.websocket_manager import ConnectionManager
        manager = ConnectionManager()
        assert hasattr(manager, 'active_connections')
        assert isinstance(manager.active_connections, dict)

    @pytest.mark.asyncio
    async def test_connect(self):
        from src.services.websocket_manager import ConnectionManager
        manager = ConnectionManager()
        websocket_mock = AsyncMock()
        
        await manager.connect(websocket_mock, "user_1")
        assert "user_1" in manager.active_connections
        assert websocket_mock in manager.active_connections["user_1"]

    @pytest.mark.asyncio
    async def test_disconnect(self):
        from src.services.websocket_manager import ConnectionManager
        manager = ConnectionManager()
        websocket_mock1 = AsyncMock()
        websocket_mock2 = AsyncMock()
        
        await manager.connect(websocket_mock1, "user_1")
        await manager.connect(websocket_mock2, "user_1")
        
        manager.disconnect(websocket_mock1, "user_1")
        
        assert "user_1" in manager.active_connections
        assert websocket_mock1 not in manager.active_connections["user_1"]
        assert websocket_mock2 in manager.active_connections["user_1"]
        
        # Disconnect last connection for user
        manager.disconnect(websocket_mock2, "user_1")
        assert "user_1" not in manager.active_connections

    @pytest.mark.asyncio
    async def test_send_personal_message(self):
        from src.services.websocket_manager import ConnectionManager
        import json
        manager = ConnectionManager()
        websocket_mock = AsyncMock()
        
        await manager.connect(websocket_mock, "user_1")
        
        test_msg = {"type": "test"}
        await manager.send_personal_message(test_msg, "user_1")
        
        websocket_mock.send_text.assert_called_once()
        args, kwargs = websocket_mock.send_text.call_args
        assert json.loads(args[0]) == test_msg

    @pytest.mark.asyncio
    async def test_broadcast(self):
        from src.services.websocket_manager import ConnectionManager
        import json
        manager = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        
        await manager.connect(ws1, "user_1")
        await manager.connect(ws2, "user_2")
        
        test_msg = {"type": "broadcast"}
        await manager.broadcast(test_msg)
        
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()
        
        args1, _ = ws1.send_text.call_args
        assert json.loads(args1[0]) == test_msg
