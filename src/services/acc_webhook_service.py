"""
ACC Webhook Service

Service to manage ACC webhooks for real-time issue notifications.
Replaces polling with efficient real-time event-driven monitoring.
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Connection, ConnectionStatus

logger = logging.getLogger(__name__)


class ACCWebhookService:
    """Service to manage ACC webhooks for real-time notifications."""
    
    def __init__(self):
        # Webhook events we want to monitor for ACC issues
        self.supported_events = [
            'issue.created-1.0',   # New issue created
            'issue.updated-1.0',   # Issue updated
            'issue.deleted-1.0',   # Issue deleted
            'issue.restored-1.0',  # Issue restored
            'issue.unlinked-1.0',  # Issue unlinked
        ]
        
        # Store active webhooks per user
        self.active_webhooks: Dict[int, List[Dict]] = {}  # user_id -> [webhook_configs]
    
    def _clean_project_id_for_issues_api(self, project_id: str) -> str:
        """Remove 'b.' prefix from project ID for Issues API calls."""
        if not project_id:
            return project_id
        return project_id.replace('b.', '') if project_id.startswith('b.') else project_id
    
    def _clean_issue_id_for_issues_api(self, issue_id: str) -> str:
        """Remove 'b.' prefix from issue ID for Issues API calls."""
        if not issue_id:
            return issue_id
        return issue_id.replace('b.', '') if issue_id.startswith('b.') else issue_id
    
    def _ensure_hub_id_prefix(self, hub_id: str) -> str:
        """Ensure hub ID has 'b.' prefix for Project API calls."""
        if not hub_id:
            return hub_id
        return hub_id if hub_id.startswith('b.') else f'b.{hub_id}'
        
    async def register_webhooks_for_user(
        self, 
        user_id: int, 
        connection: Any, 
        callback_url: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Register webhooks for all projects accessible to a user."""
        try:
            logger.info(f"[WEBHOOK SERVICE DEBUG] Starting webhook registration for user {user_id}")
            logger.info(f"[WEBHOOK SERVICE DEBUG] Connection type: {type(connection)}")
            logger.info(f"[WEBHOOK SERVICE DEBUG] Callback URL: {callback_url}")
            
            # Get access token from connection
            logger.info(f"[WEBHOOK SERVICE DEBUG] Getting access token from connection config...")
            access_token = connection.config.get('access_token')  # Fixed: use 'access_token' not 'APS_ACCESS_TOKEN'
            logger.info(f"[WEBHOOK SERVICE DEBUG] Access token found: {bool(access_token)}")
            logger.info(f"[WEBHOOK SERVICE DEBUG] Available config keys: {list(connection.config.keys())}")
            
            if access_token:
                logger.info(f"[WEBHOOK SERVICE DEBUG] Access token length: {len(access_token)}")
                logger.info(f"[WEBHOOK SERVICE DEBUG] Access token prefix: {access_token[:20]}...")
            else:
                logger.error(f"[WEBHOOK SERVICE DEBUG] No access token found in connection config")
                logger.error(f"[WEBHOOK SERVICE DEBUG] Available config keys: {list(connection.config.keys())}")
                return {
                    'success': False,
                    'message': 'No access token found in connection',
                    'webhooks': [],
                    'registration_summary': {
                        'total_attempted': 0,
                        'successful': 0,
                        'failed': 0,
                        'success_rate': 0,
                        'failed_details': [
                            {
                                'project_id': 'N/A',
                                'project_name': 'N/A',
                                'event_type': 'N/A',
                                'error': 'No access token found in connection config',
                                'error_type': 'missing_token'
                            }
                        ]
                    }
                }
            
            registered_webhooks = []
            failed_webhooks = []
            total_webhooks_attempted = 0
            
            # Get all hubs for the user
            logger.info(f"[WEBHOOK SERVICE DEBUG] Getting hubs for user...")
            hubs_response = await self._get_hubs(access_token)
            logger.info(f"[WEBHOOK SERVICE DEBUG] Hubs response type: {type(hubs_response)}")
            logger.info(f"[WEBHOOK SERVICE DEBUG] Hubs response success: {hubs_response.get('success', True)}")
            
            if not hubs_response.get('success', True):
                logger.error(f"[WEBHOOK SERVICE DEBUG] Failed to get hubs: {hubs_response}")
                return {
                    'success': False,
                    'message': 'Failed to get hubs',
                    'webhooks': [],
                    'registration_summary': {
                        'total_attempted': 0,
                        'successful': 0,
                        'failed': 0,
                        'failed_details': []
                    }
                }
            
            hubs = self._extract_data_from_response(hubs_response)
            logger.info(f"[WEBHOOK SERVICE DEBUG] Extracted {len(hubs)} hubs")
            
            for hub_idx, hub in enumerate(hubs):
                hub_id = hub.get('id', '')
                hub_name = hub.get('attributes', {}).get('name', 'Unknown')
                logger.info(f"[WEBHOOK SERVICE DEBUG] Processing hub {hub_idx+1}/{len(hubs)}: {hub_name} ({hub_id})")
                
                if not hub_id:
                    logger.warning(f"[WEBHOOK SERVICE DEBUG] Skipping hub with no ID: {hub}")
                    continue
                
                # Get projects for this hub
                logger.info(f"[WEBHOOK SERVICE DEBUG] Getting projects for hub {hub_id}...")
                try:
                    projects_response = await self._get_projects(access_token, hub_id)
                    logger.info(f"[WEBHOOK SERVICE DEBUG] Projects response for hub {hub_id}: success={projects_response.get('success', True)}")
                except Exception as e:
                    logger.error(f"[WEBHOOK SERVICE DEBUG] Exception getting projects for hub {hub_id}: {e}")
                    continue
                
                if not projects_response.get('success', True):
                    logger.warning(f"[WEBHOOK SERVICE DEBUG] Failed to get projects for hub {hub_id}: {projects_response}")
                    continue
                
                projects = self._extract_data_from_response(projects_response)
                logger.info(f"[WEBHOOK SERVICE DEBUG] Extracted {len(projects)} projects for hub {hub_id}")
                
                for project_idx, project in enumerate(projects):
                    project_id_raw = project.get('id', '')
                    project_name = project.get('attributes', {}).get('name', 'Unknown')
                    
                    # Strip "b." prefix from project ID for Issues API
                    project_id = self._clean_project_id_for_issues_api(project_id_raw)
                    
                    logger.info(f"[WEBHOOK SERVICE DEBUG] Processing project {project_idx+1}/{len(projects)}: {project_name}")
                    logger.info(f"[WEBHOOK SERVICE DEBUG] Project ID raw: {project_id_raw} -> processed: {project_id}")
                    
                    if not project_id:
                        logger.warning(f"[WEBHOOK SERVICE DEBUG] Skipping project with no ID: {project}")
                        continue
                    
                    # Register webhooks for all supported ACC issue events
                    for event_idx, event_type in enumerate(self.supported_events):
                        total_webhooks_attempted += 1
                        logger.info(f"[WEBHOOK SERVICE DEBUG] Registering webhook {event_idx+1}/{len(self.supported_events)} for project {project_id}, event {event_type}")
                        logger.info(f"[WEBHOOK SERVICE DEBUG] Progress: {total_webhooks_attempted} webhooks attempted so far")
                        
                        try:
                            webhook_result = await self._register_project_webhook_for_event(
                                access_token, project_id, callback_url, event_type
                            )
                            logger.info(f"[WEBHOOK SERVICE DEBUG] Webhook registration result for {project_id}/{event_type}: {webhook_result}")
                        except Exception as e:
                            logger.error(f"[WEBHOOK SERVICE DEBUG] Exception registering webhook for {project_id}/{event_type}: {e}")
                            import traceback
                            logger.error(f"[WEBHOOK SERVICE DEBUG] Webhook registration traceback:\n{traceback.format_exc()}")
                            
                            # Track failed webhook
                            failed_webhook = {
                                'project_id': project_id,
                                'project_name': project_name,
                                'event_type': event_type,
                                'error': f'Exception: {str(e)}',
                                'error_type': 'exception'
                            }
                            failed_webhooks.append(failed_webhook)
                            logger.error(f"[WEBHOOK FAILURE] ❌ Failed to register webhook for {project_name} ({project_id}), event {event_type}: Exception {str(e)}")
                            continue
                        
                        if webhook_result.get('success', False):
                            webhook_config = {
                                'user_id': user_id,
                                'project_id': project_id,
                                'hub_id': hub_id,
                                'webhook_id': webhook_result.get('webhook_id'),
                                'callback_url': callback_url,
                                'event_type': event_type,
                                'created_at': datetime.utcnow().isoformat(),
                                'status': 'active'
                            }
                            registered_webhooks.append(webhook_config)
                            
                            logger.info(f"[WEBHOOK SUCCESS] ✅ Successfully registered webhook for {project_name} ({project_id}), event {event_type}")
                            logger.info(f"[WEBHOOK SUCCESS] Webhook ID: {webhook_result.get('webhook_id')}")
                        else:
                            error_msg = webhook_result.get('error', webhook_result.get('message', 'Unknown error'))
                            error_type = webhook_result.get('error_type', 'api_error')
                            
                            # Check if this is a permission error
                            if error_type == 'permission_denied' or webhook_result.get('skip_project', False):
                                # Permission error - log as warning and continue
                                logger.warning(f"[WEBHOOK PERMISSION] ⚠️ Permission denied for {project_name} ({project_id}), event {event_type}")
                                logger.warning(f"[WEBHOOK PERMISSION] This project will be skipped. Your access token doesn't have webhook permissions for this project.")
                                logger.warning(f"[WEBHOOK PERMISSION] Error details: {error_msg}")
                                
                                # Track as permission issue (not a critical failure)
                                failed_webhook = {
                                    'project_id': project_id,
                                    'project_name': project_name,
                                    'event_type': event_type,
                                    'error': error_msg,
                                    'error_type': 'permission_denied'
                                }
                                failed_webhooks.append(failed_webhook)
                            else:
                                # Other API errors - log as error
                                failed_webhook = {
                                    'project_id': project_id,
                                    'project_name': project_name,
                                    'event_type': event_type,
                                    'error': error_msg,
                                    'error_type': error_type
                                }
                                failed_webhooks.append(failed_webhook)
                                logger.error(f"[WEBHOOK FAILURE] ❌ Failed to register webhook for {project_name} ({project_id}), event {event_type}: {error_msg}")
            
            # Store webhooks in memory and database
            if user_id not in self.active_webhooks:
                self.active_webhooks[user_id] = []
            self.active_webhooks[user_id].extend(registered_webhooks)
            
            # Create comprehensive registration summary
            successful_count = len(registered_webhooks)
            failed_count = len(failed_webhooks)
            success_rate = (successful_count / total_webhooks_attempted * 100) if total_webhooks_attempted > 0 else 0
            
            # Separate permission errors from actual failures
            permission_errors = [f for f in failed_webhooks if f.get('error_type') == 'permission_denied']
            api_errors = [f for f in failed_webhooks if f.get('error_type') != 'permission_denied']
            permission_count = len(permission_errors)
            api_error_count = len(api_errors)
            
            # Log comprehensive summary
            logger.info(f"")
            logger.info(f"🎯 ===== WEBHOOK REGISTRATION SUMMARY FOR USER {user_id} =====")
            logger.info(f"📊 Total webhooks attempted: {total_webhooks_attempted}")
            logger.info(f"✅ Successfully registered: {successful_count}")
            logger.info(f"⚠️ Permission denied (skipped): {permission_count}")
            logger.info(f"❌ API errors: {api_error_count}")
            logger.info(f"📈 Success rate: {success_rate:.1f}%")
            logger.info(f"🔗 Callback URL: {callback_url}")
            
            if successful_count > 0:
                logger.info(f"")
                logger.info(f"✅ SUCCESSFUL WEBHOOK REGISTRATIONS:")
                for webhook in registered_webhooks:
                    logger.info(f"   • Project: {webhook['project_id']} | Event: {webhook['event_type']} | Webhook ID: {webhook['webhook_id']}")
            
            if permission_count > 0:
                logger.info(f"")
                logger.warning(f"⚠️ PERMISSION DENIED (PROJECTS SKIPPED):")
                for failed in permission_errors:
                    logger.warning(f"   • Project: {failed['project_name']} ({failed['project_id']}) | Event: {failed['event_type']}")
                    logger.warning(f"     Reason: Access token lacks webhook permissions for this project")
                logger.warning(f"⚠️ Note: Permission errors are expected if your access token doesn't have admin rights to all projects.")
                
            if api_error_count > 0:
                logger.info(f"")
                logger.error(f"❌ ACTUAL API FAILURES:")
                for failed in api_errors:
                    logger.error(f"   • Project: {failed['project_name']} ({failed['project_id']}) | Event: {failed['event_type']}")
                    logger.error(f"     Error: {failed['error']}")
            
            logger.info(f"🏁 ===== END WEBHOOK REGISTRATION SUMMARY =====")
            logger.info(f"")
            
            # Determine overall success - successful if we registered at least one webhook
            # Permission errors don't count as failures since they're expected
            overall_success = successful_count > 0
            
            registration_summary = {
                'total_attempted': total_webhooks_attempted,
                'successful': successful_count,
                'failed': failed_count,
                'permission_denied': permission_count,
                'api_errors': api_error_count,
                'success_rate': success_rate,
                'failed_details': failed_webhooks
            }
            
            if permission_count > 0 and api_error_count == 0:
                result_message = f"Registered {successful_count}/{total_webhooks_attempted} webhooks ({success_rate:.1f}% success rate). {permission_count} projects skipped due to permissions."
            else:
                result_message = f"Registered {successful_count}/{total_webhooks_attempted} webhooks ({success_rate:.1f}% success rate)"
            
            return {
                'success': overall_success,
                'message': result_message,
                'webhooks': registered_webhooks,
                'registration_summary': registration_summary
            }
            
        except Exception as e:
            logger.error(f"❌ CRITICAL ERROR: Exception during webhook registration for user {user_id}: {e}")
            import traceback
            logger.error(f"❌ Exception traceback:\n{traceback.format_exc()}")
            return {
                'success': False,
                'message': f'Error registering webhooks: {str(e)}',
                'webhooks': [],
                'registration_summary': {
                    'total_attempted': 0,
                    'successful': 0,
                    'failed': 0,
                    'success_rate': 0,
                    'failed_details': [
                        {
                            'project_id': 'N/A',
                            'project_name': 'N/A',
                            'event_type': 'N/A',
                            'error': f'Critical exception: {str(e)}',
                            'error_type': 'critical_exception'
                        }
                    ]
                }
            }
    
    async def register_webhook_for_specific_project(
        self,
        user_id: int,
        connection: Any,
        project_id: str,
        callback_url: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Register webhooks for a specific project only."""
        try:
            logger.info(f"[SPECIFIC WEBHOOK] Registering webhooks for specific project {project_id} for user {user_id}")
            logger.info(f"[SPECIFIC WEBHOOK] Callback URL: {callback_url}")
            
            # Get access token from connection
            access_token = connection.config.get('access_token')
            if not access_token:
                return {
                    'success': False,
                    'message': 'No access token found in connection',
                    'webhooks': [],
                    'registration_summary': {
                        'total_attempted': 0,
                        'successful': 0,
                        'failed': 0,
                        'success_rate': 0,
                        'failed_details': []
                    }
                }
            
            registered_webhooks = []
            failed_webhooks = []
            total_webhooks_attempted = 0
            
            # Clean project ID for Issues API
            clean_project_id = self._clean_project_id_for_issues_api(project_id)
            logger.info(f"[SPECIFIC WEBHOOK] Using clean project ID: {clean_project_id}")
            
            # Register webhooks for all supported ACC issue events for this specific project
            for event_type in self.supported_events:
                total_webhooks_attempted += 1
                logger.info(f"[SPECIFIC WEBHOOK] Registering webhook for event {event_type}")
                
                try:
                    webhook_result = await self._register_project_webhook_for_event(
                        access_token, clean_project_id, callback_url, event_type
                    )
                    logger.info(f"[SPECIFIC WEBHOOK] Result for {event_type}: {webhook_result}")
                    
                    if webhook_result.get('success', False):
                        webhook_config = {
                            'user_id': user_id,
                            'project_id': clean_project_id,
                            'webhook_id': webhook_result.get('webhook_id'),
                            'callback_url': callback_url,
                            'event_type': event_type,
                            'created_at': datetime.utcnow().isoformat(),
                            'status': 'active'
                        }
                        registered_webhooks.append(webhook_config)
                        logger.info(f"[SPECIFIC WEBHOOK] ✅ Successfully registered webhook for event {event_type}")
                    else:
                        error_msg = webhook_result.get('error', 'Unknown error')
                        failed_webhook = {
                            'project_id': clean_project_id,
                            'project_name': f'Project {clean_project_id}',
                            'event_type': event_type,
                            'error': error_msg,
                            'error_type': webhook_result.get('error_type', 'api_error')
                        }
                        failed_webhooks.append(failed_webhook)
                        logger.error(f"[SPECIFIC WEBHOOK] ❌ Failed to register webhook for event {event_type}: {error_msg}")
                        
                except Exception as e:
                    logger.error(f"[SPECIFIC WEBHOOK] Exception registering webhook for {event_type}: {e}")
                    failed_webhook = {
                        'project_id': clean_project_id,
                        'project_name': f'Project {clean_project_id}',
                        'event_type': event_type,
                        'error': f'Exception: {str(e)}',
                        'error_type': 'exception'
                    }
                    failed_webhooks.append(failed_webhook)
            
            # Store webhooks in memory
            if user_id not in self.active_webhooks:
                self.active_webhooks[user_id] = []
            self.active_webhooks[user_id].extend(registered_webhooks)
            
            # Create registration summary
            successful_count = len(registered_webhooks)
            failed_count = len(failed_webhooks)
            success_rate = (successful_count / total_webhooks_attempted * 100) if total_webhooks_attempted > 0 else 0
            overall_success = successful_count > 0
            
            logger.info(f"")
            logger.info(f"🎯 ===== SPECIFIC PROJECT WEBHOOK SUMMARY =====")
            logger.info(f"📊 Project ID: {clean_project_id}")
            logger.info(f"📊 Total webhooks attempted: {total_webhooks_attempted}")
            logger.info(f"✅ Successfully registered: {successful_count}")
            logger.info(f"❌ Failed: {failed_count}")
            logger.info(f"📈 Success rate: {success_rate:.1f}%")
            logger.info(f"🔗 Callback URL: {callback_url}")
            logger.info(f"🏁 ===== END SPECIFIC PROJECT SUMMARY =====")
            logger.info(f"")
            
            registration_summary = {
                'total_attempted': total_webhooks_attempted,
                'successful': successful_count,
                'failed': failed_count,
                'success_rate': success_rate,
                'failed_details': failed_webhooks
            }
            
            result_message = f"Registered {successful_count}/{total_webhooks_attempted} webhooks for project {clean_project_id}"
            
            return {
                'success': overall_success,
                'message': result_message,
                'webhooks': registered_webhooks,
                'registration_summary': registration_summary,
                'project_id': clean_project_id
            }
            
        except Exception as e:
            logger.error(f"❌ CRITICAL ERROR: Exception during specific project webhook registration: {e}")
            import traceback
            logger.error(f"❌ Exception traceback:\n{traceback.format_exc()}")
            return {
                'success': False,
                'message': f'Error registering webhooks for project {project_id}: {str(e)}',
                'webhooks': [],
                'registration_summary': {
                    'total_attempted': 0,
                    'successful': 0,
                    'failed': 0,
                    'success_rate': 0,
                    'failed_details': []
                }
            }
    
    async def _get_existing_webhooks(self, access_token: str, project_id: str, event_type: str) -> Dict[str, Any]:
        """Get existing webhooks for a project and event type using GET /webhooks/v1/hooks."""
        try:
            # Use the GET webhooks endpoint as per Autodesk documentation
            # https://aps.autodesk.com/en/docs/webhooks/v1/reference/http/webhooks/hooks-GET/
            get_hooks_url = "https://developer.api.autodesk.com/webhooks/v1/hooks"
            
            clean_project_id = self._clean_project_id_for_issues_api(project_id)
            
            # Query parameters to filter hooks for this project and event type
            params = {
                'system': 'autodesk.construction.issues',
                'event': event_type,
                'scopeName': 'project',
                'scopeValue': clean_project_id
            }
            
            logger.info(f"[WEBHOOK GET DEBUG] Getting existing webhooks")
            logger.info(f"[WEBHOOK GET DEBUG] URL: {get_hooks_url}")
            logger.info(f"[WEBHOOK GET DEBUG] Params: {params}")
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    get_hooks_url,
                    params=params,
                    headers=headers,
                    timeout=30
                )
                
                logger.info(f"[WEBHOOK GET DEBUG] Response status: {response.status_code}")
                logger.info(f"[WEBHOOK GET DEBUG] Response body: {response.text}")
                
                if response.status_code == 200:
                    hooks_data = response.json()
                    return {
                        'success': True,
                        'hooks': hooks_data.get('data', []),
                        'total': len(hooks_data.get('data', []))
                    }
                elif response.status_code == 403:
                    logger.warning(f"[WEBHOOK GET DEBUG] Permission denied getting hooks")
                    return {
                        'success': False,
                        'error': 'Permission denied',
                        'error_type': 'permission_denied'
                    }
                else:
                    logger.error(f"[WEBHOOK GET DEBUG] Error getting hooks: {response.status_code}")
                    return {
                        'success': False,
                        'error': f'HTTP {response.status_code}: {response.text}'
                    }
                    
        except Exception as e:
            logger.error(f"[WEBHOOK GET DEBUG] Exception getting hooks: {e}")
            return {
                'success': False,
                'error': f'Exception: {str(e)}'
            }

    async def _register_project_webhook_for_event(
        self, 
        access_token: str, 
        project_id: str, 
        callback_url: str,
        event_type: str
    ) -> Dict[str, Any]:
        """Register a webhook for a specific project and event type."""
        try:
            # First, check for existing webhooks to prevent 409 conflicts
            logger.info(f"[WEBHOOK REGISTER DEBUG] Checking for existing webhooks first...")
            existing_hooks_result = await self._get_existing_webhooks(access_token, project_id, event_type)
            
            if existing_hooks_result.get('success'):
                existing_hooks = existing_hooks_result.get('hooks', [])
                
                # Check if webhook already exists for this callback URL
                for hook in existing_hooks:
                    if hook.get('callbackUrl') == callback_url:
                        logger.info(f"[WEBHOOK REGISTER DEBUG] Webhook already exists: {hook.get('hookId')}")
                        return {
                            'success': True,
                            'webhook_id': hook.get('hookId'),
                            'webhook_data': hook,
                            'note': 'Webhook already exists'
                        }
                
                logger.info(f"[WEBHOOK REGISTER DEBUG] Found {len(existing_hooks)} existing hooks, none match our callback URL")
            else:
                logger.warning(f"[WEBHOOK REGISTER DEBUG] Could not get existing hooks: {existing_hooks_result.get('error')}")
                # Continue with registration attempt even if we can't get existing hooks
                
            # Use the correct ACC issues webhook endpoint structure
            # Format: /webhooks/v1/systems/autodesk.construction.issues/events/{event_type}/hooks
            webhook_url = f"https://developer.api.autodesk.com/webhooks/v1/systems/autodesk.construction.issues/events/{event_type}/hooks"
            
            logger.info(f"[WEBHOOK HTTP DEBUG] Starting webhook registration")
            logger.info(f"[WEBHOOK HTTP DEBUG] URL: {webhook_url}")
            logger.info(f"[WEBHOOK HTTP DEBUG] Project ID: {project_id}")
            logger.info(f"[WEBHOOK HTTP DEBUG] Event Type: {event_type}")
            logger.info(f"[WEBHOOK HTTP DEBUG] Callback URL: {callback_url}")
            
            # Ensure project_id has no "b." prefix for Issues API
            clean_project_id = self._clean_project_id_for_issues_api(project_id)
            
            # Create webhook payload for ACC issues matching the official Autodesk example
            webhook_payload = {
                "callbackUrl": callback_url,
                "scope": {
                    "project": clean_project_id  # Use "project" instead of "workflow"
                },
                "hookAttribute": {
                    "projectId": clean_project_id  # Only projectId, no hubId
                }
            }
            
            logger.info(f"[WEBHOOK HTTP DEBUG] Payload: {webhook_payload}")
            
            headers = {
                'Authorization': f'Bearer {access_token[:20]}...',
                'Content-Type': 'application/json'
            }
            
            logger.info(f"[WEBHOOK HTTP DEBUG] Headers (token masked): {headers}")
            logger.info(f"[WEBHOOK HTTP DEBUG] Making HTTP POST request...")
            
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.post(
                        webhook_url,
                        json=webhook_payload,
                        headers={
                            'Authorization': f'Bearer {access_token}',
                            'Content-Type': 'application/json'
                        },
                        timeout=30
                    )
                    
                    logger.info(f"[WEBHOOK HTTP DEBUG] Response status: {response.status_code}")
                    logger.info(f"[WEBHOOK HTTP DEBUG] Response headers: {dict(response.headers)}")
                    
                    response_text = response.text
                    logger.info(f"[WEBHOOK HTTP DEBUG] Response body: {response_text}")
                    
                    if response.status_code == 201:
                        # Success - parse JSON response
                        try:
                            if response_text.strip():  # Check if response is not empty
                                webhook_data = response.json()
                                logger.info(f"[WEBHOOK HTTP DEBUG] Successfully created webhook: {webhook_data}")
                                return {
                                    'success': True,
                                    'webhook_id': webhook_data.get('hookId'),
                                    'webhook_data': webhook_data
                                }
                            else:
                                logger.warning(f"[WEBHOOK HTTP DEBUG] Empty response body for successful request")
                                return {
                                    'success': True,
                                    'webhook_id': 'unknown',
                                    'webhook_data': {},
                                    'note': 'Empty response body'
                                }
                        except json.JSONDecodeError as json_error:
                            logger.error(f"[WEBHOOK HTTP DEBUG] JSON decode error on success response: {json_error}")
                            return {
                                'success': True,  # Still consider it success since status was 201
                                'webhook_id': 'unknown',
                                'webhook_data': {},
                                'note': f'JSON decode error: {str(json_error)}'
                            }
                    elif response.status_code == 403:
                        # Permission error - handle gracefully (don't fail webhook mode)
                        logger.warning(f"[WEBHOOK HTTP DEBUG] Permission denied (403) - webhook already exists or insufficient permissions")
                        logger.warning(f"[WEBHOOK HTTP DEBUG] This means your access token doesn't have webhook permissions for this project")
                        try:
                            if response_text.strip():
                                error_data = response.json()
                                detail_msg = error_data.get('detail', ['Unknown permission error'])[0] if isinstance(error_data.get('detail'), list) else 'Unknown permission error'
                            else:
                                detail_msg = 'Permission denied (empty response)'
                        except json.JSONDecodeError:
                            detail_msg = 'Permission denied (invalid JSON response)'
                        
                        return {
                            'success': True,  # Don't fail webhook mode for permission issues
                            'webhook_id': 'permission_denied',
                            'webhook_data': {},
                            'error': f'Permission denied: {detail_msg}',
                            'error_type': 'permission_denied',
                            'note': 'Webhook registration skipped due to permissions'
                        }
                    elif response.status_code == 409:
                        # Conflict error - webhook already exists (don't fail webhook mode)
                        logger.warning(f"[WEBHOOK HTTP DEBUG] Conflict (409) - webhook already exists for this event/project")
                        try:
                            if response_text.strip():
                                error_data = response.json()
                                detail_msg = error_data.get('detail', ['Webhook already exists'])[0] if isinstance(error_data.get('detail'), list) else 'Webhook already exists'
                            else:
                                detail_msg = 'Webhook already exists (empty response)'
                        except json.JSONDecodeError:
                            detail_msg = 'Webhook already exists (invalid JSON response)'
                        
                        return {
                            'success': True,  # Don't fail webhook mode for conflicts
                            'webhook_id': 'already_exists',
                            'webhook_data': {},
                            'error': f'Webhook conflict: {detail_msg}',
                            'error_type': 'conflict',
                            'note': 'Webhook already exists for this event/project'
                        }
                    else:
                        # Other HTTP errors - these might indicate real issues
                        logger.error(f"[WEBHOOK HTTP DEBUG] HTTP error {response.status_code}: {response_text}")
                        try:
                            if response_text.strip():
                                error_data = response.json()
                                error_detail = str(error_data)
                            else:
                                error_detail = "Empty response"
                        except json.JSONDecodeError:
                            error_detail = response_text if response_text else "Empty response"
                        
                        return {
                            'success': False,
                            'error': f'HTTP {response.status_code}: {error_detail}',
                            'error_type': 'http_error'
                        }
                        
                except httpx.TimeoutException as e:
                    logger.error(f"[WEBHOOK HTTP DEBUG] Request timeout: {e}")
                    return {
                        'success': False,
                        'error': f'Request timeout: {str(e)}'
                    }
                except httpx.HTTPError as e:
                    logger.error(f"[WEBHOOK HTTP DEBUG] HTTP error: {e}")
                    return {
                        'success': False,
                        'error': f'HTTP error: {str(e)}'
                    }
                    
        except Exception as e:
            import traceback
            logger.error(f"[WEBHOOK HTTP DEBUG] Exception in webhook registration: {e}")
            logger.error(f"[WEBHOOK HTTP DEBUG] Exception traceback:\n{traceback.format_exc()}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def unregister_webhooks_for_user(
        self, 
        user_id: int, 
        connection: Any
    ) -> Dict[str, Any]:
        """Unregister all webhooks for a user."""
        try:
            logger.info(f"Unregistering ACC webhooks for user {user_id}")
            
            if user_id not in self.active_webhooks:
                return {
                    'success': True,
                    'message': 'No webhooks to unregister',
                    'unregistered_count': 0
                }
            
            access_token = connection.config.get('access_token')  # Fixed: use 'access_token' not 'APS_ACCESS_TOKEN'
            if not access_token:
                return {
                    'success': False,
                    'message': 'No access token found in connection'
                }
            
            webhooks = self.active_webhooks[user_id]
            unregistered_count = 0
            
            for webhook_config in webhooks:
                webhook_id = webhook_config.get('webhook_id')
                event_type = webhook_config.get('event_type')
                if webhook_id:
                    unregister_result = await self._unregister_webhook(access_token, webhook_id, event_type)
                    if unregister_result.get('success', False):
                        unregistered_count += 1
                        logger.info(f"Unregistered webhook {webhook_id} for event {event_type}")
                    else:
                        logger.warning(f"Failed to unregister webhook {webhook_id} for event {event_type}")
            
            # Clean up from memory
            del self.active_webhooks[user_id]
            
            return {
                'success': True,
                'message': f'Unregistered {unregistered_count} webhooks',
                'unregistered_count': unregistered_count
            }
            
        except Exception as e:
            logger.error(f"Error unregistering webhooks for user {user_id}: {e}")
            return {
                'success': False,
                'message': f'Error unregistering webhooks: {str(e)}'
            }
    
    async def _unregister_webhook(self, access_token: str, webhook_id: str, event_type: str = None) -> Dict[str, Any]:
        """Unregister a specific webhook."""
        try:
            # For ACC issues, use the system-specific endpoint if event_type is provided
            if event_type:
                webhook_url = f"https://developer.api.autodesk.com/webhooks/v1/systems/autodesk.construction.issues/events/{event_type}/hooks/{webhook_id}"
            else:
                # Fallback to generic endpoint if event_type not available
                webhook_url = f"https://developer.api.autodesk.com/webhooks/v1/hooks/{webhook_id}"
            
            logger.info(f"Unregistering webhook {webhook_id} at {webhook_url}")
            
            headers = {
                'Authorization': f'Bearer {access_token}'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.delete(webhook_url, headers=headers, timeout=30)
                
                if response.status_code == 204:
                    return {'success': True}
                else:
                    error_text = response.text
                    logger.error(f"Failed to unregister webhook: {response.status_code} - {error_text}")
                    return {
                        'success': False,
                        'error': f'HTTP {response.status_code}: {error_text}'
                    }
                    
        except Exception as e:
            logger.error(f"Error unregistering webhook: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def verify_webhook_signature(
        self, 
        payload: bytes, 
        signature: str, 
        secret: str
    ) -> bool:
        """Verify webhook signature for security."""
        try:
            # Create HMAC signature
            expected_signature = hmac.new(
                secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            # Compare signatures
            return hmac.compare_digest(signature, expected_signature)
            
        except Exception as e:
            logger.error(f"Error verifying webhook signature: {e}")
            return False
    
    async def process_webhook_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process incoming webhook event and trigger appropriate ambient agent actions."""
        try:
            # Extract event type from correct webhook structure (hook.event or fallback to eventType)
            event_type = event_data.get('hook', {}).get('event', event_data.get('eventType', ''))
            logger.info(f"Processing ACC webhook event: {event_type}")
            
            resource_urn = event_data.get('resourceUrn', '')
            
            # Extract project ID from payload.projectId (preferred) or hook.tenant or fallback to URN
            project_id_raw = (
                event_data.get('payload', {}).get('projectId') or
                event_data.get('hook', {}).get('tenant') or
                self._extract_project_id_from_urn(resource_urn)
            )
            
            if not project_id_raw:
                logger.warning(f"Could not extract project ID from webhook event")
                logger.warning(f"Payload: {event_data.get('payload', {})}")
                logger.warning(f"Hook: {event_data.get('hook', {})}")
                logger.warning(f"Resource URN: {resource_urn}")
                return {
                    'success': False,
                    'message': 'Could not extract project ID from webhook event'
                }
            
            # Strip "b." prefix from project ID for Issues API operations
            project_id = self._clean_project_id_for_issues_api(project_id_raw)
            logger.info(f"[WEBHOOK DEBUG] Project ID extracted: {project_id_raw} -> cleaned: {project_id}")
            logger.info(f"[WEBHOOK DEBUG] Event type extracted: {event_type}")
            
            # Find user associated with this project (try memory first, then database)
            logger.info(f"[WEBHOOK DEBUG] Looking for user associated with project {project_id}")
            user_id = self._find_user_for_project(project_id) or self._find_user_for_project(project_id_raw)
            
            if not user_id:
                logger.warning(f"[WEBHOOK DEBUG] Memory lookup failed, trying database lookup...")
                user_id = await self._find_user_for_project_db(project_id) or await self._find_user_for_project_db(project_id_raw)
            
            if not user_id:
                logger.warning(f"[WEBHOOK DEBUG] ❌ No user found for project {project_id} or {project_id_raw} in memory or database")
                logger.warning(f"[WEBHOOK DEBUG] This means either:")
                logger.warning(f"[WEBHOOK DEBUG]   1. No user has this project in their ACC connection")
                logger.warning(f"[WEBHOOK DEBUG]   2. The project ID format is different than expected")
                logger.warning(f"[WEBHOOK DEBUG]   3. The user's ACC connection is inactive")
                
                # Debug: Show all available users and their projects
                await self._debug_log_all_users_and_projects()
                
                return {
                    'success': False,
                    'message': f'No user found for project {project_id}'
                }
            
            logger.info(f"[WEBHOOK DEBUG] ✅ Found user {user_id} for project {project_id}")
            
            # Process different ACC issue event types
            if event_type == 'issue.created-1.0':
                # New issue created - trigger ambient agent processing
                await self._handle_new_issue_webhook(event_data, project_id, user_id)
            elif event_type == 'issue.updated-1.0':
                # Issue updated - may need to re-check for duplicates/completeness
                await self._handle_updated_issue_webhook(event_data, project_id, user_id)
            elif event_type == 'issue.deleted-1.0':
                # Issue deleted - log for tracking
                await self._handle_deleted_issue_webhook(event_data, project_id, user_id)
            elif event_type == 'issue.restored-1.0':
                # Issue restored - treat like new issue
                await self._handle_restored_issue_webhook(event_data, project_id, user_id)
            elif event_type == 'issue.unlinked-1.0':
                # Issue unlinked - log for tracking
                await self._handle_unlinked_issue_webhook(event_data, project_id, user_id)
            
            return {
                'success': True,
                'message': 'Webhook event processed successfully'
            }
            
        except Exception as e:
            logger.error(f"Error processing webhook event: {e}")
            return {
                'success': False,
                'message': f'Error processing webhook event: {str(e)}'
            }
    
    async def _handle_new_issue_webhook(self, event_data: Dict, project_id: str, user_id: int):
        """Handle new issue creation webhook."""
        try:
            # Import here to avoid circular imports  
            # Get user's ACC connection using a separate database session for webhook processing
            # Since webhooks come from external sources, they need their own session
            from ..database import AsyncSessionLocal
            from .acc_service import acc_service
            from .event_bus_service import event_bus_service
            async with AsyncSessionLocal() as webhook_db:
                result = await webhook_db.execute(
                    select(Connection)
                    .where(Connection.user_id == user_id)
                    .where(Connection.platform == 'acc')
                    .where(Connection.status == ConnectionStatus.ACTIVE)
                )
                connection = result.scalar_one_or_none()
                
                if not connection:
                    logger.warning(f"No ACC connection found for user {user_id}")
                    return
                
                # Get the issue details from the webhook event
                # Extract issue ID from payload.id (preferred) or fallback to old methods
                issue_id_raw = (
                    event_data.get('payload', {}).get('id') or
                    event_data.get('issueId') or 
                    event_data.get('resourceUrn', '').split('/')[-1]
                )
                
                # Strip "b." prefix from issue ID for Issues API
                issue_id = self._clean_issue_id_for_issues_api(issue_id_raw)
                
                logger.info(f"[WEBHOOK SERVICE DEBUG] Issue ID extracted: {issue_id_raw} -> processed: {issue_id}")
                
                if issue_id:
                    # Ensure project_id has no "b." prefix for Issues API
                    clean_project_id = self._clean_project_id_for_issues_api(project_id)
                    logger.info(f"[WEBHOOK SERVICE DEBUG] Using clean project ID for issue fetch: {clean_project_id}")
                    
                    # Fetch issue details using the issue ID with retry for timing issues
                    issue_data = None
                    max_retries = 3
                    
                    for attempt in range(max_retries):
                        logger.info(f"[RETRY DEBUG] Attempt {attempt + 1}/{max_retries} to fetch issue {issue_id}")
                        issue_data = await self._fetch_issue_by_id(connection, clean_project_id, issue_id, user_id, webhook_db)
                        
                        if issue_data:
                            logger.info(f"[RETRY DEBUG] Successfully fetched issue on attempt {attempt + 1}")
                            break
                        else:
                            logger.error(f"[RETRY DEBUG] Attempt {attempt + 1} failed to fetch issue {issue_id}")
                            if attempt < max_retries - 1:  # Don't sleep on the last attempt
                                import asyncio
                                wait_time = (attempt + 1) * 2  # 2s, 4s, 6s
                                logger.info(f"[RETRY DEBUG] Issue fetch failed, waiting {wait_time}s before retry...")
                                await asyncio.sleep(wait_time)
                            else:
                                logger.error(f"[RETRY DEBUG] All {max_retries} attempts failed to fetch issue {issue_id}")
                                logger.error(f"[RETRY DEBUG] This means we'll use webhook payload fallback data")
                    
                    if issue_data:
                        logger.info(f"[WEBHOOK FLOW DEBUG] ===== ISSUE DATA BEFORE PROCESSING =====")
                        logger.info(f"[WEBHOOK FLOW DEBUG] Issue ID: {issue_data.get('id')}")
                        logger.info(f"[WEBHOOK FLOW DEBUG] Title: {issue_data.get('title')}")
                        logger.info(f"[WEBHOOK FLOW DEBUG] Description: {issue_data.get('description')}")
                        logger.info(f"[WEBHOOK FLOW DEBUG] AssignedTo: {issue_data.get('assignedTo')}")
                        logger.info(f"[WEBHOOK FLOW DEBUG] DueDate: {issue_data.get('dueDate')}")
                        logger.info(f"[WEBHOOK FLOW DEBUG] Priority: {issue_data.get('priority')}")
                        logger.info(f"[WEBHOOK FLOW DEBUG] All keys: {list(issue_data.keys())}")
                        logger.info(f"[WEBHOOK FLOW DEBUG] =======================================")
                        
                        # Trigger the same ambient agent processing as before
                        await self._trigger_ambient_agent_processing(
                            user_id, connection, clean_project_id, issue_data, webhook_db
                        )
                        
                        logger.info(f"Processed new issue webhook for issue {issue_data.get('id')}")
                    else:
                        logger.warning(f"Could not fetch issue details for issue {issue_id}")
                        logger.info(f"[WEBHOOK DEBUG] ===== FULL WEBHOOK EVENT DATA =====")
                        logger.info(f"[WEBHOOK DEBUG] Complete event_data: {json.dumps(event_data, indent=2)}")
                        logger.info(f"[WEBHOOK DEBUG] Event data keys: {list(event_data.keys())}")
                        logger.info(f"[WEBHOOK DEBUG] Payload keys: {list(event_data.get('payload', {}).keys())}")
                        logger.info(f"[WEBHOOK DEBUG] =========================================")
                        
                        # Try to extract issue data from webhook payload first
                        payload_data = event_data.get('payload', {})
                        
                        # Check if webhook payload has the issue data we need
                        if payload_data and isinstance(payload_data, dict):
                            logger.info(f"Extracting issue data directly from webhook payload...")
                            logger.info(f"[PAYLOAD EXTRACT DEBUG] Raw payload keys: {list(payload_data.keys())}")
                            logger.info(f"[PAYLOAD EXTRACT DEBUG] Title in payload: {payload_data.get('title')}")
                            logger.info(f"[PAYLOAD EXTRACT DEBUG] Description in payload: {payload_data.get('description')}")
                            
                            # Extract available fields from webhook payload
                            # Try multiple possible field locations in the webhook payload
                            issue_from_payload = {
                                'id': issue_id,
                                'title': (
                                    payload_data.get('title') or 
                                    payload_data.get('attributes', {}).get('title') or
                                    event_data.get('title') or
                                    f'Issue {issue_id}'
                                ),
                                'description': (
                                    payload_data.get('description') or 
                                    payload_data.get('attributes', {}).get('description') or
                                    event_data.get('description') or
                                    'No description available'
                                ),
                                'status': payload_data.get('status', 'open'),
                                'assignedTo': payload_data.get('assignedTo'),
                                'assignedToType': payload_data.get('assignedToType'), 
                                'dueDate': payload_data.get('dueDate'),
                                'issueSubtypeId': payload_data.get('issueSubtypeId'),
                                'priority': payload_data.get('priority', 'normal'),
                                'createdAt': payload_data.get('createdAt'),
                                'updatedAt': payload_data.get('updatedAt'),
                                'createdBy': payload_data.get('createdBy'),
                                'ownerId': payload_data.get('ownerId')
                            }
                            
                            logger.info(f"[PAYLOAD DEBUG] ===== WEBHOOK PAYLOAD ISSUE DATA =====")
                            logger.info(f"[PAYLOAD DEBUG] Title: {issue_from_payload.get('title')}")
                            logger.info(f"[PAYLOAD DEBUG] AssignedTo: {issue_from_payload.get('assignedTo')} (type: {type(issue_from_payload.get('assignedTo'))})")
                            logger.info(f"[PAYLOAD DEBUG] DueDate: {issue_from_payload.get('dueDate')} (type: {type(issue_from_payload.get('dueDate'))})")  
                            logger.info(f"[PAYLOAD DEBUG] IssueSubtypeId: {issue_from_payload.get('issueSubtypeId')} (type: {type(issue_from_payload.get('issueSubtypeId'))})")
                            logger.info(f"[PAYLOAD DEBUG] Payload Keys: {list(payload_data.keys())}")
                            logger.info(f"[PAYLOAD DEBUG] ======================================")
                            
                            # Use payload data instead of minimal fallback
                            minimal_issue_data = issue_from_payload
                        else:
                            logger.info(f"Webhook payload doesn't contain issue data, using minimal fallback...")
                        
                        # Create minimal issue data from webhook payload
                        minimal_issue_data = {
                            'id': issue_id,
                            'attributes': {
                                'title': f'Issue {issue_id}',
                                'description': 'Issue details could not be fetched',
                                'status': 'open',
                                'assignedTo': None,
                                'dueDate': None,
                                'priority': 'normal'
                            }
                        }
                        
                        logger.info(f"Processing with minimal issue data for basic notifications...")
                        await self._trigger_ambient_agent_processing(
                            user_id, connection, clean_project_id, minimal_issue_data, webhook_db
                        )
                        
                        logger.info(f"Processed minimal issue webhook for issue {issue_id}")
                else:
                    logger.warning(f"No issue ID found in webhook event: {event_data}")
        
        except Exception as e:
            logger.error(f"Error handling new issue webhook: {e}")
    
    async def _handle_updated_issue_webhook(self, event_data: Dict, project_id: str, user_id: int):
        """Handle issue update webhook."""
        try:
            logger.info(f"Issue updated in project {project_id} for user {user_id}")
            
            # Get the issue details from the webhook event
            issue_id = (
                event_data.get('payload', {}).get('id') or
                event_data.get('issueId') or 
                event_data.get('resourceUrn', '').split('/')[-1]
            )
            if issue_id:
                logger.info(f"Issue {issue_id} was updated - could re-validate for completeness/duplicates")
                # Could implement re-validation of updated issues here
                # For example, if an issue was updated to add more information,
                # we might want to re-check if it's still flagged as incomplete
            
        except Exception as e:
            logger.error(f"Error handling updated issue webhook: {e}")
    
    async def _handle_deleted_issue_webhook(self, event_data: Dict, project_id: str, user_id: int):
        """Handle issue deletion webhook."""
        try:
            issue_id = (
                event_data.get('payload', {}).get('id') or
                event_data.get('issueId') or 
                event_data.get('resourceUrn', '').split('/')[-1]
            )
            logger.info(f"Issue {issue_id} deleted in project {project_id} for user {user_id}")
            
            # Could implement cleanup logic here
            # For example, remove any pending notifications or workflows for this issue
            
        except Exception as e:
            logger.error(f"Error handling deleted issue webhook: {e}")
    
    async def _handle_restored_issue_webhook(self, event_data: Dict, project_id: str, user_id: int):
        """Handle issue restoration webhook."""
        try:
            logger.info(f"Issue restored in project {project_id} for user {user_id}")
            
            # Treat restored issues like new issues - run full validation
            await self._handle_new_issue_webhook(event_data, project_id, user_id)
            
        except Exception as e:
            logger.error(f"Error handling restored issue webhook: {e}")
    
    async def _handle_unlinked_issue_webhook(self, event_data: Dict, project_id: str, user_id: int):
        """Handle issue unlink webhook."""
        try:
            issue_id = (
                event_data.get('payload', {}).get('id') or
                event_data.get('issueId') or 
                event_data.get('resourceUrn', '').split('/')[-1]
            )
            logger.info(f"Issue {issue_id} unlinked in project {project_id} for user {user_id}")
            
            # Could implement logic to handle unlinked issues
            # For example, notify about potential workflow disruptions
            
        except Exception as e:
            logger.error(f"Error handling unlinked issue webhook: {e}")
    
    async def _trigger_ambient_agent_processing(
        self, 
        user_id: int, 
        connection: Any, 
        project_id: str, 
        issue_data: Dict,
        db: AsyncSession
    ):
        """Trigger ambient agent processing for a new issue (same as polling logic)."""
        try:
            from .acc_duplicate_detection_service import \
                duplicate_detection_service
            from .acc_information_validation_service import \
                info_validation_service
            from .event_bus_service import event_bus_service
            
            logger.info(f"[TRIGGER DEBUG] ===== AMBIENT AGENT PROCESSING START =====")
            logger.info(f"[TRIGGER DEBUG] User ID: {user_id}")
            logger.info(f"[TRIGGER DEBUG] Project ID: {project_id}")
            logger.info(f"[TRIGGER DEBUG] Issue data keys: {list(issue_data.keys())}")
            logger.info(f"[TRIGGER DEBUG] Issue title: {issue_data.get('title')}")
            logger.info(f"[TRIGGER DEBUG] Issue description: {issue_data.get('description')}")
            logger.info(f"[TRIGGER DEBUG] Issue assignedTo: {issue_data.get('assignedTo')}")
            logger.info(f"[TRIGGER DEBUG] Issue priority: {issue_data.get('priority')}")
            logger.info(f"[TRIGGER DEBUG] ===============================================")
            
            logger.info(f"Processing new issue {issue_data.get('id')} via webhook for user {user_id}")
            
            # 1. Check for duplicates
            duplicate_result = await duplicate_detection_service.check_for_duplicates(
                connection, project_id, issue_data, user_id, db
            )
            
            is_duplicate = duplicate_result.get('is_duplicate', False)
            
            if is_duplicate:
                # Trigger duplicate alert workflow
                # Use containerId from issue data as project identifier
                project_name = issue_data.get('containerId', project_id)
                
                event_data = {
                    'user_id': user_id,
                    'project_id': project_id,
                    'project_name': project_name,
                    'issue': issue_data,
                    'similar_issues': duplicate_result.get('similar_issues', []),
                    'similarity_score': duplicate_result.get('similarity_score', 0),
                    'confidence': duplicate_result.get('confidence', 0),
                    'issue_url': f"https://construction.autodesk.com/projects/{project_id}/issues/{issue_data.get('id')}",
                    'source': 'webhook'  # Indicate this came from webhook
                }
                
                await event_bus_service.trigger_event(
                    'acc_issue_duplicate_detected',
                    event_data,
                    user_id
                )
                logger.info(f"🚨 DUPLICATE DETECTED - Sent alert to #acc-alerts for issue {issue_data.get('id')}")
                return  # STOP HERE - Don't send general notification for duplicates
            
            # 2. Check for missing information (only if not duplicate)
            logger.info(f"[TRIGGER DEBUG] Starting validation for issue {issue_data.get('id')}")
            validation_result = await info_validation_service.validate_issue_completeness(
                issue_data
            )
            
            logger.info(f"[TRIGGER DEBUG] ===== VALIDATION RESULT =====")
            logger.info(f"[TRIGGER DEBUG] Is complete: {validation_result.get('is_complete', True)}")
            logger.info(f"[TRIGGER DEBUG] Score: {validation_result.get('completeness_score', 'Unknown')}")
            logger.info(f"[TRIGGER DEBUG] Missing fields: {validation_result.get('missing_fields', [])}")
            logger.info(f"[TRIGGER DEBUG] ================================")
            
            is_complete = validation_result.get('is_complete', True)
            
            if not is_complete:
                # Trigger incomplete issue alert workflow
                # Use containerId from issue data as project identifier
                project_name = issue_data.get('containerId', project_id)
                
                event_data = {
                    'user_id': user_id,
                    'project_id': project_id,
                    'project_name': project_name,
                    'issue': issue_data,
                    'missing_fields': validation_result.get('missing_fields', []),
                    'suggestions': validation_result.get('suggestions', []),
                    'completeness_score': validation_result.get('completeness_score', 0),
                    'source': 'webhook'  # Indicate this came from webhook
                }
                
                await event_bus_service.trigger_event(
                    'acc_issue_incomplete_detected',
                    event_data,
                    user_id
                )
                logger.info(f"⚠️ INCOMPLETE DETECTED - Sent alert to #acc-alerts for issue {issue_data.get('id')}")
                return  # STOP HERE - Don't send general notification for incomplete issues
            
            # 3. Send general new issue notification (ONLY for complete, non-duplicate issues)
            issue_title = issue_data.get('title', 'Unknown Issue')
            issue_status = issue_data.get('status', 'Unknown')
            issue_priority = issue_data.get('priority', 'normal')
            assigned_to = issue_data.get('assignedTo', 'Unassigned')
            due_date = issue_data.get('dueDate', 'No due date')
            
            # Use containerId from issue data as project identifier (much more reliable than API lookup)
            project_name = issue_data.get('containerId', project_id)
            logger.info(f"[PROJECT DEBUG] Using containerId as project name: {project_name}")
            
            general_event_data = {
                'user_id': user_id,
                'project_id': project_id,
                'project_name': project_name,
                'issue': issue_data,
                'issue_url': f"https://construction.autodesk.com/projects/{project_id}/issues/{issue_data.get('id')}",
                'source': 'webhook',  # Indicate this came from webhook
                'validation_result': validation_result  # Include validation info
            }
            
            await event_bus_service.trigger_event(
                'acc_issue_created_general',
                general_event_data,
                user_id
            )
            logger.info(f"Triggered general new issue notification for issue {issue_data.get('id')} via webhook")
            
            # 4. Check for high priority escalation (additional notification for urgent issues)
            if issue_priority in ['high', 'critical']:
                # Use the same project name we already fetched to avoid extra API calls
                event_data = {
                    'user_id': user_id,
                    'project_id': project_id,
                    'project_name': project_name,  # Reuse project name from step 3
                    'issue': issue_data,
                    'issue_url': f"https://construction.autodesk.com/projects/{project_id}/issues/{issue_data.get('id')}",
                    'source': 'webhook'  # Indicate this came from webhook
                }
                
                await event_bus_service.trigger_event(
                    'acc_issue_high_priority',
                    event_data,
                    user_id
                )
                logger.info(f"Triggered high priority escalation for issue {issue_data.get('id')} via webhook")
                
        except Exception as e:
            logger.error(f"Error in ambient agent processing via webhook: {e}")
    
    async def _fetch_issue_by_id(self, connection: Any, project_id: str, issue_id: str, user_id: int, db: AsyncSession) -> Optional[Dict]:
        """Fetch issue details using issue ID."""
        try:
            from sqlalchemy.ext.asyncio import AsyncSession

            from .acc_service import acc_service
            
            logger.info(f"[FETCH ISSUE DEBUG] Original project_id parameter: {project_id}")
            
            # CRITICAL: Ensure project_id has no "b." prefix for Issues API
            clean_project_id = self._clean_project_id_for_issues_api(project_id)
            logger.info(f"[FETCH ISSUE DEBUG] Cleaned project_id: {clean_project_id}")
            logger.info(f"[FETCH ISSUE DEBUG] Fetching issue {issue_id} in project {clean_project_id}")
            
            # Use tool executor pattern for consistency (same as direct tool calls)
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from ..models import User
            from .tool_executor import tool_executor

            # Get user for tool executor
            user_query = select(User).where(User.id == user_id)
            result = await db.execute(user_query)
            user = result.scalars().first()
            
            if not user:
                logger.error(f"User {user_id} not found for tool execution")
                return None
                
            # MUCH MORE EFFICIENT: Get single issue by ID instead of fetching all issues
            logger.info(f"[FETCH ISSUE DEBUG] Using efficient single issue fetch for issue {issue_id}")
            logger.info(f"[FETCH ISSUE DEBUG] Project ID: {clean_project_id}")
            logger.info(f"[FETCH ISSUE DEBUG] Issue ID: {issue_id}")
            logger.info(f"[FETCH ISSUE DEBUG] User ID: {user_id}")
            
            try:
                issue_result = await tool_executor.execute_tool(
                    tool_name="acc_get_issue_by_id",
                    arguments={
                        "project_id": clean_project_id,
                        "issue_id": issue_id
                    },
                    user=user,
                    db=db
                )
                logger.info(f"[FETCH ISSUE DEBUG] Tool executor returned: {issue_result}")
            except Exception as fetch_error:
                logger.error(f"[FETCH ISSUE DEBUG] Tool executor failed: {fetch_error}")
                return None
            
            # Check both MCP format (isError: False) and tool executor format (success: True)
            if not issue_result.get('isError', True) or issue_result.get('success', False):
                logger.info(f"[FETCH ISSUE DEBUG] Single issue fetch SUCCESS - no buffer overflow possible!")
                
                # Extract issue data from MCP result or tool executor result
                if 'content' in issue_result:
                    # Direct MCP format
                    issue_data = issue_result
                else:
                    # Tool executor format
                    issue_data = issue_result.get('result', {})
                
                # Handle different response formats for single issue
                if isinstance(issue_data, dict) and 'content' in issue_data:
                    # Extract from MCP response format
                    content = issue_data['content']
                    if isinstance(content, list) and content:
                        content_text = content[0].get('text', '{}')
                        try:
                            import json
                            parsed_issue = json.loads(content_text)
                            logger.info(f"Successfully fetched single issue {issue_id}")
                            logger.info(f"[FETCH ISSUE DEBUG] ===== RETRIEVED ISSUE DATA =====")
                            logger.info(f"[FETCH ISSUE DEBUG] Issue ID: {parsed_issue.get('id')}")
                            logger.info(f"[FETCH ISSUE DEBUG] Title: {parsed_issue.get('title')}")
                            logger.info(f"[FETCH ISSUE DEBUG] AssignedTo: {parsed_issue.get('assignedTo')} (type: {type(parsed_issue.get('assignedTo'))})")
                            logger.info(f"[FETCH ISSUE DEBUG] DueDate: {parsed_issue.get('dueDate')} (type: {type(parsed_issue.get('dueDate'))})")  
                            logger.info(f"[FETCH ISSUE DEBUG] IssueSubtypeId: {parsed_issue.get('issueSubtypeId')} (type: {type(parsed_issue.get('issueSubtypeId'))})")
                            logger.info(f"[FETCH ISSUE DEBUG] All Keys: {list(parsed_issue.keys())}")
                            logger.info(f"[FETCH ISSUE DEBUG] ===============================")
                            return parsed_issue
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse single issue response")
                            return None
                    else:
                        return None
                elif isinstance(issue_data, dict):
                    # Direct issue data format
                    logger.info(f"Successfully fetched single issue {issue_id}")
                    return issue_data
                else:
                    logger.warning(f"Unexpected single issue response format")
                return None
            else:
                logger.warning(f"Failed to fetch single issue {issue_id}: {issue_result}")
                return None
            
        except Exception as e:
            logger.error(f"Error fetching issue by ID: {e}")
            return None
    
    async def _get_project_name(self, connection: Any, project_id: str, user_id: int, db: AsyncSession) -> str:
        """Get the actual project name from ACC API."""
        try:
            logger.info(f"[PROJECT NAME DEBUG] Fetching project name for {project_id}")
            
            # Use tool executor to get hubs and projects
            from sqlalchemy import select

            from ..models import User
            from .tool_executor import tool_executor

            # Get user for tool executor
            user_query = select(User).where(User.id == user_id)
            result = await db.execute(user_query)
            user = result.scalars().first()
            
            if not user:
                logger.warning(f"User {user_id} not found for project name fetch")
                return "Unknown Project"
            
            # Get hubs first
            logger.info(f"[PROJECT NAME DEBUG] Calling tool_executor.execute_tool for acc_get_hubs...")
            hubs_result = await tool_executor.execute_tool(
                tool_name="acc_get_hubs",
                arguments={},
                user=user,
                db=db
            )
            
            logger.info(f"[PROJECT NAME DEBUG] Hubs result: {hubs_result}")
            
            # Check both MCP format (isError: False) and tool executor format (success: True) 
            if hubs_result.get('isError', True) and not hubs_result.get('success', False):
                error_msg = hubs_result.get('error', 'Unknown error')
                logger.error(f"[PROJECT NAME DEBUG] Failed to get hubs: {error_msg}")
                logger.warning(f"Failed to get hubs for project name lookup")
                return "Unknown Project"
            
            # Extract hubs data - handle both MCP and tool executor formats
            if 'content' in hubs_result:
                # Direct MCP format
                hubs_data = hubs_result
            else:
                # Tool executor format
                hubs_data = hubs_result.get('result', {})
                
            if isinstance(hubs_data, dict) and 'content' in hubs_data:
                content = hubs_data['content']
                if isinstance(content, list) and content:
                    content_text = content[0].get('text', '{}')
                    try:
                        import json
                        parsed_hubs = json.loads(content_text)
                        hubs = parsed_hubs.get('data', [])
                    except json.JSONDecodeError:
                        hubs = []
                else:
                    hubs = []
            else:
                hubs = []
            
            # Search through hubs for projects
            for hub in hubs:
                hub_id = hub.get('id', '')
                if hub_id:
                    projects_result = await tool_executor.execute_tool(
                        tool_name="acc_get_projects",
                        arguments={"hub_id": hub_id},
                        user=user,
                        db=db
                    )
                    
                    if projects_result.get('success', False):
                        projects_data = projects_result.get('result', {})
                        if isinstance(projects_data, dict) and 'content' in projects_data:
                            content = projects_data['content']
                            if isinstance(content, list) and content:
                                content_text = content[0].get('text', '{}')
                                try:
                                    parsed_projects = json.loads(content_text)
                                    projects = parsed_projects.get('data', [])
                                except json.JSONDecodeError:
                                    projects = []
                            else:
                                projects = []
                        else:
                            projects = []
                        
                        # Look for our project in this hub
                        for project in projects:
                            proj_id = project.get('id', '').replace('b.', '')  # Clean for comparison
                            if proj_id == project_id:
                                project_name = project.get('attributes', {}).get('name', 'Unknown Project')
                                logger.info(f"[PROJECT NAME DEBUG] Found project name: {project_name}")
                                return project_name
            
            logger.warning(f"[PROJECT NAME DEBUG] Project {project_id} not found in any hub")
            return "Unknown Project"
            
        except Exception as e:
            logger.error(f"Error fetching project name: {e}")
            return "Unknown Project"
    
    def _extract_project_id_from_urn(self, resource_urn: str) -> Optional[str]:
        """Extract project ID from resource URN."""
        try:
            # Example URNs for ACC issues:
            # urn:adsk.wipprod:fs.file:PROJECT_ID
            # urn:adsk.wipprod:dm.lineage:PROJECT_ID
            # or sometimes the project ID might be directly in the URN
            
            if ':fs.file:' in resource_urn:
                return resource_urn.split(':fs.file:')[-1]
            elif ':dm.lineage:' in resource_urn:
                return resource_urn.split(':dm.lineage:')[-1]
            elif resource_urn.startswith('b.'):
                # Sometimes the URN might just be the project ID itself
                return resource_urn
            else:
                # Try to extract any GUID-like pattern from the URN
                parts = resource_urn.split(':')
                for part in parts:
                    if len(part) > 30 and ('-' in part or part.startswith('b.')):
                        return part
                return None
            
        except Exception as e:
            logger.error(f"Error extracting project ID from URN: {e}")
            return None
    
    def _find_user_for_project(self, project_id: str) -> Optional[int]:
        """Find user ID associated with a project."""
        try:
            logger.info(f"[USER LOOKUP DEBUG] Looking for user with project ID: {project_id}")
            logger.info(f"[USER LOOKUP DEBUG] Active webhooks: {list(self.active_webhooks.keys())}")
            
            # Search through active webhooks to find user
            for user_id, webhooks in self.active_webhooks.items():
                logger.info(f"[USER LOOKUP DEBUG] Checking user {user_id} with {len(webhooks)} webhooks")
                for webhook in webhooks:
                    webhook_project_id = webhook.get('project_id')
                    logger.info(f"[USER LOOKUP DEBUG] Webhook project ID: {webhook_project_id}")
                    if webhook_project_id == project_id:
                        logger.info(f"[USER LOOKUP DEBUG] ✅ Found user {user_id} for project {project_id}")
                        return user_id
            
            logger.warning(f"[USER LOOKUP DEBUG] ❌ No user found in active webhooks for project {project_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error finding user for project: {e}")
            return None

    async def _find_user_for_project_db(self, project_id: str) -> Optional[int]:
        """SIMPLE FIX: Just use the Mini-Hub user who has an active ACC connection."""
        try:
            logger.info(f"[USER LOOKUP] 🔍 Looking for Mini-Hub user with active ACC connection")
            
            from ..database import AsyncSessionLocal
            from ..models import Connection, ConnectionStatus, User
            
            async with AsyncSessionLocal() as db:
                # Get the first active ACC connection (there's usually only one anyway)
                result = await db.execute(
                    select(Connection, User)
                    .join(User, Connection.user_id == User.id)
                    .where(Connection.platform == 'acc')
                    .where(Connection.status == ConnectionStatus.ACTIVE)
                    .limit(1)  # Just get the first one
                )
                connection_user = result.first()
                
                if connection_user:
                    connection, user = connection_user
                    logger.info(f"[USER LOOKUP] ✅ FOUND! Using user {user.id} ({user.email}) with ACC connection '{connection.name}'")
                    logger.info(f"[USER LOOKUP] 🎯 This user will receive Slack notifications for project {project_id}")
                    return user.id
                else:
                    logger.error(f"[USER LOOKUP] ❌ No active ACC connections found")
                    return None
                
        except Exception as e:
            logger.error(f"[USER LOOKUP] Error: {e}")
            import traceback
            logger.error(f"[USER LOOKUP] Traceback: {traceback.format_exc()}")
            return None

    async def _get_project_users(self, access_token: str, project_id: str) -> List[Dict]:
        """Get users for a specific project using ACC Admin API."""
        try:
            # Use the ACC Admin API endpoint for getting project users
            # https://developer.api.autodesk.com/construction/admin/v1/projects/:projectId/users
            clean_project_id = self._clean_project_id_for_issues_api(project_id)
            url = f"https://developer.api.autodesk.com/construction/admin/v1/projects/{clean_project_id}/users"
            
            logger.info(f"[PROJECT USERS DEBUG] Getting project users from: {url}")
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=30)
                
                logger.info(f"[PROJECT USERS DEBUG] Response status: {response.status_code}")
                logger.info(f"[PROJECT USERS DEBUG] Response body: {response.text[:500]}...")
                
                if response.status_code == 200:
                    data = response.json()
                    users = data.get('results', [])
                    logger.info(f"[PROJECT USERS DEBUG] ✅ Found {len(users)} users in project")
                    
                    # Log first few users for debugging
                    for i, user in enumerate(users[:3]):
                        logger.info(f"[PROJECT USERS DEBUG]   User {i+1}: {user.get('email', 'No email')} (ID: {user.get('id', 'No ID')})")
                    
                    return users
                elif response.status_code == 403:
                    logger.warning(f"[PROJECT USERS DEBUG] Permission denied getting project users")
                    return []
                elif response.status_code == 404:
                    logger.warning(f"[PROJECT USERS DEBUG] Project not found: {clean_project_id}")
                    return []
                else:
                    logger.error(f"[PROJECT USERS DEBUG] HTTP error {response.status_code}: {response.text}")
                    return []
                    
        except Exception as e:
            logger.error(f"[PROJECT USERS DEBUG] Error getting project users: {e}")
            return []

    async def _debug_log_all_users_and_projects(self):
        """Debug method to log all users and their ACC projects."""
        try:
            logger.info(f"[DEBUG USERS/PROJECTS] ===== LISTING ALL USERS AND PROJECTS =====")
            
            from ..database import AsyncSessionLocal
            from ..models import Connection, ConnectionStatus, User
            
            async with AsyncSessionLocal() as db:
                # Get all active ACC connections with user info
                result = await db.execute(
                    select(Connection, User)
                    .join(User, Connection.user_id == User.id)
                    .where(Connection.platform == 'acc')
                    .where(Connection.status == ConnectionStatus.ACTIVE)
                )
                connections_with_users = result.all()
                
                logger.info(f"[DEBUG USERS/PROJECTS] Found {len(connections_with_users)} active ACC connections")
                
                for connection, user in connections_with_users:
                    logger.info(f"[DEBUG USERS/PROJECTS] User {user.id} ({user.email}): Connection '{connection.name}'")
                    
                    try:
                        from .acc_service import acc_service

                        # Get user's projects
                        projects_result = await acc_service.get_projects(connection)
                        if projects_result.get('success'):
                            projects = projects_result.get('projects', [])
                            logger.info(f"[DEBUG USERS/PROJECTS]   Has {len(projects)} projects:")
                            
                            for project in projects[:5]:  # Limit to first 5 projects
                                proj_id = project.get('id', 'Unknown')
                                proj_name = project.get('attributes', {}).get('name', 'Unknown')
                                proj_id_clean = self._clean_project_id_for_issues_api(proj_id)
                                logger.info(f"[DEBUG USERS/PROJECTS]     • {proj_name}")
                                logger.info(f"[DEBUG USERS/PROJECTS]       ID: {proj_id}")
                                logger.info(f"[DEBUG USERS/PROJECTS]       Clean ID: {proj_id_clean}")
                                
                            if len(projects) > 5:
                                logger.info(f"[DEBUG USERS/PROJECTS]     ... and {len(projects) - 5} more projects")
                        else:
                            logger.warning(f"[DEBUG USERS/PROJECTS]   Failed to get projects: {projects_result.get('message', 'Unknown error')}")
                            
                    except Exception as project_error:
                        logger.error(f"[DEBUG USERS/PROJECTS]   Error getting projects: {project_error}")
                
                logger.info(f"[DEBUG USERS/PROJECTS] ===== END USERS/PROJECTS LIST =====")
                
        except Exception as e:
            logger.error(f"[DEBUG USERS/PROJECTS] Error in debug logging: {e}")
    
    async def _get_hubs(self, access_token: str) -> Dict[str, Any]:
        """Get ACC hubs using access token."""
        try:
            url = "https://developer.api.autodesk.com/project/v1/hubs?filter[extension.type]=hubs:autodesk.bim360:Account"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Failed to get hubs: {response.status_code} - {response.text}")
                    return {'success': False, 'error': response.text}
                    
        except Exception as e:
            logger.error(f"Error getting hubs: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _get_projects(self, access_token: str, hub_id: str) -> Dict[str, Any]:
        """Get projects for a hub using access token."""
        try:
            url = f"https://developer.api.autodesk.com/project/v1/hubs/{hub_id}/projects"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Failed to get projects: {response.status_code} - {response.text}")
                    return {'success': False, 'error': response.text}
                    
        except Exception as e:
            logger.error(f"Error getting projects: {e}")
            return {'success': False, 'error': str(e)}
    
    def _extract_data_from_response(self, response: Dict) -> List[Dict]:
        """Extract data from various response formats."""
        try:
            if 'data' in response:
                return response['data']
            return []
        except Exception as e:
            logger.error(f"Error extracting data from response: {e}")
            return []
    
    def get_webhook_status(self, user_id: int) -> Dict[str, Any]:
        """Get webhook status for a user."""
        webhooks = self.active_webhooks.get(user_id, [])
        return {
            'active_webhooks': len(webhooks),
            'webhooks': webhooks,
            'supported_events': self.supported_events
        }


# Global instance
acc_webhook_service = ACCWebhookService()
