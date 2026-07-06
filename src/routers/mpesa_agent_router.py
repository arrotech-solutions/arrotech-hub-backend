"""
M-Pesa Agent API Router
Provides endpoints for managing M-Pesa agent configuration and viewing payments
"""
import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, MpesaAgentConfig, MpesaPayment
from ..routers.auth_router import get_current_user
from ..services.mpesa_reconciliation_service import MpesaReconciliationService
from ..services.daraja_service import daraja_service, DarajaService
from ..services.cache_service import cache_service
from ..config import settings
from ..utils.encryption import mask_value, decrypt_value

router = APIRouter(prefix="/api/agents/daraja", tags=["mpesa-agent"])
logger = logging.getLogger(__name__)


class MpesaAgentConfigUpdate(BaseModel):
    """Update model for M-Pesa agent configuration."""
    alert_channel_id: Optional[str] = None
    alert_enabled: Optional[bool] = None
    auto_match_enabled: Optional[bool] = None
    match_threshold: Optional[float] = None
    notification_preferences: Optional[Dict[str, Any]] = None
    daraja_consumer_key: Optional[str] = None
    daraja_consumer_secret: Optional[str] = None
    daraja_passkey: Optional[str] = None
    daraja_shortcode: Optional[str] = None
    daraja_environment: Optional[str] = None  # "sandbox" or "live"
    callback_url_override: Optional[str] = None


class MpesaAgentConfigResponse(BaseModel):
    """Response model for M-Pesa agent configuration."""
    alert_channel_id: Optional[str]
    alert_enabled: bool
    auto_match_enabled: bool
    match_threshold: float
    notification_preferences: Optional[Dict[str, Any]] = None
    daraja_consumer_key: Optional[str] = None
    daraja_shortcode: Optional[str] = None
    daraja_environment: Optional[str] = None
    webhook_secret: Optional[str] = None
    callback_url_override: Optional[str] = None

    class Config:
        from_attributes = True


class MpesaPaymentResponse(BaseModel):
    """Response model for M-Pesa payment."""
    id: uuid.UUID
    transaction_id: str
    amount: float
    phone_number: str
    reference: Optional[str]
    description: Optional[str]
    transaction_time: datetime
    status: str
    matched_invoice_id: Optional[uuid.UUID]
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
                notification_preferences=None,
                daraja_environment="sandbox",
                webhook_secret=None,
                callback_url_override=None
            )
        
        # Mask the consumer key for display (never return raw encrypted value)
        masked_key = mask_value(decrypt_value(config.daraja_consumer_key))
        
        return MpesaAgentConfigResponse(
            alert_channel_id=config.alert_channel_id,
            alert_enabled=config.alert_enabled,
            auto_match_enabled=config.auto_match_enabled,
            match_threshold=config.match_threshold,
            notification_preferences=config.notification_preferences,
            daraja_consumer_key=masked_key,
            daraja_shortcode=config.daraja_shortcode,
            daraja_environment=config.daraja_environment or "sandbox",
            webhook_secret=config.webhook_secret,
            callback_url_override=config.callback_url_override
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
        
        # Mask credentials in response
        masked_key = mask_value(decrypt_value(config.daraja_consumer_key))
        
        return MpesaAgentConfigResponse(
            alert_channel_id=config.alert_channel_id,
            alert_enabled=config.alert_enabled,
            auto_match_enabled=config.auto_match_enabled,
            match_threshold=config.match_threshold,
            notification_preferences=config.notification_preferences,
            daraja_consumer_key=masked_key,
            daraja_shortcode=config.daraja_shortcode,
            daraja_environment=config.daraja_environment or "sandbox",
            webhook_secret=config.webhook_secret,
            callback_url_override=config.callback_url_override
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
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        summary = await service.get_payment_summary(current_user.id, start_date, end_date, db)
        
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


@router.post("/register-urls")
async def register_mpesa_urls(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Automate Daraja C2B URL registration for the current user."""
    try:
        service = MpesaReconciliationService()
        config = await service.get_config(current_user.id, db)
        
        if not config or not config.webhook_secret:
            raise HTTPException(
                status_code=400, 
                detail="M-Pesa configuration not found or not yet saved (webhook secret missing)"
            )
            
        if not config.daraja_shortcode:
            raise HTTPException(
                status_code=400, 
                detail="Daraja ShortCode is missing in configuration"
            )

        # Determine the full webhook URL
        # Logic: If override exists, use it. Otherwise use the API base URL.
        base_url = config.callback_url_override or settings.API_BASE_URL
        # Ensure base_url doesn't end with / for consistency
        base_url = base_url.rstrip('/')
        
        webhook_url = f"{base_url}/api/agents/daraja/callback/{config.webhook_secret}"

        logger.info(f"Registering Daraja URLs for user {current_user.id}. Confirmation: {webhook_url}")

        # Decrypt tenant credentials for Daraja API call
        recon_service = MpesaReconciliationService()
        decrypted = recon_service.decrypt_config_credentials(config)
        
        # Use per-tenant environment (sandbox/live) instead of global setting
        tenant_env = config.daraja_environment or "sandbox"
        tenant_daraja = DarajaService(environment=tenant_env)
        
        # Call Daraja Service to register URLs using decrypted tenant credentials
        result = await tenant_daraja.register_c2b_urls(
            short_code=config.daraja_shortcode,
            confirmation_url=webhook_url,
            validation_url=webhook_url,
            consumer_key=decrypted["daraja_consumer_key"],
            consumer_secret=decrypted["daraja_consumer_secret"]
        )
        
        # Safaricom success is ResponseCode "0" or "00000000"
        success = result.get("ResponseCode") in ["0", "00000000"]
        
        return {
            "success": success,
            "data": result,
            "message": result.get("ResponseDescription", "Registration completed")
        }
    except Exception as e:
        logger.error(f"Error registering Daraja URLs: {e}", exc_info=True)
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


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


@router.api_route("/callback/{webhook_secret}", methods=["GET", "POST"])
async def tenant_mpesa_callback(
    webhook_secret: str,
    request: Request,
):
    """
    Handle tenant-specific Daraja callback notifications.
    
    CRITICAL: Always return ResultCode 0 to Safaricom immediately.
    All processing happens in a background task to avoid timeouts
    that cause Safaricom to reject transactions or replace BillRefNumber
    with 'ProbCheck'.
    """
    logger.info(f"Daraja callback endpoint hit: method={request.method}, secret={webhook_secret[:5]}...")

    # Support for initial validation pings (GET)
    if request.method == "GET":
        return {"ResultCode": 0, "ResultDesc": "Accepted"}

    try:
        # Read body immediately before anything else
        body = await request.body()
        logger.info(f"Daraja callback raw body ({len(body)} bytes) for secret={webhook_secret[:5]}...")

        if not body:
            logger.warning("Empty body received from Daraja callback")
            return {"ResultCode": 0, "ResultDesc": "Accepted"}

        # Fire-and-forget: process in background task with its own DB session
        asyncio.create_task(
            _handle_mpesa_callback_background(webhook_secret, body)
        )

    except Exception as e:
        logger.error(f"Error reading Daraja callback body: {e}", exc_info=True)

    # ALWAYS return success to Safaricom no matter what
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


async def _handle_mpesa_callback_background(webhook_secret: str, body: bytes):
    """
    Background task to process M-Pesa callback payload.
    Uses its own DB session (NOT the request-scoped one).
    """
    from ..database import get_session_maker

    session_maker = get_session_maker()
    async with session_maker() as db:
        try:
            # 1. Parse JSON
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON in Daraja callback: {body.decode(errors='ignore')}")
                return

            logger.info("Daraja callback payload parsed successfully.")

            # 2. Lookup tenant config by webhook secret
            stmt = select(MpesaAgentConfig).where(
                MpesaAgentConfig.webhook_secret == webhook_secret
            )
            result = await db.execute(stmt)
            config = result.scalar_one_or_none()

            if not config:
                logger.warning(f"Unauthorized Daraja webhook hit with secret: {webhook_secret}")
                return

            logger.info(f"Daraja callback matched to user_id={config.user_id}")

            service = MpesaReconciliationService()

            # 3a. STK push callbacks (ordering payments) — map via CheckoutRequestID
            if isinstance(payload, dict) and payload.get("Body", {}).get("stkCallback"):
                parsed = service._parse_stk_callback(payload)  # returns dict or None
                checkout_request_id = (parsed or {}).get("checkout_request_id")
                merchant_request_id = (parsed or {}).get("merchant_request_id")
                map_key_checkout = f"mpesa:stk:checkout:{checkout_request_id}" if checkout_request_id else ""
                map_key_merchant = f"mpesa:stk:merchant:{merchant_request_id}" if merchant_request_id else ""

                from ..services.order_tracking_service import order_tracking_service

                notify_ctx = order_tracking_service.resolve_stk_notify_context(
                    str(config.user_id),
                    checkout_request_id or "",
                    merchant_request_id or "",
                )
                if not notify_ctx:
                    notify_ctx = await order_tracking_service.resolve_stk_notify_context_from_db(
                        db,
                        str(config.user_id),
                        checkout_request_id or "",
                        merchant_request_id or "",
                    )
                if notify_ctx:
                    logger.info(
                        "STK callback resolved order %s (checkout=%s)",
                        notify_ctx.get("order_id"),
                        checkout_request_id,
                    )
                else:
                    logger.warning(
                        "STK callback: could not resolve order context "
                        "(checkout=%s merchant=%s user=%s result=%s)",
                        checkout_request_id,
                        merchant_request_id,
                        config.user_id,
                        (parsed or {}).get("result_code"),
                    )

                # Persist payment record (with order reference if we have it)
                reference_override = (notify_ctx or {}).get("order_id")
                description_override = f"Order payment {reference_override}" if reference_override else "Order payment"
                payment = await service.process_stk_callback(
                    config.user_id,
                    payload,
                    db,
                    reference_override=reference_override,
                    description_override=description_override,
                )

                # Notify + persist transaction into connected storage (best effort)
                result_code = str((parsed or {}).get("result_code") or "")
                is_paid = result_code in ("", "0")
                
                # Verify exact amount to prevent webhook forgery / underpayment fraud
                if is_paid and notify_ctx and parsed:
                    actual_paid = float(parsed.get("amount") or 0)
                    expected_amount = float(notify_ctx.get("amount") or 0)
                    if actual_paid > 0 and expected_amount > 0 and actual_paid < expected_amount:
                        logger.warning(f"Fraud check failed! Underpayment detected for order {notify_ctx.get('order_id')}: paid {actual_paid}, expected {expected_amount}")
                        is_paid = False
                        result_code = "fraud_underpayment"
                        parsed["result_desc"] = f"Underpayment: Paid {actual_paid} but expected {expected_amount}"

                if notify_ctx and is_paid:
                    if (notify_ctx or {}).get("payment_type") == "rent":
                        try:
                            from ..services.rent_stk_payment_service import finalize_rent_stk_payment

                            await finalize_rent_stk_payment(
                                db=db,
                                owner_user_id=str(config.user_id),
                                notify_ctx=notify_ctx,
                                is_paid=True,
                                mpesa_receipt=(parsed or {}).get("transaction_id") or "",
                                amount_paid=float((parsed or {}).get("amount") or notify_ctx.get("amount") or 0),
                                result_code=result_code,
                                result_desc=str((parsed or {}).get("result_desc") or ""),
                            )
                        except Exception as rent_err:
                            logger.warning(
                                "Failed to finalize rent STK callback: %s",
                                rent_err,
                                exc_info=True,
                            )
                    else:
                        order_id = (notify_ctx or {}).get("order_id")
                        whatsapp_sender = (
                            (notify_ctx or {}).get("whatsapp_sender")
                            or (notify_ctx or {}).get("sender_id")
                            or ""
                        )
                        mpesa_phone = (
                            (notify_ctx or {}).get("mpesa_phone")
                            or (notify_ctx or {}).get("customer_phone")
                            or ""
                        )
                        platform = (notify_ctx or {}).get("platform") or "whatsapp"
                        storage_config = (notify_ctx or {}).get("storage_config") or {}

                        try:
                            from ..services.order_stk_payment_service import finalize_order_stk_payment

                            await finalize_order_stk_payment(
                                db=db,
                                owner_user_id=str(config.user_id),
                                order_id=order_id,
                                whatsapp_sender=whatsapp_sender or "",
                                mpesa_phone=mpesa_phone,
                                platform=platform,
                                storage_config=storage_config,
                                is_paid=True,
                                mpesa_receipt=(parsed or {}).get("transaction_id") or "",
                                amount_paid=float((parsed or {}).get("amount") or notify_ctx.get("amount") or 0),
                                currency=str(notify_ctx.get("currency") or "KES"),
                                result_code=result_code,
                                result_desc=str((parsed or {}).get("result_desc") or ""),
                                checkout_request_id=checkout_request_id or "",
                                merchant_request_id=merchant_request_id or "",
                                payment_record=payment,
                            )
                        except Exception as notify_err:
                            logger.warning(
                                "Failed to notify customer for STK callback: %s",
                                notify_err,
                                exc_info=True,
                            )

                    if map_key_checkout:
                        cache_service.delete(map_key_checkout)
                    if map_key_merchant:
                        cache_service.delete(map_key_merchant)
                    if checkout_request_id:
                        cache_service.delete(
                            f"mpesa:stk:lookup:checkout:{checkout_request_id}"
                        )
                    if merchant_request_id:
                        cache_service.delete(
                            f"mpesa:stk:lookup:merchant:{merchant_request_id}"
                        )
                elif notify_ctx and not is_paid:
                    order_id = (notify_ctx or {}).get("order_id")
                    whatsapp_sender = (
                        (notify_ctx or {}).get("whatsapp_sender")
                        or (notify_ctx or {}).get("sender_id")
                        or ""
                    )
                    mpesa_phone = (
                        (notify_ctx or {}).get("mpesa_phone")
                        or (notify_ctx or {}).get("customer_phone")
                        or ""
                    )
                    platform = (notify_ctx or {}).get("platform") or "whatsapp"
                    storage_config = (notify_ctx or {}).get("storage_config") or {}

                    try:
                        from ..services.order_stk_payment_service import finalize_order_stk_payment

                        await finalize_order_stk_payment(
                            db=db,
                            owner_user_id=str(config.user_id),
                            order_id=order_id,
                            whatsapp_sender=whatsapp_sender or "",
                            mpesa_phone=mpesa_phone,
                            platform=platform,
                            storage_config=storage_config,
                            is_paid=False,
                            amount_paid=float((parsed or {}).get("amount") or notify_ctx.get("amount") or 0),
                            currency=str(notify_ctx.get("currency") or "KES"),
                            result_code=result_code,
                            result_desc=str((parsed or {}).get("result_desc") or ""),
                            checkout_request_id=checkout_request_id or "",
                            merchant_request_id=merchant_request_id or "",
                            payment_record=payment,
                        )
                    except Exception as fail_notify_err:
                        logger.warning(
                            "Failed to notify customer of STK failure: %s",
                            fail_notify_err,
                            exc_info=True,
                        )
                elif is_paid and not notify_ctx:
                    logger.error(
                        "STK payment succeeded (receipt=%s) but order context missing — "
                        "no WhatsApp receipt sent (checkout=%s)",
                        (parsed or {}).get("transaction_id"),
                        checkout_request_id,
                    )

                logger.info(f"Successfully processed STK callback for user {config.user_id}")
                return

            # 3b. C2B confirmation callbacks (reconciliation)
            await service.process_payment_notification(config.user_id, payload, db)

            logger.info(f"Successfully processed M-Pesa callback for user {config.user_id}")

        except Exception as e:
            logger.error(f"Error in background M-Pesa callback processing: {e}", exc_info=True)
