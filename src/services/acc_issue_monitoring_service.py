"""
ACC Issue Monitoring Service

Real-time monitoring service that polls ACC projects for new issues
and triggers ambient agent workflows when issues are detected.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models import Connection, ConnectionStatus, User
from .acc_duplicate_detection_service import duplicate_detection_service
from .acc_information_validation_service import info_validation_service
from .acc_service import acc_service
from .event_bus_service import event_bus_service

logger = logging.getLogger(__name__)


class ACCIssueMonitoringService:
    """Service to monitor ACC projects for new issues and trigger ambient agents."""
    
    def __init__(self):
        self.monitoring_tasks: Dict[int, asyncio.Task] = {}  # user_id -> task
        self.monitoring_state: Dict[int, Dict[str, Set[str]]] = {}  # user_id -> {project_id -> {issue_ids}}
        self.poll_interval = 60  # Poll every 60 seconds
        self.is_running = False
        
    async def start_monitoring_for_user(self, user_id: int, db: AsyncSession) -> bool:
        """Start monitoring ACC issues for a specific user."""
        try:
            logger.info(f"Starting ACC issue monitoring for user {user_id}")
            
            # Check if already monitoring
            if user_id in self.monitoring_tasks:
                logger.warning(f"User {user_id} already being monitored")
                return True
                
            # Get user's ACC connections
            acc_connections = await self._get_user_acc_connections(user_id, db)
            if not acc_connections:
                logger.warning(f"No active ACC connections found for user {user_id}")
                return False
                
            # Initialize monitoring state
            self.monitoring_state[user_id] = {}
            
            # Initialize with current issues to avoid triggering on existing issues
            await self._initialize_baseline_issues(user_id, acc_connections[0], db)
            
            # Start monitoring task
            task = asyncio.create_task(self._monitor_user_issues(user_id, db))
            self.monitoring_tasks[user_id] = task
            
            logger.info(f"Successfully started ACC issue monitoring for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start monitoring for user {user_id}: {e}")
            return False
    
    async def stop_monitoring_for_user(self, user_id: int) -> bool:
        """Stop monitoring ACC issues for a specific user."""
        try:
            logger.info(f"Stopping ACC issue monitoring for user {user_id}")
            
            # Cancel monitoring task
            if user_id in self.monitoring_tasks:
                task = self.monitoring_tasks[user_id]
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                del self.monitoring_tasks[user_id]
                
            # Clean up state
            if user_id in self.monitoring_state:
                del self.monitoring_state[user_id]
                
            logger.info(f"Successfully stopped ACC issue monitoring for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop monitoring for user {user_id}: {e}")
            return False
    
    async def _monitor_user_issues(self, user_id: int, db: AsyncSession):
        """Main monitoring loop for a user's ACC issues."""
        logger.info(f"Starting monitoring loop for user {user_id}")
        
        while True:
            try:
                # Get user's ACC connections
                acc_connections = await self._get_user_acc_connections(user_id, db)
                if not acc_connections:
                    logger.warning(f"No ACC connections for user {user_id}, stopping monitoring")
                    break
                    
                connection = acc_connections[0]  # Use first active connection
                
                # Get all projects for user
                hubs_response = await acc_service.get_hubs(connection)
                if not hubs_response.get('success', True):
                    logger.error(f"Failed to get hubs for user {user_id}: {hubs_response}")
                    await asyncio.sleep(self.poll_interval)
                    continue
                    
                # Extract hubs data - handle both formats
                hubs_data = hubs_response
                if 'isError' not in hubs_data and 'content' in hubs_data:
                    # This is from the content format
                    content = hubs_data['content'][0]['text']
                    hubs_json = json.loads(content)
                    hubs = hubs_json.get('data', [])
                elif isinstance(hubs_data, dict) and 'data' in hubs_data:
                    hubs = hubs_data['data']
                else:
                    # Try to parse as JSON string
                    try:
                        if isinstance(hubs_data, str):
                            hubs_json = json.loads(hubs_data)
                            hubs = hubs_json.get('data', [])
                        else:
                            hubs = []
                    except:
                        hubs = []
                
                # Check issues for each hub's projects
                for hub in hubs:
                    hub_id = hub.get('id', '')
                    if not hub_id:
                        continue
                        
                    # Get projects for this hub
                    projects_response = await acc_service.get_projects(connection, hub_id)
                    if not projects_response.get('success', True):
                        continue
                        
                    # Parse projects data
                    projects = self._extract_projects_data(projects_response)
                    
                    # Monitor issues for each project
                    for project in projects:
                        project_id = project.get('id', '')
                        if not project_id:
                            continue
                            
                        await self._check_project_for_new_issues(
                            user_id, connection, project_id, project, db
                        )
                
                # Sleep before next poll
                await asyncio.sleep(self.poll_interval)
                
            except asyncio.CancelledError:
                logger.info(f"Monitoring cancelled for user {user_id}")
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop for user {user_id}: {e}")
                await asyncio.sleep(self.poll_interval)  # Continue monitoring even on errors
    
    async def _check_project_for_new_issues(
        self, 
        user_id: int, 
        connection: Any, 
        project_id: str, 
        project_data: Dict,
        db: AsyncSession
    ):
        """Check a specific project for new issues."""
        try:
            project_name = project_data.get('attributes', {}).get('name', 'Unknown Project')
            logger.info(f"🔍 ===== CHECKING PROJECT FOR NEW ISSUES =====")
            logger.info(f"🔍 User ID: {user_id}")
            logger.info(f"🔍 Project ID: {project_id}")
            logger.info(f"🔍 Project Name: {project_name}")
            
            # Get current issues for project using tool executor pattern
            logger.info(f"🔍 Fetching issues for project {project_id} via tool executor...")
            from sqlalchemy import select

            from ..models import User
            from .tool_executor import tool_executor

            # Get user for tool executor
            user_query = select(User).where(User.id == user_id)
            result = await db.execute(user_query)
            user = result.scalars().first()
            
            if not user:
                logger.error(f"User {user_id} not found for monitoring")
                return
                
            # Execute through tool executor (same pattern as direct tool calls)
            issues_response = await tool_executor.execute_tool(
                tool_name="acc_get_issues",
                arguments={"project_id": project_id},
                user=user,
                db=db
            )
            
            logger.info(f"🔍 Issues response success: {issues_response.get('success', True)}")
            if not issues_response.get('success', True):
                logger.warning(f"🔍 Failed to get issues for project {project_id}")
                return
                
            # Parse issues data
            logger.info(f"🔍 Parsing issues data...")
            issues = self._extract_issues_data(issues_response)
            logger.info(f"🔍 Extracted {len(issues)} issues from response")
            
            current_issue_ids = {issue.get('id', '') for issue in issues if issue.get('id')}
            logger.info(f"🔍 Current issue IDs: {list(current_issue_ids)}")
            
            # Get previously seen issues for this project
            if user_id not in self.monitoring_state:
                self.monitoring_state[user_id] = {}
                logger.info(f"🔍 Initialized monitoring state for user {user_id}")
            if project_id not in self.monitoring_state[user_id]:
                self.monitoring_state[user_id][project_id] = set()
                logger.info(f"🔍 Initialized monitoring state for project {project_id}")
                
            previous_issue_ids = self.monitoring_state[user_id][project_id]
            logger.info(f"🔍 Previously seen issue IDs: {list(previous_issue_ids)}")
            
            # Find new issues
            new_issue_ids = current_issue_ids - previous_issue_ids
            logger.info(f"🔍 New issue IDs detected: {list(new_issue_ids)}")
            
            if not new_issue_ids:
                logger.info(f"🔍 No new issues found in project {project_name}")
            
            # Process new issues
            for issue_id in new_issue_ids:
                if not issue_id:
                    logger.warning(f"🔍 Skipping empty issue ID")
                    continue
                    
                # Find the issue data
                issue_data = next((issue for issue in issues if issue.get('id') == issue_id), None)
                if not issue_data:
                    logger.warning(f"🔍 Could not find issue data for ID {issue_id}")
                    continue
                
                issue_title = issue_data.get('attributes', {}).get('title', 'Unknown Issue')
                logger.info(f"🎯 NEW ISSUE DETECTED: {issue_title} ({issue_id}) in project {project_name}")
                
                # Trigger ambient agent workflows for this new issue
                logger.info(f"🔍 Processing new issue through ambient agent workflows...")
                await self._process_new_issue(
                    user_id, connection, project_id, project_data, issue_data, db
                )
                logger.info(f"🔍 Completed processing new issue {issue_id}")
            
            # Update monitoring state
            self.monitoring_state[user_id][project_id] = current_issue_ids
            logger.info(f"🔍 Updated monitoring state for project {project_id}")
            logger.info(f"🔍 ===== PROJECT CHECK COMPLETE =====")
            
        except Exception as e:
            logger.error(f"❌ Error checking project {project_id} for user {user_id}: {e}")
            import traceback
            logger.error(f"❌ Project check traceback:\n{traceback.format_exc()}")
    
    async def _process_new_issue(
        self,
        user_id: int,
        connection: Any,
        project_id: str,
        project_data: Dict,
        issue_data: Dict,
        db: AsyncSession
    ):
        """Process a newly detected issue through ambient agent workflows."""
        try:
            issue_id = issue_data.get('id', 'unknown')
            issue_title = issue_data.get('attributes', {}).get('title', 'Unknown Issue')
            project_name = project_data.get('attributes', {}).get('name', 'Unknown Project')
            
            logger.info(f"⚙️ ===== PROCESSING NEW ISSUE =====")
            logger.info(f"⚙️ Issue ID: {issue_id}")
            logger.info(f"⚙️ Issue Title: {issue_title}")
            logger.info(f"⚙️ Project: {project_name}")
            logger.info(f"⚙️ User ID: {user_id}")
            
            # 1. Check for duplicates
            logger.info(f"⚙️ Step 1: Checking for duplicates...")
            try:
                duplicate_result = await duplicate_detection_service.check_for_duplicates(
                    connection, project_id, issue_data, user_id, db
                )
                logger.info(f"⚙️ Duplicate check result: {duplicate_result}")
                
                is_duplicate = duplicate_result.get('is_duplicate', False)
                logger.info(f"⚙️ Is duplicate: {is_duplicate}")
                
                if is_duplicate:
                    logger.info(f"🚨 DUPLICATE DETECTED! Triggering duplicate alert event...")
                    # Trigger duplicate alert workflow
                    event_data = {
                        'user_id': user_id,
                        'project_id': project_id,
                        'project_name': project_name,
                        'issue': issue_data,
                        'similar_issues': duplicate_result.get('similar_issues', []),
                        'similarity_score': duplicate_result.get('similarity_score', 0),
                        'confidence': duplicate_result.get('confidence', 0),
                        'issue_url': f"https://construction.autodesk.com/projects/{project_id}/issues/{issue_id}",
                        'source': 'polling'
                    }
                    
                    await event_bus_service.trigger_event(
                        'acc_issue_duplicate_detected',
                        event_data,
                        user_id
                    )
                    logger.info(f"✅ Successfully triggered duplicate alert for issue {issue_id}")
                else:
                    logger.info(f"⚙️ No duplicates found for issue {issue_id}")
                    
            except Exception as dup_error:
                logger.error(f"❌ Error in duplicate detection: {dup_error}")
                import traceback
                logger.error(f"❌ Duplicate detection traceback:\n{traceback.format_exc()}")
            
            # 2. Check for missing information
            logger.info(f"⚙️ Step 2: Checking for missing information...")
            try:
                validation_result = await info_validation_service.validate_issue_completeness(
                    issue_data
                )
                logger.info(f"⚙️ Validation result: {validation_result}")
                
                is_complete = validation_result.get('is_complete', True)
                logger.info(f"⚙️ Is complete: {is_complete}")
                
                if not is_complete:
                    logger.info(f"⚠️ INCOMPLETE ISSUE DETECTED! Triggering incomplete alert event...")
                    # Trigger incomplete issue alert workflow
                    event_data = {
                        'user_id': user_id,
                        'project_id': project_id,
                        'project_name': project_name,
                        'issue': issue_data,
                        'missing_fields': validation_result.get('missing_fields', []),
                        'suggestions': validation_result.get('suggestions', []),
                        'completeness_score': validation_result.get('completeness_score', 0),
                        'source': 'polling'
                    }
                    
                    await event_bus_service.trigger_event(
                        'acc_issue_incomplete_detected',
                        event_data,
                        user_id
                    )
                    logger.info(f"✅ Successfully triggered incomplete alert for issue {issue_id}")
                else:
                    logger.info(f"⚙️ Issue {issue_id} is complete, no validation alert needed")
                    
            except Exception as val_error:
                logger.error(f"❌ Error in information validation: {val_error}")
                import traceback
                logger.error(f"❌ Information validation traceback:\n{traceback.format_exc()}")
            
            # 3. Check for high priority escalation
            logger.info(f"⚙️ Step 3: Checking for high priority escalation...")
            try:
                issue_priority = issue_data.get('attributes', {}).get('priority', 'unknown')
                logger.info(f"⚙️ Issue priority: {issue_priority}")
                
                if issue_priority in ['high', 'critical']:
                    logger.info(f"🚨 HIGH PRIORITY ISSUE DETECTED! Triggering escalation event...")
                    event_data = {
                        'user_id': user_id,
                        'project_id': project_id,
                        'project_name': project_name,
                        'issue': issue_data,
                        'issue_url': f"https://construction.autodesk.com/projects/{project_id}/issues/{issue_id}",
                        'source': 'polling'
                    }
                    
                    await event_bus_service.trigger_event(
                        'acc_issue_created',
                        event_data,
                        user_id
                    )
                    logger.info(f"✅ Successfully triggered high priority escalation for issue {issue_id}")
                else:
                    logger.info(f"⚙️ Issue {issue_id} is not high priority, no escalation needed")
                    
            except Exception as pri_error:
                logger.error(f"❌ Error in priority escalation: {pri_error}")
                import traceback
                logger.error(f"❌ Priority escalation traceback:\n{traceback.format_exc()}")
                
            logger.info(f"⚙️ ===== COMPLETED PROCESSING ISSUE {issue_id} =====")
                
        except Exception as e:
            logger.error(f"❌ Critical error processing new issue {issue_data.get('id')}: {e}")
            import traceback
            logger.error(f"❌ New issue processing traceback:\n{traceback.format_exc()}")
    
    async def _initialize_baseline_issues(self, user_id: int, connection: Any, db: AsyncSession):
        """Initialize baseline issues to avoid triggering on existing issues."""
        try:
            logger.info(f"Initializing baseline issues for user {user_id}")
            
            # Get all hubs and projects
            hubs_response = await acc_service.get_hubs(connection)
            if not hubs_response.get('success', True):
                return
                
            hubs = self._extract_hubs_data(hubs_response)
            
            for hub in hubs:
                hub_id = hub.get('id', '')
                if not hub_id:
                    continue
                    
                projects_response = await acc_service.get_projects(connection, hub_id)
                if not projects_response.get('success', True):
                    continue
                    
                projects = self._extract_projects_data(projects_response)
                
                for project in projects:
                    project_id = project.get('id', '')
                    if not project_id:
                        continue
                        
                    # Get current issues using tool executor pattern  
                    from sqlalchemy import select

                    from ..models import User
                    from .tool_executor import tool_executor

                    # Get user for tool executor
                    user_query = select(User).where(User.id == user_id)
                    result = await db.execute(user_query)
                    user = result.scalars().first()
                    
                    if not user:
                        logger.error(f"User {user_id} not found for baseline initialization")
                        continue
                        
                    # Execute through tool executor (same pattern as direct tool calls)
                    issues_response = await tool_executor.execute_tool(
                        tool_name="acc_get_issues",
                        arguments={"project_id": project_id},
                        user=user,
                        db=db
                    )
                    if not issues_response.get('success', True):
                        continue
                        
                    issues = self._extract_issues_data(issues_response)
                    issue_ids = {issue.get('id', '') for issue in issues if issue.get('id')}
                    
                    # Store as baseline
                    if user_id not in self.monitoring_state:
                        self.monitoring_state[user_id] = {}
                    self.monitoring_state[user_id][project_id] = issue_ids
                    
            logger.info(f"Initialized baseline for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error initializing baseline for user {user_id}: {e}")
    
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
    
    def _extract_hubs_data(self, response: Dict) -> List[Dict]:
        """Extract hubs data from various response formats."""
        try:
            if 'content' in response and isinstance(response['content'], list):
                content = response['content'][0]['text']
                hubs_json = json.loads(content)
                return hubs_json.get('data', [])
            elif 'data' in response:
                return response['data']
            return []
        except Exception as e:
            logger.error(f"Error extracting hubs data: {e}")
            return []
    
    def _extract_projects_data(self, response: Dict) -> List[Dict]:
        """Extract projects data from various response formats."""
        try:
            if 'content' in response and isinstance(response['content'], list):
                content = response['content'][0]['text']
                projects_json = json.loads(content)
                return projects_json.get('data', [])
            elif 'data' in response:
                return response['data']
            return []
        except Exception as e:
            logger.error(f"Error extracting projects data: {e}")
            return []
    
    def _extract_issues_data(self, response: Dict) -> List[Dict]:
        """Extract issues data from various response formats."""
        try:
            if 'content' in response and isinstance(response['content'], list):
                content = response['content'][0]['text']
                issues_json = json.loads(content)
                return issues_json.get('data', [])
            elif 'data' in response:
                return response['data']
            return []
        except Exception as e:
            logger.error(f"Error extracting issues data: {e}")
            return []
    
    async def get_monitoring_status(self, user_id: int) -> Dict[str, Any]:
        """Get monitoring status for a user."""
        is_monitoring = user_id in self.monitoring_tasks
        project_count = len(self.monitoring_state.get(user_id, {}))
        
        return {
            'is_monitoring': is_monitoring,
            'project_count': project_count,
            'poll_interval': self.poll_interval,
            'monitoring_state': self.monitoring_state.get(user_id, {})
        }


# Global instance
issue_monitoring_service = ACCIssueMonitoringService()
