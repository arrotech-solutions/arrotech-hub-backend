"""
Docs Service for Google Workspace Integration
Handles Google Docs document operations including creation, editing, and formatting.
"""
from typing import Dict, List, Any, Optional

from .base_client import GoogleWorkspaceBaseClient


class DocsService:
    """Service for Google Docs operations"""
    
    def __init__(self, base_client: GoogleWorkspaceBaseClient):
        self.base_client = base_client
        self.service_name = 'docs'
        self.version = 'v1'
    
    async def create_document(
        self,
        title: str
    ) -> Dict[str, Any]:
        """
        Create a new Google Doc
        
        Args:
            title: Document title
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            body = {
                'title': title
            }
            
            doc = service.documents().create(body=body).execute()
            
            return {
                'success': True,
                'document_id': doc.get('documentId'),
                'title': doc.get('title'),
                'revision_id': doc.get('revisionId')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def read_document(
        self,
        document_id: str
    ) -> Dict[str, Any]:
        """
        Read content from a Google Doc
        
        Args:
            document_id: ID of the document
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            doc = service.documents().get(documentId=document_id).execute()
            
            # Extract text content
            content = []
            for element in doc.get('body', {}).get('content', []):
                if 'paragraph' in element:
                    paragraph = element.get('paragraph', {})
                    for elem in paragraph.get('elements', []):
                        if 'textRun' in elem:
                            content.append(elem.get('textRun', {}).get('content', ''))
            
            full_text = ''.join(content)
            
            return {
                'success': True,
                'document_id': doc.get('documentId'),
                'title': doc.get('title'),
                'revision_id': doc.get('revisionId'),
                'content': full_text,
                'body': doc.get('body')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def insert_text(
        self,
        document_id: str,
        text: str,
        index: int = 1
    ) -> Dict[str, Any]:
        """
        Insert text into a document
        
        Args:
            document_id: ID of the document
            text: Text to insert
            index: Position to insert text (default 1, start of document)
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            requests = [{
                'insertText': {
                    'location': {
                        'index': index
                    },
                    'text': text
                }
            }]
            
            result = service.documents().batchUpdate(
                documentId=document_id,
                body={'requests': requests}
            ).execute()
            
            return {
                'success': True,
                'document_id': document_id,
                'revision_id': result.get('documentId')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def append_text(
        self,
        document_id: str,
        text: str
    ) -> Dict[str, Any]:
        """
        Append text to the end of a document
        
        Args:
            document_id: ID of the document
            text: Text to append
        """
        try:
            # First, get document to find end index
            doc_result = await self.read_document(document_id)
            if not doc_result.get('success'):
                return doc_result
            
            service = await self.base_client.get_service(self.service_name, self.version)
            
            # Get the end index from the document body
            doc = service.documents().get(documentId=document_id).execute()
            end_index = doc.get('body', {}).get('content', [{}])[-1].get('endIndex', 1)
            
            return await self.insert_text(document_id, text, end_index - 1)
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def replace_text(
        self,
        document_id: str,
        find_text: str,
        replace_text: str,
        match_case: bool = False
    ) -> Dict[str, Any]:
        """
        Replace text in a document
        
        Args:
            document_id: ID of the document
            find_text: Text to find
            replace_text: Replacement text
            match_case: Whether to match case
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            requests = [{
                'replaceAllText': {
                    'containsText': {
                        'text': find_text,
                        'matchCase': match_case
                    },
                    'replaceText': replace_text
                }
            }]
            
            result = service.documents().batchUpdate(
                documentId=document_id,
                body={'requests': requests}
            ).execute()
            
            occurrences_changed = result.get('replies', [{}])[0].get('replaceAllText', {}).get('occurrencesChanged', 0)
            
            return {
                'success': True,
                'document_id': document_id,
                'occurrences_changed': occurrences_changed
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def format_text(
        self,
        document_id: str,
        start_index: int,
        end_index: int,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        font_size: Optional[int] = None,
        foreground_color: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Apply formatting to text
        
        Args:
            document_id: ID of the document
            start_index: Start position
            end_index: End position
            bold: Make text bold
            italic: Make text italic
            font_size: Font size in points
            foreground_color: Color dict with 'red', 'green', 'blue' (0-1)
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            text_style = {}
            fields = []
            
            if bold is not None:
                text_style['bold'] = bold
                fields.append('bold')
            if italic is not None:
                text_style['italic'] = italic
                fields.append('italic')
            if font_size is not None:
                text_style['fontSize'] = {'magnitude': font_size, 'unit': 'PT'}
                fields.append('fontSize')
            if foreground_color is not None:
                text_style['foregroundColor'] = {
                    'color': {
                        'rgbColor': foreground_color
                    }
                }
                fields.append('foregroundColor')
            
            requests = [{
                'updateTextStyle': {
                    'range': {
                        'startIndex': start_index,
                        'endIndex': end_index
                    },
                    'textStyle': text_style,
                    'fields': ','.join(fields)
                }
            }]
            
            result = service.documents().batchUpdate(
                documentId=document_id,
                body={'requests': requests}
            ).execute()
            
            return {
                'success': True,
                'document_id': document_id
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def insert_table(
        self,
        document_id: str,
        rows: int,
        columns: int,
        index: int = 1
    ) -> Dict[str, Any]:
        """
        Insert a table into the document
        
        Args:
            document_id: ID of the document
            rows: Number of rows
            columns: Number of columns
            index: Position to insert table
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            requests = [{
                'insertTable': {
                    'rows': rows,
                    'columns': columns,
                    'location': {
                        'index': index
                    }
                }
            }]
            
            result = service.documents().batchUpdate(
                documentId=document_id,
                body={'requests': requests}
            ).execute()
            
            return {
                'success': True,
                'document_id': document_id
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def batch_update(
        self,
        document_id: str,
        requests: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Execute batch updates on a document
        
        Args:
            document_id: ID of the document
            requests: List of update requests
        """
        try:
            service = await self.base_client.get_service(self.service_name, self.version)
            
            result = service.documents().batchUpdate(
                documentId=document_id,
                body={'requests': requests}
            ).execute()
            
            return {
                'success': True,
                'document_id': result.get('documentId'),
                'replies': result.get('replies', [])
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def export_as_pdf(
        self,
        document_id: str
    ) -> Dict[str, Any]:
        """
        Export document as PDF
        
        Args:
            document_id: ID of the document
        """
        try:
            # Use Drive API to export
            drive_service = await self.base_client.get_service('drive', 'v3')
            
            request = drive_service.files().export_media(
                fileId=document_id,
                mimeType='application/pdf'
            )
            
            import io
            from googleapiclient.http import MediaIoBaseDownload
            
            file_buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(file_buffer, request)
            
            done = False
            while not done:
                status, done = downloader.next_chunk()
            
            file_buffer.seek(0)
            
            return {
                'success': True,
                'document_id': document_id,
                'pdf_content': file_buffer.getvalue()
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
