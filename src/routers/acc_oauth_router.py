"""
ACC OAuth callback router for handling Autodesk authentication.
"""

import json
import logging
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Connection, ConnectionStatus

router = APIRouter()
logger = logging.getLogger(__name__)

# Store temporary OAuth data
oauth_sessions = {}

@router.get("/callback/oauth")
async def handle_oauth_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
    db: AsyncSession = Depends(get_db)
):
    """Handle OAuth callback from Autodesk."""
    try:
        logger.info(f"[DEBUG] ===== OAuth Callback Received =====")
        logger.info(f"[DEBUG] Code: {code[:20] + '...' if code else 'None'}")
        logger.info(f"[DEBUG] State: {state}")
        logger.info(f"[DEBUG] Error: {error}")
        
        if error:
            logger.error(f"[DEBUG] OAuth error: {error}")
            return HTMLResponse(f"""
                <html><body>
                    <h2>Authentication Failed</h2>
                    <p>Error: {error}</p>
                    <p>Please try again.</p>
                </body></html>
            """, status_code=400)
        
        if not code:
            logger.error("[DEBUG] No authorization code received")
            return HTMLResponse("""
                <html><body>
                    <h2>Authentication Failed</h2>
                    <p>No authorization code received.</p>
                    <p>Please try again.</p>
                </body></html>
            """, status_code=400)
        
        # Find the ACC connection for this user (could be PENDING or ACTIVE)
        # Look for the most recent ACC connection that needs OAuth completion
        result = await db.execute(
            select(Connection).where(
                Connection.platform == "acc"
            ).order_by(Connection.created_at.desc()).limit(1)
        )
        connection = result.scalar_one_or_none()
        
        # Also check if this connection already has a token
        if connection and connection.config.get('access_token'):
            logger.info(f"[DEBUG] Connection {connection.id} already has token, skipping")
            return HTMLResponse("""
                <html><body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h2 style="color: #4CAF50;">✅ Already Authenticated!</h2>
                    <p>This connection is already authenticated.</p>
                    <p>You can close this window.</p>
                </body></html>
            """)
        
        if not connection:
            logger.warning("[DEBUG] No ACC connection found")
            return HTMLResponse("""
                <html><body>
                    <h2>No Connection Found</h2>
                    <p>No ACC connection found. Please create a new ACC connection first.</p>
                </body></html>
            """, status_code=404)
        
        logger.info(f"[DEBUG] Found pending connection: ID={connection.id}")
        
        # Exchange code for token
        env_vars = connection.config.get('env', {})
        client_id = env_vars.get('APS_CLIENT_ID')
        client_secret = env_vars.get('APS_CLIENT_SECRET')
        redirect_uri = env_vars.get('APS_REDIRECT_URI', 'http://localhost:8000/api/aps/callback/oauth')
        
        token_result = await exchange_code_for_token(code, client_id, client_secret, redirect_uri)
        
        if token_result.get('success'):
            # Store token in connection config
            token_data = token_result['token_data']
            access_token = token_data.get('access_token')
            refresh_token = token_data.get('refresh_token', '')
            expires_in = token_data.get('expires_in', 3600)
            token_type = token_data.get('token_type', 'Bearer')
            
            connection.config['access_token'] = access_token
            connection.config['refresh_token'] = refresh_token
            connection.config['expires_in'] = expires_in
            connection.config['token_type'] = token_type

            # Log token details for verification (partial for security)
            logger.info(f"[DEBUG] ===== OAuth Token Received Successfully =====")
            logger.info(f"[DEBUG] Connection ID: {connection.id}")
            logger.info(f"[DEBUG] Token Type: {token_type}")
            logger.info(f"[DEBUG] Expires In: {expires_in} seconds")
            if access_token:
                logger.info(f"[DEBUG] Access Token (partial): {access_token[:20]}...{access_token[-10:] if len(access_token) > 30 else access_token}")
                logger.info(f"[DEBUG] Access Token Length: {len(access_token)} characters")
            if refresh_token:
                logger.info(f"[DEBUG] Refresh Token (partial): {refresh_token[:15]}...{refresh_token[-8:] if len(refresh_token) > 23 else refresh_token}")
            logger.info(f"[DEBUG] Full Token Data: {token_data}")
            logger.info(f"[DEBUG] ===== Token Storage Complete =====")

            # Update connection status to active
            await db.execute(
                update(Connection)
                .where(Connection.id == connection.id)
                .values(
                    status=ConnectionStatus.ACTIVE,
                    config=connection.config,
                    error_message=None
                )
            )
            await db.commit()

            logger.info(f"[DEBUG] Successfully activated ACC connection: {connection.id}")
            
            return HTMLResponse("""
                <html><body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h2 style="color: #4CAF50;">✅ Authentication Successful!</h2>
                    <p>Your Autodesk Construction Cloud connection has been established.</p>
                    <p>You can now close this window and use ACC tools in Mini-Hub.</p>
                    <script>
                        setTimeout(function() {
                            window.close();
                        }, 3000);
                    </script>
                </body></html>
            """)
            
        else:
            # Update connection with error
            error_msg = token_result.get('error', 'Token exchange failed')
            await db.execute(
                update(Connection)
                .where(Connection.id == connection.id)
                .values(
                    error_message=error_msg
                )
            )
            await db.commit()
            
            logger.error(f"[DEBUG] Token exchange failed: {error_msg}")
            
            return HTMLResponse(f"""
                <html><body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h2 style="color: #f44336;">❌ Authentication Failed</h2>
                    <p>Error: {error_msg}</p>
                    <p>Please try creating the connection again.</p>
                </body></html>
            """, status_code=400)
            
    except Exception as e:
        logger.error(f"[DEBUG] OAuth callback error: {e}")
        return HTMLResponse(f"""
            <html><body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h2 style="color: #f44336;">❌ Unexpected Error</h2>
                <p>Error: {str(e)}</p>
                <p>Please try again.</p>
            </body></html>
        """, status_code=500)


async def exchange_code_for_token(code: str, client_id: str, client_secret: str, redirect_uri: str) -> Dict[str, Any]:
    """Exchange authorization code for access token."""
    try:
        logger.info("[DEBUG] Exchanging authorization code for token...")
        
        token_url = "https://developer.api.autodesk.com/authentication/v2/token"
        
        token_data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
            'client_id': client_id,
            'client_secret': client_secret
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data=token_data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            logger.info(f"[DEBUG] Token exchange response status: {response.status_code}")
            
            if response.status_code == 200:
                token_response = response.json()
                logger.info("[DEBUG] ===== Token Exchange Successful =====")
                logger.info(f"[DEBUG] Token type: {token_response.get('token_type')}")
                logger.info(f"[DEBUG] Expires in: {token_response.get('expires_in')} seconds")
                logger.info(f"[DEBUG] Access token received: {len(token_response.get('access_token', ''))} characters")
                logger.info(f"[DEBUG] Refresh token received: {len(token_response.get('refresh_token', ''))} characters")
                logger.info(f"[DEBUG] Raw token response: {token_response}")
                logger.info("[DEBUG] ===== Token Exchange Complete =====")
                
                return {
                    'success': True,
                    'token_data': token_response
                }
            else:
                error_text = response.text
                logger.error(f"[DEBUG] Token exchange failed: {response.status_code} - {error_text}")
                return {
                    'success': False,
                    'error': f"HTTP {response.status_code}: {error_text}"
                }
                
    except Exception as e:
        logger.error(f"[DEBUG] Token exchange error: {e}")
        return {
            'success': False,
            'error': f"Token exchange failed: {str(e)}"
        }
