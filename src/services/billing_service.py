"""
Billing service for Mini-Hub MCP Server.
"""

import logging
from typing import Any, Dict, Optional

import stripe

from ..config import settings

logger = logging.getLogger(__name__)


class BillingService:
    """Stripe billing service."""

    def __init__(self):
        self.stripe: Optional[stripe.Stripe] = None

    async def initialize(self):
        """Initialize Stripe client."""
        if settings.STRIPE_SECRET_KEY:
            stripe.api_key = settings.STRIPE_SECRET_KEY
            self.stripe = stripe
            logger.info("Stripe client initialized")
        else:
            logger.warning("Stripe secret key not configured")

    async def create_customer(self, email: str, name: Optional[str] = None) -> Dict[str, Any]:
        """Create a Stripe customer."""
        if not self.stripe:
            raise Exception("Stripe client not initialized")

        try:
            customer = self.stripe.Customer.create(
                email=email,
                name=name,
                metadata={"source": "mini-hub-mcp"}
            )

            return {
                "success": True,
                "customer_id": customer.id,
                "email": customer.email
            }

        except Exception as e:
            logger.error(f"Error creating Stripe customer: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def create_subscription(self, customer_id: str, tier: str = "pro") -> Dict[str, Any]:
        """Create a subscription."""
        if not self.stripe:
            raise Exception("Stripe client not initialized")

        try:
            # Get price ID based on tier
            price_id = self._get_price_id(tier)

            subscription = self.stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                metadata={"tier": tier}
            )

            return {
                "success": True,
                "subscription_id": subscription.id,
                "status": subscription.status,
                "tier": tier
            }

        except Exception as e:
            logger.error(f"Error creating subscription: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def create_enterprise_setup_payment(self, customer_id: str,
                                              description: str = "Enterprise Setup") -> Dict[str, Any]:
        """Create a one-time payment for enterprise setup."""
        if not self.stripe:
            raise Exception("Stripe client not initialized")

        try:
            payment_intent = self.stripe.PaymentIntent.create(
                amount=settings.ENTERPRISE_SETUP_PRICE,
                currency="usd",
                customer=customer_id,
                description=description,
                metadata={"type": "enterprise_setup"}
            )

            return {
                "success": True,
                "payment_intent_id": payment_intent.id,
                "amount": payment_intent.amount,
                "client_secret": payment_intent.client_secret
            }

        except Exception as e:
            logger.error(f"Error creating enterprise setup payment: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """Get subscription details."""
        if not self.stripe:
            raise Exception("Stripe client not initialized")

        try:
            subscription = self.stripe.Subscription.retrieve(subscription_id)

            return {
                "success": True,
                "subscription_id": subscription.id,
                "status": subscription.status,
                "current_period_start": subscription.current_period_start,
                "current_period_end": subscription.current_period_end,
                "tier": subscription.metadata.get("tier", "unknown")
            }

        except Exception as e:
            logger.error(f"Error getting subscription: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def cancel_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """Cancel a subscription."""
        if not self.stripe:
            raise Exception("Stripe client not initialized")

        try:
            subscription = self.stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=True
            )

            return {
                "success": True,
                "subscription_id": subscription.id,
                "status": subscription.status
            }

        except Exception as e:
            logger.error(f"Error canceling subscription: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _get_price_id(self, tier: str) -> str:
        """Get Stripe price ID for tier."""
        # In production, these would be actual Stripe price IDs
        price_ids = {
            "pro": "price_pro_monthly",
            "enterprise": "price_enterprise_monthly"
        }

        return price_ids.get(tier, "price_pro_monthly")
