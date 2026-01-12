"""
MCP Router for handling Model Context Protocol operations.
"""

import asyncio
import json
import os
from typing import Any, Dict, List

from fastapi import (APIRouter, Depends, HTTPException, Request, Response,
                     status)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User
from ..routers.auth_router import get_current_user
from ..services.dynamic_tool_registry import dynamic_tool_registry
from ..services.tool_executor import ToolExecutor

router = APIRouter()


class ToolCallRequest(BaseModel):
    name: str
    arguments: Dict[str, Any]


@router.get("/tools")
async def list_tools_get(
    include_all: bool = False,
    all: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get available MCP tools for the current user."""
    try:
        # Support both 'all' and 'include_all'
        discovery_mode = include_all or all
        
        print(f"[DEBUG] list_tools_get called with discovery_mode={discovery_mode} for user {current_user.id}")
        tools = await dynamic_tool_registry.get_user_tools(current_user.id, db, include_all=discovery_mode)
        print(f"[DEBUG] Found {len(tools)} tools for user {current_user.id}")

        return {
            "success": True,
            "data": {
                "tools": tools,
                "total": len(tools),
                "user_id": current_user.id
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get tools: {str(e)}"
        )


@router.post("/call")
async def call_tool(
    request: ToolCallRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Execute a tool call."""
    try:
        # Get the tool definition
        tool = dynamic_tool_registry.get_tool(request.name)
        if not tool:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown tool: {request.name}"
            )

        # Execute tool using the tool executor
        from ..services.tool_executor import tool_executor

        result = await tool_executor.execute_tool(
            tool_name=request.name,
            arguments=request.arguments,
            user=current_user,
            db=db
        )

        return {
            "success": True,
            "tool": request.name,
            "result": result
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Tool execution failed: {str(e)}"
        }


@router.post("/call/stream")
async def call_tool_stream(
    request: ToolCallRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Stream tool execution using Server-Sent Events."""
    
    async def generate_stream():
        try:
            # Send start event
            yield f"data: {json.dumps({'type': 'start', 'message': f'Starting {request.name} execution...'})}\n\n"
            
            # Initialize tool executor
            tool_executor = ToolExecutor()
            await tool_executor._initialize_services()
            
            # Send initialization event
            yield f"data: {json.dumps({'type': 'status', 'message': 'Tool executor initialized'})}\n\n"
            
            # Execute tool with streaming updates
            async for chunk_data in execute_tool_with_streaming(
                tool_executor, request.name, request.arguments, current_user, db
            ):
                yield chunk_data
            
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
        }
    )

async def execute_tool_with_streaming(
    tool_executor: ToolExecutor,
    tool_name: str,
    arguments: Dict[str, Any],
    user: User,
    db: AsyncSession
):
    """Execute tool with streaming updates."""
    
    try:
        # Send tool identification event
        yield f"data: {json.dumps({'type': 'status', 'message': f'Executing {tool_name}...'})}\n\n"
        
        # Execute the tool
        result = await tool_executor.execute_tool(tool_name, arguments, user, db)
        
        # Send progress updates based on tool type
        if tool_name.startswith('slack_'):
            yield f"data: {json.dumps({'type': 'status', 'message': 'Processing Slack operation...'})}\n\n"
        elif tool_name.startswith('hubspot_'):
            yield f"data: {json.dumps({'type': 'status', 'message': 'Processing HubSpot operation...'})}\n\n"
        elif tool_name.startswith('ga4_'):
            yield f"data: {json.dumps({'type': 'status', 'message': 'Processing Google Analytics operation...'})}\n\n"
        elif tool_name.startswith('whatsapp_'):
            yield f"data: {json.dumps({'type': 'status', 'message': 'Processing WhatsApp operation...'})}\n\n"
        elif tool_name == 'file_management':
            yield f"data: {json.dumps({'type': 'status', 'message': 'Processing file operation...'})}\n\n"
        elif tool_name == 'web_tools':
            yield f"data: {json.dumps({'type': 'status', 'message': 'Processing web tools operation...'})}\n\n"
        elif tool_name == 'content_creation':
            yield f"data: {json.dumps({'type': 'status', 'message': 'Processing content creation...'})}\n\n"
        
        # Send success event
        yield f"data: {json.dumps({'type': 'status', 'message': 'Tool execution completed successfully'})}\n\n"
        
        # Send completion with result
        yield f"data: {json.dumps({'type': 'complete', 'result': result})}\n\n"
        
    except Exception as e:
        error_msg = f"Tool execution failed: {str(e)}"
        yield f"data: {json.dumps({'type': 'error', 'error': error_msg})}\n\n"


@router.get("/test/whatsapp")
async def test_whatsapp_token(
    current_user: User = Depends(get_current_user)
):
    """Test WhatsApp token validity."""
    import aiohttp

    from ..config import settings

    try:
        url = f"{settings.WHATSAPP_BASE_URL}/{settings.WHATSAPP_PHONE_NUMBER_ID}"
        headers = {
            "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                result = await response.json()

                return {
                    "success": True,
                    "status_code": response.status,
                    "data": {
                        "url": url,
                        "token_preview": settings.WHATSAPP_TOKEN[:20] + "..." if settings.WHATSAPP_TOKEN else "Not Set",
                        "phone_number_id": settings.WHATSAPP_PHONE_NUMBER_ID,
                        "business_account_id": settings.WHATSAPP_BUSINESS_ACCOUNT_ID,
                        "base_url": settings.WHATSAPP_BASE_URL,
                        "response": result
                    }
                }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/debug/settings")
async def debug_settings(
    current_user: User = Depends(get_current_user)
):
    """Debug all WhatsApp settings."""
    from ..config import settings

    return {
        "success": True,
        "data": {
            "whatsapp_base_url": settings.WHATSAPP_BASE_URL,
            "whatsapp_phone_number_id": settings.WHATSAPP_PHONE_NUMBER_ID,
            "whatsapp_business_account_id": settings.WHATSAPP_BUSINESS_ACCOUNT_ID,
            "whatsapp_token_set": bool(settings.WHATSAPP_TOKEN),
            "whatsapp_token_preview": settings.WHATSAPP_TOKEN[:20] + "..." if settings.WHATSAPP_TOKEN else "Not Set",
            "environment": os.getenv("ENVIRONMENT", "development"),
            "docker_env_vars": {
                "WHATSAPP_BASE_URL": os.getenv("WHATSAPP_BASE_URL"),
                "WHATSAPP_PHONE_NUMBER_ID": os.getenv("WHATSAPP_PHONE_NUMBER_ID"),
                "WHATSAPP_BUSINESS_ACCOUNT_ID": os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID"),
                "WHATSAPP_TOKEN": os.getenv("WHATSAPP_TOKEN")[:20] + "..." if os.getenv("WHATSAPP_TOKEN") else "Not Set"
            }
        }
    }
