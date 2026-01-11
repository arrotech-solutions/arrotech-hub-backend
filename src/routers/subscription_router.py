"""
Subscription and Usage router for Arrotech Hub.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..database import get_db
from ..models import User, Workflow, WorkflowStatus, Connection
from .auth_router import get_current_user
from ..services.execution_orchestrator import ExecutionOrchestrator
from ..services.workflow_builder_service import WorkflowBuilderService
from ..services.feature_flags import FeatureGate

router = APIRouter(prefix="/subscription", tags=["subscription"])

@router.get("/usage")
async def get_usage_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current usage statistics for the user.
    """
    try:
        # Get active workflow count
        active_workflows = await WorkflowBuilderService.get_active_workflow_count(user.id, db)
        
        # Get daily message count
        daily_messages = await ExecutionOrchestrator.get_daily_message_count(db, user.id)
        
        # Get connection count
        conn_stmt = select(func.count(Connection.id)).where(Connection.user_id == user.id)
        conn_result = await db.execute(conn_stmt)
        connection_count = conn_result.scalar() or 0
        
        # Get limits
        limits = FeatureGate.get_limits(user.subscription_tier)
        
        return {
            "success": True,
            "data": {
                "tier": user.subscription_tier,
                "usage": {
                    "active_workflows": active_workflows,
                    "daily_messages": daily_messages,
                    "connections": connection_count
                },
                "limits": limits
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch usage stats: {str(e)}"
        )
