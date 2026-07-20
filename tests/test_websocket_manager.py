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
        
        await manager.disconnect(websocket_mock1, "user_1")
        
        assert "user_1" in manager.active_connections
        assert websocket_mock1 not in manager.active_connections["user_1"]
        assert websocket_mock2 in manager.active_connections["user_1"]
        
        # Disconnect last connection for user
        await manager.disconnect(websocket_mock2, "user_1")
        assert "user_1" not in manager.active_connections

    @pytest.mark.asyncio
    async def test_push_to_user(self):
        from src.services.websocket_manager import ConnectionManager
        manager = ConnectionManager()
        websocket_mock = AsyncMock()
        
        await manager.connect(websocket_mock, "user_1")
        
        test_data = {"msg": "hello"}
        await manager.push_to_user("user_1", "test_event", test_data)
        
        websocket_mock.send_json.assert_called_once_with({
            "type": "test_event",
            "data": test_data
        })

    @pytest.mark.asyncio
    async def test_push_to_user_not_connected(self):
        from src.services.websocket_manager import ConnectionManager
        manager = ConnectionManager()
        websocket_mock = AsyncMock()
        
        await manager.push_to_user("user_unknown", "test_event", {})
        websocket_mock.send_json.assert_not_called()
