
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Workflow, WorkflowStatus, WorkflowVisibility, WorkflowLicense, User
from ..database import get_db

logger = logging.getLogger(__name__)

class WorkflowService:
    """Service for managing workflows."""

    async def create_draft_workflow(
        self,
        user_id: int,
        title: str,
        description: str,
        steps: List[Dict[str, Any]],
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Create a new draft workflow."""
        try:
            workflow = Workflow(
                user_id=user_id,
                title=title,
                description=description,
                steps=steps,
                status=WorkflowStatus.DRAFT,
                visibility=WorkflowVisibility.PRIVATE,
                license=WorkflowLicense.PERSONAL,
                is_premium=False,
                price=0,
                downloads_count=0
            )
            db.add(workflow)
            await db.commit()
            await db.refresh(workflow)

            return {
                "success": True,
                "workflow_id": workflow.id,
                "message": f"Workflow '{title}' created successfully."
            }
        except Exception as e:
            logger.error(f"Error creating workflow: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def list_workflows(
        self,
        user_id: int,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """List workflows for a user."""
        try:
            result = await db.execute(
                select(Workflow).filter(Workflow.user_id == user_id)
            )
            workflows = result.scalars().all()
            
            return {
                "success": True,
                "workflows": [
                    {
                        "id": w.id,
                        "title": w.title,
                        "description": w.description,
                        "status": w.status,
                        "created_at": w.created_at.isoformat() if w.created_at else None
                    } for w in workflows
                ]
            }
        except Exception as e:
            logger.error(f"Error listing workflows: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_workflow(
        self,
        workflow_id: int,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Get a specific workflow."""
        try:
            result = await db.execute(
                select(Workflow).filter(Workflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()

            if not workflow:
                return {
                    "success": False,
                    "error": "Workflow not found"
                }

            return {
                "success": True,
                "workflow": {
                    "id": workflow.id,
                    "title": workflow.title,
                    "description": workflow.description,
                    "steps": workflow.steps,
                    "status": workflow.status,
                    "visibility": workflow.visibility,
                    "created_at": workflow.created_at.isoformat() if workflow.created_at else None
                }
            }
        except Exception as e:
            logger.error(f"Error getting workflow: {e}")
            return {
                "success": False,
                "error": str(e)
            }
