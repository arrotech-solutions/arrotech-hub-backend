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
                
                # Send typing indicator immediately in background
                from ..services.telegram_service import TelegramService
                tg_svc = TelegramService()
                background_tasks.add_task(
                    tg_svc.send_chat_action,
                    chat_id=chat_id,
                    action="typing"
                )
                
                # Process the trigger asynchronously
                background_tasks.add_task(
                    TelegramWorkflowTrigger.on_message_received,
                    sender_id=sender_id,
                    chat_id=chat_id,
                    message=message_text
                )
        
        # Telegram requires a 200 OK response quickly
        return Response(content="OK", status_code=200, media_type="text/plain")
        
    except Exception as e:
        logger.error(f"Error handling Telegram webhook: {str(e)}", exc_info=True)
        # Even on internal errors, we must return 200 so Telegram doesn't retry infinitely and block queue
        return Response(content="OK", status_code=200, media_type="text/plain")

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

