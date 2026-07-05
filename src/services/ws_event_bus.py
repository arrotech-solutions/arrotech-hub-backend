"""Redis pub/sub bridge so Celery workers can push WebSocket events to web processes."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

WS_INBOX_CHANNEL = "ws:inbox_events"


def publish_inbox_event_sync(user_id: uuid.UUID, event_type: str, data: Dict[str, Any]) -> None:
    """Publish from sync contexts (Celery tasks)."""
    try:
        import redis
        from ..config import settings

        client = redis.from_url(settings.REDIS_URL)
        payload = json.dumps(
            {
                "user_id": str(user_id),
                "event_type": event_type,
                "data": data,
            }
        )
        client.publish(WS_INBOX_CHANNEL, payload)
        client.close()
    except Exception as exc:
        logger.debug("WS inbox Redis publish failed: %s", exc)


async def publish_inbox_event_async(
    user_id: uuid.UUID, event_type: str, data: Dict[str, Any]
) -> None:
    """Publish from async contexts."""
    try:
        import redis.asyncio as aioredis
        from ..config import settings

        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        payload = json.dumps(
            {
                "user_id": str(user_id),
                "event_type": event_type,
                "data": data,
            }
        )
        await client.publish(WS_INBOX_CHANNEL, payload)
        await client.aclose()
    except Exception as exc:
        logger.debug("WS inbox async Redis publish failed: %s", exc)


async def run_inbox_subscriber(stop_event: asyncio.Event) -> None:
    """Subscribe on the web process and forward events to local WebSocket connections."""
    try:
        import redis.asyncio as aioredis
        from ..config import settings
        from .websocket_manager import connection_manager

        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = client.pubsub()
        await pubsub.subscribe(WS_INBOX_CHANNEL)
        logger.info("WebSocket inbox Redis subscriber started on %s", WS_INBOX_CHANNEL)

        while not stop_event.is_set():
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if not message or message.get("type") != "message":
                continue
            try:
                payload = json.loads(message["data"])
                user_id = uuid.UUID(payload["user_id"])
                await connection_manager.push_to_user(
                    user_id,
                    payload["event_type"],
                    payload.get("data") or {},
                )
            except Exception as exc:
                logger.warning("WS inbox subscriber parse/deliver failed: %s", exc)

        await pubsub.unsubscribe(WS_INBOX_CHANNEL)
        await pubsub.aclose()
        await client.aclose()
    except Exception as exc:
        logger.error("WebSocket inbox Redis subscriber failed: %s", exc)
