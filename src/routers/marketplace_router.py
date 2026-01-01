"""
Marketplace Router

API endpoints for workflow sharing, marketplace, and community features.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from .auth_router import get_current_user
from ..models import User, Workflow, WorkflowVisibility, WorkflowLicense
from ..services.workflow_sharing_service import WorkflowSharingService

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


# Request/Response Models
class UpdateVisibilityRequest(BaseModel):
    """Request to update workflow visibility."""
    visibility: str = Field(..., description="Visibility level: private, unlisted, public, marketplace")
    license_type: Optional[str] = Field(None, description="License type: free, personal, commercial, enterprise")
    price: Optional[int] = Field(None, description="Price in cents (for marketplace)")
    currency: Optional[str] = Field("USD", description="Currency code")
    category: Optional[str] = Field(None, description="Workflow category")
    tags: Optional[List[str]] = Field(None, description="Tags for search")
    author_name: Optional[str] = Field(None, description="Author display name")


class ImportWorkflowRequest(BaseModel):
    """Request to import a workflow."""
    workflow_data: Dict[str, Any] = Field(..., description="Exported workflow JSON data")
    source_workflow_id: Optional[int] = Field(None, description="Original workflow ID if from marketplace")


class AddReviewRequest(BaseModel):
    """Request to add a review."""
    rating: int = Field(..., ge=1, le=5, description="Rating 1-5")
    title: Optional[str] = Field(None, max_length=100)
    comment: Optional[str] = Field(None, max_length=1000)


class WorkflowSummary(BaseModel):
    """Summary of a workflow for marketplace listing."""
    id: int
    name: str
    description: Optional[str]
    author_name: Optional[str]
    category: Optional[str]
    tags: Optional[List[str]]
    visibility: str
    license_type: str
    price: Optional[int]
    currency: str
    downloads_count: int
    rating: Optional[float]
    rating_count: int
    required_connections: Optional[List[str]]
    steps_count: int
    created_at: str


class ReviewResponse(BaseModel):
    """Review response model."""
    id: int
    user_id: int
    rating: int
    title: Optional[str]
    comment: Optional[str]
    helpful_count: int
    created_at: str


class MarketplaceResponse(BaseModel):
    """Generic marketplace API response."""
    success: bool
    data: Any = None
    message: Optional[str] = None


# Endpoints

@router.get("/browse", response_model=MarketplaceResponse)
async def browse_workflows(
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search term"),
    sort_by: str = Query("downloads", description="Sort by: downloads, rating, newest"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Browse public and marketplace workflows."""
    try:
        sharing_service = WorkflowSharingService()
        workflows = await sharing_service.get_public_workflows(
            db, category=category, search=search, sort_by=sort_by, limit=limit, offset=offset
        )
        
        summaries = []
        for wf in workflows:
            summaries.append({
                "id": wf.id,
                "name": wf.name,
                "description": wf.description,
                "author_name": wf.author_name or "Anonymous",
                "category": wf.category,
                "tags": wf.tags,
                "visibility": wf.visibility,
                "license_type": wf.license_type or WorkflowLicense.FREE,
                "price": wf.price,
                "currency": wf.currency or "USD",
                "downloads_count": wf.downloads_count,
                "rating": round(wf.rating_sum / wf.rating_count, 1) if wf.rating_count > 0 else None,
                "rating_count": wf.rating_count,
                "required_connections": wf.required_connections,
                "steps_count": len(wf.steps),
                "created_at": wf.created_at.isoformat() if wf.created_at else None,
            })
        
        return MarketplaceResponse(success=True, data=summaries)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to browse workflows: {str(e)}"
        )


@router.get("/categories", response_model=MarketplaceResponse)
async def get_categories(
    db: AsyncSession = Depends(get_db),
):
    """Get all marketplace categories with counts."""
    try:
        sharing_service = WorkflowSharingService()
        categories = await sharing_service.get_marketplace_categories(db)
        return MarketplaceResponse(success=True, data=categories)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get categories: {str(e)}"
        )


@router.get("/workflow/{share_code}", response_model=MarketplaceResponse)
async def get_workflow_by_share_code(
    share_code: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a workflow by its share code (for unlisted sharing)."""
    try:
        sharing_service = WorkflowSharingService()
        workflow = await sharing_service.get_workflow_by_share_code(share_code, db)
        
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found"
            )
        
        # Check visibility
        if workflow.visibility == WorkflowVisibility.PRIVATE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This workflow is private"
            )
        
        # Return summary (not full export unless they import)
        data = {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "author_name": workflow.author_name or "Anonymous",
            "category": workflow.category,
            "tags": workflow.tags,
            "visibility": workflow.visibility,
            "license_type": workflow.license_type or WorkflowLicense.FREE,
            "price": workflow.price,
            "currency": workflow.currency or "USD",
            "downloads_count": workflow.downloads_count,
            "rating": round(workflow.rating_sum / workflow.rating_count, 1) if workflow.rating_count > 0 else None,
            "rating_count": workflow.rating_count,
            "required_connections": workflow.required_connections,
            "steps_count": len(workflow.steps),
            "steps_preview": [{"tool_name": s.tool_name, "description": s.description} for s in workflow.steps[:5]],
            "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
        }
        
        return MarketplaceResponse(success=True, data=data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get workflow: {str(e)}"
        )


@router.post("/workflow/{workflow_id}/export", response_model=MarketplaceResponse)
async def export_workflow(
    workflow_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export a workflow as sanitized JSON."""
    try:
        sharing_service = WorkflowSharingService()
        export_data = await sharing_service.export_workflow(
            workflow_id, user.id, db, include_metadata=True
        )
        return MarketplaceResponse(success=True, data=export_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export workflow: {str(e)}"
        )


@router.post("/workflow/import", response_model=MarketplaceResponse)
async def import_workflow(
    request: ImportWorkflowRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Import a workflow from JSON data."""
    try:
        sharing_service = WorkflowSharingService()
        new_workflow = await sharing_service.import_workflow(
            user.id,
            request.workflow_data,
            db,
            source_workflow_id=request.source_workflow_id,
        )
        
        return MarketplaceResponse(
            success=True,
            data={"workflow_id": new_workflow.id, "name": new_workflow.name},
            message="Workflow imported successfully"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import workflow: {str(e)}"
        )


@router.put("/workflow/{workflow_id}/visibility", response_model=MarketplaceResponse)
async def update_workflow_visibility(
    workflow_id: int,
    request: UpdateVisibilityRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update workflow visibility and marketplace settings."""
    try:
        sharing_service = WorkflowSharingService()
        
        # Validate visibility
        valid_visibilities = [v.value for v in WorkflowVisibility]
        if request.visibility not in valid_visibilities:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid visibility. Must be one of: {valid_visibilities}"
            )
        
        workflow = await sharing_service.update_visibility(
            workflow_id,
            user.id,
            request.visibility,
            db,
            license_type=request.license_type or WorkflowLicense.FREE,
            price=request.price,
            currency=request.currency,
            category=request.category,
            tags=request.tags,
            author_name=request.author_name,
        )
        
        return MarketplaceResponse(
            success=True,
            data={
                "workflow_id": workflow.id,
                "visibility": workflow.visibility,
                "share_code": workflow.share_code,
                "share_url": f"/marketplace/workflow/{workflow.share_code}" if workflow.share_code else None,
            },
            message=f"Workflow visibility updated to {request.visibility}"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update visibility: {str(e)}"
        )


@router.get("/workflow/{workflow_id}/reviews", response_model=MarketplaceResponse)
async def get_workflow_reviews(
    workflow_id: int,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get reviews for a workflow."""
    try:
        sharing_service = WorkflowSharingService()
        reviews = await sharing_service.get_workflow_reviews(
            workflow_id, db, limit=limit, offset=offset
        )
        
        review_data = [
            {
                "id": r.id,
                "user_id": r.user_id,
                "rating": r.rating,
                "title": r.title,
                "comment": r.comment,
                "helpful_count": r.helpful_count,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reviews
        ]
        
        return MarketplaceResponse(success=True, data=review_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get reviews: {str(e)}"
        )


@router.post("/workflow/{workflow_id}/review", response_model=MarketplaceResponse)
async def add_workflow_review(
    workflow_id: int,
    request: AddReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Add or update a review for a workflow."""
    try:
        sharing_service = WorkflowSharingService()
        review = await sharing_service.add_review(
            workflow_id,
            user.id,
            request.rating,
            db,
            title=request.title,
            comment=request.comment,
        )
        
        return MarketplaceResponse(
            success=True,
            data={
                "review_id": review.id,
                "rating": review.rating,
            },
            message="Review added successfully"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add review: {str(e)}"
        )


@router.get("/my-shared", response_model=MarketplaceResponse)
async def get_my_shared_workflows(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get workflows shared by the current user."""
    try:
        from sqlalchemy import select, or_
        
        result = await db.execute(
            select(Workflow)
            .where(
                Workflow.user_id == user.id,
                or_(
                    Workflow.visibility == WorkflowVisibility.UNLISTED,
                    Workflow.visibility == WorkflowVisibility.PUBLIC,
                    Workflow.visibility == WorkflowVisibility.MARKETPLACE,
                )
            )
            .order_by(Workflow.updated_at.desc())
        )
        workflows = result.scalars().all()
        
        data = [
            {
                "id": wf.id,
                "name": wf.name,
                "visibility": wf.visibility,
                "share_code": wf.share_code,
                "downloads_count": wf.downloads_count,
                "rating": round(wf.rating_sum / wf.rating_count, 1) if wf.rating_count > 0 else None,
                "rating_count": wf.rating_count,
            }
            for wf in workflows
        ]
        
        return MarketplaceResponse(success=True, data=data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get shared workflows: {str(e)}"
        )


@router.get("/my-downloads", response_model=MarketplaceResponse)
async def get_my_downloads(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get workflows downloaded/imported by the current user."""
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from ..models import WorkflowDownload
        
        result = await db.execute(
            select(WorkflowDownload)
            .options(selectinload(WorkflowDownload.workflow))
            .where(WorkflowDownload.user_id == user.id)
            .order_by(WorkflowDownload.downloaded_at.desc())
        )
        downloads = result.scalars().all()
        
        data = [
            {
                "id": d.id,
                "workflow_id": d.workflow_id,
                "workflow_name": d.workflow.name if d.workflow else "Unknown",
                "downloaded_at": d.downloaded_at.isoformat() if d.downloaded_at else None,
                "imported_workflow_id": d.imported_workflow_id,
            }
            for d in downloads
        ]
        
        return MarketplaceResponse(success=True, data=data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get downloads: {str(e)}"
        )


# ================== Workflow Versioning Endpoints ==================

class CreateVersionRequest(BaseModel):
    """Request to create a new version of a workflow."""
    changelog: Optional[str] = Field(None, description="What changed in this version")
    is_breaking: bool = Field(False, description="Whether this is a breaking change")


class VersionResponse(BaseModel):
    """Response for a workflow version."""
    id: int
    workflow_id: int
    version_number: int
    name: str
    description: Optional[str]
    changelog: Optional[str]
    is_breaking: bool
    created_at: str


@router.get("/workflow/{workflow_id}/versions", response_model=MarketplaceResponse)
async def get_workflow_versions(
    workflow_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get all versions of a workflow."""
    try:
        from sqlalchemy import select
        from ..models import WorkflowVersion
        
        result = await db.execute(
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.version_number.desc())
        )
        versions = result.scalars().all()
        
        data = [
            {
                "id": v.id,
                "workflow_id": v.workflow_id,
                "version_number": v.version_number,
                "name": v.name,
                "description": v.description,
                "changelog": v.changelog,
                "is_breaking": v.is_breaking,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in versions
        ]
        
        return MarketplaceResponse(success=True, data=data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get versions: {str(e)}"
        )


@router.post("/workflow/{workflow_id}/version", response_model=MarketplaceResponse)
async def create_workflow_version(
    workflow_id: int,
    request: CreateVersionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new version snapshot of a workflow."""
    try:
        from sqlalchemy import select, func
        from sqlalchemy.orm import selectinload
        from ..models import WorkflowVersion
        
        # Get the workflow with steps
        result = await db.execute(
            select(Workflow)
            .options(selectinload(Workflow.steps))
            .where(Workflow.id == workflow_id, Workflow.user_id == user.id)
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found or not authorized"
            )
        
        # Get the next version number
        result = await db.execute(
            select(func.max(WorkflowVersion.version_number))
            .where(WorkflowVersion.workflow_id == workflow_id)
        )
        max_version = result.scalar() or 0
        new_version_number = max_version + 1
        
        # Create steps snapshot
        steps_snapshot = [
            {
                "step_number": step.step_number,
                "tool_name": step.tool_name,
                "tool_parameters": step.tool_parameters,
                "description": step.description,
                "condition": step.condition,
                "retry_config": step.retry_config,
                "timeout": step.timeout,
            }
            for step in sorted(workflow.steps, key=lambda s: s.step_number)
        ]
        
        # Create the version record
        version = WorkflowVersion(
            workflow_id=workflow_id,
            version_number=new_version_number,
            name=workflow.name,
            description=workflow.description,
            steps_snapshot=steps_snapshot,
            variables_snapshot=workflow.variables,
            trigger_config_snapshot=workflow.trigger_config,
            changelog=request.changelog,
            is_breaking=request.is_breaking,
            created_by=user.id,
        )
        
        db.add(version)
        
        # Update workflow version number
        workflow.version = new_version_number
        
        await db.commit()
        await db.refresh(version)
        
        return MarketplaceResponse(
            success=True,
            data={
                "id": version.id,
                "version_number": version.version_number,
                "changelog": version.changelog,
            },
            message=f"Version {new_version_number} created successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create version: {str(e)}"
        )


@router.get("/workflow/{workflow_id}/version/{version_number}", response_model=MarketplaceResponse)
async def get_workflow_version(
    workflow_id: int,
    version_number: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific version of a workflow."""
    try:
        from sqlalchemy import select
        from ..models import WorkflowVersion
        
        result = await db.execute(
            select(WorkflowVersion)
            .where(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.version_number == version_number
            )
        )
        version = result.scalar_one_or_none()
        
        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Version not found"
            )
        
        return MarketplaceResponse(
            success=True,
            data={
                "id": version.id,
                "workflow_id": version.workflow_id,
                "version_number": version.version_number,
                "name": version.name,
                "description": version.description,
                "steps": version.steps_snapshot,
                "variables": version.variables_snapshot,
                "trigger_config": version.trigger_config_snapshot,
                "changelog": version.changelog,
                "is_breaking": version.is_breaking,
                "created_at": version.created_at.isoformat() if version.created_at else None,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get version: {str(e)}"
        )


@router.post("/workflow/{workflow_id}/rollback/{version_number}", response_model=MarketplaceResponse)
async def rollback_to_version(
    workflow_id: int,
    version_number: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Rollback a workflow to a specific version."""
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from ..models import WorkflowVersion, WorkflowStep
        
        # Get the workflow
        result = await db.execute(
            select(Workflow)
            .options(selectinload(Workflow.steps))
            .where(Workflow.id == workflow_id, Workflow.user_id == user.id)
        )
        workflow = result.scalar_one_or_none()
        
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workflow not found or not authorized"
            )
        
        # Get the version to rollback to
        result = await db.execute(
            select(WorkflowVersion)
            .where(
                WorkflowVersion.workflow_id == workflow_id,
                WorkflowVersion.version_number == version_number
            )
        )
        version = result.scalar_one_or_none()
        
        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Version not found"
            )
        
        # Delete current steps
        for step in workflow.steps:
            await db.delete(step)
        
        # Restore from version snapshot
        workflow.name = version.name
        workflow.description = version.description
        workflow.variables = version.variables_snapshot
        workflow.trigger_config = version.trigger_config_snapshot
        
        # Recreate steps from snapshot
        for step_data in version.steps_snapshot:
            step = WorkflowStep(
                workflow_id=workflow_id,
                step_number=step_data.get("step_number", 1),
                tool_name=step_data.get("tool_name"),
                tool_parameters=step_data.get("tool_parameters"),
                description=step_data.get("description"),
                condition=step_data.get("condition"),
                retry_config=step_data.get("retry_config"),
                timeout=step_data.get("timeout"),
            )
            db.add(step)
        
        await db.commit()
        
        return MarketplaceResponse(
            success=True,
            message=f"Rolled back to version {version_number}"
        )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rollback: {str(e)}"
        )

