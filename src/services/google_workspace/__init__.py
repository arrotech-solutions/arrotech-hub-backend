"""
Google Workspace Integration Package
Provides services for Gmail, Calendar, Drive, Sheets, and Docs integration.
"""

from .base_client import GoogleWorkspaceBaseClient
from .gmail_service import GmailService
from .calendar_service import CalendarService
from .drive_service import DriveService
from .sheets_service import SheetsService
from .docs_service import DocsService
from .analytics_service import AnalyticsService

__all__ = [
    'GoogleWorkspaceBaseClient',
    'GmailService',
    'CalendarService',
    'DriveService',
    'SheetsService',
    'DocsService',
    'AnalyticsService',
]
