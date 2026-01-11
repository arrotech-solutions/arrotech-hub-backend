"""
Payment service for Mini-Hub with M-Pesa and Stripe integration.
"""

import base64
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import requests
import stripe
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Payment


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
        """Format phone number for M-Pesa API."""
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
            print(f"M-Pesa Payload: {payload}")

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
        user_id: int,
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
        user_id: int,
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
