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

    def __init__(self):
        self.consumer_key = settings.MPESA_CONSUMER_KEY
        self.consumer_secret = settings.MPESA_CONSUMER_SECRET
        self.environment = settings.MPESA_ENVIRONMENT.lower()
        self.business_short_code = settings.MPESA_BUSINESS_SHORT_CODE
        self.passkey = settings.MPESA_PASSKEY
        
        if self.environment == "live":
            self.base_url = "https://api.safaricom.co.ke"
        else:
            self.base_url = "https://sandbox.safaricom.co.ke"

        self._access_token: Optional[str] = None
        self._token_expiry: float = 0

    async def _get_access_token(self) -> str:
        """Get or refresh OAuth access token."""
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token

        if not self.consumer_key or not self.consumer_secret:
            raise ValueError("M-Pesa Consumer Key or Secret not configured")

        auth_str = f"{self.consumer_key}:{self.consumer_secret}"
        encoded_auth = base64.b64encode(auth_str.encode()).decode()

        headers = {
            "Authorization": f"Basic {encoded_auth}"
        }

        url = f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Failed to generate M-Pesa token: {error_text}")
                        raise Exception(f"Daraja Auth Error: {response.status}")
                    
                    data = await response.json()
                    self._access_token = data["access_token"]
                    # Token usually expires in 3600s, refresh slightly earlier
                    self._token_expiry = time.time() + int(data["expires_in"]) - 60
                    return self._access_token
        except Exception as e:
            logger.error(f"Error getting Daraja access token: {e}")
            raise

    async def query_transaction_status(self, transaction_id: str, originator_conversation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Query the status of a transaction.
        Note: This usually requires a Callback URL to receive the result asynchronously.
        However, for Fraud Detection, we mainly want to verify if the ID exists in our records
        or if we can fetch it via Transaction Status API.
        """
        token = await self._get_access_token()
        
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        password_str = f"{self.business_short_code}{self.passkey}{timestamp}"
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
            "PartyA": self.business_short_code,
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

    async def test_connection(self) -> Dict[str, Any]:
        """Test authentication with Daraja."""
        try:
            token = await self._get_access_token()
            return {"success": True, "message": "Authentication successful"}
        except Exception as e:
            return {"success": False, "error": str(e)}

# Global instance
daraja_service = DarajaService()
