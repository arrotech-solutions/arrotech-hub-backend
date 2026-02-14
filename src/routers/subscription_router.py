"""
Subscription and Usage router for Arrotech Hub.
Implements monthly AI action and automation run tracking with plan enforcement.
"""
from datetime import datetime, timedelta, timezone
from calendar import monthrange
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from ..database import get_db
from ..models import (
    User, Workflow, WorkflowStatus, Connection, UsageRecord
)
from .auth_router import get_current_user
from ..services.execution_orchestrator import ExecutionOrchestrator
from ..services.workflow_builder_service import WorkflowBuilderService
from ..services.feature_flags import FeatureGate, PLAN_LIMITS

router = APIRouter(prefix="/subscription", tags=["subscription"])


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_current_period() -> tuple[datetime, datetime]:
    """Get the current billing period (month)."""
    now = datetime.now(timezone.utc)
    # Period starts on the 1st of the month
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Period ends on the last day of the month
    _, last_day = monthrange(now.year, now.month)
    period_end = now.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)
    return period_start, period_end


async def get_or_create_usage_record(
    db: AsyncSession, 
    user: User,
    period_start: Optional[datetime] = None,
    period_end: Optional[datetime] = None
) -> UsageRecord:
    """Get or create a usage record for the current period."""
    if period_start is None or period_end is None:
        period_start, period_end = get_current_period()
    
    # Try to find existing record
    stmt = select(UsageRecord).where(
        and_(
            UsageRecord.user_id == user.id,
            UsageRecord.period_start == period_start
        )
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    
    if record:
        # Check if limits need to be updated (e.g. user upgraded)
        limits = FeatureGate.get_limits(user.subscription_tier)
        current_ai_limit = limits.get("ai_actions_monthly", 100)
        current_auto_limit = limits.get("automation_runs_monthly", 500)
        
        if record.ai_actions_limit != current_ai_limit or record.automation_runs_limit != current_auto_limit:
            record.ai_actions_limit = current_ai_limit
            record.automation_runs_limit = current_auto_limit
            db.add(record)
            await db.commit()
            await db.refresh(record)
        
        return record
    
    # Create new record with plan limits
    limits = FeatureGate.get_limits(user.subscription_tier)
    record = UsageRecord(
        user_id=user.id,
        period_start=period_start,
        period_end=period_end,
        ai_actions_count=0,
        automation_runs_count=0,
        ai_actions_limit=limits.get("ai_actions_monthly", 100),
        automation_runs_limit=limits.get("automation_runs_monthly", 500),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


# ============================================================================
# USAGE STATS ENDPOINT
# ============================================================================

@router.get("/usage")
async def get_usage_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current usage statistics for the user including monthly AI/automation usage."""
    try:
        # Get active workflow count
        active_workflows = await WorkflowBuilderService.get_active_workflow_count(user.id, db)
        
        # Get daily message count (legacy)
        daily_messages = await ExecutionOrchestrator.get_daily_message_count(db, user.id)
        
        # Get connection count
        conn_stmt = select(func.count(Connection.id)).where(Connection.user_id == user.id)
        conn_result = await db.execute(conn_stmt)
        connection_count = conn_result.scalar() or 0
        
        # Get monthly usage record
        usage_record = await get_or_create_usage_record(db, user)
        
        # Get plan limits
        limits = FeatureGate.get_limits(user.subscription_tier)
        pricing = FeatureGate.get_pricing(user.subscription_tier)
        
        # Calculate percentages
        ai_percentage = FeatureGate.get_usage_percentage(
            usage_record.ai_actions_count, 
            usage_record.ai_actions_limit
        )
        automation_percentage = FeatureGate.get_usage_percentage(
            usage_record.automation_runs_count,
            usage_record.automation_runs_limit
        )
        
        return {
            "success": True,
            "data": {
                "tier": user.subscription_tier,
                "tier_name": pricing.get("name"),
                "tier_tagline": pricing.get("tagline"),
                "usage": {
                    "active_workflows": active_workflows,
                    "daily_messages": daily_messages,
                    "connections": connection_count,
                    # Monthly usage
                    "ai_actions": {
                        "used": usage_record.ai_actions_count,
                        "limit": usage_record.ai_actions_limit,
                        "percentage": round(ai_percentage, 1),
                        "warning": ai_percentage >= 80,
                        "at_limit": ai_percentage >= 100,
                    },
                    "automation_runs": {
                        "used": usage_record.automation_runs_count,
                        "limit": usage_record.automation_runs_limit,
                        "percentage": round(automation_percentage, 1),
                        "warning": automation_percentage >= 80,
                        "at_limit": automation_percentage >= 100,
                    },
                    "period": {
                        "start": usage_record.period_start.isoformat(),
                        "end": usage_record.period_end.isoformat(),
                    }
                },
                "limits": limits
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch usage stats: {str(e)}"
        )


# ============================================================================
# INCREMENT USAGE ENDPOINTS (Called internally by other services)
# ============================================================================

@router.post("/usage/ai-action")
async def increment_ai_action(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Increment AI action counter for the current period.
    Returns whether the user can proceed (not at limit).
    """
    try:
        usage_record = await get_or_create_usage_record(db, user)
        
        # Check if at limit
        if usage_record.ai_actions_count >= usage_record.ai_actions_limit:
            return {
                "success": False,
                "allowed": False,
                "message": "Monthly AI action limit reached. Upgrade your plan for more.",
                "upgrade_to": _get_upgrade_recommendation(user.subscription_tier),
                "data": {
                    "used": usage_record.ai_actions_count,
                    "limit": usage_record.ai_actions_limit,
                }
            }
        
        # Increment counter
        usage_record.ai_actions_count += 1
        
        # Check for 80% warning
        percentage = (usage_record.ai_actions_count / usage_record.ai_actions_limit) * 100
        warning = percentage >= 80 and not usage_record.ai_warning_sent
        
        if warning:
            usage_record.ai_warning_sent = True
        
        await db.commit()
        
        return {
            "success": True,
            "allowed": True,
            "warning": warning,
            "message": "80% of your AI actions used this month." if warning else None,
            "data": {
                "used": usage_record.ai_actions_count,
                "limit": usage_record.ai_actions_limit,
                "percentage": round(percentage, 1),
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to increment AI action: {str(e)}"
        )


@router.post("/usage/automation-run")
async def increment_automation_run(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Increment automation run counter for the current period.
    Returns whether the user can proceed (not at limit).
    """
    try:
        usage_record = await get_or_create_usage_record(db, user)
        
        # Check if at limit
        if usage_record.automation_runs_count >= usage_record.automation_runs_limit:
            return {
                "success": False,
                "allowed": False,
                "message": "Monthly automation run limit reached. Upgrade your plan for more.",
                "upgrade_to": _get_upgrade_recommendation(user.subscription_tier),
                "data": {
                    "used": usage_record.automation_runs_count,
                    "limit": usage_record.automation_runs_limit,
                }
            }
        
        # Increment counter
        usage_record.automation_runs_count += 1
        
        # Check for 80% warning
        percentage = (usage_record.automation_runs_count / usage_record.automation_runs_limit) * 100
        warning = percentage >= 80 and not usage_record.automation_warning_sent
        
        if warning:
            usage_record.automation_warning_sent = True
        
        await db.commit()
        
        return {
            "success": True,
            "allowed": True,
            "warning": warning,
            "message": "80% of your automation runs used this month." if warning else None,
            "data": {
                "used": usage_record.automation_runs_count,
                "limit": usage_record.automation_runs_limit,
                "percentage": round(percentage, 1),
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to increment automation run: {str(e)}"
        )


@router.get("/usage/check")
async def check_usage_limits(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Check if user is within their usage limits without incrementing.
    Returns status for both AI actions and automation runs.
    """
    try:
        usage_record = await get_or_create_usage_record(db, user)
        
        ai_percentage = (usage_record.ai_actions_count / usage_record.ai_actions_limit) * 100 if usage_record.ai_actions_limit > 0 else 0
        auto_percentage = (usage_record.automation_runs_count / usage_record.automation_runs_limit) * 100 if usage_record.automation_runs_limit > 0 else 0
        
        return {
            "success": True,
            "data": {
                "ai_actions": {
                    "can_proceed": usage_record.ai_actions_count < usage_record.ai_actions_limit,
                    "used": usage_record.ai_actions_count,
                    "limit": usage_record.ai_actions_limit,
                    "percentage": round(ai_percentage, 1),
                    "at_warning": ai_percentage >= 80,
                    "at_limit": ai_percentage >= 100,
                },
                "automation_runs": {
                    "can_proceed": usage_record.automation_runs_count < usage_record.automation_runs_limit,
                    "used": usage_record.automation_runs_count,
                    "limit": usage_record.automation_runs_limit,
                    "percentage": round(auto_percentage, 1),
                    "at_warning": auto_percentage >= 80,
                    "at_limit": auto_percentage >= 100,
                }
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check usage limits: {str(e)}"
        )


@router.get("/features/{feature_name}")
async def check_feature_access(
    feature_name: str,
    user: User = Depends(get_current_user)
):
    """
    Check if user has access to a specific feature.
    Returns access status and upgrade message if gated.
    """
    has_access = FeatureGate.has_feature(user, feature_name)
    
    return {
        "success": True,
        "data": {
            "feature": feature_name,
            "has_access": has_access,
            "tier": user.subscription_tier,
            "upgrade_message": FeatureGate.get_upgrade_message(user.subscription_tier, feature_name) if not has_access else None
        }
    }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_upgrade_recommendation(current_tier: str) -> dict:
    """Get upgrade recommendation based on current tier."""
    from ..models import SubscriptionTier
    
    upgrade_path = {
        SubscriptionTier.FREE: {"tier": "starter", "name": "Starter", "price": 1500},
        SubscriptionTier.STARTER: {"tier": "business", "name": "Business", "price": 5000},
        SubscriptionTier.BUSINESS: {"tier": "pro", "name": "Pro / Agency", "price": 10000},
        SubscriptionTier.PRO: {"tier": "enterprise", "name": "Enterprise", "price": None},
        SubscriptionTier.ENTERPRISE: None,
    }
    
    return upgrade_path.get(current_tier)
