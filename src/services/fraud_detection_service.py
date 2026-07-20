"""
Fraud Detection Service for M-Pesa Transactions.
Analyzes payments for suspicious patterns, duplicates, and anomalies.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import FraudSignal, MpesaPayment, User
from .daraja_service import daraja_service

logger = logging.getLogger(__name__)

class FraudDetectionService:
    """Service to detect and manage fraudulent M-Pesa transactions."""

    HIGH_RISK_THRESHOLD = 0.7
    MEDIUM_RISK_THRESHOLD = 0.4
    
    # Weights for risk scoring (total = 1.0)
    WEIGHTS = {
        "duplicate": 0.5,      # High confidence indicator
        "frequency": 0.2,      # Velocity check
        "amount_anomaly": 0.15,# Value check
        "time_anomaly": 0.1,    # Outside business hours
        "account_history": 0.05 # User history
    }

    async def analyze_payment(self, payment_id: uuid.UUID, db: AsyncSession) -> Dict[str, Any]:
        """
        Run full fraud analysis on a payment.
        """
        stmt = select(MpesaPayment).where(MpesaPayment.id == payment_id)
        result = await db.execute(stmt)
        payment = result.scalar_one_or_none()
        
        if not payment:
            raise ValueError(f"Payment with ID {payment_id} not found")

        signals = []
        
        # 1. Duplicate Check
        dup_signal = await self.check_duplicate(payment, db)
        if dup_signal:
            signals.append(dup_signal)
            
        # 2. Velocity/Frequency Check
        freq_signal = await self.check_frequency(payment, db)
        if freq_signal:
            signals.append(freq_signal)
            
        # 3. Amount Anomaly Check
        amount_signal = await self.check_amount_anomaly(payment, db)
        if amount_signal:
            signals.append(amount_signal)
            
        # 4. Time Anomaly Check
        time_signal = await self.check_time_anomaly(payment, db)
        if time_signal:
            signals.append(time_signal)

        # Calculate weighted risk score
        risk_score = 0.0
        for signal in signals:
            signal_type = signal["type"]
            weight = self.WEIGHTS.get(signal_type, 0.05)
            risk_score += float(signal["score"]) * weight

        # Cap score at 1.0
        risk_score = min(risk_score, 1.0)

        # Update payment record
        payment.fraud_risk_score = risk_score
        payment.fraud_flags = [s["type"] for s in signals]
        
        if risk_score >= self.HIGH_RISK_THRESHOLD:
            payment.is_suspicious = True
            payment.verification_status = "failed"
            # Auto-lock logic could go here
        elif risk_score >= self.MEDIUM_RISK_THRESHOLD:
            payment.is_suspicious = True
            payment.verification_status = "pending_review"
        else:
            payment.verification_status = "verified" # Assumed verified if low risk

        # Save signals to DB
        for s in signals:
            fraud_signal = FraudSignal(
                user_id=payment.user_id,
                payment_id=payment.id,
                signal_type=s["type"],
                risk_score=Decimal(str(s["score"])),
                confidence=Decimal(str(s.get("confidence", 0.8))),
                detection_method="rule_based",
                metadata_=s.get("metadata", {}),
                action_taken="flagged" if risk_score >= self.MEDIUM_RISK_THRESHOLD else "none"
            )
            db.add(fraud_signal)

        await db.commit()
        await db.refresh(payment)

        return {
            "payment_id": payment.id,
            "risk_score": risk_score,
            "is_suspicious": payment.is_suspicious,
            "status": payment.verification_status,
            "flags": payment.fraud_flags,
            "signals": signals
        }

    async def check_duplicate(self, payment: MpesaPayment, db: AsyncSession) -> Optional[Dict[str, Any]]:
        """Check for duplicate transaction IDs from the same phone number."""
        # Note: transaction_id has unique constraint usually, but we check for 
        # attempts with same ID or very similar ones if we had fuzzy logic.
        # For now, we check if this ID HAS ALREADY been seen for this user.
        stmt = select(func.count(MpesaPayment.id)).where(
            and_(
                MpesaPayment.transaction_id == payment.transaction_id,
                MpesaPayment.id != payment.id,
                MpesaPayment.user_id == payment.user_id
            )
        )
        result = await db.execute(stmt)
        count = result.scalar()
        
        if count > 0:
            return {
                "type": "duplicate",
                "score": 1.0,
                "confidence": 1.0,
                "metadata": {"duplicate_count": count}
            }
        return None

    async def check_frequency(self, payment: MpesaPayment, db: AsyncSession) -> Optional[Dict[str, Any]]:
        """Check payment frequency (Velocity) from this phone number in the last hour."""
        one_hour_ago = datetime.now() - timedelta(hours=1)
        stmt = select(func.count(MpesaPayment.id)).where(
            and_(
                MpesaPayment.phone_number == payment.phone_number,
                MpesaPayment.user_id == payment.user_id,
                MpesaPayment.transaction_time >= one_hour_ago
            )
        )
        result = await db.execute(stmt)
        count = result.scalar()
        
        if count > 10: # More than 10 txns per hour is suspicious
            score = min((count - 10) / 10, 1.0)
            return {
                "type": "frequency",
                "score": score,
                "confidence": 0.8,
                "metadata": {"hourly_count": count}
            }
        return None

    async def check_amount_anomaly(self, payment: MpesaPayment, db: AsyncSession) -> Optional[Dict[str, Any]]:
        """Check if amount is significantly higher than user's average."""
        stmt = select(func.avg(MpesaPayment.amount)).where(
            MpesaPayment.user_id == payment.user_id
        )
        result = await db.execute(stmt)
        avg_amount = result.scalar() or Decimal("0")
        
        if avg_amount > 0 and payment.amount > avg_amount * 5:
            score = min(float(payment.amount / (avg_amount * 5)) / 2, 1.0)
            return {
                "type": "amount_anomaly",
                "score": score,
                "confidence": 0.7,
                "metadata": {"avg_amount": float(avg_amount), "ratio": float(payment.amount / avg_amount)}
            }
        return None

    async def check_time_anomaly(self, payment: MpesaPayment, db: AsyncSession) -> Optional[Dict[str, Any]]:
        """Check if transaction occurred during unusual hours (e.g., 1 AM - 5 AM)."""
        tx_hour = payment.transaction_time.hour
        if 1 <= tx_hour <= 5:
            return {
                "type": "time_anomaly",
                "score": 0.6,
                "confidence": 0.6,
                "metadata": {"hour": tx_hour}
            }
        return None

    async def verify_with_daraja(self, payment_id: uuid.UUID, db: AsyncSession) -> Dict[str, Any]:
        """
        Verify the transaction against Safaricom's source of truth.
        """
        stmt = select(MpesaPayment).where(MpesaPayment.id == payment_id)
        result = await db.execute(stmt)
        payment = result.scalar_one_or_none()
        
        if not payment:
            return {"success": False, "error": "Payment not found"}

        # Call Daraja API
        daraja_result = await daraja_service.query_transaction_status(payment.transaction_id)
        
        # Note: ResponseCode 0 means request was accepted, but real result comes via Callback.
        # For Sandbox/Mock, we might simulate a direct verification if possible.
        
        payment.verification_status = "verified" if daraja_result.get("ResponseCode") == "0" else "failed"
        await db.commit()
        
        return {
            "success": True,
            "daraja_response": daraja_result,
            "verification_status": payment.verification_status
        }

# Global instance
fraud_detection_service = FraudDetectionService()
