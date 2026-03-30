"""
Workflow Sharing Service

Handles exporting, importing, and sharing workflows in the marketplace.
Includes sanitization to remove sensitive data from exported workflows.
"""

import hashlib
import re
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from ..models import (
    User,
    Workflow,
    WorkflowDownload,
    WorkflowReview,
    WorkflowStep,
    WorkflowVisibility,
    WorkflowLicense,
    WorkflowStatus,
)


# Patterns that indicate sensitive data
SENSITIVE_PATTERNS = [
    r'api[_-]?key',
    r'secret',
    r'password',
    r'token',
    r'credential',
    r'auth',
    r'bearer',
    r'private[_-]?key',
    r'access[_-]?key',
]

# Compile patterns for efficiency
SENSITIVE_REGEX = re.compile('|'.join(SENSITIVE_PATTERNS), re.IGNORECASE)


class WorkflowSharingService:
    """Service for sharing workflows in the marketplace."""

    def generate_share_code(self, workflow_id: uuid.UUID) -> str:
        """Generate a unique share code for a workflow."""
        random_part = secrets.token_urlsafe(8)
        hash_part = hashlib.sha256(f"{workflow_id}{random_part}".encode()).hexdigest()[:8]
        return f"{hash_part}-{random_part}"

    def sanitize_value(self, key: str, value: Any, parameterize: bool = True) -> Any:
        """
        Sanitize a parameter value, replacing sensitive data with placeholders.
        
        Args:
            key: The parameter key name
            value: The parameter value
            parameterize: If True, replace with {{input.key}}, else use placeholder text
        
        Returns:
            Sanitized value
        """
        if value is None:
            return None
            
        # Check if the key suggests sensitive data
        is_sensitive_key = bool(SENSITIVE_REGEX.search(key))
        
        if isinstance(value, str):
            # Check if value looks like a secret (long random string, contains specific patterns)
            looks_like_secret = (
                len(value) > 20 and 
                not ' ' in value and
                any(c.isdigit() for c in value) and
                any(c.isalpha() for c in value)
            )
            
            # Check for common secret patterns in value
            has_secret_pattern = bool(SENSITIVE_REGEX.search(value))
            
            if is_sensitive_key or looks_like_secret or has_secret_pattern:
                if parameterize:
                    return f"{{{{input.{key}}}}}"
                else:
                    return "[REDACTED]"
            
            # Check for email addresses - parameterize but don't redact
            if '@' in value and '.' in value:
                if parameterize:
                    return f"{{{{input.{key}}}}}"
                    
            return value
            
        elif isinstance(value, dict):
            return {k: self.sanitize_value(k, v, parameterize) for k, v in value.items()}
            
        elif isinstance(value, list):
            return [self.sanitize_value(key, item, parameterize) for item in value]
            
        return value

    def extract_required_connections(self, steps: List[WorkflowStep]) -> List[str]:
        """Extract the list of required connection platforms from workflow steps."""
        connections = set()
        
        # Map tool names to connection platforms
        tool_to_platform = {
            'slack': 'slack',
            'hubspot': 'hubspot',
            'ga4': 'google_analytics',
            'google_analytics': 'google_analytics',
            'powerbi': 'powerbi',
            'salesforce': 'salesforce',
            'whatsapp': 'whatsapp',
            'facebook': 'facebook',
            'twitter': 'twitter',
            'linkedin': 'linkedin',
            'instagram': 'instagram',
            'zoom': 'zoom',
            'teams': 'microsoft_teams',
            'asana': 'asana',
        }
        
        for step in steps:
            tool_name = step.tool_name.lower()
            for tool_prefix, platform in tool_to_platform.items():
                if tool_prefix in tool_name:
                    connections.add(platform)
                    break
                    
        return list(connections)

    def extract_input_variables(self, steps: List[WorkflowStep]) -> Dict[str, Any]:
        """Extract input variables from parameterized step parameters."""
        variables = {}
        
        # Pattern to match {{input.variable_name}}
        input_pattern = re.compile(r'\{\{input\.(\w+)\}\}')
        
        for step in steps:
            if step.tool_parameters:
                params_str = str(step.tool_parameters)
                matches = input_pattern.findall(params_str)
                for var_name in matches:
                    if var_name not in variables:
                        variables[var_name] = {
                            "type": "string",
                            "required": True,
                            "description": f"Input for {var_name.replace('_', ' ')}"
                        }
                        
        return variables

    async def export_workflow(
        self,
        workflow_id: uuid.UUID,
        user_id: uuid.UUID,
        db: AsyncSession,
        include_metadata: bool = True,
    ) -> Dict[str, Any]:
        """
        Export a workflow as a sanitized JSON structure.
        
        Args:
            workflow_id: ID of the workflow to export
            user_id: ID of the user requesting export
            db: Database session
            include_metadata: Whether to include marketplace metadata
        
        Returns:
            Sanitized workflow data as dictionary
        """
        # Fetch workflow with steps
        result = await db.execute(
            select(Workflow)
            .options(selectinload(Workflow.steps))
            .where(Workflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")
            
        # Check access permissions
        if workflow.user_id != user_id and workflow.visibility == WorkflowVisibility.PRIVATE:
            raise PermissionError("Cannot export private workflow")
        
        # Sanitize step parameters
        sanitized_steps = []
        for step in sorted(workflow.steps, key=lambda s: s.step_number):
            sanitized_params = self.sanitize_value("params", step.tool_parameters)
            
            sanitized_steps.append({
                "step_number": step.step_number,
                "tool_name": step.tool_name,
                "tool_parameters": sanitized_params,
                "description": step.description,
                "condition": step.condition,
                "retry_config": step.retry_config,
                "timeout": step.timeout,
            })
        
        # Build export structure
        export_data = {
            "format_version": "1.0",
            "exported_at": datetime.utcnow().isoformat(),
            "workflow": {
                "name": workflow.name,
                "description": workflow.description,
                "version": workflow.version,
                "trigger_type": workflow.trigger_type,
                "trigger_config": self.sanitize_value("trigger", workflow.trigger_config),
                "variables": workflow.variables or self.extract_input_variables(workflow.steps),
                "category": workflow.category,
                "tags": workflow.tags or [],
                "steps": sanitized_steps,
            },
            "requirements": {
                "connections": workflow.required_connections or self.extract_required_connections(workflow.steps),
            }
        }
        
        if include_metadata:
            export_data["metadata"] = {
                "author": workflow.author_name or "Anonymous",
                "license": workflow.license_type or WorkflowLicense.FREE,
                "downloads": workflow.downloads_count,
                "rating": round(workflow.rating_sum / workflow.rating_count, 1) if workflow.rating_count > 0 else None,
                "original_id": workflow.id,
                "share_code": workflow.share_code,
            }
        
        # Include agent configuration if this workflow has been converted to an agent
        if workflow.workflow_metadata and workflow.workflow_metadata.get("agent"):
            agent_data = workflow.workflow_metadata["agent"]
            export_data["agent_config"] = {
                "trigger_type": agent_data.get("trigger_type", "manual"),
                "schedule": self.sanitize_value("schedule", agent_data.get("schedule", {})),
                "is_agent": True,
            }
            
        return export_data

    async def import_workflow(
        self,
        user_id: uuid.UUID,
        workflow_data: Dict[str, Any],
        db: AsyncSession,
        source_workflow_id: Optional[uuid.UUID] = None,
    ) -> Workflow:
        """
        Import a workflow from exported JSON data.
        
        Args:
            user_id: ID of the user importing the workflow
            workflow_data: Exported workflow data
            db: Database session
            source_workflow_id: Original workflow ID if importing from marketplace
        
        Returns:
            Newly created Workflow instance
        """
        workflow_info = workflow_data.get("workflow", workflow_data)
        
        # Build workflow metadata
        workflow_metadata = {}
        if source_workflow_id:
            workflow_metadata["imported_from"] = source_workflow_id
        
        # Include agent config if present in export data
        agent_config = workflow_data.get("agent_config")
        if agent_config and agent_config.get("is_agent"):
            workflow_metadata["has_agent_template"] = True
            workflow_metadata["agent_template"] = {
                "trigger_type": agent_config.get("trigger_type", "manual"),
                "schedule": agent_config.get("schedule", {}),
            }
        
        # Create new workflow
        new_workflow = Workflow(
            user_id=user_id,
            name=f"{workflow_info.get('name', 'Imported Workflow')}",
            description=workflow_info.get('description'),
            status=WorkflowStatus.DRAFT,
            version=1,
            is_template=False,
            trigger_type=workflow_info.get('trigger_type', 'manual'),
            trigger_config=workflow_info.get('trigger_config'),
            variables=workflow_info.get('variables'),
            workflow_metadata=workflow_metadata if workflow_metadata else None,
            visibility=WorkflowVisibility.PRIVATE,
            category=workflow_info.get('category'),
            tags=workflow_info.get('tags'),
            required_connections=workflow_data.get('requirements', {}).get('connections'),
        )
        
        db.add(new_workflow)
        await db.flush()  # Get the new workflow ID
        
        # Create steps
        steps_data = workflow_info.get('steps', [])
        for step_data in steps_data:
            step = WorkflowStep(
                workflow_id=new_workflow.id,
                step_number=step_data.get('step_number', 1),
                tool_name=step_data.get('tool_name'),
                tool_parameters=step_data.get('tool_parameters'),
                description=step_data.get('description'),
                condition=step_data.get('condition'),
                retry_config=step_data.get('retry_config'),
                timeout=step_data.get('timeout'),
            )
            db.add(step)
        
        # Record download if from marketplace
        if source_workflow_id:
            download = WorkflowDownload(
                workflow_id=source_workflow_id,
                user_id=user_id,
                source_version=workflow_data.get('metadata', {}).get('version', 1),
                imported_workflow_id=new_workflow.id,
            )
            db.add(download)
            
            # Increment download count on source
            await db.execute(
                Workflow.__table__.update()
                .where(Workflow.id == source_workflow_id)
                .values(downloads_count=Workflow.downloads_count + 1)
            )
        
        await db.commit()
        await db.refresh(new_workflow)
        
        return new_workflow

    async def update_visibility(
        self,
        workflow_id: uuid.UUID,
        user_id: uuid.UUID,
        visibility: str,
        db: AsyncSession,
        **kwargs
    ) -> Workflow:
        """
        Update workflow visibility and related settings.
        
        Args:
            workflow_id: ID of the workflow
            user_id: ID of the user (must be owner)
            visibility: New visibility setting
            db: Database session
            **kwargs: Additional fields (license_type, price, category, etc.)
        
        Returns:
            Updated Workflow instance
        """
        result = await db.execute(
            select(Workflow).where(
                and_(Workflow.id == workflow_id, Workflow.user_id == user_id)
            )
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            raise ValueError("Workflow not found or access denied")
        
        # Update visibility
        workflow.visibility = visibility
        
        # Generate share code for unlisted/public/marketplace
        if visibility != WorkflowVisibility.PRIVATE and not workflow.share_code:
            workflow.share_code = self.generate_share_code(workflow_id)
        
        # Update additional fields (skip None values for NOT NULL columns)
        not_null_columns = {'license_type', 'visibility', 'downloads_count', 'rating_sum', 'rating_count'}
        for key, value in kwargs.items():
            if hasattr(workflow, key):
                # Skip None values for NOT NULL columns
                if value is None and key in not_null_columns:
                    continue
                setattr(workflow, key, value)
        
        # Auto-extract required connections if not set
        if not workflow.required_connections:
            result = await db.execute(
                select(WorkflowStep).where(WorkflowStep.workflow_id == workflow_id)
            )
            steps = result.scalars().all()
            workflow.required_connections = self.extract_required_connections(steps)
        
        await db.commit()
        await db.refresh(workflow)
        
        return workflow

    async def get_public_workflows(
        self,
        db: AsyncSession,
        category: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "downloads",
        limit: int = 20,
        offset: int = 0,
    ) -> List[Workflow]:
        """
        Get public/marketplace workflows.
        
        Args:
            db: Database session
            category: Filter by category
            search: Search term for name/description
            sort_by: Sort field (downloads, rating, created_at)
            limit: Maximum results
            offset: Pagination offset
        
        Returns:
            List of public workflows
        """
        query = select(Workflow).where(
            or_(
                Workflow.visibility == WorkflowVisibility.PUBLIC,
                Workflow.visibility == WorkflowVisibility.MARKETPLACE
            )
        )
        
        if category:
            query = query.where(Workflow.category == category)
            
        if search:
            search_filter = or_(
                Workflow.name.ilike(f"%{search}%"),
                Workflow.description.ilike(f"%{search}%"),
            )
            query = query.where(search_filter)
        
        # Sorting
        if sort_by == "downloads":
            query = query.order_by(Workflow.downloads_count.desc())
        elif sort_by == "rating":
            # Calculate average rating on the fly
            query = query.order_by(
                (Workflow.rating_sum / func.nullif(Workflow.rating_count, 0)).desc().nullslast()
            )
        elif sort_by == "newest":
            query = query.order_by(Workflow.created_at.desc())
        else:
            query = query.order_by(Workflow.downloads_count.desc())
        
        query = query.offset(offset).limit(limit)
        
        result = await db.execute(query.options(selectinload(Workflow.steps)))
        return result.scalars().all()

    async def get_workflow_by_share_code(
        self,
        share_code: str,
        db: AsyncSession,
    ) -> Optional[Workflow]:
        """Get a workflow by its share code."""
        result = await db.execute(
            select(Workflow)
            .options(selectinload(Workflow.steps))
            .where(Workflow.share_code == share_code)
        )
        return result.scalar_one_or_none()

    async def add_review(
        self,
        workflow_id: uuid.UUID,
        user_id: uuid.UUID,
        rating: int,
        db: AsyncSession,
        title: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> WorkflowReview:
        """
        Add or update a review for a workflow.
        
        Args:
            workflow_id: ID of the workflow
            user_id: ID of the reviewer
            rating: Rating 1-5
            db: Database session
            title: Review title
            comment: Review comment
        
        Returns:
            WorkflowReview instance
        """
        if not 1 <= rating <= 5:
            raise ValueError("Rating must be between 1 and 5")
        
        # Check if user already reviewed
        result = await db.execute(
            select(WorkflowReview).where(
                and_(
                    WorkflowReview.workflow_id == workflow_id,
                    WorkflowReview.user_id == user_id
                )
            )
        )
        existing_review = result.scalar_one_or_none()
        
        if existing_review:
            # Update existing review
            old_rating = existing_review.rating
            existing_review.rating = rating
            existing_review.title = title
            existing_review.comment = comment
            
            # Update workflow rating
            await db.execute(
                Workflow.__table__.update()
                .where(Workflow.id == workflow_id)
                .values(rating_sum=Workflow.rating_sum - old_rating + rating)
            )
            
            review = existing_review
        else:
            # Create new review
            review = WorkflowReview(
                workflow_id=workflow_id,
                user_id=user_id,
                rating=rating,
                title=title,
                comment=comment,
            )
            db.add(review)
            
            # Update workflow rating
            await db.execute(
                Workflow.__table__.update()
                .where(Workflow.id == workflow_id)
                .values(
                    rating_sum=Workflow.rating_sum + rating,
                    rating_count=Workflow.rating_count + 1
                )
            )
        
        await db.commit()
        await db.refresh(review)
        
        return review

    async def get_workflow_reviews(
        self,
        workflow_id: uuid.UUID,
        db: AsyncSession,
        limit: int = 20,
        offset: int = 0,
    ) -> List[WorkflowReview]:
        """Get reviews for a workflow."""
        result = await db.execute(
            select(WorkflowReview)
            .where(WorkflowReview.workflow_id == workflow_id)
            .order_by(WorkflowReview.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()

    async def get_marketplace_categories(self, db: AsyncSession) -> List[Dict[str, Any]]:
        """Get all categories with workflow counts."""
        result = await db.execute(
            select(
                Workflow.category,
                func.count(Workflow.id).label('count')
            )
            .where(
                and_(
                    or_(
                        Workflow.visibility == WorkflowVisibility.PUBLIC,
                        Workflow.visibility == WorkflowVisibility.MARKETPLACE
                    ),
                    Workflow.category.isnot(None)
                )
            )
            .group_by(Workflow.category)
            .order_by(func.count(Workflow.id).desc())
        )
        
        categories = []
        for row in result:
            categories.append({
                "name": row.category,
                "count": row.count
            })
        
        return categories

