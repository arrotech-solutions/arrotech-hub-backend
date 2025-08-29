"""
ACC Ambient Agent Service

Central controller for ACC ambient agents that monitor issues and trigger workflows.
Coordinates issue monitoring, duplicate detection, information validation, and notifications.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Connection, ConnectionStatus, User
from .acc_issue_monitoring_service import issue_monitoring_service
from .acc_service import acc_service
from .event_bus_service import event_bus_service

logger = logging.getLogger(__name__)


class ACCAmbientAgentService:
    """Central controller for ACC ambient agents."""
    
    def __init__(self):
        self.active_agents = {}  # user_id -> agent_status
        self.monitoring_config = {
            'poll_interval': 60,  # seconds (fallback when webhooks fail)
            'enable_duplicate_detection': True,
            'enable_info_validation': True,
            'enable_slack_notifications': True,
            'weekly_summary_day': 1,  # Monday
            'weekly_summary_hour': 9,   # 9 AM
            'prefer_webhooks': True,  # Prefer real-time webhooks over polling
            'webhook_callback_url': 'https://15a2e6bfcc71.ngrok-free.app/api/acc/webhooks/events'
        }
    
    async def start_monitoring(self, user_id: int, db: AsyncSession, project_id: Optional[str] = None, callback_url: Optional[str] = None) -> Dict[str, Any]:
        """Start comprehensive ambient agent monitoring for a user."""
        try:
            logger.info(f"Starting ACC ambient agent monitoring for user {user_id}")
            
            # Use provided parameters or defaults
            target_callback_url = callback_url or self.monitoring_config['webhook_callback_url']
            logger.info(f"[AMBIENT AGENT] Using callback URL: {target_callback_url}")
            if project_id:
                logger.info(f"[AMBIENT AGENT] Targeting specific project: {project_id}")
            else:
                logger.info(f"[AMBIENT AGENT] Will register webhooks for all user projects")
            
            # Check if already monitoring
            if user_id in self.active_agents:
                return {
                    'success': True,
                    'message': f'Ambient agent already active for user {user_id}',
                    'status': self.active_agents[user_id]
                }
            
            # Verify user has ACC connections
            acc_connections = await self._get_user_acc_connections(user_id, db)
            if not acc_connections:
                return {
                    'success': False,
                    'message': 'No active ACC connections found',
                    'status': None
                }
            
            # Initialize agent status
            agent_status = {
                'user_id': user_id,
                'started_at': datetime.utcnow().isoformat(),
                'status': 'starting',
                'components': {},
                'last_activity': datetime.utcnow().isoformat()
            }
            
            self.active_agents[user_id] = agent_status
            
            # 1. Try to start webhook monitoring first (preferred)
            webhook_success = False
            if self.monitoring_config['prefer_webhooks']:
                try:
                    logger.info(f"[WEBHOOK DEBUG] Starting webhook registration for user {user_id}")
                    logger.info(f"[WEBHOOK DEBUG] ACC connections count: {len(acc_connections)}")
                    logger.info(f"[WEBHOOK DEBUG] First connection ID: {acc_connections[0].id}")
                    logger.info(f"[WEBHOOK DEBUG] Callback URL: {self.monitoring_config['webhook_callback_url']}")
                    
                    from .acc_webhook_service import acc_webhook_service
                    
                    logger.info(f"[WEBHOOK DEBUG] Imported acc_webhook_service successfully")
                    logger.info(f"[WEBHOOK DEBUG] Calling register_webhooks_for_user...")
                    
                    # Use a separate database session for webhook registration to avoid conflicts
                    from ..database import AsyncSessionLocal
                    
                    logger.info(f"[WEBHOOK DEBUG] Starting separate DB session for webhook registration")
                    try:
                        async with AsyncSessionLocal() as webhook_db:
                            logger.info(f"[WEBHOOK DEBUG] Created separate webhook DB session")
                            if project_id:
                                # Register webhook for specific project only
                                logger.info(f"[WEBHOOK DEBUG] Registering webhook for specific project: {project_id}")
                                webhook_result = await acc_webhook_service.register_webhook_for_specific_project(
                                    user_id,
                                    acc_connections[0],
                                    project_id,
                                    target_callback_url,
                                    webhook_db
                                )
                            else:
                                # Register webhooks for all user projects (default behavior)
                                logger.info(f"[WEBHOOK DEBUG] Registering webhooks for all user projects")
                                webhook_result = await acc_webhook_service.register_webhooks_for_user(
                                    user_id, 
                                    acc_connections[0], 
                                    target_callback_url,
                                    webhook_db
                                )
                            logger.info(f"[WEBHOOK DEBUG] Webhook registration completed, committing session")
                            await webhook_db.commit()
                            logger.info(f"[WEBHOOK DEBUG] Webhook DB session committed successfully")
                    except Exception as webhook_db_error:
                        logger.error(f"[WEBHOOK DEBUG] Error in webhook DB session: {webhook_db_error}")
                        raise
                    
                    logger.info(f"[WEBHOOK DEBUG] Webhook registration returned: {webhook_result}")
                    webhook_success = webhook_result.get('success', False)
                    
                    # Log comprehensive webhook registration results
                    summary = webhook_result.get('registration_summary', {})
                    
                    if webhook_success:
                        webhook_count = len(webhook_result.get('webhooks', []))
                        
                        logger.info(f"🎉 [AMBIENT AGENT] Webhook registration SUCCESSFUL for user {user_id}")
                        logger.info(f"📊 [AMBIENT AGENT] Webhook Summary:")
                        logger.info(f"   • Total attempted: {summary.get('total_attempted', 0)}")
                        logger.info(f"   • Successfully registered: {summary.get('successful', 0)}")
                        logger.info(f"   • Failed: {summary.get('failed', 0)}")
                        logger.info(f"   • Success rate: {summary.get('success_rate', 0):.1f}%")
                        logger.info(f"   • Message: {webhook_result.get('message', 'N/A')}")
                        
                        if summary.get('failed', 0) > 0:
                            logger.warning(f"⚠️ [AMBIENT AGENT] Some webhooks failed to register:")
                            for failed in summary.get('failed_details', []):
                                logger.warning(f"   • {failed.get('project_name', 'Unknown')} - {failed.get('event_type', 'Unknown')}: {failed.get('error', 'Unknown error')}")
                        
                        agent_status['components']['webhooks'] = {
                            'active': True,
                            'started_at': datetime.utcnow().isoformat(),
                            'webhook_count': webhook_count,
                            'callback_url': target_callback_url,
                            'target_project_id': project_id,
                            'mode': 'webhooks',
                            'registration_summary': summary
                        }
                    else:
                        error_msg = webhook_result.get('message', 'Unknown error')
                        
                        logger.error(f"❌ [AMBIENT AGENT] Webhook registration FAILED for user {user_id}")
                        logger.error(f"📊 [AMBIENT AGENT] Failure Summary:")
                        logger.error(f"   • Total attempted: {summary.get('total_attempted', 0)}")
                        logger.error(f"   • Successfully registered: {summary.get('successful', 0)}")
                        logger.error(f"   • Failed: {summary.get('failed', 0)}")
                        logger.error(f"   • Success rate: {summary.get('success_rate', 0):.1f}%")
                        logger.error(f"   • Error message: {error_msg}")
                        
                        if summary.get('failed_details'):
                            logger.error(f"❌ [AMBIENT AGENT] Detailed failures:")
                            for failed in summary.get('failed_details', []):
                                logger.error(f"   • {failed.get('project_name', 'Unknown')} - {failed.get('event_type', 'Unknown')}: {failed.get('error', 'Unknown error')}")
                        
                        agent_status['components']['webhooks'] = {
                            'active': False,
                            'error': error_msg,
                            'registration_summary': summary
                        }
                        
                except Exception as webhook_error:
                    import traceback
                    logger.error(f"[WEBHOOK DEBUG] Exception during webhook registration for user {user_id}")
                    logger.error(f"[WEBHOOK DEBUG] Exception type: {type(webhook_error).__name__}")
                    logger.error(f"[WEBHOOK DEBUG] Exception message: {str(webhook_error)}")
                    logger.error(f"[WEBHOOK DEBUG] Full traceback:\n{traceback.format_exc()}")
                    webhook_success = False
            else:
                logger.info(f"[WEBHOOK DEBUG] Webhooks disabled via config for user {user_id}")
            
            # 2. Fall back to polling if webhooks failed or disabled
            polling_success = False
            if not webhook_success:
                logger.info(f"Starting polling-based issue monitoring for user {user_id}")
                polling_success = await issue_monitoring_service.start_monitoring_for_user(user_id, db)
                
            # Set monitoring component status
            agent_status['components']['issue_monitoring'] = {
                'webhook_mode': webhook_success,
                'polling_mode': polling_success,
                'active': webhook_success or polling_success,
                'started_at': datetime.utcnow().isoformat() if (webhook_success or polling_success) else None,
                'mode': 'webhooks' if webhook_success else 'polling' if polling_success else 'none'
            }
            
            monitoring_success = webhook_success or polling_success
            
            # 2. Start event bus listening
            logger.info(f"Starting event bus listening for user {user_id}")
            event_types = [
                'acc_issue_duplicate_detected',
                'acc_issue_incomplete_detected', 
                'acc_issue_created',
                'acc_weekly_summary_trigger'
            ]
            event_success = await event_bus_service.start_listening_for_user(user_id, event_types)
            agent_status['components']['event_bus'] = {
                'active': event_success,
                'event_types': event_types if event_success else []
            }
            
            # 3. Schedule weekly summary (placeholder for now)
            logger.info(f"Scheduling weekly summary for user {user_id}")
            weekly_success = True  # Placeholder
            agent_status['components']['weekly_summary'] = {
                'active': weekly_success,
                'schedule': f"Every Monday at {self.monitoring_config['weekly_summary_hour']}:00"
            }
            
            # Update overall status
            all_success = monitoring_success and event_success and weekly_success
            agent_status['status'] = 'active' if all_success else 'partial'
            
            logger.info(f"[AMBIENT AGENT DEBUG] ACC ambient agent started for user {user_id} - Status: {agent_status['status']}")
            
            final_result = {
                'success': True,
                'message': f'Ambient agent started successfully',
                'status': agent_status
            }
            logger.info(f"[AMBIENT AGENT DEBUG] Final result: {final_result}")
            return final_result
            
        except Exception as e:
            import traceback
            logger.error(f"[AMBIENT AGENT DEBUG] Exception starting ambient agent for user {user_id}")
            logger.error(f"[AMBIENT AGENT DEBUG] Exception type: {type(e).__name__}")
            logger.error(f"[AMBIENT AGENT DEBUG] Exception message: {str(e)}")
            logger.error(f"[AMBIENT AGENT DEBUG] Full traceback:\n{traceback.format_exc()}")
            
            # Cleanup on error
            if user_id in self.active_agents:
                logger.info(f"[AMBIENT AGENT DEBUG] Cleaning up active agent entry for user {user_id}")
                del self.active_agents[user_id]
            
            # Ensure database session is in clean state on error
            try:
                logger.info(f"[AMBIENT AGENT DEBUG] Rolling back main DB session due to error...")
                await db.rollback()
                logger.info(f"[AMBIENT AGENT DEBUG] Main DB session rollback successful")
            except Exception as db_error:
                logger.error(f"[AMBIENT AGENT DEBUG] Error rolling back database: {db_error}")
            
            error_result = {
                'success': False,
                'message': f'Failed to start ambient agent: {str(e)}',
                'status': None,
                'exception_type': type(e).__name__,
                'exception_details': str(e)
            }
            logger.error(f"[AMBIENT AGENT DEBUG] Error result: {error_result}")
            return error_result
    
    async def stop_monitoring(self, user_id: int, db: AsyncSession = None) -> Dict[str, Any]:
        """Stop ambient agent monitoring for a user."""
        try:
            logger.info(f"Stopping ACC ambient agent monitoring for user {user_id}")
            
            if user_id not in self.active_agents:
                return {
                    'success': True,
                    'message': f'No active ambient agent found for user {user_id}',
                    'status': None
                }
            
            # Get agent status to determine what to stop
            agent_status = self.active_agents[user_id]
            
            # Stop webhooks if active
            if agent_status.get('components', {}).get('webhooks', {}).get('active', False):
                try:
                    from .acc_webhook_service import acc_webhook_service

                    # Get ACC connection to unregister webhooks if db is available
                    if db:
                        acc_connections = await self._get_user_acc_connections(user_id, db)
                        if acc_connections:
                            await acc_webhook_service.unregister_webhooks_for_user(user_id, acc_connections[0])
                            logger.info(f"Unregistered webhooks for user {user_id}")
                    else:
                        # If no db session, just clean up memory state
                        if user_id in acc_webhook_service.active_webhooks:
                            del acc_webhook_service.active_webhooks[user_id]
                            logger.info(f"Cleaned up webhook state for user {user_id}")
                except Exception as e:
                    logger.warning(f"Error unregistering webhooks for user {user_id}: {e}")
            
            # Stop polling if active
            if agent_status.get('components', {}).get('issue_monitoring', {}).get('polling_mode', False):
                await issue_monitoring_service.stop_monitoring_for_user(user_id)
                logger.info(f"Stopped polling for user {user_id}")
            
            # Stop event bus listening
            await event_bus_service.stop_listening_for_user(user_id)
            
            # Remove from active agents
            del self.active_agents[user_id]
            
            logger.info(f"ACC ambient agent stopped for user {user_id}")
            
            return {
                'success': True,
                'message': 'Ambient agent stopped successfully',
                'status': None
            }
            
        except Exception as e:
            logger.error(f"Error stopping ambient agent for user {user_id}: {e}")
            return {
                'success': False,
                'message': f'Error stopping ambient agent: {str(e)}',
                'status': self.active_agents.get(user_id)
            }
    
    async def get_monitoring_status(self, user_id: int) -> Dict[str, Any]:
        """Get current monitoring status for a user."""
        try:
            if user_id not in self.active_agents:
                return {
                    'is_active': False,
                    'status': None,
                    'components': {},
                    'uptime': None
                }
            
            agent_status = self.active_agents[user_id]
            
            # Calculate uptime
            started_at = datetime.fromisoformat(agent_status['started_at'])
            uptime_seconds = (datetime.utcnow() - started_at).total_seconds()
            
            # Get detailed component status
            issue_monitoring_status = await issue_monitoring_service.get_monitoring_status(user_id)
            event_bus_status = event_bus_service.get_listening_status(user_id)
            
            return {
                'is_active': True,
                'status': agent_status['status'],
                'started_at': agent_status['started_at'],
                'uptime_seconds': uptime_seconds,
                'components': {
                    'issue_monitoring': {
                        **agent_status['components'].get('issue_monitoring', {}),
                        'details': issue_monitoring_status
                    },
                    'event_bus': {
                        **agent_status['components'].get('event_bus', {}),
                        'details': event_bus_status
                    },
                    'weekly_summary': agent_status['components'].get('weekly_summary', {})
                },
                'configuration': self.monitoring_config
            }
            
        except Exception as e:
            logger.error(f"Error getting monitoring status for user {user_id}: {e}")
            return {
                'is_active': False,
                'status': 'error',
                'error': str(e)
            }
    
    async def generate_weekly_summary(self, user_id: int, db: AsyncSession) -> Dict[str, Any]:
        """Generate comprehensive weekly summary of ACC issues."""
        try:
            logger.info(f"Generating weekly summary for user {user_id}")
            
            # Get user's ACC connections
            acc_connections = await self._get_user_acc_connections(user_id, db)
            if not acc_connections:
                return {
                    'success': False,
                    'message': 'No active ACC connections found',
                    'summary': None
                }
            
            connection = acc_connections[0]
            
            # Calculate date range (last 7 days)
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=7)
            
            # Initialize summary data
            summary_data = {
                'period': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat(),
                    'days': 7
                },
                'totals': {
                    'total_issues': 0,
                    'new_issues': 0,
                    'resolved_issues': 0,
                    'open_issues': 0
                },
                'projects': [],
                'insights': [],
                'top_issues': [],
                'generated_at': datetime.utcnow().isoformat()
            }
            
            # Get basic summary data (simplified for now)
            summary_data['insights'] = [
                'Weekly summary generated successfully',
                'Monitoring system is operational'
            ]
            
            logger.info(f"Weekly summary generated for user {user_id}")
            
            return {
                'success': True,
                'message': 'Weekly summary generated successfully',
                'summary': summary_data
            }
            
        except Exception as e:
            logger.error(f"Error generating weekly summary for user {user_id}: {e}")
            return {
                'success': False,
                'message': f'Error generating weekly summary: {str(e)}',
                'summary': None
            }
    
    async def _get_user_acc_connections(self, user_id: int, db: AsyncSession) -> List[Any]:
        """Get active ACC connections for a user."""
        try:
            result = await db.execute(
                select(Connection)
                .where(Connection.user_id == user_id)
                .where(Connection.platform == 'acc')
                .where(Connection.status == ConnectionStatus.ACTIVE)
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting ACC connections for user {user_id}: {e}")
            return []


# Global instance
acc_ambient_agent_service = ACCAmbientAgentService()
