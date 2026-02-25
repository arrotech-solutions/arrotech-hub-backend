import logging
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError, jwt

from ..database import get_db
from ..models import User
from .auth_router import SECRET_KEY, ALGORITHM
from ..services.websocket_manager import ConnectionManager

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
    await ConnectionManager.connect(websocket, user.id)

    try:
        while True:
            # We don't strictly expect the client to send data, 
            # but we need to receive to keep the connection alive
            # and detect client disconnects.
            data = await websocket.receive_text()
            
            # Simple ping/pong to keep connection alive if load balancers drop idle conns
            if data == "ping":
                await websocket.send_text("pong")
                
    except WebSocketDisconnect:
        await ConnectionManager.disconnect(websocket, user.id)
    except Exception as e:
        logger.error(f"WebSocket error for user {user.id}: {e}")
        await ConnectionManager.disconnect(websocket, user.id)
