"""
Google Workspace Base Client for OAuth authentication.
"""

import logging
from typing import Any, Dict, Optional
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class GoogleWorkspaceBaseClient:
    """Base client for Google Workspace API authentication and service access."""
    
    def __init__(self, credentials_data: Dict[str, Any]):
        """
        Initialize with credential data from connection config.
        
        Args:
            credentials_data: Dict containing access_token, refresh_token, client_id, client_secret
        """
        self.credentials = self._build_credentials(credentials_data)
        self.credentials_data = credentials_data
        
    def _build_credentials(self, data: Dict[str, Any]) -> Credentials:
        """Build Google OAuth2 credentials from stored data."""
        try:
            creds = Credentials(
                token=data.get("access_token"),
                refresh_token=data.get("refresh_token"),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=data.get("client_id"),
                client_secret=data.get("client_secret"),
                scopes=data.get("scopes")
            )
            return creds
        except Exception as e:
            logger.error(f"Error building credentials: {e}")
            raise
    
    def refresh_token_if_needed(self) -> bool:
        """Refresh the access token if expired."""
        try:
            if not self.credentials.valid:
                if self.credentials.expired and self.credentials.refresh_token:
                    self.credentials.refresh(Request())
                    logger.info("Access token refreshed successfully")
                    return True
                else:
                    logger.warning("Credentials invalid and no refresh token available")
                    return False
            return True
        except Exception as e:
            logger.error(f"Error refreshing token: {e}")
            return False
    
    def get_service(self, api_name: str, version: str):
        """
        Get a Google API service client.
        
        Args:
            api_name: API name (e.g., 'gmail', 'calendar', 'drive')
            version: API version (e.g., 'v1', 'v3')
            
        Returns:
            Google API service client
        """
        try:
            # Refresh if needed
            self.refresh_token_if_needed()
            
            # Build and return service
            service = build(api_name, version, credentials=self.credentials)
            return service
        except Exception as e:
            logger.error(f"Error building {api_name} service: {e}")
            raise
    
    def get_updated_credentials(self) -> Dict[str, Any]:
        """
        Get updated credential data (in case token was refreshed).
        
        Returns:
            Updated credentials dict
        """
        return {
            "access_token": self.credentials.token,
            "refresh_token": self.credentials.refresh_token,
            "client_id": self.credentials_data.get("client_id"),
            "client_secret": self.credentials_data.get("client_secret"),
            "scopes": self.credentials.scopes,
            "token_expiry": self.credentials.expiry.isoformat() if self.credentials.expiry else None
        }
