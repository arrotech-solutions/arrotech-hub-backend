"""
Payment router for Mini-Hub with M-Pesa and Stripe integration.
"""

import json
import logging
from typing import Any, Dict

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models import User
from ..routers.auth_router import get_current_user
from ..services.payment_service import PaymentService

logger = logging.getLogger(__name__)

router = APIRouter()
payment_service = PaymentService()

# Initialize Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY


class MpesaPaymentRequest(BaseModel):
    phone_number: str
    amount: int
    reference: str
    description: str = "Mini-Hub Payment"


class StripePaymentRequest(BaseModel):
    amount: int
    currency: str = "kes"
    customer_id: str = None


class StripeCustomerRequest(BaseModel):
    email: str
    name: str


class PaymentVerificationRequest(BaseModel):
    checkout_request_id: str


@router.post("/mpesa/initiate")
async def initiate_mpesa_payment(
    request: MpesaPaymentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Initiate M-Pesa STK push payment."""
    try:
        result = await payment_service.initiate_mpesa_payment(
            phone_number=request.phone_number,
            amount=request.amount,
            reference=request.reference,
            description=request.description
        )

        if result["success"]:
            return {
                "success": True,
                "data": {
                    "checkout_request_id": result["checkout_request_id"],
                    "merchant_request_id": result["merchant_request_id"],
                    "message": result["message"]
                }
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payment initiation failed: {str(e)}"
        )


@router.post("/mpesa/verify")
async def verify_mpesa_payment(
    request: PaymentVerificationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Verify M-Pesa payment status."""
    try:
        result = await payment_service.verify_mpesa_payment(
            request.checkout_request_id
        )

        if result["success"]:
            return {
                "success": True,
                "data": {
                    "status": result["status"],
                    "transaction_id": result["transaction_id"],
                    "amount": result["amount"],
                    "phone_number": result["phone_number"]
                }
            }
        else:
            return {
                "success": False,
                "error": result["error"]
            }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payment verification failed: {str(e)}"
        )


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Handle Stripe webhook notifications."""
    try:
        # Get the raw body
        body = await request.body()

        # Verify webhook signature
        if settings.STRIPE_WEBHOOK_SECRET:
            try:
                event = stripe.Webhook.construct_event(
                    body, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
                )
            except ValueError as e:
                logger.error(f"Invalid payload: {e}")
                raise HTTPException(status_code=400, detail="Invalid payload")
            except stripe.error.SignatureVerificationError as e:
                logger.error(f"Invalid signature: {e}")
                raise HTTPException(
                    status_code=400, detail="Invalid signature")
        else:
            # For development, parse without signature verification
            event = json.loads(body.decode('utf-8'))

        # Handle the event using the payment service
        event_type = event['type']
        logger.info(f"Processing Stripe webhook: {event_type}")

        # Process the webhook using the payment service
        await payment_service.process_stripe_webhook(event, db)

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error processing Stripe webhook: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Webhook processing failed: {str(e)}"
        )


@router.post("/stripe/create-customer")
async def create_stripe_customer(
    request: StripeCustomerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a Stripe customer."""
    try:
        result = await payment_service.create_stripe_customer(
            email=request.email,
            name=request.name
        )

        if result["success"]:
            return {
                "success": True,
                "data": {
                    "customer_id": result["customer_id"]
                }
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Customer creation failed: {str(e)}"
        )


@router.post("/stripe/create-subscription")
async def create_stripe_subscription(
    customer_id: str,
    price_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a Stripe subscription."""
    try:
        result = await payment_service.create_stripe_subscription(
            customer_id, price_id
        )

        if result["success"]:
            return {
                "success": True,
                "data": {
                    "subscription_id": result["subscription_id"],
                    "client_secret": result["client_secret"]
                }
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Subscription creation failed: {str(e)}"
        )


@router.post("/stripe/create-payment-intent")
async def create_stripe_payment_intent(
    request: StripePaymentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a Stripe payment intent."""
    try:
        result = await payment_service.create_stripe_payment_intent(
            amount=request.amount,
            currency=request.currency,
            customer_id=request.customer_id
        )

        if result["success"]:
            return {
                "success": True,
                "data": {
                    "payment_intent_id": result["payment_intent_id"],
                    "client_secret": result["client_secret"],
                    "amount": result["amount"]
                }
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payment intent creation failed: {str(e)}"
        )


@router.get("/pricing")
async def get_pricing_plans():
    """Get pricing plans with Kenyan pricing."""
    return {
        "success": True,
        "data": {
            "plans": {
                "free": {
                    "name": "Free",
                    "price": "KES 0",
                    "price_amount": 0,
                    "requests_per_day": 100,
                    "features": [
                        "HubSpot basic integration",
                        "GA4 basic reports",
                        "Slack basic messaging",
                        "Email support"
                    ]
                },
                "pro": {
                    "name": "Pro",
                    "price": "KES 5,000",
                    "price_amount": 5000,
                    "requests_per_day": 10000,
                    "features": [
                        "Full HubSpot integration",
                        "Advanced GA4 reports",
                        "Slack rich messaging",
                        "Priority support",
                        "Custom workflows",
                        "API access"
                    ]
                },
                "agency": {
                    "name": "Agency",
                    "price": "KES 15,000",
                    "price_amount": 15000,
                    "requests_per_day": 50000,
                    "features": [
                        "Everything in Pro",
                        "Multiple team members",
                        "White-label options",
                        "Advanced analytics",
                        "Custom integrations",
                        "Dedicated support"
                    ]
                },
                "enterprise": {
                    "name": "Enterprise",
                    "price": "Contact Us",
                    "price_amount": 0,
                    "requests_per_day": 100000,
                    "features": [
                        "Everything in Agency",
                        "Custom pricing",
                        "On-premise deployment",
                        "SLA guarantees",
                        "24/7 support",
                        "Custom development"
                    ]
                }
            }
        }
    }


@router.post("/mpesa/callback")
async def mpesa_callback(request: Request):
    """Handle M-Pesa callback notifications."""
    try:
        # Log the callback data
        callback_data = await request.json()
        logger.info(f"M-Pesa callback received: {callback_data}")

        # Extract relevant information
        result_code = callback_data.get("ResultCode")
        result_desc = callback_data.get("ResultDesc")
        checkout_request_id = callback_data.get("CheckoutRequestID")
        merchant_request_id = callback_data.get("MerchantRequestID")

        # Log the result
        logger.info(
            f"Payment result - Code: {result_code}, Desc: {result_desc}")
        logger.info(
            f"Request IDs - Checkout: {checkout_request_id}, Merchant: {merchant_request_id}")

        # Return success response to M-Pesa
        return {
            "ResultCode": 0,
            "ResultDesc": "Success"
        }

    except Exception as e:
        logger.error(f"Error processing M-Pesa callback: {str(e)}")
        return {
            "ResultCode": 1,
            "ResultDesc": "Error processing callback"
        }
