"""
M-Pesa Payment Reconciliation Agent
Handles natural language queries about M-Pesa payments via Slack
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User
from ..llm_service import LLMService
from ..mpesa_reconciliation_service import MpesaReconciliationService
from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class MpesaReconciliationAgent(BaseAgent):
    """Agent for M-Pesa payment reconciliation queries."""

    SYSTEM_PROMPT = """You are a helpful financial assistant for M-Pesa payment reconciliation.
You help users understand their M-Pesa payment data through natural language queries.
You can answer questions about:
- Payment summaries (daily, weekly, monthly, today, yesterday)
- Specific payment details
- Unmatched payments
- Payment trends

Always respond in a clear, concise manner. If the user asks in a local language like Swahili, respond in that language.
Format numbers with commas (e.g., KES 10,000.00).

When users ask about payments, extract:
- Date range (today, yesterday, week, month, or specific dates)
- Any filters (amount, phone number, reference)
- Summary type (total, count, breakdown)

Respond in a friendly, professional tone appropriate for the regional business context."""

    def __init__(self, user: User, db: AsyncSession):
        super().__init__(user, db)
        self.reconciliation_service = MpesaReconciliationService()

    async def process_message(
        self,
        message: str,
        channel: str,
        slack_user_id: str
    ) -> Dict[str, Any]:
        """Process incoming message and return response."""
        try:
            # Classify intent
            intent = await self.classify_intent(message)

            # Execute based on intent
            if intent["intent"] == "get_summary":
                return await self.handle_summary_query(message, intent)
            elif intent["intent"] == "query_payments":
                return await self.handle_payment_query(message, intent)
            elif intent["intent"] == "get_unmatched":
                return await self.handle_unmatched_query(message, intent)
            else:
                return await self.handle_general_query(message)

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "response": "Sorry, I encountered an error processing your request. Please try again."
            }

    async def classify_intent(self, message: str) -> Dict[str, Any]:
        """Classify user intent using LLM."""
        prompt = f"""Classify the intent of this user query about M-Pesa payments:

Query: "{message}"

Respond with JSON only (no markdown, no code blocks):
{{
    "intent": "get_summary|query_payments|get_unmatched|general",
    "confidence": 0.0-1.0,
    "date_range": "today|yesterday|week|month|custom|all",
    "filters": {{}}
}}

Intent meanings:
- get_summary: User wants payment totals, counts, or aggregated data
- query_payments: User wants to search for specific payments
- get_unmatched: User wants to see unmatched payments
- general: General question or greeting"""
        
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await self.get_llm_response(
                messages=messages,
                provider="openai",
                temperature=0.3
            )
            
            # Parse response - try to extract JSON
            response = response.strip()
            # Remove markdown code blocks if present
            if response.startswith("```"):
                # Extract JSON from code block
                lines = response.split("\n")
                json_lines = [l for l in lines if not l.strip().startswith("```")]
                response = "\n".join(json_lines)
            
            # Try to parse JSON
            try:
                intent_data = json.loads(response)
                return intent_data
            except json.JSONDecodeError:
                # If JSON parsing fails, try to extract intent from text
                response_lower = response.lower()
                if "summary" in response_lower or "total" in response_lower or "today" in response_lower:
                    return {"intent": "get_summary", "confidence": 0.7, "date_range": "today", "filters": {}}
                elif "unmatched" in response_lower or "unmatched" in response_lower:
                    return {"intent": "get_unmatched", "confidence": 0.7, "date_range": "all", "filters": {}}
                else:
                    return {"intent": "general", "confidence": 0.5, "date_range": "all", "filters": {}}
        
        except Exception as e:
            logger.error(f"Error classifying intent: {e}")
            # Default to general intent on error
            return {"intent": "general", "confidence": 0.5, "date_range": "all", "filters": {}}

    async def handle_summary_query(
        self,
        message: str,
        intent: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle payment summary queries."""
        date_range = intent.get("date_range", "today")
        
        # Calculate date range
        end_date = datetime.utcnow()
        if date_range == "today":
            start_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
        elif date_range == "yesterday":
            start_date = (end_date - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=1) - timedelta(seconds=1)
        elif date_range == "week":
            start_date = end_date - timedelta(days=7)
        elif date_range == "month":
            start_date = end_date - timedelta(days=30)
        else:
            start_date = end_date - timedelta(days=1)

        # Get summary
        summary = await self.reconciliation_service.get_payment_summary(
            user_id=self.user.id,
            start_date=start_date,
            end_date=end_date,
            db=self.db
        )

        # Format response
        date_label = date_range.replace("_", " ").title()
        response_text = f"📊 M-Pesa Payment Summary ({date_label})\n\n"
        response_text += f"*Total Amount:* KES {summary['total_amount']:,.2f}\n"
        response_text += f"*Total Payments:* {summary['total_count']}\n"
        response_text += f"*Matched:* {summary['matched_count']}\n"
        response_text += f"*Unmatched:* {summary['unmatched_count']}\n"
        response_text += f"*Pending:* {summary['pending_count']}"

        return {
            "success": True,
            "response": response_text,
            "data": summary
        }

    async def handle_payment_query(
        self,
        message: str,
        intent: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle payment search queries."""
        payments = await self.reconciliation_service.query_payments(
            user_id=self.user.id,
            query=message,
            db=self.db,
            limit=10
        )

        if not payments:
            return {
                "success": True,
                "response": "No payments found matching your query."
            }

        # Format response
        response_text = f"Found {len(payments)} payment(s):\n\n"
        for payment in payments[:5]:  # Show max 5
            response_text += f"• *KES {payment.amount:,.2f}* from {payment.phone_number}"
            response_text += f" ({payment.transaction_time.strftime('%Y-%m-%d %H:%M')})\n"
            if payment.reference:
                response_text += f"  Reference: {payment.reference}\n"
            response_text += f"  Status: {payment.status}\n\n"

        if len(payments) > 5:
            response_text += f"... and {len(payments) - 5} more"

        return {
            "success": True,
            "response": response_text,
            "data": [{
                "amount": float(p.amount),
                "phone": p.phone_number,
                "reference": p.reference,
                "status": p.status
            } for p in payments]
        }

    async def handle_unmatched_query(
        self,
        message: str,
        intent: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle unmatched payments query."""
        payments = await self.reconciliation_service.get_unmatched_payments(
            user_id=self.user.id,
            db=self.db,
            limit=10
        )

        if not payments:
            return {
                "success": True,
                "response": "✅ No unmatched payments found. All payments are matched!"
            }

        # Format response
        total_unmatched = sum(float(p.amount) for p in payments)
        response_text = f"⚠️ Found {len(payments)} unmatched payment(s) (KES {total_unmatched:,.2f} total):\n\n"
        
        for payment in payments[:5]:  # Show max 5
            response_text += f"• *KES {payment.amount:,.2f}* from {payment.phone_number}\n"
            response_text += f"  Date: {payment.transaction_time.strftime('%Y-%m-%d %H:%M')}\n"
            if payment.reference:
                response_text += f"  Reference: {payment.reference}\n"
            response_text += f"  ID: {payment.transaction_id}\n\n"

        if len(payments) > 5:
            response_text += f"... and {len(payments) - 5} more unmatched payments"

        return {
            "success": True,
            "response": response_text,
            "data": [{
                "amount": float(p.amount),
                "phone": p.phone_number,
                "reference": p.reference,
                "transaction_id": p.transaction_id
            } for p in payments]
        }

    async def handle_general_query(self, message: str) -> Dict[str, Any]:
        """Handle general queries using LLM."""
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": message}
        ]

        response = await self.get_llm_response(
            messages=messages,
            provider="openai",
            temperature=0.7
        )

        return {
            "success": True,
            "response": response
        }

