"""
M-Pesa Payment Reconciliation Service
Handles payment processing, matching, and alerts for M-Pesa business payments
"""
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from slack_sdk.web import WebClient

from ..models import (
    Connection,
    ConnectionPlatform,
    ConnectionStatus,
    MpesaAgentConfig,
    MpesaPayment,
    User,
    Invoice,
    InvoiceStatus
)
from .slack_service import SlackService
from .invoice_service import InvoiceService
import difflib

logger = logging.getLogger(__name__)


class MpesaReconciliationService:
    """Service for M-Pesa payment reconciliation and alerts."""

    # Match confidence thresholds
    EXACT_MATCH_THRESHOLD = 1.0
    HIGH_CONFIDENCE_THRESHOLD = 0.9
    MEDIUM_CONFIDENCE_THRESHOLD = 0.7

    def __init__(self):
        self.slack_service = SlackService()
        self.invoice_service = InvoiceService()

    async def get_config(
        self,
        user_id: int,
        db: AsyncSession
    ) -> Optional[MpesaAgentConfig]:
        """Get M-Pesa agent configuration for user."""
        stmt = select(MpesaAgentConfig).where(
            MpesaAgentConfig.user_id == user_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_or_update_config(
        self,
        user_id: int,
        config_data: Dict[str, Any],
        db: AsyncSession
    ) -> MpesaAgentConfig:
        """Create or update M-Pesa agent configuration."""
        config = await self.get_config(user_id, db)

        if config:
            # Update existing config
            for key, value in config_data.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            config.updated_at = datetime.utcnow()
        else:
            # Create new config
            config = MpesaAgentConfig(
                user_id=user_id,
                **config_data
            )
            db.add(config)

        await db.commit()
        await db.refresh(config)
        return config

    async def process_payment_notification(
        self,
        user_id: int,
        payment_data: Dict[str, Any],
        db: AsyncSession
    ) -> MpesaPayment:
        """
        Process incoming M-Pesa payment notification.

        Args:
            user_id: User who owns this payment
            payment_data: Payment data from M-Pesa callback
            db: Database session

        Returns:
            Created MpesaPayment record
        """
        # Extract payment details from M-Pesa callback format
        # M-Pesa callback can have different formats, handle both
        transaction_id = (
            payment_data.get("TransID") or
            payment_data.get("transaction_id") or
            payment_data.get("TransactionID")
        )
        amount_str = (
            payment_data.get("TransAmount") or
            payment_data.get("amount") or
            payment_data.get("TransactionAmount") or
            "0"
        )
        phone = (
            payment_data.get("MSISDN") or
            payment_data.get("phone_number") or
            payment_data.get("PhoneNumber") or
            ""
        )
        reference = (
            payment_data.get("BillRefNumber") or
            payment_data.get("reference") or
            payment_data.get("Reference") or
            ""
        )
        description = (
            payment_data.get("TransDesc") or
            payment_data.get("description") or
            payment_data.get("TransactionDesc") or
            ""
        )
        timestamp_str = (
            payment_data.get("TransTime") or
            payment_data.get("timestamp") or
            payment_data.get("TransactionTime") or
            ""
        )

        if not transaction_id:
            raise ValueError("Transaction ID is required")

        # Parse amount
        try:
            amount = Decimal(str(amount_str))
        except (ValueError, TypeError):
            amount = Decimal("0")

        # Parse timestamp (M-Pesa format: YYYYMMDDHHmmss)
        if timestamp_str and len(timestamp_str) == 14:
            try:
                transaction_time = datetime.strptime(timestamp_str, "%Y%m%d%H%M%S")
            except ValueError:
                transaction_time = datetime.utcnow()
        else:
            transaction_time = datetime.utcnow()

        # Check if payment already exists
        stmt = select(MpesaPayment).where(
            MpesaPayment.transaction_id == transaction_id
        )
        result = await db.execute(stmt)
        existing_payment = result.scalar_one_or_none()

        if existing_payment:
            logger.info(f"Payment {transaction_id} already exists, skipping")
            return existing_payment

        # Create payment record
        payment = MpesaPayment(
            user_id=user_id,
            transaction_id=transaction_id,
            amount=amount,
            phone_number=phone,
            reference=reference,
            description=description,
            transaction_time=transaction_time,
            status="pending"
        )

        db.add(payment)
        await db.flush()

        # Auto-match if enabled
        config = await self.get_config(user_id, db)
        if config and config.auto_match_enabled:
            await self.attempt_auto_match(payment, db)

        # Send alert if enabled
        if config and config.alert_enabled:
            await self.send_payment_alert(payment, config, db)

        await db.commit()
        await db.refresh(payment)

        return payment

    async def attempt_auto_match(
        self,
        payment: MpesaPayment,
        db: AsyncSession
    ) -> Optional[Dict[str, Any]]:
        """
        Attempt to automatically match payment to invoice.
        Uses both exact and fuzzy matching.
        """
        match_result = await self.find_matching_invoice(payment, db)
        
        if match_result and match_result["match_type"] != "none":
            # Update payment with match info
            payment.matched_invoice_id = match_result["invoice"].id
            payment.match_confidence = match_result["confidence"]
            payment.status = "matched"
            
            # If high confidence/exact, verify it automatically
            config = await self.get_config(payment.user_id, db)
            threshold = config.match_threshold if config else self.HIGH_CONFIDENCE_THRESHOLD
            
            if match_result["confidence"] >= threshold:
                 # Update Invoice status
                 await self.invoice_service.update_invoice(
                     match_result["invoice"].id,
                     payment.user_id,
                     {"status": InvoiceStatus.PAID},
                     db
                 )
                 payment.status = "verified"
            
            await db.flush()
            return match_result
            
        # No match found
        payment.status = "unmatched"
        await db.flush()
        return None

    async def match_all_pending_payments(
        self,
        user_id: int,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Match all pending payments for a user."""
        stmt = select(MpesaPayment).where(
            and_(
                MpesaPayment.user_id == user_id,
                MpesaPayment.status == "pending"
            )
        )
        result = await db.execute(stmt)
        payments = result.scalars().all()
        
        matched_count = 0
        unmatched_count = 0
        results = []
        
        for payment in payments:
            match = await self.attempt_auto_match(payment, db)
            if match:
                matched_count += 1
                results.append({
                    "transaction_id": payment.transaction_id,
                    "matched": True,
                    "invoice_number": match["invoice"].invoice_number,
                    "confidence": match["confidence"]
                })
            else:
                unmatched_count += 1
                results.append({
                    "transaction_id": payment.transaction_id,
                    "matched": False
                })
        
        await db.commit()
        return {
            "total_processed": len(payments),
            "matched_count": matched_count,
            "unmatched_count": unmatched_count,
            "results": results
        }

    async def find_matching_invoice(
        self,
        payment: MpesaPayment,
        db: AsyncSession
    ) -> Optional[Dict[str, Any]]:
        """
        Find best matching invoice for payment.
        """
        # Get all pending invoices for user
        invoices = await self.invoice_service.get_invoices(
            user_id=payment.user_id, 
            db=db, 
            limit=100,
            status=InvoiceStatus.SENT
        )
        
        best_match = None
        best_score = 0.0
        match_type = "none"
        
        payment_ref = (payment.reference or "").lower()
        payment_phone = (payment.phone_number or "").replace("+", "").replace("254", "0")
        
        for invoice in invoices:
            score = 0.0
            current_match_type = "none"
            
            # invoice identifiers
            inv_number = (invoice.invoice_number or "").lower()
            inv_ref = (invoice.reference or "").lower()
            if not inv_ref: inv_ref = inv_number # Fallback
            
            # exact amount match is usually required for auto-reconciliation
            amount_match = float(payment.amount) == float(invoice.amount)
            
            if not amount_match:
                # If amounts differ significantly, skip or penalize?
                # For now simplify: MUST match amount for high confidence
                pass
            
            # 1. Exact Reference Match
            if payment_ref and (payment_ref == inv_number or payment_ref == inv_ref):
                score = 1.0
                current_match_type = "exact_reference"
            
            # 2. Exact Phone Match (if invoice has customer phone)
            elif invoice.customer_phone and payment_phone in str(invoice.customer_phone):
                 # Phone match alone is weak, but with amount it's decent
                 if amount_match:
                     score = 0.8
                     current_match_type = "phone_amount"
            
            # 3. Fuzzy Reference Match
            elif payment_ref:
                # Use difflib for similarity
                sim_number = difflib.SequenceMatcher(None, payment_ref, inv_number).ratio()
                sim_ref = difflib.SequenceMatcher(None, payment_ref, inv_ref).ratio()
                max_sim = max(sim_number, sim_ref)
                
                if max_sim > 0.6: # Filter low quality
                    score = max_sim
                    current_match_type = "fuzzy_reference"
            
            # Apply Amount Penalty if mismatched
            if not amount_match:
                 score = score * 0.5 # significantly reduce confidence
            
            if score > best_score:
                best_score = score
                best_match = invoice
                match_type = current_match_type
        
        if best_match:
            return {
                "invoice": best_match,
                "confidence": best_score,
                "match_type": match_type
            }
            
        return None

    async def send_payment_alert(
        self,
        payment: MpesaPayment,
        config: MpesaAgentConfig,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Send payment alert to Slack channel."""
        if not config.alert_channel_id:
            return {"success": False, "error": "No alert channel configured"}

        # Format message
        amount_str = f"KES {payment.amount:,.2f}"
        message = f"💰 New M-Pesa Payment Received\n\n"
        message += f"*Amount:* {amount_str}\n"
        message += f"*Phone:* {payment.phone_number}\n"
        message += f"*Reference:* {payment.reference or 'N/A'}\n"
        message += f"*Description:* {payment.description or 'N/A'}\n"
        message += f"*Time:* {payment.transaction_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        message += f"*Status:* {payment.status}\n"
        message += f"*Transaction ID:* {payment.transaction_id}"

        # Get user's Slack connection
        stmt = select(Connection).where(
            Connection.user_id == payment.user_id,
            Connection.platform == ConnectionPlatform.SLACK,
            Connection.status == ConnectionStatus.ACTIVE
        )
        result = await db.execute(stmt)
        connection = result.scalar_one_or_none()

        if not connection:
            logger.warning(f"No active Slack connection for user {payment.user_id}")
            return {"success": False, "error": "No active Slack connection"}

        # Initialize Slack service with user's token
        bot_token = connection.config.get("bot_token")
        if not bot_token:
            logger.warning(f"No bot token in Slack connection for user {payment.user_id}")
            return {"success": False, "error": "No bot token in connection"}

        self.slack_service.client = WebClient(token=bot_token)

        # Send message
        try:
            result = await self.slack_service.send_message(
                channel=config.alert_channel_id,
                message=message
            )
            return result
        except Exception as e:
            logger.error(f"Error sending Slack alert: {e}")
            return {"success": False, "error": str(e)}

    async def get_payment_summary(
        self,
        user_id: int,
        start_date: datetime,
        end_date: datetime,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Get payment summary for date range."""
        stmt = select(
            func.sum(MpesaPayment.amount).label("total_amount"),
            func.count(MpesaPayment.id).label("total_count"),
            func.count(MpesaPayment.id).filter(
                MpesaPayment.status == "matched"
            ).label("matched_count"),
            func.count(MpesaPayment.id).filter(
                MpesaPayment.status == "unmatched"
            ).label("unmatched_count"),
            func.count(MpesaPayment.id).filter(
                MpesaPayment.status == "pending"
            ).label("pending_count")
        ).where(
            and_(
                MpesaPayment.user_id == user_id,
                MpesaPayment.transaction_time >= start_date,
                MpesaPayment.transaction_time <= end_date
            )
        )

        result = await db.execute(stmt)
        row = result.first()

        return {
            "total_amount": float(row.total_amount or 0),
            "total_count": row.total_count or 0,
            "matched_count": row.matched_count or 0,
            "unmatched_count": row.unmatched_count or 0,
            "pending_count": row.pending_count or 0,
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            }
        }

    async def query_payments(
        self,
        user_id: int,
        query: str,
        db: AsyncSession,
        limit: int = 10
    ) -> List[MpesaPayment]:
        """
        Query payments based on natural language query.
        This is a simple implementation - will be enhanced with LLM in the agent.
        """
        # Simple implementation - return recent payments
        # Full implementation will use LLM for better query parsing
        stmt = select(MpesaPayment).where(
            MpesaPayment.user_id == user_id
        ).order_by(MpesaPayment.transaction_time.desc()).limit(limit)

        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_unmatched_payments(
        self,
        user_id: int,
        db: AsyncSession,
        limit: int = 20
    ) -> List[MpesaPayment]:
        """Get unmatched payments for a user."""
        stmt = select(MpesaPayment).where(
            and_(
                MpesaPayment.user_id == user_id,
                MpesaPayment.status == "unmatched"
            )
        ).order_by(MpesaPayment.transaction_time.desc()).limit(limit)

        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_payments_by_date_range(
        self,
        user_id: int,
        start_date: datetime,
        end_date: datetime,
        db: AsyncSession,
        limit: int = 100
    ) -> List[MpesaPayment]:
        """Get payments within a date range."""
        stmt = select(MpesaPayment).where(
            MpesaPayment.user_id == user_id,
            MpesaPayment.transaction_time >= start_date,
            MpesaPayment.transaction_time <= end_date
        ).order_by(MpesaPayment.transaction_time.desc()).limit(limit)
        
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_payment_by_transaction_id(
        self,
        user_id: int,
        db: AsyncSession,
        transaction_id: str
    ) -> Optional[MpesaPayment]:
        """Get a specific payment by its transaction ID."""
        stmt = select(MpesaPayment).where(
            MpesaPayment.user_id == user_id,
            MpesaPayment.transaction_id == transaction_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
