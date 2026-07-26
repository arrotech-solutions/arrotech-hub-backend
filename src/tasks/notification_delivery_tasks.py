"""
Outbound notification delivery — email, Slack, webhook via Celery.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional

from src.celery_app import app
from .utils import run_async as _run_async

logger = logging.getLogger(__name__)


def _build_email_html(title: str, body: str, action_url: Optional[str], event_key: str) -> str:
    link = ""
    if action_url:
        href = action_url if action_url.startswith("http") else f"https://hub.arrotechsolutions.com{action_url}"
        link = f'<p><a href="{href}">Open in Hub</a></p>'
    return (
        f"<div style='font-family:sans-serif;max-width:560px'>"
        f"<h2>{title}</h2>"
        f"<p>{body}</p>"
        f"{link}"
        f"<hr/><p style='color:#888;font-size:12px'>Event: {event_key} · Arrotech Hub</p>"
        f"</div>"
    )


async def _deliver_email(user_id: str, title: str, body: str, action_url: Optional[str], event_key: str) -> bool:
    from src.database import get_session_maker
    from src.models import User
    from src.services.email_service import email_service
    from sqlalchemy import select
    import uuid

    session_maker = get_session_maker()
    async with session_maker() as db:
        result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
        user = result.scalar_one_or_none()
        if not user or not user.email:
            return False
        html = _build_email_html(title, body, action_url, event_key)
        return await email_service.send_email(
            to_email=user.email,
            subject=f"[Arrotech Hub] {title}",
            html_content=html,
            text_content=f"{title}\n\n{body}",
        )


async def _deliver_slack(user_id: str, title: str, body: str, action_url: Optional[str]) -> bool:
    """Post to the user's connected Slack default channel when available."""
    from src.database import get_session_maker
    from src.models import Connection
    from src.services.slack_service import SlackService
    from sqlalchemy import select
    import uuid

    session_maker = get_session_maker()
    async with session_maker() as db:
        result = await db.execute(
            select(Connection).where(
                Connection.user_id == uuid.UUID(user_id),
                Connection.platform == "slack",
            ).limit(1)
        )
        conn = result.scalar_one_or_none()
        if not conn or not conn.config:
            logger.debug("No active Slack connection for user %s", user_id)
            return False

        config = conn.config if isinstance(conn.config, dict) else {}
        token = config.get("bot_token") or config.get("access_token")
        channel = config.get("default_channel") or config.get("notification_channel")
        if not token or not channel:
            logger.debug("Slack connection missing token/channel for user %s", user_id)
            return False

        service = SlackService()
        text = f"*{title}*\n{body}"
        if action_url:
            href = action_url if action_url.startswith("http") else f"https://hub.arrotechsolutions.com{action_url}"
            text += f"\n<{href}|Open in Hub>"
        try:
            from slack_sdk.web import WebClient

            client = WebClient(token=token)
            resp = client.chat_postMessage(channel=channel, text=text, unfurl_links=False)
            return bool(resp.get("ok"))
        except Exception as e:
            logger.warning("Slack notification failed: %s", e)
            return False


async def _deliver_webhook(
    webhook_url: str,
    user_id: str,
    event_key: str,
    title: str,
    body: str,
    action_url: Optional[str],
    data: Optional[Dict[str, Any]],
    notification_id: Optional[str],
) -> bool:
    import aiohttp
    from src.config import settings

    payload = {
        "event": event_key,
        "user_id": user_id,
        "notification_id": notification_id,
        "title": title,
        "body": body,
        "action_url": action_url,
        "data": data or {},
    }
    body_bytes = json.dumps(payload, default=str).encode("utf-8")
    secret = getattr(settings, "NOTIFICATION_WEBHOOK_SECRET", None) or getattr(
        settings, "SECRET_KEY", "hub-notification"
    )
    signature = hmac.new(
        str(secret).encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": f"sha256={signature}",
        "User-Agent": "ArrotechHub-Notifications/1.0",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                data=body_bytes,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status >= 400:
                    logger.warning("Webhook delivery HTTP %s for %s", resp.status, webhook_url)
                    return False
                return True
    except Exception as e:
        logger.warning("Webhook delivery failed: %s", e)
        return False


@app.task(
    name="src.tasks.notification_delivery_tasks.deliver_notification_channels",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    acks_late=True,
)
def deliver_notification_channels(
    self,
    user_id: str,
    event_key: str,
    title: str,
    body: str,
    channels: Dict[str, bool],
    action_url: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    webhook_url: Optional[str] = None,
    notification_id: Optional[str] = None,
):
    """Deliver notification to enabled external channels."""
    results = {}

    if channels.get("email"):
        results["email"] = _run_async(_deliver_email(user_id, title, body, action_url, event_key))

    if channels.get("slack"):
        results["slack"] = _run_async(_deliver_slack(user_id, title, body, action_url))

    if channels.get("webhook") and webhook_url:
        results["webhook"] = _run_async(
            _deliver_webhook(
                webhook_url, user_id, event_key, title, body, action_url, data, notification_id
            )
        )

    logger.info(
        "[NotificationDelivery] user=%s event=%s results=%s",
        user_id,
        event_key,
        results,
    )
    return {"status": "ok", "results": results}
