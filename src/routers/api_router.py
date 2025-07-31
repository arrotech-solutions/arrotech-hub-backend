"""
API router for Mini-Hub MCP Server.
"""


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..services import BillingService, RateLimitService

router = APIRouter()

# Initialize services
billing_service = BillingService()
rate_limit_service = RateLimitService()


@router.get("/status")
async def get_status():
    """Get server status."""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "services": {
            "hubspot": "connected",
            "ga4": "connected",
            "slack": "connected",
            "stripe": "connected",
            "redis": "connected",
            "file_management": "connected",
            "web_tools": "connected",
            "content_creation": "connected"
        }
    }


@router.post("/subscriptions")
async def create_subscription(
    email: str,
    tier: str = "pro",
    db: AsyncSession = Depends(get_db)
):
    """Create a new subscription."""
    try:
        # Create Stripe customer
        customer_result = await billing_service.create_customer(email)
        if not customer_result["success"]:
            raise HTTPException(
                status_code=400, detail=customer_result["error"])

        # Create subscription
        subscription_result = await billing_service.create_subscription(
            customer_result["customer_id"],
            tier
        )

        if not subscription_result["success"]:
            raise HTTPException(
                status_code=400, detail=subscription_result["error"])

        return {
            "success": True,
            "customer_id": customer_result["customer_id"],
            "subscription_id": subscription_result["subscription_id"],
            "tier": tier
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/usage/{user_id}")
async def get_usage(user_id: str):
    """Get usage statistics for a user."""
    try:
        usage = await rate_limit_service.get_usage(user_id)
        return usage
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/enterprise-setup")
async def create_enterprise_setup(email: str, description: str = "Enterprise Setup"):
    """Create enterprise setup payment."""
    try:
        # Create customer first
        customer_result = await billing_service.create_customer(email)
        if not customer_result["success"]:
            raise HTTPException(
                status_code=400, detail=customer_result["error"])

        # Create payment intent
        payment_result = await billing_service.create_enterprise_setup_payment(
            customer_result["customer_id"],
            description
        )

        if not payment_result["success"]:
            raise HTTPException(
                status_code=400, detail=payment_result["error"])

        return {
            "success": True,
            "payment_intent_id": payment_result["payment_intent_id"],
            "client_secret": payment_result["client_secret"],
            "amount": payment_result["amount"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pricing")
async def get_pricing():
    """Get pricing information."""
    return {
        "tiers": {
            "free": {
                "price": "$0/month",
                "requests_per_day": 100,
                "features": [
                    "HubSpot basic integration",
                    "GA4 basic reports",
                    "Slack basic messaging"
                ]
            },
            "pro": {
                "price": "$49/month",
                "requests_per_day": 10000,
                "features": [
                    "Full HubSpot integration",
                    "Advanced GA4 reports",
                    "Slack rich messaging",
                    "Priority support"
                ]
            },
            "enterprise": {
                "price": "$299 one-time",
                "requests_per_day": 100000,
                "features": [
                    "Custom integrations",
                    "White-glove setup",
                    "Dedicated support",
                    "Custom rate limits"
                ]
            }
        }
    }
