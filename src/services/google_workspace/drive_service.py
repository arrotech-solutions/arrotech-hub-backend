"""
Drive Service for Google Workspace Integration
Handles file and folder operations in Google Drive.
"""
from typing import Dict, List, Any, Optional
import io
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

from .base_client import GoogleWorkspaceBaseClient


class DriveService:
    """Service for Google Drive operations"""
    
    def __init__(self, base_client: GoogleWorkspaceBaseClient):
        self.base_client = base_client
        self.service_name = 'drive'
        self.version = 'v3'
    
    async def upload_file(
        self,
        filename: str,
        content: bytes,
        mime_type: str = 'application/octet-stream',
        folder_id: Optional[str] = None,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Upload a file to Google Drive
        
        Args:
            filename: Name of the file
            content: File content as bytes
            mime_type: MIME type of the file
            folder_id: Parent folder ID (optional)
            description: File description
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            file_metadata = {'name': filename}
            
            if folder_id:
                file_metadata['parents'] = [folder_id]
            if description:
                file_metadata['description'] = description
            
            media = MediaIoBaseUpload(
                io.BytesIO(content),
                mimetype=mime_type,
                resumable=True
            )
            
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, mimeType, webViewLink, size, createdTime'
            ).execute()
            
            return {
                'success': True,
                'file_id': file.get('id'),
                'name': file.get('name'),
                'web_view_link': file.get('webViewLink'),
                'size': file.get('size'),
                'created_time': file.get('createdTime')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def download_file(
        self,
        file_id: str
    ) -> Dict[str, Any]:
        """
        Download a file from Google Drive
        
        Args:
            file_id: ID of the file to download
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            request = service.files().get_media(fileId=file_id)
            
            file_buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(file_buffer, request)
            
            done = False
            while not done:
                status, done = downloader.next_chunk()
            
            file_buffer.seek(0)
            
            # Get file metadata
            metadata = service.files().get(
                fileId=file_id,
                fields='name, mimeType, size'
            ).execute()
            
            return {
                'success': True,
                'file_id': file_id,
                'name': metadata.get('name'),
                'mime_type': metadata.get('mimeType'),
                'size': metadata.get('size'),
                'content': file_buffer.getvalue()
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def list_files(
        self,
        folder_id: Optional[str] = None,
        query: Optional[str] = None,
        max_results: int = 100,
        order_by: str = 'modifiedTime desc'
    ) -> Dict[str, Any]:
        """
        List files in Google Drive
        
        Args:
            folder_id: Filter by parent folder ID
            query: Custom query string
            max_results: Maximum number of results
            order_by: Sort order (e.g., 'modifiedTime desc', 'name')
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            # Build query
            q_parts = []
            if folder_id:
                q_parts.append(f"'{folder_id}' in parents")
            if query:
                q_parts.append(query)
            
            q_string = ' and '.join(q_parts) if q_parts else None
            
            params = {
                'pageSize': max_results,
                'fields': 'files(id, name, mimeType, size, createdTime, modifiedTime, webViewLink, owners)',
                'orderBy': order_by
            }
            
            if q_string:
                params['q'] = q_string
            
            result = service.files().list(**params).execute()
            files = result.get('files', [])
            
            formatted_files = []
            for file in files:
                formatted_files.append({
                    'id': file.get('id'),
                    'name': file.get('name'),
                    'mime_type': file.get('mimeType'),
                    'size': file.get('size'),
                    'created_time': file.get('createdTime'),
                    'modified_time': file.get('modifiedTime'),
                    'web_view_link': file.get('webViewLink'),
                    'owners': file.get('owners', [])
                })
            
            return {
                'success': True,
                'files': formatted_files,
                'total': len(formatted_files)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def create_folder(
        self,
        name: str,
        parent_folder_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a folder in Google Drive
        
        Args:
            name: Folder name
            parent_folder_id: Parent folder ID (optional)
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            file_metadata = {
                'name': name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            
            if parent_folder_id:
                file_metadata['parents'] = [parent_folder_id]
            
            folder = service.files().create(
                body=file_metadata,
                fields='id, name, webViewLink'
            ).execute()
            
            return {
                'success': True,
                'folder_id': folder.get('id'),
                'name': folder.get('name'),
                'web_view_link': folder.get('webViewLink')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def delete_file(
        self,
        file_id: str
    ) -> Dict[str, Any]:
        """
        Delete a file from Google Drive
        
        Args:
            file_id: ID of the file to delete
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            service.files().delete(fileId=file_id).execute()
            
            return {
                'success': True,
                'file_id': file_id
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def share_file(
        self,
        file_id: str,
        email: str,
        role: str = 'reader',
        send_notification: bool = True
    ) -> Dict[str, Any]:
        """
        Share a file with a user
        
        Args:
            file_id: ID of the file to share
            email: Email address of the user
            role: Permission role ('reader', 'writer', 'commenter', 'owner')
            send_notification: Send email notification
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            permission = {
                'type': 'user',
                'role': role,
                'emailAddress': email
            }
            
            result = service.permissions().create(
                fileId=file_id,
                body=permission,
                sendNotificationEmail=send_notification,
                fields='id'
            ).execute()
            
            return {
                'success': True,
                'permission_id': result.get('id'),
                'file_id': file_id,
                'email': email,
                'role': role
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def search_files(
        self,
        query: str,
        max_results: int = 50
    ) -> Dict[str, Any]:
        """
        Search for files in Google Drive
        
        Args:
            query: Search query (e.g., "name contains 'report'")
            max_results: Maximum number of results
        """
        return await self.list_files(
            query=query,
            max_results=max_results
        )
    
    async def get_file_metadata(
        self,
        file_id: str
    ) -> Dict[str, Any]:
        """
        Get detailed metadata for a file
        
        Args:
            file_id: ID of the file
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            file = service.files().get(
                fileId=file_id,
                fields='*'
            ).execute()
            
            return {
                'success': True,
                'file': file
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    async def move_file(
        self,
        file_id: str,
        folder_id: str
    ) -> Dict[str, Any]:
        """
        Move a file to a new folder
        
        Args:
            file_id: ID of the file to move
            folder_id: ID of the destination folder
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            # Retrieve the existing parents to remove
            file = service.files().get(
                fileId=file_id,
                fields='parents'
            ).execute()
            
            previous_parents = ",".join(file.get('parents', []))
            
            # Move the file by adding the new parent and removing the old ones
            file = service.files().update(
                fileId=file_id,
                addParents=folder_id,
                removeParents=previous_parents,
                fields='id, parents, name, webViewLink'
            ).execute()
            
            return {
                'success': True,
                'file_id': file.get('id'),
                'name': file.get('name'),
                'parents': file.get('parents'),
                'web_view_link': file.get('webViewLink')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    async def list_folders(self) -> Dict[str, Any]:
        """
        List all available folders in Google Drive for selection
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            result = service.files().list(
                q="mimeType = 'application/vnd.google-apps.folder' and trashed = false",
                pageSize=100,
                fields="files(id, name)"
            ).execute()
            
            folders = result.get('files', [])
            
            # Format for dynamic options: list of {label, value}
            options = [{'label': folder['name'], 'value': folder['id']} for folder in folders]
            
            return {
                'success': True,
                'options': options,
                'count': len(options)
            }
        except Exception as e:
            logger.error(f"Error listing Google Drive folders: {e}")
            return {
                'success': False,
                'error': str(e)
            }
