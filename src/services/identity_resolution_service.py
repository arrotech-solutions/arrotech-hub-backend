"""
Identity Resolution Service
Solves the 'Identity Gap' (Proxy Payers) by linking Payer Identity (Phone) to Customer Identity (ID/Account).
"""
import logging
from typing import Dict, Any, Optional, List
from sqlalchemy import select, and_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

# Assuming a model needs to exist to store this history. 
# For now, we will assume we can store it in a JSON field in UserSettings or a new model.
# Since we can't create new tables easily without migrations here, 
# we will simulate the storage or use generic 'metadata' fields on existing Customer/Invoice tables if possible.
# Ideally, we would have a `PayerHistory` table. 
# Let's use `Invoice` history as the "Knowledge Base".

from ..models import Invoice, MpesaPayment, User

logger = logging.getLogger(__name__)

class IdentityResolutionService:
    """Service for resolving payer identity."""

    async def resolve_payer(
        self, 
        phone_number: str, 
        sender_name: str,
        user_id: int,
        db: AsyncSession
    ) -> Optional[Dict[str, Any]]:
        """
        Identify who this payer likely is based on history.
        
        Args:
            phone_number: The M-Pesa phone number
            sender_name: The M-Pesa name (e.g. JOHN DOE)
            user_id: The Business User ID
            
        Returns:
            Dict with 'customer_name', 'customer_email', 'confidence'
        """
        # Step 1: Check Global Identity Map (Not implemented in this MVP, would be cross-tenant)
        # Step 2: Check User's History
        
        # Look for past Invoices PAID by this phone number
        # We need to find MpesaPayments with this phone linked to an Invoice
        
        # Query: Find matched payments from this phone
        stmt = select(Invoice).join(
            MpesaPayment, 
            MpesaPayment.matched_invoice_id == Invoice.id
        ).where(
            and_(
                MpesaPayment.user_id == user_id,
                MpesaPayment.phone_number == phone_number,
                MpesaPayment.status.in_(["matched", "verified"])
            )
        ).order_by(MpesaPayment.transaction_time.desc()).limit(1)
        
        result = await db.execute(stmt)
        last_invoice = result.scalar_one_or_none()
        
        if last_invoice:
            # We found a past match!
            # "John Doe (07xx)" paid for "Jane Student's Invoice" last month.
            return {
                "suggested_customer_name": last_invoice.customer_name,
                "suggested_customer_email": last_invoice.customer_email,
                "confidence": 0.85, # High confidence from history
                "match_source": "historical_payment"
            }
            
        # Step 3: Fuzzy Name Match
        # If "John Doe" pays, check if we have a customer named "John Doe"
        # This resolves self-payers who haven't paid *digitally* before but exist in DB.
        
        # This requires a Customer table which we might not have explicitly, 
        # so we search distinct customer_names in Invoices.
        
        stmt_name = select(Invoice.customer_name, Invoice.customer_email).where(
            and_(
                Invoice.user_id == user_id,
                Invoice.customer_name.ilike(f"%{sender_name}%")
            )
        ).limit(1)
        
        result_name = await db.execute(stmt_name)
        name_match = result_name.first()
        
        if name_match:
             return {
                "suggested_customer_name": name_match.customer_name,
                "suggested_customer_email": name_match.customer_email,
                "confidence": 0.6, # Medium confidence (names can be common)
                "match_source": "name_match"
            }

        return None
        
    async def learn_identity(self, payment_id: int, invoice_id: int, db: AsyncSession):
        """
        Record a successful link.
        In this MVP, relying on the MpesaPayment->Invoice foreign key IS the record.
        No explicit action needed unless we create a dedicated lookup table.
        """
        pass
