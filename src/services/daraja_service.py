"""
Safaricom Daraja API Service.
Handles authentication and transaction status queries.
"""

import base64
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp
from ..config import settings

logger = logging.getLogger(__name__)

class DarajaService:
    """Service to interact with Safaricom Daraja API."""

    def __init__(self, environment: Optional[str] = None):
        """
        Initialize DarajaService.
        
        Args:
            environment: Optional override for Daraja environment ("sandbox" or "live").
                         If None, uses the global MPESA_ENVIRONMENT setting from config.
                         
                         The global singleton `daraja_service` uses platform-level settings
                         (for subscription payments). Per-tenant instances should pass
                         the tenant's chosen environment explicitly.
        """
        self.consumer_key = settings.MPESA_CONSUMER_KEY
        self.consumer_secret = settings.MPESA_CONSUMER_SECRET
        self.environment = (environment or settings.MPESA_ENVIRONMENT).lower()
        self.business_short_code = settings.MPESA_BUSINESS_SHORT_CODE
        self.passkey = settings.MPESA_PASSKEY
        
        if self.environment == "live":
            self.base_url = "https://api.safaricom.co.ke"
        else:
            self.base_url = "https://sandbox.safaricom.co.ke"

        self._access_token: Optional[str] = None
        self._token_expiry: float = 0

    async def _get_access_token(self, consumer_key: Optional[str] = None, consumer_secret: Optional[str] = None) -> str:
        """Get or refresh OAuth access token."""
        # Use provided credentials or default to settings
        c_key = consumer_key or self.consumer_key
        c_secret = consumer_secret or self.consumer_secret

        if not c_key or not c_secret:
            raise ValueError("M-Pesa Consumer Key or Secret not configured")

        # If using default keys, check cache
        if not consumer_key and not consumer_secret:
            if self._access_token and time.time() < self._token_expiry:
                return self._access_token

        auth_str = f"{c_key}:{c_secret}"
        encoded_auth = base64.b64encode(auth_str.encode()).decode()

        headers = {
            "Authorization": f"Basic {encoded_auth}"
        }

        url = f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    # Safaricom returns 400 Bad Request (text/plain) if credentials are wrong
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Failed to generate M-Pesa token | Status: {response.status} | Body: {error_text}")
                        # Try to parse as JSON if possible, otherwise use the text
                        try:
                            data = await response.json(content_type=None)
                            error_msg = data.get("errorMessage", f"Auth Error {response.status}")
                        except Exception:
                            error_msg = f"Auth Error {response.status}: Invalid Consumer Key or Secret"
                        
                        raise Exception(error_msg)
                        
                    data = await response.json(content_type=None)
                    token = data["access_token"]
                    
                    # Store in cache only if using default keys
                    if not consumer_key and not consumer_secret:
                        self._access_token = token
                        self._token_expiry = time.time() + int(data["expires_in"]) - 60
                        
                    return token
        except Exception as e:
            logger.error(f"Error getting Daraja access token: {e}")
            raise

    async def register_c2b_urls(
        self, 
        short_code: str, 
        confirmation_url: str, 
        validation_url: str,
        consumer_key: Optional[str] = None,
        consumer_secret: Optional[str] = None,
        response_type: str = "Completed"
    ) -> Dict[str, Any]:
        """
        Register C2B Confirmation and Validation URLs with Safaricom.
        """
        try:
            token = await self._get_access_token(consumer_key, consumer_secret)
            
            # Using v2 as requested by user
            url = f"{self.base_url}/mpesa/c2b/v2/registerurl"
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "ShortCode": short_code,
                "ResponseType": response_type,
                "ConfirmationURL": confirmation_url,
                "ValidationURL": validation_url
            }

            logger.info(f"Registering Daraja URLs for shortcode {short_code}...")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    data = await response.json()
                    logger.info(f"Daraja URL Registration response: {data}")
                    return data
        except Exception as e:
            logger.error(f"Error registering Daraja URLs: {e}")
            return {"ResponseCode": "1", "ResponseDescription": str(e)}

    async def query_transaction_status(
        self,
        transaction_id: str,
        originator_conversation_id: Optional[str] = None,
        consumer_key: Optional[str] = None,
        consumer_secret: Optional[str] = None,
        short_code: Optional[str] = None,
        passkey: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Query the status of a transaction.
        Note: This usually requires a Callback URL to receive the result asynchronously.
        However, for Fraud Detection, we mainly want to verify if the ID exists in our records
        or if we can fetch it via Transaction Status API.
        """
        token = await self._get_access_token(consumer_key, consumer_secret)
        
        bsc = short_code or self.business_short_code
        pk = passkey or self.passkey
        
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        password_str = f"{bsc}{pk}{timestamp}"
        password = base64.b64encode(password_str.encode()).decode()

        url = f"{self.base_url}/mpesa/transactionstatus/v1/query"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # This is the standard Daraja Transaction Status Query payload
        payload = {
            "Initiator": "HubAdmin", # Should ideally be from config
            "SecurityCredential": "CREDENTIAL", # Should be encrypted
            "CommandID": "TransactionStatusQuery",
            "TransactionID": transaction_id,
            "PartyA": bsc,
            "IdentifierType": "4", # 4 for Shortcode
            "Remarks": "Fraud Verification",
            "Occasion": "Fraud Check",
            "QueueTimeOutURL": settings.MPESA_CALLBACK_URL,
            "ResultURL": settings.MPESA_CALLBACK_URL
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    data = await response.json()
                    logger.info(f"Daraja Transaction Status Query initiated for {transaction_id}: {data}")
                    return data
        except Exception as e:
            logger.error(f"Error querying Daraja transaction status: {e}")
            return {"ResponseCode": "1", "ResponseDescription": str(e)}

    async def test_connection(
        self,
        consumer_key: Optional[str] = None,
        consumer_secret: Optional[str] = None
    ) -> Dict[str, Any]:
        """Test authentication with Daraja."""
        try:
            token = await self._get_access_token(consumer_key, consumer_secret)
            return {"success": True, "message": "Authentication successful"}
        except Exception as e:
            return {"success": False, "error": str(e)}

# Global instance
daraja_service = DarajaService()
