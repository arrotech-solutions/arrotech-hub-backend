from typing import Optional
from fastapi import APIRouter, Request, Response, BackgroundTasks, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging
import json

from ..database import get_db
from ..models import User, Connection, ConnectionStatus
from .auth_router import get_current_user

from ..config import settings
from ..utils.oauth_frontend import (
    connections_redirect,
    with_frontend_origin,
)
from ..services.telegram_service import TelegramService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telegram", tags=["telegram"])


def _enqueue_telegram_update(data: dict, bot_id: Optional[str] = None):
    from ..tasks.webhook_tasks import process_telegram_message_task

    process_telegram_message_task.delay(data, bot_id=bot_id)


async def _handle_webhook_payload(
    data: dict,
    background_tasks: BackgroundTasks,
    bot_id: Optional[str] = None,
):
    if "message" in data:
        message_obj = data["message"]
        message_text = message_obj.get("text", "")
        has_location = bool(message_obj.get("location"))
        chat = message_obj.get("chat", {})
        sender = message_obj.get("from", {})
        chat_id = str(chat.get("id") or "")
        sender_id = str(sender.get("id") or "")

        if (message_text or has_location) and chat_id:
            logger.info(
                "[TELEGRAM_WEBHOOK] Message from %s in chat %s (bot_id=%s)",
                sender_id,
                chat_id,
                bot_id,
            )
            _enqueue_telegram_update(data, bot_id=bot_id)

    elif "callback_query" in data:
        callback = data["callback_query"]
        callback_id = callback.get("id")
        callback_data = callback.get("data", "")
        cb_sender = callback.get("from", {})
        cb_message = callback.get("message", {})
        cb_chat = cb_message.get("chat", {})

        chat_id = str(cb_chat.get("id") or "")
        sender_id = str(cb_sender.get("id") or "")

        translated_message = ""
        if callback_data.startswith("cancel_order:"):
            order_id = callback_data.split(":", 1)[1]
            translated_message = (
                f"I want to cancel order {order_id}. Please proceed with the cancellation."
            )
        elif callback_data.startswith("order_details:"):
            order_id = callback_data.split(":", 1)[1]
            translated_message = f"Show me the full details of order {order_id}."
        elif callback_data.startswith("confirm_cancel:"):
            order_id = callback_data.split(":", 1)[1]
            translated_message = (
                f"Yes, please confirm the cancellation of order {order_id}."
            )
        elif callback_data.startswith("keep_order:"):
            order_id = callback_data.split(":", 1)[1]
            translated_message = (
                f"No, I changed my mind. Please keep order {order_id} active."
            )
        else:
            translated_message = callback_data

        if translated_message and chat_id:
            logger.info(
                "[TELEGRAM_WEBHOOK] Callback from %s in chat %s: %s",
                sender_id,
                chat_id,
                callback_data,
            )
            synthetic_data = {
                "message": {
                    "text": translated_message,
                    "chat": cb_chat,
                    "from": cb_sender,
                    "message_id": cb_message.get("message_id"),
                }
            }
            _enqueue_telegram_update(synthetic_data, bot_id=bot_id)

        if callback_id:
            background_tasks.add_task(_answer_callback_query, callback_id, bot_id)


@router.post("/webhook")
@router.post("/webhook/{bot_id}")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    bot_id: Optional[str] = None,
):
    """
    Receive webhook events from Telegram.
    Prefer /webhook/{bot_id} for multi-tenant BotFather bots.
    """
    try:
        body = await request.body()
        data = json.loads(body)
        await _handle_webhook_payload(data, background_tasks, bot_id=bot_id)
        return Response(content="OK", status_code=200, media_type="text/plain")
    except Exception as e:
        logger.error(f"Error handling Telegram webhook: {str(e)}", exc_info=True)
        return Response(content="OK", status_code=200, media_type="text/plain")


async def _answer_callback_query(callback_query_id: str, bot_id: Optional[str] = None):
    """Answer a Telegram callback query to dismiss the loading indicator on the client."""
    try:
        import httpx
        from sqlalchemy import select, and_
        from ..database import get_session_maker
        from ..models import Connection

        bot_token = settings.TELEGRAM_BOT_TOKEN
        if bot_id:
            session_maker = get_session_maker()
            async with session_maker() as db:
                result = await db.execute(
                    select(Connection).where(
                        and_(
                            Connection.platform == "telegram",
                            Connection.status == "active",
                        )
                    )
                )
                for conn in result.scalars().all():
                    cfg = conn.config or {}
                    if str(cfg.get("bot_id") or "") == str(bot_id) and cfg.get("bot_token"):
                        bot_token = cfg["bot_token"]
                        break

        if not bot_token:
            return
        url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
        async with httpx.AsyncClient() as client:
            await client.post(
                url, json={"callback_query_id": callback_query_id}, timeout=5.0
            )
    except Exception as e:
        logger.warning(f"[TELEGRAM_WEBHOOK] Failed to answer callback query: {e}")


@router.get("/auth-url")
async def get_auth_url(
    frontend_origin: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    """Return the auth URL which renders the Telegram Login Widget (optional identity link)."""
    from urllib.parse import quote

    origin_q = quote(frontend_origin or "", safe="")
    auth_url = (
        f"{settings.API_BASE_URL.rstrip('/')}/api/telegram/login"
        f"?user_id={user.id}&frontend_origin={origin_q}"
    )
    return {"auth_url": auth_url, "state": str(user.id)}


@router.get("/login", response_class=HTMLResponse)
async def telegram_login_page(
    request: Request,
    user_id: str,
    frontend_origin: Optional[str] = None,
):
    """Render the Telegram Login Widget (links personal account / notify chat id)."""
    from urllib.parse import quote

    bot_name = settings.TELEGRAM_BOT_NAME or "ArrotechHubBot"
    origin_q = quote(frontend_origin or "", safe="")
    callback_url = (
        f"{settings.API_BASE_URL.rstrip('/')}/api/telegram/callback"
        f"?user_id={user_id}&frontend_origin={origin_q}"
    )
    html_content = f"""
    <html>
      <head><title>Connect Telegram</title></head>
      <body style="display: flex; justify-content: center; align-items: center; height: 100vh; background-color: #f3f4f6; font-family: sans-serif;">
        <div style="text-align: center; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
            <h2 style="margin-bottom: 20px;">Link your Telegram account</h2>
            <p style="color:#6b7280;margin-bottom:20px;max-width:320px;">
              Optional: link your personal Telegram so we can send you order alerts.
              For ordering bots, connect a BotFather token from Connections.
            </p>
            <script async src="https://telegram.org/js/telegram-widget.js?22" data-telegram-login="{bot_name}" data-size="large" data-auth-url="{callback_url}" data-request-access="write"></script>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@router.get("/callback")
async def telegram_callback(
    user_id: str,
    id: str = None,
    first_name: str = None,
    username: str = None,
    auth_date: str = None,
    hash: str = None,
    photo_url: str = None,
    last_name: str = None,
    frontend_origin: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Handle Telegram Login Widget callback — stores notify chat id on existing or new connection."""
    state = with_frontend_origin(user_id, frontend_origin)
    try:
        import uuid

        uid = uuid.UUID(user_id)
        bot_token = settings.TELEGRAM_BOT_TOKEN
        login_data = {
            "id": id,
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
            "photo_url": photo_url,
            "auth_date": auth_date,
            "hash": hash,
        }
        if bot_token and hash:
            if not TelegramService.verify_login_widget_hash(
                {k: v for k, v in login_data.items() if v is not None},
                bot_token,
            ):
                logger.warning("[TELEGRAM] Login widget hash verification failed")
                return connections_redirect(state, error="telegram_auth_invalid")

        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == uid,
                Connection.platform == "telegram",
            )
        )
        connection = result.scalar_one_or_none()

        config_data = {
            "telegram_user_id": id,
            "notify_chat_id": id,
            "first_name": first_name,
            "username": username,
        }
        if bot_token:
            config_data["bot_token"] = bot_token

        if connection:
            connection.status = ConnectionStatus.ACTIVE
            connection.config = {**(connection.config or {}), **config_data}
        else:
            connection = Connection(
                user_id=uid,
                platform="telegram",
                name="Telegram Account",
                status=ConnectionStatus.ACTIVE,
                config=config_data,
            )
            db.add(connection)

        await db.commit()
        return connections_redirect(state, success="telegram_connected")
    except Exception as e:
        logger.error(f"Error in telegram callback: {e}")
        return connections_redirect(state, error="telegram_failed")
