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


class PaystackVerificationRequest(BaseModel):
    reference: str


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



@router.get("/paystack/config")
async def get_paystack_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get Paystack public key."""
    if not payment_service.paystack_public_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Paystack configuration error"
        )
    
    return {
        "success": True,
        "data": {
            "key": payment_service.paystack_public_key
        }
    }


@router.post("/paystack/webhook")
async def paystack_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Handle Paystack webhook events.
    Verifies signature and dispatches to service.
    """
    try:
        # Get signature and payload
        signature = request.headers.get("x-paystack-signature")
        payload = await request.body()
        
        if not signature:
            logger.warning("Paystack webhook missing signature")
            # Paystack expects 200 even if ignored, but we 400 for security
            raise HTTPException(status_code=400, detail="Missing signature")
            
        # Verify signature via service
        if not payment_service.validate_paystack_signature(payload, signature):
            logger.warning("Invalid Paystack webhook signature")
            raise HTTPException(status_code=400, detail="Invalid signature")
            
        event = json.loads(payload)
        
        # Process event
        await payment_service.process_paystack_webhook(event, db)
        
        return status.HTTP_200_OK
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing Paystack webhook: {str(e)}")
        # Return 200 to acknowledge receipt to Paystack even if interna error, 
        # to prevent retries of bad events. But mostly 500 is better for debugging.
        # Paystack retries 500s.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Webhook processing failed"
        )


@router.post("/approve-transfer")
async def approve_transfer_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Alias for /paystack/webhook to satisfy specific user requirement.
    https://yourserver.com/approve-transfer
    """
    return await paystack_webhook(request, db)


@router.post("/paystack/verify")
async def verify_paystack_payment(
    request: PaystackVerificationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Verify Paystack payment status and update subscription."""
    try:
        # Pass user_id and db to service to handle persistence
        result = await payment_service.verify_paystack_payment(
            reference=request.reference,
            db=db,
            user_id=current_user.id
        )

        if result["success"]:
            return {
                "success": True,
                "data": result
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result.get("error", "Verification failed")
            )

    except HTTPException:
        raise
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



class SubscriptionCheckoutRequest(BaseModel):
    plan_id: str
    amount: int
    currency: str = "kes"


@router.post("/stripe/create-subscription-checkout-session")
async def create_stripe_subscription_checkout_session(
    request: SubscriptionCheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a Stripe Checkout Session for subscription."""
    try:
        # Determine success and cancel URLs based on frontend environment
        frontend_url = settings.ALLOWED_ORIGINS[0] 
        success_url = f"{frontend_url}/pricing?success=true&session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{frontend_url}/pricing?canceled=true"
        
        result = await payment_service.create_subscription_checkout_session(
            plan_id=request.plan_id,
            amount=request.amount,
            currency=request.currency,
            user_email=current_user.email,
            user_id=current_user.id,
            success_url=success_url,
            cancel_url=cancel_url
        )

        if result["success"]:
            return {
                "success": True,
                "data": {
                    "checkout_url": result["checkout_url"],
                    "session_id": result["session_id"]
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
            detail=f"Checkout session creation failed: {str(e)}"
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
    """Get pricing plans with regional pricing."""
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


# ================== Workflow Purchase Endpoints ==================

class WorkflowPurchaseRequest(BaseModel):
    workflow_id: int
    payment_method: str = "stripe"  # stripe, mpesa
    phone_number: str = None  # Required for M-Pesa


class WorkflowPurchaseResponse(BaseModel):
    success: bool
    data: Dict[str, Any] = None
    message: str = None


@router.post("/workflow/purchase", response_model=WorkflowPurchaseResponse)
async def purchase_workflow(
    request: WorkflowPurchaseRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Purchase a paid workflow from the marketplace."""
    from sqlalchemy import select
    from ..models import Workflow, WorkflowDownload, Payment, Notification
    
    try:
        # Get the workflow
        result = await db.execute(
            select(Workflow).where(Workflow.id == request.workflow_id)
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found"
            )
        
        # Check if workflow is available for purchase
        if workflow.visibility not in ['public', 'marketplace']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This workflow is not available for purchase"
            )
        
        # Check if already purchased
        result = await db.execute(
            select(WorkflowDownload).where(
                WorkflowDownload.workflow_id == request.workflow_id,
                WorkflowDownload.user_id == current_user.id
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return WorkflowPurchaseResponse(
                success=True,
                message="You already own this workflow"
            )
        
        # If workflow is free, just add to downloads
        if workflow.license_type == 'free' or not workflow.price or workflow.price == 0:
            download = WorkflowDownload(
                workflow_id=workflow.id,
                user_id=current_user.id,
            )
            db.add(download)
            
            # Increment download count
            workflow.downloads_count = (workflow.downloads_count or 0) + 1
            
            # Notify the creator
            notification = Notification(
                user_id=workflow.user_id,
                notification_type="workflow_imported",
                title="New Download!",
                message=f"{current_user.name} downloaded your workflow '{workflow.name}'",
                workflow_id=workflow.id,
                actor_id=current_user.id,
                action_url="/creator-profile",
            )
            db.add(notification)
            
            await db.commit()
            
            return WorkflowPurchaseResponse(
                success=True,
                message="Workflow added to your library"
            )
        
        # Handle paid workflow
        amount = int(workflow.price)  # Price in cents
        currency = workflow.currency or "USD"
        
        if request.payment_method == "stripe":
            # Create Stripe checkout session
            try:
                checkout_session = stripe.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[{
                        'price_data': {
                            'currency': currency.lower(),
                            'product_data': {
                                'name': workflow.name,
                                'description': workflow.description or f"Workflow by {workflow.author_name}",
                            },
                            'unit_amount': amount,
                        },
                        'quantity': 1,
                    }],
                    mode='payment',
                    success_url=f"{settings.FRONTEND_URL}/marketplace?purchase=success&workflow_id={workflow.id}",
                    cancel_url=f"{settings.FRONTEND_URL}/marketplace?purchase=cancelled",
                    metadata={
                        'workflow_id': str(workflow.id),
                        'user_id': str(current_user.id),
                        'type': 'workflow_purchase'
                    }
                )
                
                # Create pending payment record
                payment = Payment(
                    user_id=current_user.id,
                    payment_method="stripe",
                    amount=amount,
                    currency=currency,
                    status="pending",
                    transaction_id=checkout_session.id,
                    payment_metadata={
                        'workflow_id': workflow.id,
                        'type': 'workflow_purchase'
                    }
                )
                db.add(payment)
                await db.commit()
                
                return WorkflowPurchaseResponse(
                    success=True,
                    data={
                        'checkout_url': checkout_session.url,
                        'session_id': checkout_session.id
                    },
                    message="Redirecting to payment..."
                )
            except stripe.error.StripeError as e:
                logger.error(f"Stripe error: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Payment error: {str(e)}"
                )
        
        elif request.payment_method == "mpesa":
            if not request.phone_number:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Phone number required for M-Pesa payment"
                )
            
            # Convert to KES if needed (assuming 1 USD = 150 KES for simplicity)
            if currency.upper() == "USD":
                amount_kes = amount * 150 // 100  # Convert cents to KES
            else:
                amount_kes = amount // 100  # Convert cents to base unit
            
            result = await payment_service.initiate_mpesa_payment(
                phone_number=request.phone_number,
                amount=amount_kes,
                reference=f"WF-{workflow.id}-{current_user.id}",
                description=f"Purchase: {workflow.name}"
            )
            
            if result["success"]:
                # Create pending payment record
                payment = Payment(
                    user_id=current_user.id,
                    payment_method="mpesa",
                    amount=amount_kes * 100,  # Store in cents equivalent
                    currency="KES",
                    status="pending",
                    transaction_id=result["checkout_request_id"],
                    payment_metadata={
                        'workflow_id': workflow.id,
                        'type': 'workflow_purchase',
                        'merchant_request_id': result.get("merchant_request_id")
                    }
                )
                db.add(payment)
                await db.commit()
                
                return WorkflowPurchaseResponse(
                    success=True,
                    data={
                        'checkout_request_id': result["checkout_request_id"],
                        'message': result["message"]
                    },
                    message="M-Pesa payment initiated. Please check your phone."
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=result.get("error", "M-Pesa payment failed")
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payment method"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Purchase error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process purchase: {str(e)}"
        )


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Stripe webhook events."""
    from sqlalchemy import select
    from ..models import Payment, Workflow, WorkflowDownload, Notification, CreatorProfile
    
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        metadata = session.get('metadata', {})
        
        if metadata.get('type') == 'workflow_purchase':
            workflow_id = int(metadata.get('workflow_id'))
            user_id = int(metadata.get('user_id'))
            
            # Update payment status
            result = await db.execute(
                select(Payment).where(Payment.transaction_id == session['id'])
            )
            payment = result.scalar_one_or_none()
            if payment:
                payment.status = "completed"
            
            # Get the workflow
            result = await db.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()
            
            if workflow:
                # Add to user's downloads
                download = WorkflowDownload(
                    workflow_id=workflow_id,
                    user_id=user_id,
                )
                db.add(download)
                
                # Increment download count
                workflow.downloads_count = (workflow.downloads_count or 0) + 1
                
                # Get buyer info
                result = await db.execute(
                    select(User).where(User.id == user_id)
                )
                buyer = result.scalar_one_or_none()
                
                # Notify the creator
                notification = Notification(
                    user_id=workflow.user_id,
                    notification_type="earnings_received",
                    title="New Sale! 💰",
                    message=f"{buyer.name if buyer else 'Someone'} purchased your workflow '{workflow.name}'",
                    workflow_id=workflow.id,
                    actor_id=user_id,
                    action_url="/creator-profile",
                    metadata={'amount': session.get('amount_total'), 'currency': session.get('currency')}
                )
                db.add(notification)
                
                # Update creator earnings
                result = await db.execute(
                    select(CreatorProfile).where(CreatorProfile.user_id == workflow.user_id)
                )
                creator_profile = result.scalar_one_or_none()
                if creator_profile:
                    amount = (session.get('amount_total') or 0) / 100  # Convert from cents
                    creator_profile.total_earnings = (creator_profile.total_earnings or 0) + amount
                
                await db.commit()
    
    return {"status": "success"}


@router.get("/my-purchases")
async def get_my_purchases(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get list of workflows purchased by the current user."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from ..models import WorkflowDownload
    
    result = await db.execute(
        select(WorkflowDownload)
        .options(selectinload(WorkflowDownload.workflow))
        .where(WorkflowDownload.user_id == current_user.id)
        .order_by(WorkflowDownload.downloaded_at.desc())
    )
    downloads = result.scalars().all()
    
    data = [
        {
            "id": d.id,
            "workflow_id": d.workflow_id,
            "workflow_name": d.workflow.name if d.workflow else None,
            "workflow_description": d.workflow.description if d.workflow else None,
            "downloaded_at": d.downloaded_at.isoformat() if d.downloaded_at else None,
        }
        for d in downloads
    ]
    
    return {"success": True, "data": data}


@router.get("/creator/earnings")
async def get_creator_earnings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get earnings summary for a creator."""
    from sqlalchemy import select, func
    from ..models import Payment, Workflow, CreatorProfile
    
    # Get creator profile
    result = await db.execute(
        select(CreatorProfile).where(CreatorProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    
    if not profile:
        return {
            "success": True,
            "data": {
                "total_earnings": 0,
                "pending_earnings": 0,
                "this_month": 0,
                "transactions": []
            }
        }
    
    # Get user's workflow IDs
    result = await db.execute(
        select(Workflow.id).where(Workflow.user_id == current_user.id)
    )
    workflow_ids = [row[0] for row in result.all()]
    
    # Get completed payments for user's workflows
    from datetime import datetime, timedelta
    start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    result = await db.execute(
        select(Payment)
        .where(
            Payment.status == "completed",
            Payment.payment_metadata['workflow_id'].astext.in_([str(wid) for wid in workflow_ids])
        )
        .order_by(Payment.created_at.desc())
        .limit(20)
    )
    payments = result.scalars().all()
    
    # Calculate this month's earnings
    this_month_total = sum(
        (p.amount or 0) / 100 for p in payments 
        if p.created_at and p.created_at >= start_of_month
    )
    
    return {
        "success": True,
        "data": {
            "total_earnings": float(profile.total_earnings or 0),
            "pending_earnings": 0,  # Could track pending payouts
            "this_month": this_month_total,
            "transactions": [
                {
                    "id": p.id,
                    "amount": (p.amount or 0) / 100,
                    "currency": p.currency,
                    "status": p.status,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in payments
            ]
        }
    }


# ========================================
# SUBSCRIPTION MANAGEMENT ENDPOINTS
# ========================================

class CancelSubscriptionRequest(BaseModel):
    reason: str = None
    feedback: str = None


@router.post("/subscriptions/cancel")
async def cancel_subscription(
    request: CancelSubscriptionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Cancel user's subscription.
    Access is retained until the end of the current billing period.
    """
    try:
        from datetime import datetime
        from sqlalchemy import update
        from ..models import SubscriptionStatus
        
        # Check if user has an active subscription
        if current_user.subscription_tier == "free":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You don't have an active subscription to cancel"
            )
        
        if current_user.subscription_status == SubscriptionStatus.CANCELED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your subscription is already canceled"
            )
        
        # Update subscription status to canceled        
        stmt = update(User).where(User.id == current_user.id).values(
            subscription_status=SubscriptionStatus.CANCELED,
            updated_at=datetime.utcnow()
        )
        await db.execute(stmt)
        await db.commit()
        
        # Log cancellation reason (could store in a separate table or field)
        logger.info(f"User {current_user.id} canceled subscription. Reason: {request.reason}")
        
        # TODO: Send cancellation confirmation email
        
        return {
            "success": True,
            "message": f"Subscription canceled. You'll retain access until {current_user.subscription_end_date.strftime('%B %d, %Y') if current_user.subscription_end_date else 'end of billing period'}",
            "access_until": current_user.subscription_end_date.isoformat() if current_user.subscription_end_date else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error canceling subscription: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel subscription: {str(e)}"
        )


@router.post("/subscriptions/reactivate")
async def reactivate_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Reactivate a canceled subscription before the end date.
    """
    try:
        from datetime import datetime
        from sqlalchemy import update
        from ..models import SubscriptionStatus
        
        # Check if subscription is canceled
        if current_user.subscription_status != SubscriptionStatus.CANCELED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your subscription is not canceled"
            )
        
        # Check if subscription end date has passed
        if current_user.subscription_end_date and current_user.subscription_end_date < datetime.now(current_user.subscription_end_date.tzinfo):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your subscription has already expired. Please upgrade to reactivate."
            )
        
        # Reactivate subscription
        stmt = update(User).where(User.id == current_user.id).values(
            subscription_status=SubscriptionStatus.ACTIVE,
            updated_at=datetime.utcnow()
        )
        await db.execute(stmt)
        await db.commit()
        
        logger.info(f"User {current_user.id} reactivated subscription")
        
        # TODO: Send reactivation confirmation email
        
        return {
            "success": True,
            "message": "Subscription reactivated successfully",
            "next_billing_date": current_user.subscription_end_date.isoformat() if current_user.subscription_end_date else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reactivating subscription: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reactivate subscription: {str(e)}"
        )