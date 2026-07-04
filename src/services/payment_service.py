"""
Payment service for Mini-Hub with M-Pesa and Stripe integration.
"""

import base64
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import uuid

import requests
import stripe
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import logging
from ..config import settings
from ..models import Payment, User, SubscriptionStatus  # Make sure User and SubscriptionStatus are imported

logger = logging.getLogger(__name__)

class PaymentService:
    def __init__(self):
        # Stripe configuration
        self.stripe = stripe
        self.stripe.api_key = settings.STRIPE_SECRET_KEY

        # M-Pesa configuration
        self.mpesa_consumer_key = settings.MPESA_CONSUMER_KEY
        self.mpesa_consumer_secret = settings.MPESA_CONSUMER_SECRET
        self.mpesa_passkey = settings.MPESA_PASSKEY
        self.mpesa_shortcode = settings.MPESA_BUSINESS_SHORT_CODE
        self.mpesa_callback_url = settings.MPESA_CALLBACK_URL

        # Paystack configuration
        self.paystack_secret_key = settings.PAYSTACK_SECRET_KEY
        self.paystack_public_key = settings.PAYSTACK_PUBLIC_KEY
        self.paystack_base_url = "https://api.paystack.co"

        # Only log M-Pesa config if credentials are provided
        if self.mpesa_consumer_key:
            key = self.mpesa_consumer_key[:10]
            print(f"M-Pesa Consumer Key: {key}...")
        if self.mpesa_consumer_secret:
            secret = self.mpesa_consumer_secret[:10]
            print(f"M-Pesa Consumer Secret: {secret}...")
        if self.mpesa_passkey:
            passkey = self.mpesa_passkey[:10]
            print(f"M-Pesa Passkey: {passkey}...")
        if self.mpesa_shortcode:
            print(f"M-Pesa Short Code: {self.mpesa_shortcode}")
        if self.mpesa_callback_url:
            print(f"M-Pesa Callback URL: {self.mpesa_callback_url}")

        if not self.mpesa_consumer_key:
            print("M-Pesa not configured - payment features disabled")

        # Base URLs - use environment setting
        if settings.MPESA_ENVIRONMENT == "live":
            self.mpesa_base_url = "https://api.safaricom.co.ke"
        else:
            self.mpesa_base_url = "https://sandbox.safaricom.co.ke"

        self.access_token = None
        self.token_expiry = None

    def _format_phone_number(self, phone_number: str) -> str:
        """Format phone number for M-Pesa API (international format 254...)."""
        # Remove all non-digit characters
        cleaned = re.sub(r'\D', '', phone_number)

        # Handle different formats
        if cleaned.startswith('254'):
            return cleaned
        elif cleaned.startswith('0'):
            return '254' + cleaned[1:]
        elif cleaned.startswith('7'):
            return '254' + cleaned
        elif len(cleaned) == 9:
            return '254' + cleaned
        else:
            raise ValueError(f"Invalid phone number format: {phone_number}")

    def _format_phone_local(self, phone_number: str) -> str:
        """
        Format phone number to LOCAL Kenyan format (07XXXXXXXX or 01XXXXXXXX).
        Required by Paystack for mobile_money transfers.
        """
        # Remove all non-digit characters
        cleaned = re.sub(r'\D', '', phone_number)
        
        # Convert to local format
        if cleaned.startswith('254'):
            # 254711371265 -> 0711371265
            return '0' + cleaned[3:]
        elif cleaned.startswith('0'):
            # Already local format
            return cleaned
        elif cleaned.startswith('7') or cleaned.startswith('1'):
            # 711371265 -> 0711371265
            return '0' + cleaned
        else:
            raise ValueError(f"Invalid phone number format: {phone_number}")

    async def get_mpesa_access_token(self) -> str:
        """Get M-Pesa access token."""
        if (self.access_token and self.token_expiry and
                datetime.now() < self.token_expiry):
            return self.access_token

        # Check if credentials are configured
        if not self.mpesa_consumer_key or not self.mpesa_consumer_secret:
            raise HTTPException(
                status_code=500,
                detail="M-Pesa credentials not configured. Please set "
                       "MPESA_CONSUMER_KEY and MPESA_CONSUMER_SECRET"
            )

        url = (f"{self.mpesa_base_url}/oauth/v1/generate?"
               f"grant_type=client_credentials")

        # Create proper Basic Auth header
        credentials = f"{self.mpesa_consumer_key}:{self.mpesa_consumer_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Authorization": f"Basic {encoded_credentials}"
        }

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            self.access_token = data["access_token"]
            self.token_expiry = datetime.now() + timedelta(hours=1)

            return self.access_token
        except requests.exceptions.RequestException as e:
            raise HTTPException(
                status_code=500,
                detail=f"M-Pesa token error: {str(e)}"
            )

    async def initiate_mpesa_payment(
        self,
        phone_number: str,
        amount: int,
        reference: str,
        description: str = "Mini-Hub Payment"
    ) -> Dict[str, Any]:
        """Initiate M-Pesa STK push payment."""
        try:
            # Validate and format phone number
            formatted_phone = self._format_phone_number(phone_number)
            print(f"Original phone: {phone_number}, "
                  f"Formatted: {formatted_phone}")

            # Validate amount
            if amount < 1:
                return {
                    "success": False,
                    "error": "Amount must be at least 1 KES"
                }

            # Check callback URL
            if not self.mpesa_callback_url:
                return {
                    "success": False,
                    "error": "M-Pesa callback URL not configured"
                }

            access_token = await self.get_mpesa_access_token()

            print(f"Access Token: {access_token}")

            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            # password = self.mpesa_shortcode + self.mpesa_passkey + timestamp
            # password_hash = hashlib.sha256(password.encode()).hexdigest()
            password_string = f"{self.mpesa_shortcode}{self.mpesa_passkey}{timestamp}"
            import base64
            password_hash = base64.b64encode(password_string.encode()).decode()

            url = f"{self.mpesa_base_url}/mpesa/stkpush/v1/processrequest"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            payload = {
                "BusinessShortCode": self.mpesa_shortcode,
                "Password": password_hash,
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": amount,
                "PartyA": formatted_phone,
                "PartyB": self.mpesa_shortcode,
                "PhoneNumber": formatted_phone,
                "CallBackURL": self.mpesa_callback_url,
                "AccountReference": reference,
                "TransactionDesc": description
            }

            print(f"M-Pesa API URL: {url}")
            safe_payload = payload.copy()
            safe_payload["Password"] = "***MASKED***"
            print(f"M-Pesa Payload: {safe_payload}")

            response = requests.post(url, json=payload, headers=headers)

            print(f"M-Pesa Response Status: {response.status_code}")
            print(f"M-Pesa Response Headers: {dict(response.headers)}")
            print(f"M-Pesa Response Body: {response.text}")

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"M-Pesa API error: {response.status_code} - "
                    f"{response.text}"
                }

            result = response.json()

            if result.get("ResponseCode") == "0":
                return {
                    "success": True,
                    "checkout_request_id": result["CheckoutRequestID"],
                    "merchant_request_id": result["MerchantRequestID"],
                    "message": "Payment initiated successfully"
                }
            else:
                return {
                    "success": False,
                    "error": result.get("ResponseDescription",
                                        "Payment failed")
                }

        except ValueError as e:
            return {
                "success": False,
                "error": f"Phone number error: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"M-Pesa payment error: {str(e)}"
            }

    async def process_mpesa_subscription(
        self,
        phone_number: str,
        amount: int,
        user_id: uuid.UUID,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Process M-Pesa subscription payment and extend validity."""
        try:
            from sqlalchemy import select
            from ..models import User, SubscriptionStatus
            
            # Find user
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            
            if not user:
                return {"success": False, "error": "User not found"}
                
            # Calculate new end date
            # If currently active and not expired, add to existing end date
            # If expired or none, start from today
            now = datetime.now()
            days_to_add = 30 # Default monthly
            
            if user.subscription_end_date and user.subscription_end_date > now:
                user.subscription_end_date += timedelta(days=days_to_add)
            else:
                user.subscription_end_date = now + timedelta(days=days_to_add)
            
            user.subscription_status = SubscriptionStatus.ACTIVE
            
            # Update tier based on amount (Hardcoded logic for now, ideally strictly coupled with plans)
            if amount >= 5000:
                user.subscription_tier = "pro"
            elif amount >= 1500:
                user.subscription_tier = "starter"
                
            await db.commit()
            
            return {
                "success": True, 
                "new_end_date": user.subscription_end_date,
                "tier": user.subscription_tier
            }
            
        except Exception as e:
            return {"success": False, "error": f"Failed to process subscription: {str(e)}"}

    async def create_stripe_customer(self, email: str, name: str) -> Dict[str, Any]:
        """Create a Stripe customer."""
        try:
            customer = self.stripe.Customer.create(
                email=email,
                name=name,
                metadata={"source": "mini-hub"}
            )
            return {
                "success": True,
                "customer_id": customer.id
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Stripe customer creation failed: {str(e)}"
            }

    async def create_stripe_subscription(
        self,
        customer_id: str,
        price_id: str
    ) -> Dict[str, Any]:
        """Create a Stripe subscription."""
        try:
            subscription = self.stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                payment_behavior="default_incomplete",
                expand=["latest_invoice.payment_intent"]
            )
            return {
                "success": True,
                "subscription_id": subscription.id,
                "client_secret": subscription.latest_invoice.payment_intent.client_secret
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Stripe subscription creation failed: {str(e)}"
            }

    async def create_subscription_checkout_session(
        self,
        plan_id: str,
        amount: int,
        currency: str,
        user_email: str,
        user_id: uuid.UUID,
        success_url: str,
        cancel_url: str
    ) -> Dict[str, Any]:
        """Create a Stripe Checkout Session for subscription."""
        try:
            # Create a price object for the subscription
            # In a real app, you might use pre-defined Price IDs from Stripe
            # Here we use ad-hoc prices for flexibility
            
            checkout_session = self.stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': currency.lower(),
                        'product_data': {
                            'name': f"{plan_id.title()} Subscription",
                            'description': f"Monthly subscription for {plan_id.title()} plan",
                        },
                        'unit_amount': amount * 100, # Stripe expects cents
                        'recurring': {
                            'interval': 'month',
                        },
                    },
                    'quantity': 1,
                }],
                mode='subscription',
                customer_email=user_email,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    'plan_id': plan_id,
                    'user_id': str(user_id),
                    'type': 'subscription_upgrade'
                }
            )
            
            return {
                "success": True,
                "checkout_url": checkout_session.url,
                "session_id": checkout_session.id
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Stripe checkout session failed: {str(e)}"
            }

    async def create_stripe_payment_intent(
        self,
        amount: int,
        currency: str = "kes",
        customer_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a Stripe payment intent."""
        try:
            intent_data = {
                "amount": amount,
                "currency": currency,
                "metadata": {"source": "mini-hub"}
            }

            if customer_id:
                intent_data["customer"] = customer_id

            payment_intent = self.stripe.PaymentIntent.create(**intent_data)

            return {
                "success": True,
                "payment_intent_id": payment_intent.id,
                "client_secret": payment_intent.client_secret,
                "amount": amount
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Stripe payment intent creation failed: {str(e)}"
            }

    async def verify_mpesa_payment(self, checkout_request_id: str) -> Dict[str, Any]:
        """Verify M-Pesa payment status."""
        try:
            access_token = await self.get_mpesa_access_token()

            url = f"{self.mpesa_base_url}/mpesa/stkpushquery/v1/query"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            # password = self.mpesa_shortcode + self.mpesa_passkey + timestamp
            # password_hash = hashlib.sha256(password.encode()).hexdigest()
            password_string = f"{self.mpesa_shortcode}{self.mpesa_passkey}{timestamp}"
            import base64
            password_hash = base64.b64encode(password_string.encode()).decode()

            payload = {
                "BusinessShortCode": self.mpesa_shortcode,
                "Password": password_hash,
                "Timestamp": timestamp,
                "CheckoutRequestID": checkout_request_id
            }

            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()

            result = response.json()

            if result.get("ResponseCode") == "0":
                return {
                    "success": True,
                    "status": "completed",
                    "transaction_id": result.get("TransactionID"),
                    "amount": result.get("Amount"),
                    "phone_number": result.get("PhoneNumber")
                }
            else:
                return {
                    "success": False,
                    "status": "failed",
                    "error": result.get("ResponseDescription",
                                        "Payment verification failed")
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Payment verification error: {str(e)}"
            }

    async def _activate_paystack_charge(
        self,
        user,
        data: Dict[str, Any],
        reference: str,
        amount_kes: float,
        metadata: Dict[str, Any],
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Shared activation path for verify API and charge.success webhook."""
        from .subscription_service import PaymentActivationData, subscription_service

        plan_id, billing_cycle = subscription_service.resolve_plan_from_paystack_metadata(
            metadata, amount_kes
        )
        if not plan_id:
            logger.warning(
                "[PAYSTACK] Could not resolve plan for user %s amount=%s metadata=%s",
                user.id,
                amount_kes,
                metadata,
            )
            return {"success": False, "error": "Could not determine subscription plan"}

        customer = data.get("customer", {}) or {}
        authorization = data.get("authorization", {}) or {}
        auth_code = None
        if authorization.get("reusable") and authorization.get("authorization_code"):
            auth_code = authorization["authorization_code"]

        payment_data = PaymentActivationData(
            transaction_id=str(data.get("id")),
            reference=reference,
            amount_kes=amount_kes,
            currency=data.get("currency", "KES"),
            plan_id=plan_id,
            billing_cycle=billing_cycle,
            metadata=metadata,
            paystack_customer_code=customer.get("customer_code"),
            paystack_authorization_code=auth_code,
        )
        return await subscription_service.activate_from_payment(
            user, plan_id, billing_cycle, payment_data, db
        )

    async def verify_paystack_payment(
        self,
        reference: str,
        db: Optional[AsyncSession] = None,
        user_id: Optional[uuid.UUID] = None
    ) -> Dict[str, Any]:
        """
        Verify Paystack payment and update user subscription.
        
        Args:
            reference: Paystack transaction reference
            db: Database session for persistence
            user_id: ID of the user who made the payment
            
        Returns:
            Dict with success status and payment details
        """
        logger.info(f"[PAYSTACK] Starting verification for reference: {reference}, user_id: {user_id}")
        
        try:
            # Validate configuration
            if not self.paystack_secret_key:
                logger.error("[PAYSTACK] Secret key not configured")
                return {"success": False, "error": "Paystack not configured"}

            # Call Paystack API to verify
            url = f"{self.paystack_base_url}/transaction/verify/{reference}"
            headers = {"Authorization": f"Bearer {self.paystack_secret_key}"}
            
            logger.info(f"[PAYSTACK] Calling API: {url}")
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"[PAYSTACK] API returned status {response.status_code}: {response.text}")
                return {"success": False, "error": f"Paystack API error: {response.status_code}"}

            result = response.json()
            logger.info(f"[PAYSTACK] API response status: {result.get('status')}, data.status: {result.get('data', {}).get('status')}")

            # Check if payment was successful
            if not (result.get("status") and result.get("data", {}).get("status") == "success"):
                error_msg = result.get("message", "Payment verification failed")
                logger.error(f"[PAYSTACK] Verification failed: {error_msg}")
                return {"success": False, "status": "failed", "error": error_msg}

            # Payment verified successfully
            data = result["data"]
            amount_kobo = data.get("amount", 0)
            amount_kes = amount_kobo / 100  # Convert from kobo to KES
            metadata = data.get("metadata") or {}
            
            logger.info(f"[PAYSTACK] Payment verified: amount={amount_kes} KES, metadata={metadata}")

            # Persist to database if session provided
            if db and user_id:
                from sqlalchemy import select
                from ..models import User
                from .subscription_service import (
                    PaymentActivationData,
                    subscription_service,
                )

                user_result = await db.execute(select(User).where(User.id == user_id))
                user = user_result.scalar_one_or_none()
                if not user:
                    return {"success": False, "error": "User not found"}

                activation_result = await self._activate_paystack_charge(
                    user=user,
                    data=data,
                    reference=reference,
                    amount_kes=amount_kes,
                    metadata=metadata,
                    db=db,
                )
                if not activation_result.get("success"):
                    return activation_result

                sub = activation_result.get("subscription", {})
                return {
                    "success": True,
                    "status": "completed",
                    "transaction_id": str(data.get("id")),
                    "reference": reference,
                    "amount": amount_kobo,
                    "amount_kes": amount_kes,
                    "currency": data.get("currency"),
                    "customer_email": data.get("customer", {}).get("email"),
                    "plan": sub.get("tier") or metadata.get("plan_id"),
                    "subscription": sub,
                }

            return {
                "success": True,
                "status": "completed",
                "transaction_id": str(data.get("id")),
                "reference": reference,
                "amount": amount_kobo,
                "amount_kes": amount_kes,
                "currency": data.get("currency"),
                "customer_email": data.get("customer", {}).get("email"),
                "plan": metadata.get("plan_id"),
            }

        except requests.exceptions.Timeout:
            logger.error(f"[PAYSTACK] Request timeout for reference: {reference}")
            return {"success": False, "error": "Payment verification timed out"}
        except requests.exceptions.RequestException as e:
            logger.error(f"[PAYSTACK] Request error: {str(e)}")
            return {"success": False, "error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.error(f"[PAYSTACK] Unexpected error: {str(e)}", exc_info=True)
            return {"success": False, "error": f"Verification error: {str(e)}"}

    # Stripe Webhook Handlers
    async def handle_payment_intent_succeeded(
        self,
        event: Dict[str, Any],
        db: AsyncSession
    ) -> None:
        """Handle successful payment intent."""
        payment_intent = event['data']['object']

        # Create or update payment record
        payment = Payment(
            payment_method="stripe",
            amount=payment_intent['amount'],
            currency=payment_intent['currency'],
            status="completed",
            transaction_id=payment_intent['id'],
            payment_metadata={
                'customer_id': payment_intent.get('customer'),
                'payment_method': payment_intent.get('payment_method'),
                'receipt_url': payment_intent.get('charges', {}).get('data', [{}])[0].get('receipt_url')
            }
        )

        db.add(payment)
        await db.commit()

    async def handle_payment_intent_failed(
        self,
        event: Dict[str, Any],
        db: AsyncSession
    ) -> None:
        """Handle failed payment intent."""
        payment_intent = event['data']['object']

        # Create or update payment record
        payment = Payment(
            payment_method="stripe",
            amount=payment_intent['amount'],
            currency=payment_intent['currency'],
            status="failed",
            transaction_id=payment_intent['id'],
            payment_metadata={
                'customer_id': payment_intent.get('customer'),
                'last_payment_error': payment_intent.get('last_payment_error', {})
            }
        )

        db.add(payment)
        await db.commit()

    async def handle_invoice_payment_succeeded(
        self,
        event: Dict[str, Any],
        db: AsyncSession
    ) -> None:
        """Handle successful invoice payment."""
        invoice = event['data']['object']

        # Update subscription status
        subscription_id = invoice.get('subscription')
        
        # Sync with user's subscription end date if it's a subscription invoice
        if subscription_id:
             # Fetch subscription details from Stripe to get current_period_end
            try:
                subscription = self.stripe.Subscription.retrieve(subscription_id)
                current_period_end = datetime.fromtimestamp(subscription.current_period_end)
                
                # Find user by customer ID
                customer_id = invoice.get('customer')
                from sqlalchemy import select
                from ..models import User, SubscriptionStatus
                
                result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
                user = result.scalar_one_or_none()
                
                if user:
                    user.subscription_end_date = current_period_end
                    user.subscription_status = SubscriptionStatus.ACTIVE
                    # Optionally update tier based on plan product ID if needed
                    # user.subscription_tier = ... 
                    
            except Exception as e:
                print(f"Error syncing subscription date: {e}")

        # Create payment record
        payment = Payment(
            payment_method="stripe",
            amount=invoice['amount_paid'],
            currency=invoice['currency'],
            status="completed",
            transaction_id=invoice['id'],
            payment_metadata={
                'customer_id': invoice.get('customer'),
                'subscription_id': subscription_id,
                'invoice_url': invoice.get('hosted_invoice_url')
            }
        )

        db.add(payment)
        await db.commit()

    async def handle_invoice_payment_failed(
        self,
        event: Dict[str, Any],
        db: AsyncSession
    ) -> None:
        """Handle failed invoice payment."""
        invoice = event['data']['object']

        # Update subscription status
        subscription_id = invoice.get('subscription')

        # Create payment record
        payment = Payment(
            payment_method="stripe",
            amount=invoice['amount_due'],
            currency=invoice['currency'],
            status="failed",
            transaction_id=invoice['id'],
            payment_metadata={
                'customer_id': invoice.get('customer'),
                'subscription_id': subscription_id,
                'attempt_count': invoice.get('attempt_count', 0)
            }
        )

        db.add(payment)
        await db.commit()

    async def handle_subscription_created(
        self,
        event: Dict[str, Any],
        db: AsyncSession
    ) -> None:
        """Handle subscription creation."""
        subscription = event['data']['object']
        # Add subscription logic here

    async def handle_subscription_updated(
        self,
        event: Dict[str, Any],
        db: AsyncSession
    ) -> None:
        """Handle subscription updates."""
        subscription = event['data']['object']
        # Add subscription update logic here

    async def handle_subscription_deleted(
        self,
        event: Dict[str, Any],
        db: AsyncSession
    ) -> None:
        """Handle subscription deletion."""
        subscription = event['data']['object']
        # Add subscription deletion logic here

    async def process_stripe_webhook(
        self,
        event: Dict[str, Any],
        db: AsyncSession
    ) -> None:
        """Process Stripe webhook events."""
        event_type = event['type']

        if event_type == 'payment_intent.succeeded':
            await self.handle_payment_intent_succeeded(event, db)
        elif event_type == 'payment_intent.payment_failed':
            await self.handle_payment_intent_failed(event, db)
        elif event_type == 'invoice.payment_succeeded':
            await self.handle_invoice_payment_succeeded(event, db)
        elif event_type == 'invoice.payment_failed':
            await self.handle_invoice_payment_failed(event, db)
        elif event_type == 'customer.subscription.created':
            await self.handle_subscription_created(event, db)
        elif event_type == 'customer.subscription.updated':
            await self.handle_subscription_updated(event, db)
        elif event_type == 'customer.subscription.deleted':
            await self.handle_subscription_deleted(event, db)

    async def process_kenyan_payment(
        self,
        provider: str,
        phone_number: str,
        amount: int,
        operation: str = "initiate_payment",
        transaction_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Process payments for Kenyan Fintech providers (Airtel, T-Kash, Equity, etc.)."""
        # Mock logic for new providers - in production, this would call provider-specific APIs
        # provider is one of airtel_money, t_kash, equity_jenga, etc.
        
        provider_name = provider.replace("_", " ").title()
        
        if operation == "initiate_payment":
            return {
                "success": True,
                "provider": provider,
                "transaction_id": f"{provider[:2].upper()}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "message": f"Payment of {amount} KES initiated via {provider_name}"
            }
        elif operation == "query_status":
            return {
                "success": True,
                "provider": provider,
                "status": "completed",
                "transaction_id": transaction_id,
                "message": f"Status query for {transaction_id} on {provider_name} returned: COMPLETED"
            }
        elif operation == "fetch_payouts":
            return {
                "success": True,
                "provider": provider,
                "payouts": [
                    {"id": "P1", "amount": 1200, "date": "2024-01-10"},
                    {"id": "P2", "amount": 5500, "date": "2024-01-11"}
                ]
            }
        else:
            return {"success": False, "error": f"Unsupported operation: {operation}"}

    async def initialize_paystack_transaction(
        self,
        email: str,
        amount_kes: float,
        metadata: Dict[str, Any],
        callback_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Initialize a Paystack transaction for premium link purchases.
        
        Args:
            email: Customer email (required by Paystack)
            amount_kes: Amount in KES (will be converted to kobo for Paystack)
            metadata: Transaction metadata (link_id, creator_profile_id, etc.)
            callback_url: URL to redirect after payment
            
        Returns:
            Dict with authorization_url to redirect user to Paystack checkout
        """
        logger.info(f"[PAYSTACK] Initializing transaction for {email}, amount={amount_kes} KES")
        
        if not self.paystack_secret_key:
            logger.error("[PAYSTACK] Secret key not configured")
            return {"success": False, "error": "Paystack not configured"}
        
        try:
            url = f"{self.paystack_base_url}/transaction/initialize"
            headers = {
                "Authorization": f"Bearer {self.paystack_secret_key}",
                "Content-Type": "application/json"
            }
            
            # Paystack expects amount in kobo (smallest currency unit)
            # For KES: 1 KES = 100 kobo equivalent
            amount_kobo = int(amount_kes * 100)
            
            payload = {
                "email": email,
                "amount": amount_kobo,
                "currency": "KES",
                "metadata": metadata,
                "channels": ["mobile_money", "card"]  # Enable M-Pesa
            }
            
            if callback_url:
                payload["callback_url"] = callback_url
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"[PAYSTACK] Init failed: {response.text}")
                return {"success": False, "error": f"Paystack error: {response.status_code}"}
            
            result = response.json()
            
            if result.get("status"):
                data = result.get("data", {})
                logger.info(f"[PAYSTACK] Transaction initialized: ref={data.get('reference')}")
                return {
                    "success": True,
                    "authorization_url": data.get("authorization_url"),
                    "access_code": data.get("access_code"),
                    "reference": data.get("reference")
                }
            else:
                return {"success": False, "error": result.get("message", "Initialization failed")}
                
        except requests.exceptions.RequestException as e:
            logger.error(f"[PAYSTACK] Network error: {str(e)}")
            return {"success": False, "error": f"Network error: {str(e)}"}
        except Exception as e:
            logger.error(f"[PAYSTACK] Unexpected error: {str(e)}")
            return {"success": False, "error": f"Error: {str(e)}"}

    def calculate_revenue_split(
        self,
        gross_amount: float,
        platform_fee_percent: float = 10.0
    ) -> Dict[str, float]:
        """
        Calculate the revenue split between platform and creator.
        
        Args:
            gross_amount: Total amount paid by fan (KES)
            platform_fee_percent: Platform's cut (default 10%)
            
        Returns:
            Dict with platform_fee and creator_amount
        """
        from decimal import Decimal, ROUND_HALF_UP
        
        gross = Decimal(str(gross_amount))
        fee_percent = Decimal(str(platform_fee_percent)) / Decimal("100")
        
        platform_fee = (gross * fee_percent).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        creator_amount = (gross - platform_fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        return {
            "gross_amount": float(gross),
            "platform_fee": float(platform_fee),
            "creator_amount": float(creator_amount),
            "platform_fee_percent": platform_fee_percent
        }

    async def create_paystack_transfer_recipient(
        self,
        name: str,
        phone_number: str,
        bank_code: str = "MPESA"  # For M-Pesa mobile money
    ) -> Dict[str, Any]:
        """
        Create a transfer recipient for Paystack (M-Pesa number).
        
        Args:
            name: Recipient's name
            phone_number: M-Pesa number (will be formatted)
            bank_code: "MPESA" for Safaricom M-Pesa
            
        Returns:
            Dict with recipient_code if successful
        """
        try:
            # Format phone for Paystack - must be LOCAL Kenyan format (07XXXXXXXX)
            # Paystack mobile_money requires local format, NOT international (254...)
            formatted_phone = self._format_phone_local(phone_number)
            
            # Validate Kenya phone number length (10 digits starting with 0)
            if len(formatted_phone) != 10 or not formatted_phone.startswith('0'):
                return {"success": False, "error": f"Invalid phone number format: {formatted_phone}. Expected 07XXXXXXXX or 01XXXXXXXX"}
            
            url = f"{self.paystack_base_url}/transferrecipient"
            headers = {
                "Authorization": f"Bearer {self.paystack_secret_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "type": "mobile_money",
                "name": name,
                "account_number": formatted_phone,
                "bank_code": bank_code,  # "MPESA" for Safaricom
                "currency": "KES"
            }
            
            logger.info(f"[PAYSTACK] Creating transfer recipient: phone={formatted_phone}, name={name}, bank_code={bank_code}")
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            result = response.json()
            
            logger.info(f"[PAYSTACK] Transfer recipient response: {result}")
            
            if result.get("status"):
                data = result.get("data", {})
                logger.info(f"[PAYSTACK] Created transfer recipient: {data.get('recipient_code')}")
                return {
                    "success": True,
                    "recipient_code": data.get("recipient_code"),
                    "details": data
                }
            else:
                error_msg = result.get("message", "Failed to create recipient")
                logger.error(f"[PAYSTACK] Failed to create recipient: {error_msg}, full response: {result}")
                return {"success": False, "error": error_msg}
                
        except Exception as e:
            logger.error(f"[PAYSTACK] Error creating recipient: {str(e)}")
            return {"success": False, "error": str(e)}

    async def initiate_paystack_transfer(
        self,
        amount_kes: float,
        recipient_code: str,
        reason: str = "Creator Withdrawal"
    ) -> Dict[str, Any]:
        """
        Initiate a Paystack transfer to send funds to M-Pesa.
        
        Args:
            amount_kes: Amount in KES
            recipient_code: Recipient code from create_paystack_transfer_recipient
            reason: Transfer description
            
        Returns:
            Dict with transfer_code and status
        """
        try:
            url = f"{self.paystack_base_url}/transfer"
            headers = {
                "Authorization": f"Bearer {self.paystack_secret_key}",
                "Content-Type": "application/json"
            }
            
            # Amount in kobo
            amount_kobo = int(amount_kes * 100)
            
            payload = {
                "source": "balance",
                "amount": amount_kobo,
                "recipient": recipient_code,
                "reason": reason,
                "currency": "KES"
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            result = response.json()
            
            if result.get("status"):
                data = result.get("data", {})
                logger.info(f"[PAYSTACK] Transfer initiated: {data.get('transfer_code')}, status={data.get('status')}")
                return {
                    "success": True,
                    "transfer_code": data.get("transfer_code"),
                    "status": data.get("status"),
                    "amount": amount_kes,
                    "reference": data.get("reference")
                }
            else:
                logger.error(f"[PAYSTACK] Transfer failed: {result.get('message')}")
                return {"success": False, "error": result.get("message", "Transfer failed")}
                
        except Exception as e:
            logger.error(f"[PAYSTACK] Transfer error: {str(e)}")
            return {"success": False, "error": str(e)}


    def validate_paystack_signature(self, payload: bytes, signature: str) -> bool:
        """Validate Paystack webhook signature."""
        import hmac
        import hashlib
        
        if not self.paystack_secret_key:
            return False
            
        computed_hash = hmac.new(
            self.paystack_secret_key.encode('utf-8'),
            payload,
            hashlib.sha512
        ).hexdigest()
        
        return computed_hash == signature

    async def process_paystack_webhook(self, event: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
        """
        Process Paystack webhook events.
        Handles: charge.success, transfer.success, transfer.failed, transfer.reversed
        """
        event_type = event.get("event")
        data = event.get("data", {})
        
        logger.info(f"[PAYSTACK WEBHOOK] Processing event: {event_type}")
        
        if event_type == "charge.success":
            return await self.handle_charge_success(data, db)
        if event_type == "transfer.success":
            return await self.handle_transfer_success(data, db)
        elif event_type == "transfer.failed":
            return await self.handle_transfer_failed(data, db)
        elif event_type == "transfer.reversed":
            return await self.handle_transfer_reversed(data, db)
        
        return {"processed": False, "reason": "Event ignored"}

    async def handle_charge_success(self, data: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
        """Activate subscription from Paystack charge.success webhook (idempotent)."""
        from sqlalchemy import select
        from ..models import User
        import uuid as _uuid

        if data.get("status") != "success":
            return {"processed": False, "reason": "Non-success charge"}

        metadata = data.get("metadata") or {}
        amount_kes = (data.get("amount") or 0) / 100
        reference = data.get("reference", "")

        user = None
        user_id_raw = metadata.get("user_id")
        if user_id_raw:
            try:
                uid = _uuid.UUID(str(user_id_raw))
                result = await db.execute(select(User).where(User.id == uid))
                user = result.scalar_one_or_none()
            except (ValueError, TypeError):
                pass

        if not user:
            email = (data.get("customer") or {}).get("email")
            if email:
                result = await db.execute(select(User).where(User.email == email))
                user = result.scalar_one_or_none()

        if not user:
            logger.warning("[PAYSTACK WEBHOOK] charge.success: user not found ref=%s", reference)
            return {"processed": False, "error": "User not found"}

        result = await self._activate_paystack_charge(
            user=user,
            data=data,
            reference=reference,
            amount_kes=amount_kes,
            metadata=metadata,
            db=db,
        )
        return {"processed": True, **result}

    async def handle_transfer_success(self, data: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
        """Handle successful transfer event."""
        from sqlalchemy import select
        from ..models import CreatorTransaction, Notification
        
        reference = data.get("reference")
        
        # Find transaction
        result = await db.execute(
            select(CreatorTransaction).where(CreatorTransaction.paystack_reference == reference)
        )
        transaction = result.scalar_one_or_none()
        
        if not transaction:
             # Try finding by pending reference convention if applicable
             # For now, simplistic match
             logger.warning(f"[PAYSTACK] Transfer {reference} not found in DB")
             return {"processed": False, "error": "Transaction not found"}
             
        if transaction.status == "completed":
            return {"processed": True, "message": "Already completed"}
            
        # Update status
        transaction.status = "completed"
        transaction.updated_at = datetime.utcnow()
        
        # Notify user (if we had a reference to the user, typically via profile_id)
        # We need to fetch profile to get user_id for notification
        from ..models import TikTokProfile
        profile = await db.get(TikTokProfile, transaction.profile_id)
        
        if profile:
            notification = Notification(
                user_id=profile.user_id,
                notification_type="withdrawal_completed",
                title="Withdrawal Successful ✅",
                message=f"Your withdrawal of KES {abs(transaction.creator_amount)} has been sent to M-Pesa.",
                actor_id=profile.user_id, # System
                action_url="/wallet",
                metadata={"amount": abs(transaction.creator_amount), "reference": reference}
            )
            db.add(notification)
            
        await db.commit()
        logger.info(f"[PAYSTACK] Transfer {reference} marked as completed")
        
        return {"processed": True, "status": "completed"}

    async def handle_transfer_failed(self, data: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
        """Handle failed transfer event (Refund logic)."""
        from sqlalchemy import select
        from ..models import CreatorTransaction, TikTokProfile, Notification
        from decimal import Decimal
        
        reference = data.get("reference")
        
        # Find transaction
        result = await db.execute(
            select(CreatorTransaction).where(CreatorTransaction.paystack_reference == reference)
        )
        transaction = result.scalar_one_or_none()
        
        if not transaction:
             logger.warning(f"[PAYSTACK] Transfer {reference} not found for failure processing")
             return {"processed": False, "error": "Transaction not found"}
             
        if transaction.status == "failed":
            return {"processed": True, "message": "Already failed"}
            
        # Update status
        transaction.status = "failed"
        transaction.updated_at = datetime.utcnow()
        
        # REFUND: Add amount back to wallet
        # creator_amount is negative for withdrawals, so we subtract it (double negative = positive)
        # Or better, just take abs value
        refund_amount = abs(transaction.creator_amount)
        
        profile = await db.get(TikTokProfile, transaction.profile_id)
        if profile:
            current_balance = profile.wallet_balance or Decimal("0.0")
            profile.wallet_balance = current_balance + Decimal(str(refund_amount))
            
            error_reason = data.get("reason", "Transfer failed")
            
            # Notify user
            notification = Notification(
                user_id=profile.user_id,
                notification_type="withdrawal_failed",
                title="Withdrawal Failed ❌",
                message=f"Withdrawal of KES {refund_amount} failed. Funds have been returned to your wallet.",
                actor_id=profile.user_id,
                action_url="/wallet",
                metadata={"reason": error_reason, "amount": refund_amount}
            )
            db.add(notification)
            
        await db.commit()
        logger.info(f"[PAYSTACK] Transfer {reference} marked as failed and refunded")
        
        return {"processed": True, "status": "failed", "refunded": True}

    async def handle_transfer_reversed(self, data: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
        """Handle reversed transfer event (Same as failed)."""
        logger.info(f"[PAYSTACK] Handling transfer reversal for {data.get('reference')}")
        return await self.handle_transfer_failed(data, db)
