import logging
import json
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError, jwt

from ..database import get_db
from ..models import User
from .auth_router import SECRET_KEY, ALGORITHM
from ..services.websocket_manager import connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ws",
    tags=["websocket"]
)

@router.websocket("/realtime")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str,
    db: AsyncSession = Depends(get_db)
):
    """
    WebSocket endpoint for real-time frontend updates.
    The client must connect with ?token=<JWT> to authenticate.
    """
    user = None
    # We can't use generic HTTPBearer for WebSockets natively because browsers don't send auth headers for WS.
    # We passed the token as a query parameter in the frontend: ?token=...
    try:
        if not token:
            await websocket.close(code=1008, reason="Missing token")
            return
            
        # Decode the token directly
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if not email:
            await websocket.close(code=1008, reason="Invalid token")
            return
            
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        
    except Exception as e:
        logger.warning(f"WebSocket auth failed: {e}")
        await websocket.close(code=1008)
        return

    if not user:
        await websocket.close(code=1008)
        return

    # Authenticated successfully, add to ConnectionManager
    await connection_manager.connect(websocket, user.id)

    try:
        while True:
            data = await websocket.receive_text()

            if data == "ping":
                await websocket.send_text("pong")
                continue

            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue

            if payload.get("type") == "whatsapp_presence":
                contact_id = payload.get("contact_id")
                presence = await connection_manager.set_contact_presence(
                    user.id,
                    user.name or user.email,
                    str(contact_id) if contact_id else None,
                )
                await connection_manager.push_to_user(
                    user.id,
                    "whatsapp_inbox_presence",
                    presence,
                )
                if contact_id:
                    from ..services.whatsapp_inbox_events import emit_to_org_members

                    await emit_to_org_members(
                        user.id,
                        "whatsapp_inbox_presence",
                        presence,
                        exclude_user_id=user.id,
                        db=db,
                    )

    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket, user.id)
        await connection_manager.set_contact_presence(user.id, user.name or user.email, None)
    except Exception as e:
        logger.error(f"WebSocket error for user {user.id}: {e}")
        await connection_manager.disconnect(websocket, user.id)
