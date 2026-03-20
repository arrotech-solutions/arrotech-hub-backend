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
from ..utils.encryption import encrypt_value, decrypt_value
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

    # Fields that must be encrypted at rest
    _ENCRYPTED_FIELDS = {"daraja_consumer_key", "daraja_consumer_secret", "daraja_passkey"}

    async def get_config(
        self,
        user_id: int,
        db: AsyncSession
    ) -> Optional[MpesaAgentConfig]:
        """Get M-Pesa agent configuration for user (credentials remain encrypted)."""
        stmt = select(MpesaAgentConfig).where(
            MpesaAgentConfig.user_id == user_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    def decrypt_config_credentials(self, config: MpesaAgentConfig) -> Dict[str, Optional[str]]:
        """
        Decrypt the sensitive fields from a config for use in API calls.
        Returns a dict with decrypted values.
        """
        return {
            "daraja_consumer_key": decrypt_value(config.daraja_consumer_key),
            "daraja_consumer_secret": decrypt_value(config.daraja_consumer_secret),
            "daraja_passkey": decrypt_value(config.daraja_passkey),
        }

    async def create_or_update_config(
        self,
        user_id: int,
        config_data: Dict[str, Any],
        db: AsyncSession
    ) -> MpesaAgentConfig:
        """Create or update M-Pesa agent configuration. Encrypts sensitive fields."""
        import secrets
        
        # Encrypt sensitive fields before persisting
        data = dict(config_data)
        for field in self._ENCRYPTED_FIELDS:
            if field in data and data[field]:
                data[field] = encrypt_value(data[field])
        
        config = await self.get_config(user_id, db)

        if config:
            # Update existing
            for key, value in data.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            config.updated_at = datetime.utcnow()
            
            # Ensure webhook_secret exists if daraja fields are provided
            if (data.get("daraja_shortcode") and not config.webhook_secret):
                config.webhook_secret = secrets.token_urlsafe(32)
                
        else:
            # Create new
            config_kwargs = {
                "user_id": user_id,
                **data
            }
            if data.get("daraja_shortcode"):
                config_kwargs["webhook_secret"] = secrets.token_urlsafe(32)
                
            config = MpesaAgentConfig(**config_kwargs)
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

        # Ignore Daraja dummy test payloads (sent during URL registration)
        if reference == "ProbCheck" or transaction_id == "ProbCheck" or "probcheck" in str(description).lower():
            logger.info(f"Ignoring Daraja URL registration dummy payload for user {user_id}")
            return None

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
        
        # CRITICAL: Commit the payment record FIRST so it's never lost
        # even if auto-match or alerting fails
        await db.commit()
        await db.refresh(payment)
        logger.info(f"Payment {transaction_id} saved to database with status 'pending'")

        # Auto-match if enabled (best-effort, won't lose the payment if it fails)
        config = await self.get_config(user_id, db)
        if config and config.auto_match_enabled:
            try:
                await self.attempt_auto_match(payment, db)
                await db.commit()
            except Exception as e:
                logger.error(f"Auto-match failed for payment {transaction_id}, payment is still saved: {e}", exc_info=True)
                await db.rollback()

        # Send alert if enabled (best-effort)
        if config and config.alert_enabled:
            try:
                await self.send_payment_alert(payment, config, db)
            except Exception as e:
                logger.error(f"Alert failed for payment {transaction_id}: {e}", exc_info=True)

        await db.refresh(payment)
        return payment

    async def attempt_auto_match(
        self,
        payment: MpesaPayment,
        db: AsyncSession,
        external_invoices: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Attempt to automatically match payment to invoice.
        Uses both exact and fuzzy matching.
        
        Args:
            external_invoices: Optional list of invoice dicts from connected 
                accounting tools (Xero, QuickBooks, etc.). If provided, matches
                against these instead of querying the local DB.
        """
        match_result = await self.find_matching_invoice(payment, db, external_invoices)
        
        if match_result and match_result["match_type"] != "none":
            # Update payment with match info
            invoice_data = match_result["invoice"]
            
            # Store match metadata — works for both local Invoice objects and external dicts
            if isinstance(invoice_data, dict):
                # External invoice — store ID and number in payment metadata
                payment.match_confidence = match_result["confidence"]
                payment.status = "matched"
                payment.reference = payment.reference or ""
                
                # Store external invoice info for later Xero sync
                external_id = invoice_data.get("id") or invoice_data.get("invoice_id")
                external_number = invoice_data.get("invoice_number")
            else:
                # Local Invoice ORM object (backward compat)
                payment.matched_invoice_id = invoice_data.id
                payment.match_confidence = match_result["confidence"]
                payment.status = "matched"
                external_id = None
                external_number = invoice_data.invoice_number
            
            # If high confidence, verify automatically
            config = await self.get_config(payment.user_id, db)
            threshold = config.match_threshold if config else self.HIGH_CONFIDENCE_THRESHOLD
            
            if match_result["confidence"] >= threshold:
                payment.status = "verified"
                
                if isinstance(invoice_data, dict):
                    # External invoice — sync payment back to Xero using invoice ID
                    await self._sync_payment_to_xero_by_id(
                        payment, external_id, db
                    )
                else:
                    # Local invoice — update status and sync
                    await self.invoice_service.update_invoice(
                        invoice_data.id,
                        payment.user_id,
                        {"status": InvoiceStatus.PAID},
                        db
                    )
                    await self._sync_payment_to_xero(payment, invoice_data, db)
            
            await db.flush()
            
            return {
                "invoice": invoice_data,
                "invoice_number": external_number if isinstance(invoice_data, dict) else invoice_data.invoice_number,
                "confidence": match_result["confidence"],
                "match_type": match_result["match_type"]
            }
            
        # No match found
        payment.status = "unmatched"
        await db.flush()
        return None

    async def _sync_payment_to_xero(
        self,
        payment: MpesaPayment,
        invoice: Invoice,
        db: AsyncSession
    ) -> None:
        """Helper to sync matched M-Pesa payments to Xero."""
        try:
            from .xero_service import xero_service
            from ..models import Connection, ConnectionPlatform, ConnectionStatus
            
            # 1. Check if user has Xero connection
            stmt = select(Connection).where(
                Connection.user_id == payment.user_id,
                Connection.platform == ConnectionPlatform.XERO,
                Connection.status == ConnectionStatus.ACTIVE
            )
            result = await db.execute(stmt)
            connection = result.scalar_one_or_none()
            
            if not connection:
                logger.debug(f"No active Xero connection for user {payment.user_id}. Skipping Xero payment sync.")
                return
                
            # 2. Get Xero Invoice ID
            xero_invoice_id = invoice.metadata_.get("xero_invoice_id") if invoice.metadata_ else None
            if not xero_invoice_id:
                logger.warning(f"Invoice {invoice.id} lacks 'xero_invoice_id'. Cannot sync payment {payment.transaction_id} to Xero.")
                return
                
            # Configure service with user's token
            xero_service._configure_from_connection(connection.config)
            
            # 3. Find Bank Account dynamically
            accounts_res = await xero_service.get_accounts(account_type="BANK")
            if not accounts_res.get("success") or not accounts_res.get("accounts"):
                logger.error(f"Failed to fetch Xero bank accounts for user {payment.user_id}. Cannot sync payment.")
                return
                
            accounts = accounts_res["accounts"]
            target_account_id = None
            
            # Try to find an M-Pesa account first
            for acc in accounts:
                if "mpesa" in str(acc.get("name", "")).lower():
                    target_account_id = acc.get("id")
                    break
                    
            if not target_account_id:
                target_account_id = accounts[0].get("id") # Fallback to first bank account
                
            # 4. Push payment explicitly
            payment_res = await xero_service.create_payment(
                invoice_id=xero_invoice_id,
                account_id=target_account_id,
                amount=float(payment.amount),
                date=payment.transaction_time.strftime("%Y-%m-%d"),
                reference=f"M-Pesa: {payment.transaction_id}"
            )
            
            if not payment_res.get("success"):
                logger.error(f"Failed to sync payment {payment.transaction_id} to Xero: {payment_res.get('error')}")
            else:
                logger.info(f"Successfully synced M-Pesa payment {payment.transaction_id} to Xero")
                
        except Exception as e:
            logger.error(f"Exception syncing payment {payment.transaction_id} to Xero: {e}", exc_info=True)

    async def _sync_payment_to_xero_by_id(
        self,
        payment: MpesaPayment,
        xero_invoice_id: Optional[str],
        db: AsyncSession
    ) -> None:
        """Sync matched payment to Xero using the external invoice ID directly."""
        if not xero_invoice_id:
            logger.warning(f"No Xero invoice ID for payment {payment.transaction_id}, skipping sync")
            return
        
        try:
            from .xero_service import xero_service
            from ..models import Connection, ConnectionPlatform, ConnectionStatus
            
            stmt = select(Connection).where(
                Connection.user_id == payment.user_id,
                Connection.platform == ConnectionPlatform.XERO,
                Connection.status == ConnectionStatus.ACTIVE
            )
            result = await db.execute(stmt)
            connection = result.scalar_one_or_none()
            
            if not connection:
                logger.debug(f"No active Xero connection for user {payment.user_id}")
                return
            
            xero_service._configure_from_connection(connection.config)
            
            # Find bank account
            accounts_res = await xero_service.get_accounts(account_type="BANK")
            if not accounts_res.get("success") or not accounts_res.get("accounts"):
                logger.error(f"Failed to fetch Xero bank accounts for user {payment.user_id}")
                return
            
            accounts = accounts_res["accounts"]
            target_account_id = None
            for acc in accounts:
                if "mpesa" in str(acc.get("name", "")).lower():
                    target_account_id = acc.get("id")
                    break
            if not target_account_id:
                target_account_id = accounts[0].get("id")
            
            payment_res = await xero_service.create_payment(
                invoice_id=xero_invoice_id,
                account_id=target_account_id,
                amount=float(payment.amount),
                date=payment.transaction_time.strftime("%Y-%m-%d"),
                reference=f"M-Pesa: {payment.transaction_id}"
            )
            
            if not payment_res.get("success"):
                logger.error(f"Failed to sync payment {payment.transaction_id} to Xero: {payment_res.get('error')}")
            else:
                logger.info(f"Successfully synced M-Pesa payment {payment.transaction_id} to Xero")
                
        except Exception as e:
            logger.error(f"Exception syncing payment {payment.transaction_id} to Xero by ID: {e}", exc_info=True)

    async def match_all_pending_payments(
        self,
        user_id: int,
        db: AsyncSession,
        external_invoices: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Match all pending and unmatched payments for a user.
        
        Args:
            external_invoices: Optional list of invoice dicts from connected
                accounting tools (Xero, QuickBooks, Zoho). Passed directly to
                the matching engine — no local invoice table needed.
        """
        stmt = select(MpesaPayment).where(
            and_(
                MpesaPayment.user_id == user_id,
                MpesaPayment.status.in_(["pending", "unmatched"])
            )
        )
        result = await db.execute(stmt)
        payments = result.scalars().all()
        
        matched_count = 0
        unmatched_count = 0
        results = []
        
        for payment in payments:
            match = await self.attempt_auto_match(payment, db, external_invoices)
            if match:
                matched_count += 1
                results.append({
                    "transaction_id": payment.transaction_id,
                    "matched": True,
                    "invoice_number": match.get("invoice_number", "unknown"),
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
        db: AsyncSession,
        external_invoices: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Find best matching invoice for payment.
        
        Args:
            external_invoices: Optional list of invoice dicts from connected
                accounting tool. Each dict should have at minimum:
                - invoice_number: str
                - total or amount_due: number
                Optionally: id, reference, contact_name, contact_phone, status
        """
        # Use external invoices if provided, otherwise fall back to local DB
        if external_invoices:
            # Normalize external invoice dicts into a standard format
            invoices = []
            for inv in external_invoices:
                invoices.append({
                    "invoice_number": (inv.get("invoice_number") or "").lower(),
                    "reference": (inv.get("reference") or inv.get("invoice_number") or "").lower(),
                    "amount": float(inv.get("amount_due") or inv.get("total") or 0),
                    "customer_phone": inv.get("contact_phone") or inv.get("customer_phone") or "",
                    "id": inv.get("id"),
                    "_raw": inv  # Keep original dict for return
                })
        else:
            # Fall back to local invoices table (for callback auto-match)
            local_invoices = await self.invoice_service.get_invoices(
                user_id=payment.user_id, 
                db=db, 
                limit=100,
                status=InvoiceStatus.SENT
            )
            invoices = []
            for inv in local_invoices:
                invoices.append({
                    "invoice_number": (inv.invoice_number or "").lower(),
                    "reference": (inv.reference or inv.invoice_number or "").lower(),
                    "amount": float(inv.amount),
                    "customer_phone": inv.customer_phone or "",
                    "id": inv.id,
                    "_raw": inv  # Keep ORM object
                })
        
        if not invoices:
            return None
        
        best_match = None
        best_score = 0.0
        match_type = "none"
        
        payment_ref = (payment.reference or "").lower()
        payment_phone = (payment.phone_number or "").replace("+", "").replace("254", "0")
        
        for inv in invoices:
            score = 0.0
            current_match_type = "none"
            
            inv_number = inv["invoice_number"]
            inv_ref = inv["reference"] or inv_number
            inv_amount = inv["amount"]
            inv_phone = str(inv["customer_phone"]).replace("+", "").replace("254", "0")
            
            amount_match = float(payment.amount) == inv_amount
            
            # 1. Exact Reference Match
            if payment_ref and (payment_ref == inv_number or payment_ref == inv_ref):
                score = 1.0
                current_match_type = "exact_reference"
            
            # 2. Phone + Amount Match
            elif inv_phone and payment_phone and payment_phone in inv_phone:
                if amount_match:
                    score = 0.8
                    current_match_type = "phone_amount"
            
            # 3. Fuzzy Reference Match
            elif payment_ref:
                sim_number = difflib.SequenceMatcher(None, payment_ref, inv_number).ratio()
                sim_ref = difflib.SequenceMatcher(None, payment_ref, inv_ref).ratio()
                max_sim = max(sim_number, sim_ref)
                
                if max_sim > 0.6:
                    score = max_sim
                    current_match_type = "fuzzy_reference"
            
            # Apply Amount Penalty if mismatched
            if not amount_match:
                score = score * 0.5
            
            if score > best_score:
                best_score = score
                best_match = inv
                match_type = current_match_type
        
        if best_match:
            return {
                "invoice": best_match["_raw"],  # Return original object/dict
                "invoice_number": best_match["invoice_number"],
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
