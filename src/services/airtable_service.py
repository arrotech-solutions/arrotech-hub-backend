import json
import logging
import base64
from typing import Dict, Any, List, Optional
import aiohttp
from urllib.parse import urlencode

from ..config import get_settings

logger = logging.getLogger(__name__)

class AirtableService:
    AUTH_URL = "https://airtable.com/oauth2/v1/authorize"
    TOKEN_URL = "https://airtable.com/oauth2/v1/token"
    API_BASE_URL = "https://api.airtable.com/v0"

    # Airtable scopes needed for full integration functionality
    SCOPES = "data.records:read data.records:write schema.bases:read schema.bases:write"

    def __init__(self, access_token: str = None, refresh_token: str = None):
        self.access_token = access_token
        self.refresh_token = refresh_token
        settings = get_settings()
        self.client_id = settings.AIRTABLE_CLIENT_ID
        self.client_secret = settings.AIRTABLE_CLIENT_SECRET
        self.redirect_uri = settings.AIRTABLE_REDIRECT_URI

    @classmethod
    def get_auth_url(cls, state: str, code_challenge: str) -> str:
        settings = get_settings()
        params = {
            "client_id": settings.AIRTABLE_CLIENT_ID,
            "redirect_uri": settings.AIRTABLE_REDIRECT_URI,
            "response_type": "code",
            "scope": cls.SCOPES,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256"
        }
        return f"{cls.AUTH_URL}?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str, code_verifier: str) -> Dict[str, Any]:
        """Exchange the OAuth authorization code for tokens, using PKCE verifier."""
        auth_bytes = f"{self.client_id}:{self.client_secret}".encode("ascii")
        auth_header = base64.b64encode(auth_bytes).decode("ascii")

        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": code_verifier
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.TOKEN_URL, headers=headers, data=data) as response:
                text = await response.text()
                if not response.ok:
                    logger.error(f"Airtable token exchange failed: {response.status} {text}")
                    raise Exception(f"Failed to exchange Airtable code: {text}")

                token_data = json.loads(text)
                self.access_token = token_data.get("access_token")
                self.refresh_token = token_data.get("refresh_token")
                return token_data

    async def refresh_access_token(self) -> Dict[str, Any]:
        """Refresh an expired access token using the refresh token."""
        if not self.refresh_token:
            raise Exception("No Airtable refresh token available")

        auth_bytes = f"{self.client_id}:{self.client_secret}".encode("ascii")
        auth_header = base64.b64encode(auth_bytes).decode("ascii")

        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.TOKEN_URL, headers=headers, data=data) as response:
                text = await response.text()
                if not response.ok:
                    logger.error(f"Airtable token refresh failed: {text}")
                    raise Exception(f"Failed to refresh Airtable token: {text}")

                token_data = json.loads(text)
                self.access_token = token_data.get("access_token")
                if "refresh_token" in token_data:
                    self.refresh_token = token_data["refresh_token"]
                return token_data

    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Helper for authenticated API requests with auto token refresh."""
        if not self.access_token:
            raise Exception("No access token available for Airtable")

        url = f"{self.API_BASE_URL}{endpoint}"
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"
        kwargs["headers"] = headers

        async with aiohttp.ClientSession() as session:
            response = await session.request(method, url, **kwargs)

            # Auto-refresh on 401 Unauthorized
            if response.status == 401 and self.refresh_token:
                logger.info("Airtable token expired, refreshing...")
                await self.refresh_access_token()
                headers["Authorization"] = f"Bearer {self.access_token}"
                kwargs["headers"] = headers
                response = await session.request(method, url, **kwargs)

            response_text = await response.text()
            
            if not response.ok:
                logger.error(f"Airtable API error ({response.status}): {response_text}")
                try:
                    error_data = json.loads(response_text)
                    error_obj = error_data.get("error")
                    if isinstance(error_obj, dict):
                        error_msg = error_obj.get("message", response_text)
                    elif isinstance(error_obj, str):
                        error_msg = error_obj
                    else:
                        error_msg = response_text
                except:
                    error_msg = response_text
                raise Exception(f"Airtable API Error: {error_msg}")

            try:
                return json.loads(response_text) if response_text else {}
            except json.JSONDecodeError:
                return response_text

    async def list_bases(self) -> Dict[str, Any]:
        """Fetch all bases the user has granted access to."""
        return await self._request("GET", "/meta/bases")

    async def get_base_schema(self, base_id: str) -> Dict[str, Any]:
        """Fetch tables and fields for a specific base."""
        return await self._request("GET", f"/meta/bases/{base_id}/tables")

    async def get_records(self, base_id: str, table_id_or_name: str, max_records: int = 100, **kwargs) -> Dict[str, Any]:
        """Fetch records from a specific table."""
        params = {"maxRecords": max_records}
        params.update(kwargs) # Allows passing filterByFormula, sort, etc.
        return await self._request("GET", f"/{base_id}/{table_id_or_name}", params=params)

    async def create_records(self, base_id: str, table_id_or_name: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create new records in a specific table."""
        # 'records' is expected to be a list of field dictionaries
        payload = {"records": [{"fields": r} for r in records]}
        headers = {"Content-Type": "application/json"}
        return await self._request("POST", f"/{base_id}/{table_id_or_name}", json=payload, headers=headers)

    async def update_records(self, base_id: str, table_id_or_name: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Update existing records.
        `records` should be a list of dicts, each containing an 'id' and 'fields'.
        Example: [{"id": "recXyxz", "fields": {"Name": "New Name"}}]
        """
        payload = {"records": records}
        headers = {"Content-Type": "application/json"}
        return await self._request("PATCH", f"/{base_id}/{table_id_or_name}", json=payload, headers=headers)
