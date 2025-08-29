"""
Event Bus Service

Central event system that triggers ambient agent workflows when ACC events occur.
Connects issue monitoring to workflow execution.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, Workflow, WorkflowStatus
from .autonomous_agent_service import AutonomousAgentService
from .slack_service import slack_service
from .workflow_builder_service import WorkflowBuilderService

logger = logging.getLogger(__name__)


class EventBusService:
    """Central event bus for triggering ambient agent workflows."""
    
    def __init__(self):
        self.workflow_service = WorkflowBuilderService()
        self.agent_service = AutonomousAgentService()
        self.event_handlers = {}  # event_type -> List[handler_functions]
        self.active_listeners = {}  # user_id -> List[event_types]
        
        # Register default event handlers
        self._register_default_handlers()
    
    def _register_default_handlers(self):
        """Register default event handlers for ACC events."""
        self.register_handler('acc_issue_duplicate_detected', self._handle_duplicate_detected)
        self.register_handler('acc_issue_incomplete_detected', self._handle_incomplete_detected)
        self.register_handler('acc_issue_created_general', self._handle_general_issue_created)
        self.register_handler('acc_issue_created', self._handle_high_priority_issue)
        self.register_handler('acc_issue_high_priority', self._handle_high_priority_issue)
        self.register_handler('acc_weekly_summary_trigger', self._handle_weekly_summary)
    
    def register_handler(self, event_type: str, handler_function):
        """Register an event handler for a specific event type."""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler_function)
        logger.info(f"Registered handler for event type: {event_type}")
    
    async def trigger_event(self, event_type: str, event_data: Dict[str, Any], user_id: int):
        """Trigger an event and execute all registered handlers."""
        try:
            logger.info("🎯 ===== EVENT BUS TRIGGER EVENT =====")
            logger.info(f"🎯 Event Type: {event_type}")
            logger.info(f"🎯 User ID: {user_id}")
            logger.info(f"🎯 Event Data Keys: {list(event_data.keys())}")
            logger.info(f"🎯 Event Data Preview: {str(event_data)[:500]}...")
            
            # Add event metadata
            event_data.update({
                'event_type': event_type,
                'timestamp': datetime.utcnow().isoformat(),
                'triggered_by': 'ambient_agent'
            })
            
            # Execute handlers for this event type
            if event_type in self.event_handlers:
                handlers_count = len(self.event_handlers[event_type])
                logger.info(f"🎯 Found {handlers_count} handlers for event '{event_type}'")
                
                for i, handler in enumerate(self.event_handlers[event_type]):
                    try:
                        handler_name = handler.__name__
                        logger.info(f"🎯 Executing handler {i+1}/{handlers_count}: {handler_name}")
                        await handler(event_data, user_id)
                        logger.info(f"✅ Handler {handler_name} completed successfully")
                    except Exception as handler_error:
                        logger.error(f"❌ Handler error for {event_type} ({handler.__name__}): {handler_error}")
                        import traceback
                        logger.error(f"❌ Handler traceback:\n{traceback.format_exc()}")
                        
                logger.info(f"🎯 All handlers completed for event '{event_type}'")
            else:
                logger.warning(f"⚠️ No handlers registered for event type: {event_type}")
                logger.warning(f"⚠️ Available event types: {list(self.event_handlers.keys())}")
            
            logger.info("🎯 ===== EVENT BUS TRIGGER COMPLETE =====")
            
        except Exception as e:
            logger.error(f"❌ Error triggering event {event_type}: {e}")
            import traceback
            logger.error(f"❌ Event trigger traceback:\n{traceback.format_exc()}")
    
    async def _handle_duplicate_detected(self, event_data: Dict[str, Any], user_id: int):
        """Handle duplicate issue detection events."""
        try:
            logger.info(f"Handling duplicate detection event for user {user_id}")
            
            # Send Slack notification if user has Slack configured
            await self._send_duplicate_slack_notification(event_data, user_id)
            
            # Execute duplicate alert workflow if exists
            await self._execute_workflow_for_event('duplicate_issue_alert', event_data, user_id)
            
        except Exception as e:
            logger.error(f"Error handling duplicate detected event: {e}")
    
    async def _handle_incomplete_detected(self, event_data: Dict[str, Any], user_id: int):
        """Handle incomplete issue detection events."""
        try:
            logger.info(f"Handling incomplete issue detection event for user {user_id}")
            
            # Send Slack notification if user has Slack configured
            await self._send_incomplete_slack_notification(event_data, user_id)
            
            # Execute incomplete alert workflow if exists
            await self._execute_workflow_for_event('incomplete_issue_alert', event_data, user_id)
            
        except Exception as e:
            logger.error(f"Error handling incomplete detected event: {e}")
    
    async def _handle_high_priority_issue(self, event_data: Dict[str, Any], user_id: int):
        """Handle high priority issue events."""
        try:
            logger.info(f"Handling high priority issue event for user {user_id}")
            
            # Send immediate escalation notification
            await self._send_escalation_slack_notification(event_data, user_id)
            
            # Execute escalation workflow if exists
            await self._execute_workflow_for_event('high_priority_escalation', event_data, user_id)
            
        except Exception as e:
            logger.error(f"Error handling high priority issue event: {e}")
    
    async def _handle_weekly_summary(self, event_data: Dict[str, Any], user_id: int):
        """Handle weekly summary generation events."""
        try:
            logger.info(f"Handling weekly summary event for user {user_id}")
            
            # Execute weekly summary workflow if exists
            await self._execute_workflow_for_event('weekly_summary', event_data, user_id)
            
        except Exception as e:
            logger.error(f"Error handling weekly summary event: {e}")
    
    async def _handle_general_issue_created(self, event_data: Dict[str, Any], user_id: int):
        """Handle general new issue creation events (for all issues)."""
        try:
            logger.info(f"Handling general issue creation event for user {user_id}")
            await self._send_general_issue_slack_notification(event_data, user_id)
            
        except Exception as e:
            logger.error(f"Error handling general issue creation: {e}")
    
    async def _send_duplicate_slack_notification(self, event_data: Dict[str, Any], user_id: int):
        """Send Slack notification for duplicate issue detection."""
        try:
            logger.info(f"💬 ===== SENDING DUPLICATE SLACK NOTIFICATION =====")
            logger.info(f"💬 User ID: {user_id}")
            
            issue = event_data.get('issue', {})
            issue_id = issue.get('id', 'Unknown ID')
            
            # Try to get title from multiple possible locations (same as other notifications)
            issue_title = (
                issue.get('title') or 
                issue.get('attributes', {}).get('title') or 
                f"Issue {issue_id}"
            )
            
            project_name = event_data.get('project_name', 'Unknown Project')
            similarity_score = event_data.get('similarity_score', 0)
            similar_issues = event_data.get('similar_issues', [])
            confidence = event_data.get('confidence', 0)
            
            logger.info(f"💬 Issue Title: {issue_title}")
            logger.info(f"💬 Project Name: {project_name}")
            logger.info(f"💬 Similarity Score: {similarity_score:.1%}")
            logger.info(f"💬 Similar Issues Count: {len(similar_issues)}")
            
            message = f"""🚨 **Potential Duplicate Issue Detected**

**Project:** {project_name}
**New Issue:** {issue_title} ({issue_id})
**Similarity Score:** {similarity_score:.1%} | **Confidence:** {confidence:.1%}

**Similar Issues:**"""
            
            for similar_issue in similar_issues[:3]:
                # Try multiple locations for similar issue title
                similar_data = similar_issue.get('issue', {})
                similar_title = (
                    similar_data.get('title') or 
                    similar_data.get('attributes', {}).get('title') or 
                    f"Issue {similar_data.get('id', 'Unknown')}"
                )
                similar_score = similar_issue.get('similarity_score', 0)
                similar_id = similar_data.get('id', 'Unknown')
                message += f"\n• {similar_title} ({similar_score:.1%} similar) - ID: {similar_id}"
            
            message += f"\n\n**Action Required:** Please review and determine if this is a duplicate."
            
            logger.info(f"💬 Message Length: {len(message)} characters")
            logger.info(f"💬 Message Preview: {message[:200]}...")
            
            # Try to send to Slack
            logger.info(f"💬 Attempting to send Slack message to channel 'acc-alerts'")
            await self._try_send_slack_message(user_id, message, 'acc-alerts')
            logger.info(f"💬 ===== DUPLICATE SLACK NOTIFICATION COMPLETE =====")
            
        except Exception as e:
            logger.error(f"❌ Error sending duplicate Slack notification: {e}")
            import traceback
            logger.error(f"❌ Duplicate notification traceback:\n{traceback.format_exc()}")
    
    async def _send_incomplete_slack_notification(self, event_data: Dict[str, Any], user_id: int):
        """Send Slack notification for incomplete issue detection."""
        try:
            issue = event_data.get('issue', {})
            issue_id = issue.get('id', 'Unknown ID')
            
            # Try to get title from multiple possible locations
            issue_title = (
                issue.get('title') or 
                issue.get('attributes', {}).get('title') or 
                f"Issue {issue_id}"  # Use issue ID if title not available
            )
            
            project_name = event_data.get('project_name', 'Unknown Project')
            missing_fields = event_data.get('missing_fields', [])
            suggestions = event_data.get('suggestions', [])
            
            message = f"""⚠️ **Incomplete Issue Information**

**Project:** {project_name}
**Issue:** {issue_title}

**Missing Fields:**"""
            
            for field in missing_fields[:5]:
                message += f"\n• {field}"
            
            if suggestions:
                message += f"\n\n**Suggestions:**"
                for suggestion in suggestions[:3]:
                    message += f"\n• {suggestion}"
            
            message += f"\n\n**Action Required:** Please update the issue with missing information."
            
            # Try to send to Slack
            await self._try_send_slack_message(user_id, message, 'acc-alerts')
            
        except Exception as e:
            logger.error(f"Error sending incomplete Slack notification: {e}")
    
    async def _send_escalation_slack_notification(self, event_data: Dict[str, Any], user_id: int):
        """Send Slack notification for high priority issue escalation."""
        try:
            issue = event_data.get('issue', {})
            issue_attrs = issue.get('attributes', {})
            issue_title = issue_attrs.get('title', 'Unknown Issue')
            project_name = event_data.get('project_name', 'Unknown Project')
            priority = issue_attrs.get('priority', 'unknown')
            
            message = f"""🚨 **HIGH PRIORITY ACC ISSUE**

**Project:** {project_name}
**Issue:** {issue_title}
**Priority:** {priority.upper()}
**Created:** {issue_attrs.get('createdAt', 'Unknown')}

**Description:**
{issue_attrs.get('description', 'No description provided')[:200]}...

**Action Required:** This issue requires immediate attention due to its high priority status."""
            
            # Try to send to management channel
            await self._try_send_slack_message(user_id, message, 'acc-management')
            
        except Exception as e:
            logger.error(f"Error sending escalation Slack notification: {e}")
    
    async def _send_general_issue_slack_notification(self, event_data: Dict[str, Any], user_id: int):
        """Send Slack notification for general new issue creation."""
        try:
            logger.info(f"💬 ===== SENDING GENERAL ISSUE SLACK NOTIFICATION =====")
            logger.info(f"💬 User ID: {user_id}")
            
            issue = event_data.get('issue', {})
            issue_title = issue.get('title', 'Unknown Issue')
            issue_description = issue.get('description', 'No description provided')
            project_name = event_data.get('project_name', 'Unknown Project')
            issue_id = issue.get('id', 'Unknown ID')
            
            # Get validation info to show completeness status
            validation_result = event_data.get('validation_result', {})
            is_complete = validation_result.get('is_complete', True)
            completeness_score = validation_result.get('completeness_score', 0)
            
            # Issue details
            status = issue.get('status', 'Unknown')
            priority = issue.get('priority', 'normal')
            assigned_to = issue.get('assignedTo', 'Unassigned')
            due_date = issue.get('dueDate', 'No due date set')
            
            # Build status icon based on completeness
            if is_complete:
                status_icon = "✅"
                completeness_text = f"Complete (Score: {completeness_score:.0%})"
            else:
                status_icon = "⚠️"
                # Only show REQUIRED missing fields, not recommended ones
                missing_fields = validation_result.get('missing_fields', [])  # Required only
                recommended_missing = validation_result.get('recommended_missing', [])  # Optional
                
                if missing_fields:
                    completeness_text = f"Incomplete - Missing required: {', '.join(missing_fields)}"
                elif recommended_missing:
                    completeness_text = f"Complete (could be enhanced - optional: {', '.join(recommended_missing)})"
                else:
                    completeness_text = f"Complete (Score: {completeness_score:.0%})"
            
            message = f"""{status_icon} **New ACC Issue Created**

**Project:** {project_name}
**Issue:** {issue_title} ({issue_id})
**Status:** {status.upper()} | **Priority:** {priority.upper()}
**Completeness:** {completeness_text}

**Description:**
{issue_description[:300]}{"..." if len(issue_description) > 300 else ""}

**Details:**
• **Assigned To:** {assigned_to}
• **Due Date:** {due_date}
• **Issue ID:** {issue_id}

**Action:** {"✅ Issue is complete and ready for work" if is_complete else "⚠️ Please review and add missing information"}"""
            
            # Send complete issues to acc-management, incomplete issues get sent to acc-alerts (separate notification)
            if is_complete:
                await self._try_send_slack_message(user_id, message, 'acc-management')
                logger.info(f"💬 Complete issue notification sent to acc-management for issue {issue_id}")
            else:
                logger.info(f"💬 Skipping general notification for incomplete issue {issue_id} (will be sent to acc-alerts instead)")
            
        except Exception as e:
            logger.error(f"Error sending general issue Slack notification: {e}")
    
    async def _try_send_slack_message(self, user_id: int, message: str, channel: str):
        """Try to send a Slack message if user has Slack configured."""
        try:
            logger.info(f"📱 ===== ATTEMPTING SLACK MESSAGE SEND =====")
            logger.info(f"📱 User ID: {user_id}")
            logger.info(f"📱 Channel: {channel}")
            logger.info(f"📱 Message Length: {len(message)} characters")
            
            # Check if user has active Slack connection
            from ..database import AsyncSessionLocal
            async with AsyncSessionLocal() as db:
                from ..models import Connection, ConnectionStatus
                logger.info(f"📱 Querying for Slack connection for user {user_id}...")
                
                result = await db.execute(
                    select(Connection)
                    .where(Connection.user_id == user_id)
                    .where(Connection.platform == 'slack')
                    .where(Connection.status == ConnectionStatus.ACTIVE)
                )
                slack_connection = result.scalar_one_or_none()
                
                if slack_connection:
                    logger.info(f"📱 Found active Slack connection: {slack_connection.name}")
                    logger.info(f"📱 Slack connection ID: {slack_connection.id}")
                    logger.info(f"📱 Slack connection config keys: {list(slack_connection.config.keys())}")
                    
                    # Get bot token for detailed logging
                    bot_token = slack_connection.config.get('bot_token', '')
                    logger.info(f"📱 Bot token present: {bool(bot_token)}")
                    logger.info(f"📱 Bot token preview: {bot_token[:20]}... (length: {len(bot_token)})")
                    
                    # Initialize Slack service with user's connection token (following tool_executor pattern)
                    logger.info(f"📱 Initializing user-specific Slack service...")
                    from slack_sdk.web import WebClient

                    from .slack_service import SlackService
                    
                    try:
                        user_slack_service = SlackService()
                        
                        if bot_token:
                            # Initialize the service with the user's token (same as tool_executor.py)
                            user_slack_service.client = WebClient(token=bot_token)
                            logger.info(f"📱 ✅ Initialized Slack service with user's bot token")
                            
                            # Test the client authentication
                            try:
                                auth_test = user_slack_service.client.auth_test()
                                logger.info(f"📱 ✅ Slack auth test successful: {auth_test.get('user', 'Unknown user')}")
                                logger.info(f"📱 ✅ Slack bot user ID: {auth_test.get('user_id', 'Unknown')}")
                                logger.info(f"📱 ✅ Slack team: {auth_test.get('team', 'Unknown team')}")
                            except Exception as auth_error:
                                logger.error(f"📱 ❌ Slack auth test failed: {auth_error}")
                                
                            # Send message using the service
                            logger.info(f"📱 Calling user_slack_service.send_message(channel='{channel}', message_length={len(message)})...")
                            slack_result = await user_slack_service.send_message(
                                channel=channel,
                                message=message
                            )
                            logger.info(f"📱 ✅ Slack service call completed")
                            logger.info(f"📱 Slack service result: {slack_result}")
                            
                            if slack_result.get('success'):
                                logger.info(f"📱 ✅ SUCCESS: Message sent to {channel}")
                                logger.info(f"📱 Message timestamp: {slack_result.get('message_ts', 'N/A')}")
                            else:
                                logger.error(f"📱 ❌ FAILED: Slack service returned error: {slack_result.get('error', 'Unknown error')}")
                                
                        else:
                            slack_result = {
                                'success': False,
                                'error': 'No bot token found in user\'s Slack connection'
                            }
                            logger.error(f"📱 ❌ No bot token found in connection config")
                            
                    except Exception as slack_init_error:
                        logger.error(f"📱 ❌ Error initializing Slack service: {slack_init_error}")
                        import traceback
                        logger.error(f"📱 ❌ Slack initialization traceback:\n{traceback.format_exc()}")
                        slack_result = {
                            'success': False,
                            'error': f'Slack service initialization error: {str(slack_init_error)}'
                        }
                    
                    logger.info(f"📱 Final result: {slack_result}")
                    logger.info(f"📱 ✅ Completed Slack notification attempt for user {user_id} in channel '{channel}'")
                else:
                    logger.warning(f"⚠️ No active Slack connection found for user {user_id}")
                    
                    # Let's check what connections this user has
                    all_connections_result = await db.execute(
                        select(Connection).where(Connection.user_id == user_id)
                    )
                    all_connections = all_connections_result.scalars().all()
                    
                    logger.info(f"📱 User {user_id} has {len(all_connections)} total connections:")
                    for conn in all_connections:
                        logger.info(f"   • {conn.platform} ({conn.status}) - {conn.name}")
                    
            logger.info(f"📱 ===== SLACK MESSAGE SEND COMPLETE =====")
                    
        except Exception as e:
            logger.error(f"❌ Error sending Slack message: {e}")
            import traceback
            logger.error(f"❌ Slack message traceback:\n{traceback.format_exc()}")
    
    async def _execute_workflow_for_event(self, workflow_name: str, event_data: Dict[str, Any], user_id: int):
        """Execute a specific workflow triggered by an event."""
        try:
            from ..database import AsyncSessionLocal
            async with AsyncSessionLocal() as db:
                # Find workflow by name for this user
                result = await db.execute(
                    select(Workflow)
                    .where(Workflow.user_id == user_id)
                    .where(Workflow.name.ilike(f'%{workflow_name}%'))
                    .where(Workflow.status == WorkflowStatus.ACTIVE)
                )
                workflow = result.scalar_one_or_none()
                
                if workflow:
                    logger.info(f"Executing workflow '{workflow.name}' for event")
                    
                    # Execute workflow with event data as trigger data
                    execution_result = await self.workflow_service.execute_workflow(
                        workflow.id,
                        user_id,
                        db,
                        trigger_data=event_data
                    )
                    
                    logger.info(f"Workflow execution completed: {execution_result}")
                else:
                    logger.info(f"No active '{workflow_name}' workflow found for user {user_id}")
                    
        except Exception as e:
            logger.error(f"Error executing workflow for event: {e}")
    
    async def start_listening_for_user(self, user_id: int, event_types: List[str]):
        """Start listening for specific event types for a user."""
        try:
            if user_id not in self.active_listeners:
                self.active_listeners[user_id] = []
            
            for event_type in event_types:
                if event_type not in self.active_listeners[user_id]:
                    self.active_listeners[user_id].append(event_type)
            
            logger.info(f"Started listening for events {event_types} for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error starting event listening for user {user_id}: {e}")
            return False
    
    async def stop_listening_for_user(self, user_id: int, event_types: Optional[List[str]] = None):
        """Stop listening for specific event types for a user."""
        try:
            if user_id not in self.active_listeners:
                return True
            
            if event_types is None:
                # Stop listening to all events
                del self.active_listeners[user_id]
            else:
                # Stop listening to specific events
                for event_type in event_types:
                    if event_type in self.active_listeners[user_id]:
                        self.active_listeners[user_id].remove(event_type)
                
                # Clean up if no events left
                if not self.active_listeners[user_id]:
                    del self.active_listeners[user_id]
            
            logger.info(f"Stopped listening for events for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping event listening for user {user_id}: {e}")
            return False
    
    def get_listening_status(self, user_id: int) -> Dict[str, Any]:
        """Get the event listening status for a user."""
        return {
            'is_listening': user_id in self.active_listeners,
            'event_types': self.active_listeners.get(user_id, []),
            'available_events': list(self.event_handlers.keys())
        }


# Global instance
event_bus_service = EventBusService()
