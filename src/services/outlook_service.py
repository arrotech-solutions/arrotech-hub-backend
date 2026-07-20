"""
Outlook service for Mini-Hub MCP Server.
"""

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import aiohttp
from pydantic import BaseModel

from ..config import settings

logger = logging.getLogger(__name__)


class OutlookService:
    """Microsoft Outlook API service."""

    def __init__(self):
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        # Outlook uses the same Entra ID (Azure AD) app as Teams usually, 
        # but can have different config if needed. 
        # For now, we assume specific Outlook environment variables if they exist, 
        # or fall back to general Microsoft ones if we decide to unify. 
        # The prompt implies adding a new integration, so we'll look for OUTLOOK_ specific vars 
        # or re-use broadly if the user intends a single Microsoft app.
        # Given the "Outlook Integration" task, it's safer to use OUTLOOK_ prefix for clarity,
        # but often it's the same Client ID.
        # Check task.md/User Context: User wants "Outlook" integration.
        # I'll use OUTLOOK_CLIENT_ID etc. to be safe, but default to others if missing? 
        # Actually, best to just stick to new variables: OUTLOOK_CLIENT_ID, OUTLOOK_CLIENT_SECRET.
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
        self.tenant_id: Optional[str] = None

    async def initialize(self):
        """Initialize Outlook client."""
        # Check for Outlook specific settings, or generic Microsoft ones if not found?
        # For this implementation, I will rely on settings having these.
        # If they don't exist in settings.py yet, I might need to rely on the caller passing them 
        # or defining them. 
        # Since I cannot see settings.py right now, I will use:
        # settings.OUTLOOK_CLIENT_ID, etc.
        # If they are missing at runtime, it will log a warning.
        
        self.client_id = getattr(settings, "OUTLOOK_CLIENT_ID", None)
        self.client_secret = getattr(settings, "OUTLOOK_CLIENT_SECRET", None)
        self.tenant_id = getattr(settings, "OUTLOOK_TENANT_ID", "common") 
        
        if self.client_id and self.client_secret:
             logger.info("Outlook credentials initialized")
        else:
             logger.warning("Outlook credentials not fully configured")

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        """Generate Outlook OAuth authorization URL."""
        if not self.client_id:
            raise ValueError("Outlook client_id must be configured")

        scopes = [
            "User.Read",
            "Mail.Read",
            "Mail.Send",
            "offline_access"
        ]

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": " ".join(scopes),
            "state": state,
            "prompt": "select_account"
        }
        
        base_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/authorize"
        return f"{base_url}?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange authorization code for access token."""
        if not self.client_id or not self.client_secret:
            raise ValueError("Outlook credentials must be configured")

        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        
        data = {
            "client_id": self.client_id,
            "scope": "User.Read Mail.Read Mail.Send offline_access",
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "client_secret": self.client_secret
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, data=data) as response:
                if response.status == 200:
                    token_data = await response.json()
                    logger.info(f"Token Exchange Success. Scopes: {token_data.get('scope')}")
                    return token_data
                else:
                    error_text = await response.text()
                    raise Exception(f"Failed to exchange token: {response.status} - {error_text}")

    async def get_recent_emails(self, limit: int = 10) -> Dict[str, Any]:
        """Get recent emails from Inbox."""
        if not self.access_token:
            return {"success": False, "error": "Access token required"}

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        # Select standard fields + bodyPreview + body
        # Note: body is complex, might need specific select syntax or just default
        url = f"https://graph.microsoft.com/v1.0/me/messages?$top={limit}&$orderby=receivedDateTime desc&$select=id,receivedDateTime,subject,from,isRead,bodyPreview,body,webLink"
        
        logger.info(f"Fetching Outlook emails. URL: {url}")
        logger.info(f"Token Preview: {self.access_token[:50]}...")

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Outlook API Success. Items: {len(data.get('value', []))}")
                    emails = []
                    for msg in data.get("value", []):
                        emails.append({
                            "id": msg.get("id"),
                            "subject": msg.get("subject"),
                            "preview": msg.get("bodyPreview"),
                            "body": msg.get("body"), # Include full body structure
                            "from": msg.get("from", {}).get("emailAddress", {}).get("name") or msg.get("from", {}).get("emailAddress", {}).get("address"),
                            "sender_email": msg.get("from", {}).get("emailAddress", {}).get("address"),
                            "timestamp": msg.get("receivedDateTime"),
                            "is_read": msg.get("isRead"),
                            "link": msg.get("webLink"),
                            "source": "outlook"
                        })
                    return {
                        "success": True,
                        "messages": emails,
                        "count": len(emails)
                    }
                else:
                    try:
                        error_json = await response.json()
                        text = str(error_json)
                    except:
                        text = await response.text()
                    
                    all_headers = dict(response.headers)
                    logger.error(f"Outlook API Error: {response.status} {response.reason}")
                    logger.error(f"Response Headers: {all_headers}")
                    logger.error(f"Response Body: {text}")
                    return {"success": False, "error": f"Failed to fetch emails: {text}"}

    async def send_email(self, to_email: str, subject: str, content: str, content_type: str = "text", cc: Optional[str] = None, bcc: Optional[str] = None) -> Dict[str, Any]:
        """Send an email."""
        if not self.access_token:
            return {"success": False, "error": "Access token required"}

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        to_recipients = [{"emailAddress": {"address": to_email}}]
        
        message_payload = {
            "subject": subject,
            "body": {
                "contentType": "HTML" if content_type.lower() == "html" else "Text",
                "content": content
            },
            "toRecipients": to_recipients
        }
        
        if cc:
            cc_recipients = [{"emailAddress": {"address": email.strip()}} for email in cc.split(",") if email.strip()]
            if cc_recipients:
                message_payload["ccRecipients"] = cc_recipients
                
        if bcc:
            bcc_recipients = [{"emailAddress": {"address": email.strip()}} for email in bcc.split(",") if email.strip()]
            if bcc_recipients:
                message_payload["bccRecipients"] = bcc_recipients

        payload = {
            "message": message_payload,
            "saveToSentItems": "true"
        }

        url = "https://graph.microsoft.com/v1.0/me/sendMail"

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 202:
                    return {"success": True, "message": "Email sent successfully"}
                else:
                    text = await response.text()
                    return {"success": False, "error": f"Failed to send email: {text}"}

    async def search_emails(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """Search emails."""
        if not self.access_token:
            return {"success": False, "error": "Access token required"}

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        # Use $search query parameter
        url = f"https://graph.microsoft.com/v1.0/me/messages?$search=\"{query}\"&$top={limit}&$select=id,receivedDateTime,subject,from,isRead,bodyPreview,webLink"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    emails = []
                    for msg in data.get("value", []):
                        emails.append({
                            "id": msg.get("id"),
                            "subject": msg.get("subject"),
                            "preview": msg.get("bodyPreview"),
                            "from": msg.get("from", {}).get("emailAddress", {}).get("name"),
                            "timestamp": msg.get("receivedDateTime"),
                            "link": msg.get("webLink"),
                            "source": "outlook"
                        })
                    return {
                        "success": True,
                        "messages": emails,
                        "count": len(emails),
                        "query": query
                    }
                else:
                    text = await response.text()
                    return {"success": False, "error": f"Failed to search emails: {text}"}
