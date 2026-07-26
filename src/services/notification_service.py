"""
Central notification service — preference-aware delivery across in-app,
email, Slack, and webhook channels.
"""
from __future__ import annotations

import hashlib
import logging
import time as time_mod
import uuid
from datetime import datetime, time, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Notification, UserSettings
from src.services.notification_events import (
    CHANNELS,
    category_for_event,
    merge_rules,
    severity_for_event,
)

logger = logging.getLogger(__name__)

_dedupe_cache: Dict[str, float] = {}
_DEDUPE_TTL_SECONDS = 120.0


def _dedupe_key(user_id: uuid.UUID, event_key: str, entity_id: Optional[str]) -> str:
    raw = f"{user_id}:{event_key}:{entity_id or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _should_dedupe(key: str) -> bool:
    now = time_mod.time()
    if len(_dedupe_cache) > 5000:
        expired = [k for k, ts in _dedupe_cache.items() if now - ts > _DEDUPE_TTL_SECONDS]
        for k in expired:
            _dedupe_cache.pop(k, None)
    prev = _dedupe_cache.get(key)
    if prev is not None and now - prev < _DEDUPE_TTL_SECONDS:
        return True
    _dedupe_cache[key] = now
    return False


def _in_quiet_hours(quiet: Optional[Dict], now: Optional[datetime] = None) -> bool:
    """Return True if current local time falls within quiet hours (non-critical only)."""
    if not quiet or not isinstance(quiet, dict):
        return False
    start_s = quiet.get("start")
    end_s = quiet.get("end")
    if not start_s or not end_s:
        return False
    tz_name = quiet.get("timezone") or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc).astimezone(tz)
    else:
        now = now.astimezone(tz)

    def parse_hm(s: str) -> time:
        parts = str(s).split(":")
        return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)

    try:
        start_t = parse_hm(start_s)
        end_t = parse_hm(end_s)
    except Exception:
        return False

    cur = now.time()
    if start_t <= end_t:
        return start_t <= cur < end_t
    return cur >= start_t or cur < end_t


async def _get_settings(db: AsyncSession, user_id: uuid.UUID) -> Optional[UserSettings]:
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    return result.scalar_one_or_none()


def resolve_channels(
    settings: Optional[UserSettings],
    event_key: str,
) -> Dict[str, bool]:
    """
    Resolve which channels should fire for this event.
    Critical severity always keeps in_app True.
    Channel masters on UserSettings gate email/slack/webhook.
    Quiet hours suppress email/slack/webhook for non-critical events.
    """
    severity = severity_for_event(event_key)
    category = category_for_event(event_key)

    stored_rules = getattr(settings, "notification_rules", None) if settings else None
    rules = merge_rules(stored_rules)
    cat_rules = rules.get(category, {})

    channels = {ch: bool(cat_rules.get(ch, False)) for ch in CHANNELS}

    if settings:
        if not settings.email_notifications:
            channels["email"] = False
        if not settings.slack_notifications:
            channels["slack"] = False
        if not settings.webhook_notifications or not settings.notification_webhook_url:
            channels["webhook"] = False
    else:
        channels["email"] = False
        channels["slack"] = False
        channels["webhook"] = False

    if severity == "critical":
        channels["in_app"] = True

    quiet = getattr(settings, "quiet_hours", None) if settings else None
    if severity != "critical" and _in_quiet_hours(quiet):
        channels["email"] = False
        channels["slack"] = False
        channels["webhook"] = False

    digest = bool(getattr(settings, "digest_email_daily", False)) if settings else False
    if digest and severity == "info" and category in ("messaging", "marketplace", "workflows"):
        channels["email"] = False

    return channels


def serialize_notification(n: Notification) -> Dict[str, Any]:
    """Safe dict for API / WebSocket — never use SQLAlchemy MetaData."""
    return {
        "id": str(n.id),
        "user_id": str(n.user_id),
        "notification_type": n.notification_type,
        "title": n.title,
        "message": n.message,
        "is_read": n.is_read,
        "action_url": n.action_url,
        "workflow_id": str(n.workflow_id) if n.workflow_id else None,
        "extra_data": n.extra_data or {},
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


class NotificationService:
    """Single entry point for durable, preference-aware notifications."""

    @staticmethod
    async def notify(
        db: AsyncSession,
        user_id: uuid.UUID,
        event_key: str,
        title: str,
        body: str,
        *,
        action_url: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        actor_id: Optional[uuid.UUID] = None,
        workflow_id: Optional[uuid.UUID] = None,
        entity_id: Optional[str] = None,
        commit: bool = True,
        enqueue_delivery: bool = True,
    ) -> Optional[Notification]:
        """
        Create an in-app notification (if allowed) and enqueue channel delivery.
        Returns the Notification row when in-app was written, else None.
        """
        dkey = _dedupe_key(user_id, event_key, entity_id)
        if _should_dedupe(dkey):
            logger.debug("Skipping duplicate notification %s for %s", event_key, user_id)
            return None

        settings = await _get_settings(db, user_id)
        channels = resolve_channels(settings, event_key)
        category = category_for_event(event_key)
        severity = severity_for_event(event_key)

        payload = dict(data or {})
        payload.setdefault("event_key", event_key)
        payload.setdefault("category", category)
        payload.setdefault("severity", severity)
        if actor_id:
            payload["actor_id"] = str(actor_id)
        if entity_id:
            payload["entity_id"] = entity_id

        notification: Optional[Notification] = None
        if channels.get("in_app"):
            notification = Notification(
                user_id=user_id,
                notification_type=event_key,
                title=title,
                message=body,
                action_url=action_url,
                workflow_id=workflow_id,
                actor_id=actor_id,
                extra_data=payload,
            )
            db.add(notification)
            if commit:
                await db.commit()
                await db.refresh(notification)
            else:
                await db.flush()
                await db.refresh(notification)

            try:
                from src.services.ws_event_bus import publish_inbox_event_async

                await publish_inbox_event_async(
                    user_id,
                    "notification.created",
                    {"notification": serialize_notification(notification)},
                )
            except Exception as e:
                logger.debug("WS notification push failed: %s", e)

        if enqueue_delivery and any(channels.get(ch) for ch in ("email", "slack", "webhook")):
            try:
                from src.tasks.notification_delivery_tasks import deliver_notification_channels

                webhook_url = settings.notification_webhook_url if settings else None
                deliver_notification_channels.delay(
                    str(user_id),
                    event_key,
                    title,
                    body,
                    {
                        "email": bool(channels.get("email")),
                        "slack": bool(channels.get("slack")),
                        "webhook": bool(channels.get("webhook")),
                    },
                    action_url,
                    payload,
                    webhook_url,
                    str(notification.id) if notification else None,
                )
            except Exception as e:
                logger.warning("Failed to enqueue notification delivery: %s", e)

        return notification


# Module-level convenience
notification_service = NotificationService()
