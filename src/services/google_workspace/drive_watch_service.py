"""
Google Drive Watch Service
Manages registration and lifecycle of Google Drive "Changes" API watches for workflow automation.
"""
import logging
import uuid
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

from ...models import User, Workflow
from ...config import settings
from .base_client import GoogleWorkspaceBaseClient
from .drive_service import DriveService

logger = logging.getLogger(__name__)

class GoogleDriveWatchService:
    def __init__(self):
        self.base_client = GoogleWorkspaceBaseClient()
        self.drive_service = DriveService(self.base_client)

    async def register_drive_watch(self, db: AsyncSession, user: User, workflow: Workflow) -> bool:
        """
        Registers a Google Drive "Changes" API watch for a user and workflow.
        Stores the necessary metadata in the workflow record.
        """
        try:
            # 1. Get current start page token
            token_result = await self.drive_service.get_start_page_token()
            if not token_result.get('success'):
                logger.error(f"Failed to get start page token for user {user.id}: {token_result.get('error')}")
                return False
            
            start_page_token = token_result.get('start_page_token')
            
            # 2. Setup watch channel
            channel_id = f"wf-{workflow.id}-{str(uuid.uuid4())[:8]}"
            webhook_url = f"{settings.API_BASE_URL}/api/google-drive/events"
            
            watch_result = await self.drive_service.watch_changes(
                page_token=start_page_token,
                webhook_url=webhook_url,
                channel_id=channel_id,
                token=str(workflow.id) # Use workflow ID as our secret token for verification
            )
            
            if not watch_result.get('success'):
                logger.error(f"Failed to create Google Drive watch for user {user.id}: {watch_result.get('error')}")
                return False
            
            # 3. Update workflow metadata
            metadata = workflow.workflow_metadata or {}
            metadata.update({
                "google_drive_channel_id": channel_id,
                "google_drive_resource_id": watch_result.get('resourceId'),
                "google_drive_expiration": watch_result.get('expiration'),
                "google_drive_last_page_token": start_page_token,
                "google_drive_watch_active": True
            })
            
            # Use direct update to ensure it's saved
            await db.execute(
                update(Workflow)
                .where(Workflow.id == workflow.id)
                .values(workflow_metadata=metadata)
            )
            await db.commit()
            
            logger.info(f"Successfully registered Google Drive watch for workflow {workflow.id}, channel {channel_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error in register_drive_watch: {e}", exc_info=True)
            return False

    async def stop_drive_watch(self, workflow: Workflow) -> bool:
        """
        Stops an existing Google Drive watch channel.
        """
        # TODO: Implement channels().stop() in DriveService and call it here
        metadata = workflow.workflow_metadata or {}
        metadata["google_drive_watch_active"] = False
        # Save change...
        return True
