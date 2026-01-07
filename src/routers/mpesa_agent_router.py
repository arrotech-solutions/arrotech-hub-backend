"""
M-Pesa Agent API Router
Provides endpoints for managing M-Pesa agent configuration and viewing payments
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, MpesaAgentConfig, MpesaPayment
from ..routers.auth_router import get_current_user
from ..services.mpesa_reconciliation_service import MpesaReconciliationService

router = APIRouter(prefix="/api/agents/mpesa", tags=["mpesa-agent"])
logger = logging.getLogger(__name__)


class MpesaAgentConfigUpdate(BaseModel):
    """Update model for M-Pesa agent configuration."""
    alert_channel_id: Optional[str] = None
    alert_enabled: Optional[bool] = None
    auto_match_enabled: Optional[bool] = None
    match_threshold: Optional[float] = None
    notification_preferences: Optional[Dict[str, Any]] = None


class MpesaAgentConfigResponse(BaseModel):
    """Response model for M-Pesa agent configuration."""
    alert_channel_id: Optional[str]
    alert_enabled: bool
    auto_match_enabled: bool
    match_threshold: float
    notification_preferences: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class MpesaPaymentResponse(BaseModel):
    """Response model for M-Pesa payment."""
    id: int
    transaction_id: str
    amount: float
    phone_number: str
    reference: Optional[str]
    description: Optional[str]
    transaction_time: datetime
    status: str
    matched_invoice_id: Optional[int]
    match_confidence: Optional[float]
    channel: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class MpesaPaymentSummaryResponse(BaseModel):
    """Response model for payment summary."""
    total_amount: float
    total_count: int
    matched_count: int
    unmatched_count: int
    pending_count: int
    period: Dict[str, datetime]


@router.get("/config", response_model=MpesaAgentConfigResponse)
async def get_mpesa_agent_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get M-Pesa agent configuration for current user."""
    try:
        service = MpesaReconciliationService()
        config = await service.get_config(current_user.id, db)
        
        if not config:
            # Return default config if none exists
            return MpesaAgentConfigResponse(
                alert_channel_id=None,
                alert_enabled=True,
                auto_match_enabled=True,
                match_threshold=0.8,
                notification_preferences=None
            )
        
        return MpesaAgentConfigResponse(
            alert_channel_id=config.alert_channel_id,
            alert_enabled=config.alert_enabled,
            auto_match_enabled=config.auto_match_enabled,
            match_threshold=config.match_threshold,
            notification_preferences=config.notification_preferences
        )
    except Exception as e:
        logger.error(f"Error getting M-Pesa agent config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get configuration")


@router.post("/config", response_model=MpesaAgentConfigResponse)
async def update_mpesa_agent_config(
    config_data: MpesaAgentConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update M-Pesa agent configuration."""
    try:
        service = MpesaReconciliationService()
        config_dict = config_data.dict(exclude_none=True)
        config = await service.create_or_update_config(
            current_user.id,
            config_dict,
            db
        )
        
        return MpesaAgentConfigResponse(
            alert_channel_id=config.alert_channel_id,
            alert_enabled=config.alert_enabled,
            auto_match_enabled=config.auto_match_enabled,
            match_threshold=config.match_threshold,
            notification_preferences=config.notification_preferences
        )
    except Exception as e:
        logger.error(f"Error updating M-Pesa agent config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update configuration")


@router.get("/summary", response_model=MpesaPaymentSummaryResponse)
async def get_payment_summary(
    days: int = Query(1, ge=1, le=365, description="Number of days to include in summary"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get payment summary for the specified period."""
    try:
        service = MpesaReconciliationService()
        summary = await service.get_payment_summary(current_user.id, db, days=days)
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        return MpesaPaymentSummaryResponse(
            total_amount=float(summary.get("total_amount", 0)),
            total_count=summary.get("total_count", 0),
            matched_count=summary.get("matched_count", 0),
            unmatched_count=summary.get("unmatched_count", 0),
            pending_count=summary.get("pending_count", 0),
            period={
                "start": start_date,
                "end": end_date
            }
        )
    except Exception as e:
        logger.error(f"Error getting payment summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get payment summary")


@router.get("/payments", response_model=Dict[str, Any])
async def get_payments(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, description="Filter by status: pending, matched, unmatched"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get list of payments with pagination."""
    try:
        # Build query
        stmt = select(MpesaPayment).where(
            MpesaPayment.user_id == current_user.id
        )
        
        if status:
            stmt = stmt.where(MpesaPayment.status == status)
        
        # Get total count
        count_stmt = select(func.count()).select_from(MpesaPayment).where(
            MpesaPayment.user_id == current_user.id
        )
        if status:
            count_stmt = count_stmt.where(MpesaPayment.status == status)
        
        total_result = await db.execute(count_stmt)
        total = total_result.scalar()
        
        # Get paginated results
        stmt = stmt.order_by(MpesaPayment.transaction_time.desc()).limit(limit).offset(offset)
        result = await db.execute(stmt)
        payments = result.scalars().all()
        
        return {
            "payments": [
                MpesaPaymentResponse(
                    id=p.id,
                    transaction_id=p.transaction_id,
                    amount=float(p.amount),
                    phone_number=p.phone_number,
                    reference=p.reference,
                    description=p.description,
                    transaction_time=p.transaction_time,
                    status=p.status,
                    matched_invoice_id=p.matched_invoice_id,
                    match_confidence=p.match_confidence,
                    channel=p.channel,
                    created_at=p.created_at,
                    updated_at=p.updated_at
                ).dict()
                for p in payments
            ],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        logger.error(f"Error getting payments: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get payments")


@router.get("/payments/unmatched", response_model=Dict[str, List[Dict[str, Any]]])
async def get_unmatched_payments(
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get list of unmatched payments."""
    try:
        service = MpesaReconciliationService()
        payments = await service.get_unmatched_payments(current_user.id, db, limit=limit)
        
        return {
            "payments": [
                MpesaPaymentResponse(
                    id=p.id,
                    transaction_id=p.transaction_id,
                    amount=float(p.amount),
                    phone_number=p.phone_number,
                    reference=p.reference,
                    description=p.description,
                    transaction_time=p.transaction_time,
                    status=p.status,
                    matched_invoice_id=p.matched_invoice_id,
                    match_confidence=p.match_confidence,
                    channel=p.channel,
                    created_at=p.created_at,
                    updated_at=p.updated_at
                ).dict()
                for p in payments
            ]
        }
    except Exception as e:
        logger.error(f"Error getting unmatched payments: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get unmatched payments")

