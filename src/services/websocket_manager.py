import asyncio
import json
import logging
from typing import Dict, List, Set, Any, Optional
import uuid
from fastapi import WebSocket
import redis.asyncio as aioredis

from ..config import settings

logger = logging.getLogger(__name__)

class ConnectionManager:
    """
    Manages active WebSocket connections to push real-time updates to connected clients.
    Clients are mapped by their user_id to allow targeted event pushing.
    
    Uses Redis Pub/Sub to bridge events between processes (FastAPI workers and Celery workers).
    """
    def __init__(self):
        # Maps user_id -> set of active WebSockets
        self.active_connections: Dict[uuid.UUID, Set[WebSocket]] = {}
        self.lock = asyncio.Lock()
        self.redis_client: Optional[aioredis.Redis] = None
        self.pubsub_task: Optional[asyncio.Task] = None
        self.redis_channel = "hub_ws_events"

    async def initialize(self, subscribe: bool = True):
        """Initialize Redis connection and start subscriber task."""
        if self.redis_client:
            if subscribe and not self.pubsub_task:
                 self.pubsub_task = asyncio.create_task(self._listen_to_redis())
            return

        try:
            self.redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            if subscribe:
                # Start background subscriber task
                self.pubsub_task = asyncio.create_task(self._listen_to_redis())
            logger.info(f"ConnectionManager Redis bridge initialized (subscribe={subscribe})")
        except Exception as e:
            logger.error(f"ConnectionManager Redis initialization failed: {e}")

    async def _listen_to_redis(self):
        """Background task to listen for events from other processes via Redis."""
        pubsub = self.redis_client.pubsub()
        try:
            await pubsub.subscribe(self.redis_channel)
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        payload = json.loads(message["data"])
                        user_id_str = payload.get("user_id")
                        event_type = payload.get("event")
                        data = payload.get("data")
                        
                        if user_id_str:
                            user_id = uuid.UUID(user_id_str)
                            # Only push if we have local connections for this user
                            await self._push_local(user_id, event_type, data)
                    except Exception as e:
                        logger.error(f"Error processing Redis WS message: {e}")
        except asyncio.CancelledError:
            try:
                await pubsub.unsubscribe(self.redis_channel)
                await pubsub.close()
            except:
                pass
        except Exception as e:
            logger.error(f"Redis Pub/Sub listener error: {e}")
            # Try to restart after a delay
            await asyncio.sleep(5)
            self.pubsub_task = asyncio.create_task(self._listen_to_redis())

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
        Push an event to a user. This will publish to Redis so ALL worker processes 
        can check if they have active connections for this user.
        """
        # Lazy initialization if not already done (e.g. in Celery workers)
        if not self.redis_client:
            await self.initialize(subscribe=False)

        # 1. Publish to Redis for cross-process delivery
        if self.redis_client:
            try:
                payload = {
                    "user_id": str(user_id),
                    "event": event_type,
                    "data": data
                }
                await self.redis_client.publish(self.redis_channel, json.dumps(payload))
            except Exception as e:
                logger.error(f"Failed to publish WS event to Redis: {e}")
        
        # NOTE: Redis listener handles ALL pushes to local websockets.
        pass

    async def _push_local(self, user_id: uuid.UUID, event_type: str, data: Any):
        """Internal method to push to local connections only."""
        if user_id not in self.active_connections:
            return
            
        message = {
            "type": event_type,
            "data": data
        }
        
        async with self.lock:
            connections = set(self.active_connections.get(user_id, []))
        
        if not connections:
            return

        disconnected = set()
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.debug(f"Error sending local WS msg to user {user_id}: {e}")
                disconnected.add(websocket)
                
        if disconnected:
            async with self.lock:
                if user_id in self.active_connections:
                    for ws in disconnected:
                        self.active_connections[user_id].discard(ws)
                    if not self.active_connections[user_id]:
                        del self.active_connections[user_id]

# Singleton instance
connection_manager = ConnectionManager()
