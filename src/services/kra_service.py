import logging
import os
import httpx
import time
from typing import Dict, Any, Optional
from datetime import datetime

from ..config import settings

logger = logging.getLogger(__name__)

class KraService:
    """
    Service for interacting with KRA (Kenya Revenue Authority) GavaConnect APIs.
    Handles authentication and functional API calls.
    """
    
    def __init__(self):
        # Multi-App Credentials with per-scope environment override
        self.credentials = {
            "identity_pin": {
                "key": settings.KRA_IDENTITY_PIN_KEY, 
                "secret": settings.KRA_IDENTITY_PIN_SECRET,
                "scope": "identity_pin",
                "env": "production"  # Use production
            },
            "identity_id": {
                "key": settings.KRA_IDENTITY_ID_KEY, 
                "secret": settings.KRA_IDENTITY_ID_SECRET,
                "scope": "identity_id",
                "env": "production"  # Use production for PIN checker by ID
            },
            "filing": {
                "key": settings.KRA_NIL_FILING_KEY, 
                "secret": settings.KRA_NIL_FILING_SECRET,
                "scope": "filing",
                "env": "sandbox"  # Use sandbox
            },
            "etims": {
                "key": settings.KRA_ETIMS_KEY, 
                "secret": settings.KRA_ETIMS_SECRET,
                "scope": "etims",
                "env": "sandbox"  # Use sandbox
            },
            "registration": {
                "key": settings.KRA_INDIVIDUAL_PIN_REGISTRATION_KEY,
                "secret": settings.KRA_INDIVIDUAL_PIN_REGISTRATION_SECRET,
                "scope": "registration",
                "env": "sandbox"  # Use sandbox
            }
        }
        
        # Base URLs
        self.urls = {
            "production": {
                "base": "https://api.kra.go.ke",
                "token": "https://api.kra.go.ke/v1/token/generate?grant_type=client_credentials"
            },
            "sandbox": {
                "base": "https://sbx.kra.go.ke",
                "token": "https://sbx.kra.go.ke/v1/token/generate?grant_type=client_credentials"
            }
        }
            
        # Token storage: {"scope": {"token": "...", "expiry": 1234567890}}
        self._tokens: Dict[str, Dict[str, Any]] = {}
    
    def _get_urls_for_scope(self, scope: str) -> Dict[str, str]:
        """Get the correct base and token URLs for a given scope."""
        creds = self.credentials.get(scope, {})
        env = creds.get("env", "sandbox")  # Default to sandbox
        return self.urls.get(env, self.urls["sandbox"])
        
    async def _get_access_token(self, scope: str = "default") -> str:
        """
        Retrieves a valid bearer token for a specific scope (App).
        Includes caching logic per scope.
        """
        # Determine effective scope
        creds = self.credentials.get(scope)
        if not creds:
             raise ValueError(f"Invalid scope '{scope}' for KRA API")

        # Check cache
        token_data = self._tokens.get(scope)
        if token_data and time.time() < token_data.get("expiry", 0):
            return token_data["token"]
            
        consumer_key = creds.get("key")
        consumer_secret = creds.get("secret")

        if not consumer_key or not consumer_secret:
            print(f"[KRA DEBUG] Credentials missing for scope: {scope}")
            raise ValueError(f"KRA credentials missing for scope: {scope}")
            
        print(f"[KRA DEBUG] Auth [{scope}] Key: {consumer_key[:4]}... Secret: {consumer_secret[:4]}...")
        
        # Get environment-specific URLs for this scope
        scope_urls = self._get_urls_for_scope(scope)
        token_url = scope_urls["token"]
        
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            try:
                print(f"[KRA DEBUG] Sending request to: {token_url}")
                response = await client.get(
                    token_url,
                    auth=(consumer_key, consumer_secret)
                )
                
                print(f"[KRA DEBUG] Auth Response Status: {response.status_code}")
                
                if response.status_code != 200:
                    print(f"[KRA DEBUG] Auth Response Body: {response.text}")
                    logger.error(f"Failed to generate KRA token [{scope}]: {response.text}")
                    raise Exception(f"KRA Auth Failed [{scope}]: {response.status_code}")
                    
                data = response.json()
                token = data.get("access_token")
                # Set expiry to now + expires_in (minus a 60s buffer)
                expires_in = int(data.get("expires_in", 3600))
                expiry = time.time() + expires_in - 60
                
                # Cache token
                self._tokens[scope] = {
                    "token": token,
                    "expiry": expiry
                }
                
                return token
            except Exception as e:
                print(f"[KRA DEBUG] Connection Error [{scope}] ({type(e).__name__}): {str(e)}")
                raise

    async def _make_request(self, method: str, path: str, json_data: Dict[str, Any] = None, scope: str = "default") -> Dict[str, Any]:
        """Helper to make authenticated requests to KRA with scope selection."""
        try:
            token = await self._get_access_token(scope)
        except Exception as e:
            print(f"[KRA DEBUG] Token generation failed for {scope}: {e}")
            return {"success": False, "error": f"Auth failed for {scope}: {str(e)}"}
        
        # Get environment-specific base URL for this scope
        scope_urls = self._get_urls_for_scope(scope)
        base_url = scope_urls["base"]
        url = f"{base_url}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        
        print(f"[KRA DEBUG] Request: {method} {url}")
        print(f"[KRA DEBUG] Payload: {json_data}")
        
        async with httpx.AsyncClient(verify=False, timeout=180.0) as client:
            try:
                if method.upper() == "POST":
                    response = await client.post(url, json=json_data, headers=headers)
                else:
                    response = await client.get(url, headers=headers)
                
                print(f"[KRA DEBUG] API Response Status: {response.status_code}")
                try:
                    print(f"[KRA DEBUG] API Response Body: {response.text}")
                except Exception as text_err:
                     print(f"[KRA DEBUG] Could not read response text: {text_err}")
                
                if response.status_code != 200:
                    logger.warning(f"KRA API Error ({path}): {response.text}")
                    return {"success": False, "error": response.text, "status_code": response.status_code}
                    
                return {"success": True, "data": response.json()}
            except Exception as e:
                print(f"[KRA DEBUG] Request Integrity Error: {repr(e)}")
                raise

    async def test_connection(self) -> bool:
        """Validates that at least one configured app can authorize."""
        for scope in self.credentials.keys():
            try:
                # If we have keys for this scope, try to auth
                creds = self.credentials[scope]
                if creds.get("key") and creds.get("secret"):
                    await self._get_access_token(scope)
                    return True
            except Exception:
                continue
        return False

    async def check_pin(self, pin: str) -> Dict[str, Any]:
        """
        Verifies a KRA PIN using the 'PIN Checker by PIN' product.
        API: /checker/v1/pinbypin
        Documentation: https://sbx.kra.go.ke/checker/v1/pinbypin
        """
        payload = {"KRAPIN": pin}
        # Use Identity (PIN) App
        return await self._make_request("POST", "/checker/v1/pinbypin", payload, scope="identity_pin")

    async def get_pin_by_id(self, id_number: str, taxpayer_type: str = "KE") -> Dict[str, Any]:
        """
        Retrieves a KRA PIN using National ID Number.
        API: /checker/v1/pin
        """
        payload = {
            "TaxpayerType": taxpayer_type,
            "TaxpayerID": id_number
        }
        # Use Identity (ID) App
        return await self._make_request("POST", "/checker/v1/pin", payload, scope="identity_id")

    async def check_tcc(self, pin: str, tcc_number: str) -> Dict[str, Any]:
        """
        Checks Tax Compliance Certificate status.
        API: /checker/v1/tcc
        """
        payload = {"pin": pin, "tccNumber": tcc_number}
        # Use Identity (PIN) App
        return await self._make_request("POST", "/checker/v1/tcc", payload, scope="identity_pin")

    async def file_nil_return(self, pin: str, obligation_code: str, month: str, year: str) -> Dict[str, Any]:
        """
        Files a NIL return for a taxpayer.
        API: /dtd/return/v1/nil
        """
        payload = {
            "TAXPAYERDETAILS": {
                "TaxpayerPIN": pin,
                "ObligationCode": str(obligation_code),
                "Month": str(month),
                "Year": str(year)
            }
        }
        # Use Filing App
        return await self._make_request("POST", "/dtd/return/v1/nil", payload, scope="filing")

    async def generate_pin(self, id_number: str, dob: str, mobile: str, email: str, taxpayer_type: str = "KE", is_pin_with_no_oblig: str = "Yes") -> Dict[str, Any]:
        """
        Generates a new KRA PIN for an individual.
        API: /v1/generate/pin
        """
        payload = {
            "TAXPAYERDETAILS": {
                "TaxpayerType": taxpayer_type,
                "IdentificationNumber": id_number,
                "DateOfBirth": dob,
                "MobileNumber": mobile,
                "EmailAddress": email,
                "IsPinWithNoOblig": is_pin_with_no_oblig
            }
        }
        # Use Registration scope
        return await self._make_request("POST", "/v1/generate/pin", payload, scope="registration")

    async def verify_eslip(self, pin: str, eslip_number: str) -> Dict[str, Any]:
        """
        Verifies an e-Slip.
        API: /payments/v1/eslip/verify
        """
        payload = {"pin": pin, "eSlipNumber": eslip_number}
        # Use eTIMS App (or Filing if bundled)
        return await self._make_request("POST", "/payments/v1/eslip/verify", payload, scope="etims")

    async def init_etims(self, pin: str, branch_id: str, device_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Initializes eTIMS OSCU/VSCU setup.
        API: /selectInitOsdcInfo
        """
        payload = {
            "pin": pin,
            "branchId": branch_id,
            "deviceInfo": device_info
        }
        # Use eTIMS App
        return await self._make_request("POST", "/selectInitOsdcInfo", payload, scope="etims")

# Global instances of the service can be imported
kra_service = KraService()
