"""
Gmail Service for Google Workspace Integration
Handles email operations including sending, reading, searching, labels, and drafts.
"""
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Dict, List, Any, Optional
from datetime import datetime

from .base_client import GoogleWorkspaceBaseClient


class GmailService:
    """Service for Gmail operations"""
    
    def __init__(self, base_client: GoogleWorkspaceBaseClient):
        self.base_client = base_client
        self.service_name = 'gmail'
        self.version = 'v1'
    
    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        html: bool = False
    ) -> Dict[str, Any]:
        """
        Send an email via Gmail
        
        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body
            cc: CC recipients (comma-separated)
            bcc: BCC recipients (comma-separated)
            attachments: List of attachments with 'filename' and 'content' keys
            html: Whether body is HTML
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            # Create message
            if html or attachments:
                message = MIMEMultipart()
                message.attach(MIMEText(body, 'html' if html else 'plain'))
                
                # Add attachments
                if attachments:
                    for attachment in attachments:
                        part = MIMEBase('application', 'octet-stream')
                        # Content from frontend is base64 encoded, decode it first
                        content = attachment['content']
                        if isinstance(content, str):
                            # Decode base64 string to bytes
                            content = base64.b64decode(content)
                        part.set_payload(content)
                        encoders.encode_base64(part)
                        part.add_header(
                            'Content-Disposition',
                            f'attachment; filename= {attachment["filename"]}'
                        )
                        message.attach(part)
            else:
                message = MIMEText(body)
            
            message['to'] = to
            message['subject'] = subject
            if cc:
                message['cc'] = cc
            if bcc:
                message['bcc'] = bcc
            
            # Encode message
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            
            # Send message
            result = service.users().messages().send(
                userId='me',
                body={'raw': raw_message}
            ).execute()
            
            return {
                'success': True,
                'message_id': result.get('id'),
                'thread_id': result.get('threadId'),
                'label_ids': result.get('labelIds', [])
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def read_emails(
        self,
        max_results: int = 10,
        label_ids: Optional[List[str]] = None,
        query: Optional[str] = None,
        include_spam_trash: bool = False
    ) -> Dict[str, Any]:
        """
        Read emails from Gmail
        
        Args:
            max_results: Maximum number of emails to retrieve
            label_ids: Filter by label IDs (e.g., ['INBOX', 'UNREAD'])
            query: Gmail search query
            include_spam_trash: Include spam and trash
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            # List messages
            list_params = {
                'userId': 'me',
                'maxResults': max_results,
                'includeSpamTrash': include_spam_trash
            }
            
            if label_ids:
                list_params['labelIds'] = label_ids
            if query:
                list_params['q'] = query
            
            results = service.users().messages().list(**list_params).execute()
            messages = results.get('messages', [])
            
            # Get full message details
            emails = []
            for msg in messages:
                email_data = service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='full'
                ).execute()
                
                headers = email_data.get('payload', {}).get('headers', [])
                subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
                sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
                date = next((h['value'] for h in headers if h['name'] == 'Date'), '')
                
                emails.append({
                    'id': email_data['id'],
                    'thread_id': email_data.get('threadId'),
                    'subject': subject,
                    'from': sender,
                    'date': date,
                    'snippet': email_data.get('snippet'),
                    'label_ids': email_data.get('labelIds', [])
                })
            
            return {
                'success': True,
                'emails': emails,
                'total': len(emails)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def search_emails(
        self,
        query: str,
        max_results: int = 50
    ) -> Dict[str, Any]:
        """
        Search emails using Gmail search syntax
        
        Args:
            query: Gmail search query (e.g., 'from:user@example.com subject:meeting')
            max_results: Maximum results to return
        """
        return await self.read_emails(
            max_results=max_results,
            query=query
        )
    
    async def create_label(
        self,
        name: str,
        label_list_visibility: str = 'labelShow',
        message_list_visibility: str = 'show'
    ) -> Dict[str, Any]:
        """
        Create a new Gmail label
        
        Args:
            name: Label name
            label_list_visibility: 'labelShow', 'labelShowIfUnread', or 'labelHide'
            message_list_visibility: 'show' or 'hide'
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            label_object = {
                'name': name,
                'labelListVisibility': label_list_visibility,
                'messageListVisibility': message_list_visibility
            }
            
            result = service.users().labels().create(
                userId='me',
                body=label_object
            ).execute()
            
            return {
                'success': True,
                'label_id': result.get('id'),
                'name': result.get('name')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def apply_label(
        self,
        message_ids: List[str],
        label_ids: List[str]
    ) -> Dict[str, Any]:
        """
        Apply labels to messages
        
        Args:
            message_ids: List of message IDs
            label_ids: List of label IDs to apply
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            body = {
                'ids': message_ids,
                'addLabelIds': label_ids
            }
            
            result = service.users().messages().batchModify(
                userId='me',
                body=body
            ).execute()
            
            return {
                'success': True,
                'modified_count': len(message_ids)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        html: bool = False
    ) -> Dict[str, Any]:
        """
        Create an email draft
        
        Args:
            to: Recipient email
            subject: Email subject
            body: Email body
            cc: CC recipients
            html: Whether body is HTML
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            # Create message
            message = MIMEText(body, 'html' if html else 'plain')
            message['to'] = to
            message['subject'] = subject
            if cc:
                message['cc'] = cc
            
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            
            draft = service.users().drafts().create(
                userId='me',
                body={'message': {'raw': raw_message}}
            ).execute()
            
            return {
                'success': True,
                'draft_id': draft.get('id'),
                'message_id': draft.get('message', {}).get('id')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    async def list_drafts(self, max_results: int = 50) -> Dict[str, Any]:
        """List Gmail drafts."""
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            results = service.users().drafts().list(userId='me', maxResults=max_results).execute()
            
            drafts = results.get('drafts', [])
            return {
                'success': True,
                'drafts': drafts,
                'total': len(drafts)
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def get_draft(self, draft_id: str) -> Dict[str, Any]:
        """Get details of a specific draft."""
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            draft = service.users().drafts().get(userId='me', id=draft_id, format='full').execute()
            
            message = draft.get('message', {})
            headers = message.get('payload', {}).get('headers', [])
            
            return {
                'success': True,
                'draft': {
                    'id': draft['id'],
                    'message_id': message.get('id'),
                    'thread_id': message.get('threadId'),
                    'headers': {h['name']: h['value'] for h in headers},
                    'snippet': message.get('snippet')
                }
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def update_draft(
        self,
        draft_id: str,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        html: bool = False
    ) -> Dict[str, Any]:
        """Update an existing draft."""
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            # Create message
            message = MIMEText(body, 'html' if html else 'plain')
            message['to'] = to
            message['subject'] = subject
            if cc:
                message['cc'] = cc
            
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            
            draft = service.users().drafts().update(
                userId='me',
                id=draft_id,
                body={'message': {'raw': raw_message}}
            ).execute()
            
            return {
                'success': True,
                'draft_id': draft.get('id'),
                'message_id': draft.get('message', {}).get('id')
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def delete_email(
        self,
        message_id: str,
        permanent: bool = False
    ) -> Dict[str, Any]:
        """
        Delete an email (move to trash or permanent delete)
        
        Args:
            message_id: Message ID to delete
            permanent: If True, permanently delete; if False, move to trash
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            if permanent:
                service.users().messages().delete(
                    userId='me',
                    id=message_id
                ).execute()
            else:
                service.users().messages().trash(
                    userId='me',
                    id=message_id
                ).execute()
            
            return {
                'success': True,
                'message_id': message_id,
                'permanent': permanent
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def get_email_details(
        self,
        message_id: str
    ) -> Dict[str, Any]:
        """
        Get full details of a specific email
        
        Args:
            message_id: Message ID
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            message = service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            headers = message.get('payload', {}).get('headers', [])
            
            return {
                'success': True,
                'email': {
                    'id': message['id'],
                    'thread_id': message.get('threadId'),
                    'labels': message.get('labelIds', []),
                    'snippet': message.get('snippet'),
                    'headers': {h['name']: h['value'] for h in headers},
                    'payload': message.get('payload')
                }
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    async def watch_inbox(
        self,
        topic_name: Optional[str] = None,
        label_ids: Optional[List[str]] = None,
        label_filter_action: str = 'include'
    ) -> Dict[str, Any]:
        """
        Set up Gmail push notifications via Google Cloud Pub/Sub.
        
        When configured, Gmail will send notifications to the Pub/Sub topic
        whenever matching emails arrive, enabling event-driven processing
        instead of polling.
        
        Args:
            topic_name: Full Pub/Sub topic name. Defaults to GMAIL_PUBSUB_TOPIC from settings.
            label_ids: List of label IDs to watch (e.g., ['INBOX']). If None, watches all.
            label_filter_action: 'include' to only watch specified labels, 'exclude' to watch all except specified
        """
        try:
            # Use platform-configured topic if not explicitly provided
            if not topic_name:
                from ...config import settings
                topic_name = settings.GMAIL_PUBSUB_TOPIC
            service = self.base_client.get_service(self.service_name, self.version)
            
            watch_request = {
                'topicName': topic_name,
                'labelFilterAction': label_filter_action
            }
            
            if label_ids:
                watch_request['labelIds'] = label_ids
            
            result = service.users().watch(
                userId='me',
                body=watch_request
            ).execute()
            
            return {
                'success': True,
                'history_id': result.get('historyId'),
                'expiration': result.get('expiration'),
                'message': f'Gmail watch set up. Notifications will be sent to {topic_name}. Expires at {result.get("expiration")}.'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    async def stop_watch(self) -> Dict[str, Any]:
        """
        Stop receiving Gmail push notifications.
        Cancels the current watch subscription.
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            service.users().stop(userId='me').execute()
            
            return {
                'success': True,
                'message': 'Gmail watch stopped successfully.'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    async def mark_as_read(
        self,
        message_ids: List[str]
    ) -> Dict[str, Any]:
        """
        Mark messages as read by removing the UNREAD label.
        Useful after processing emails in the auto-responder workflow.
        
        Args:
            message_ids: List of message IDs to mark as read
        """
        try:
            service = self.base_client.get_service(self.service_name, self.version)
            
            body = {
                'ids': message_ids,
                'removeLabelIds': ['UNREAD']
            }
            
            service.users().messages().batchModify(
                userId='me',
                body=body
            ).execute()
            
            return {
                'success': True,
                'modified_count': len(message_ids),
                'message': f'Marked {len(message_ids)} message(s) as read.'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
