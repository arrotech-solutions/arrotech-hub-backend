import asyncio
import json
import logging
from typing import Dict, List, Set, Any
import uuid
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class ConnectionManager:
    """
    Manages active WebSocket connections to push real-time updates to connected clients.
    Clients are mapped by their user_id to allow targeted event pushing.
    """
    def __init__(self):
        # Maps user_id -> set of active WebSockets
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: uuid.UUID):
        await websocket.accept()
        async with self.lock:
            if user_id not in self.active_connections:
                self.active_connections[user_id] = set()
            self.active_connections[user_id].add(websocket)
            logger.info(f"WebSocket connected for user {user_id}. Active sessions: {len(self.active_connections[user_id])}")

    async def disconnect(self, websocket: WebSocket, user_id: uuid.UUID):
        async with self.lock:
            if user_id in self.active_connections:
                self.active_connections[user_id].discard(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
                logger.info(f"WebSocket disconnected for user {user_id}.")

    async def push_to_user(self, user_id: uuid.UUID, event_type: str, data: Any):
        """
        Push a JSON event to all active WebSocket connections for a specific user.
        """
        if user_id not in self.active_connections:
            return  # User is not currently connected
            
        message = {
            "type": event_type,
            "data": data
        }
        
        # We need to copy the set to safely iterate while awaiting async pushes
        # in case a client disconnects mid-broadcast
        connections = set(self.active_connections[user_id])
        
        disconnected = set()
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error sending WS msg to user {user_id}: {e}")
                disconnected.add(websocket)
                
        # Clean up any dead connections
        if disconnected:
            async with self.lock:
                for ws in disconnected:
                    if user_id in self.active_connections:
                        self.active_connections[user_id].discard(ws)
                if user_id in self.active_connections and not self.active_connections[user_id]:
                    del self.active_connections[user_id]

# Singleton instance
connection_manager = ConnectionManager()
