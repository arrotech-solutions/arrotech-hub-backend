from fastapi import APIRouter, Request, Response, BackgroundTasks, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging
import json

from ..database import get_db
from ..models import User, Connection, ConnectionStatus
from .auth_router import get_current_user

from ..config import settings
from ..services.telegram_workflow_trigger import TelegramWorkflowTrigger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telegram", tags=["telegram"])

@router.post("/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receive webhook events from Telegram.
    Called by Telegram Bot API when new updates arrive.
    """
    try:
        body = await request.body()
        data = json.loads(body)
        
        # Check if this is a message update
        if "message" in data:
            message_obj = data["message"]
            
            # Extract relevant fields
            message_text = message_obj.get("text", "")
            chat = message_obj.get("chat", {})
            sender = message_obj.get("from", {})
            
            chat_id = str(chat.get("id"))
            sender_id = str(sender.get("id"))
            
            # If it's a valid text message
            if message_text and chat_id:
                logger.info(f"[TELEGRAM_WEBHOOK] Received message from user {sender_id} in chat {chat_id}: {message_text[:50]}")
                
                # Process the trigger asynchronously via Celery
                from ..tasks.webhook_tasks import process_telegram_message_task
                process_telegram_message_task.delay(data)

        # Handle callback_query from inline keyboard button presses (e.g. order action buttons)
        elif "callback_query" in data:
            callback = data["callback_query"]
            callback_id = callback.get("id")
            callback_data = callback.get("data", "")
            cb_sender = callback.get("from", {})
            cb_message = callback.get("message", {})
            cb_chat = cb_message.get("chat", {})

            chat_id = str(cb_chat.get("id"))
            sender_id = str(cb_sender.get("id"))

            # Translate callback_data to a natural language message
            translated_message = ""
            if callback_data.startswith("cancel_order:"):
                order_id = callback_data.split(":", 1)[1]
                translated_message = f"I want to cancel order {order_id}. Please proceed with the cancellation."
            elif callback_data.startswith("order_details:"):
                order_id = callback_data.split(":", 1)[1]
                translated_message = f"Show me the full details of order {order_id}."
            elif callback_data.startswith("confirm_cancel:"):
                order_id = callback_data.split(":", 1)[1]
                translated_message = f"Yes, please confirm the cancellation of order {order_id}."
            elif callback_data.startswith("keep_order:"):
                order_id = callback_data.split(":", 1)[1]
                translated_message = f"No, I changed my mind. Please keep order {order_id} active."
            else:
                translated_message = callback_data

            if translated_message and chat_id:
                logger.info(f"[TELEGRAM_WEBHOOK] Callback query from {sender_id} in chat {chat_id}: {callback_data}")

                # Build a synthetic message payload that the Celery task expects
                synthetic_data = {
                    "message": {
                        "text": translated_message,
                        "chat": cb_chat,
                        "from": cb_sender,
                        "message_id": cb_message.get("message_id"),
                    }
                }
                from ..tasks.webhook_tasks import process_telegram_message_task
                process_telegram_message_task.delay(synthetic_data)

            # Answer the callback query to dismiss the loading indicator
            if callback_id:
                background_tasks.add_task(_answer_callback_query, callback_id)
        
        # Telegram requires a 200 OK response quickly
        return Response(content="OK", status_code=200, media_type="text/plain")
        
    except Exception as e:
        logger.error(f"Error handling Telegram webhook: {str(e)}", exc_info=True)
        # Even on internal errors, we must return 200 so Telegram doesn't retry infinitely and block queue
        return Response(content="OK", status_code=200, media_type="text/plain")


async def _answer_callback_query(callback_query_id: str):
    """Answer a Telegram callback query to dismiss the loading indicator on the client."""
    try:
        import httpx
        bot_token = settings.TELEGRAM_BOT_TOKEN
        if not bot_token:
            return
        url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
        async with httpx.AsyncClient() as client:
            await client.post(url, json={"callback_query_id": callback_query_id}, timeout=5.0)
    except Exception as e:
        logger.warning(f"[TELEGRAM_WEBHOOK] Failed to answer callback query: {e}")


@router.get("/auth-url")
async def get_auth_url(user: User = Depends(get_current_user)):
    """Return the auth URL which renders the Telegram widget."""
    auth_url = f"{settings.API_BASE_URL.rstrip('/')}/api/telegram/login?user_id={user.id}"
    return {"auth_url": auth_url, "state": str(user.id)}

@router.get("/login", response_class=HTMLResponse)
async def telegram_login_page(request: Request, user_id: str):
    """Render the Telegram Login Widget."""
    bot_name = settings.TELEGRAM_BOT_NAME or "ArrotechHubBot"
    callback_url = f"{settings.API_BASE_URL.rstrip('/')}/api/telegram/callback"
    html_content = f"""
    <html>
      <head><title>Connect Telegram</title></head>
      <body style="display: flex; justify-content: center; align-items: center; height: 100vh; background-color: #f3f4f6; font-family: sans-serif;">
        <div style="text-align: center; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
            <h2 style="margin-bottom: 20px;">Connect your Telegram Account</h2>
            <script async src="https://telegram.org/js/telegram-widget.js?22" data-telegram-login="{bot_name}" data-size="large" data-auth-url="{callback_url}?user_id={user_id}" data-request-access="write"></script>
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
    hash: str = None,
    db: AsyncSession = Depends(get_db)
):
    """Handle Telegram Login callback."""
    try:
        import uuid
        uid = uuid.UUID(user_id)
        
        result = await db.execute(
            select(Connection).filter(
                Connection.user_id == uid,
                Connection.platform == "telegram"
            )
        )
        connection = result.scalar_one_or_none()
        
        config_data = {
            "telegram_user_id": id,
            "first_name": first_name,
            "username": username,
            "bot_token": settings.TELEGRAM_BOT_TOKEN
        }

        if connection:
            connection.status = ConnectionStatus.ACTIVE
            connection.config = {**connection.config, **config_data}
        else:
            connection = Connection(
                user_id=uid,
                platform="telegram",
                name="Telegram Account",
                status=ConnectionStatus.ACTIVE,
                config=config_data
            )
            db.add(connection)
        
        await db.commit()
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/connections?success=telegram_connected")
    except Exception as e:
        logger.error(f"Error in telegram callback: {e}")
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/connections?error=telegram_failed")

