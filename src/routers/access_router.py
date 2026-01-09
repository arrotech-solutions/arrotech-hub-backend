"""
Access request router for Arrotech Hub.
Handles waitlist requests, status checks, and approvals.
"""

from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import AccessRequest, AccessRequestStatus

router = APIRouter(prefix="/access", tags=["access"])

class AccessRequestSchema(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    reason: Optional[str] = None

class AccessStatusResponse(BaseModel):
    email: str
    status: str
    created_at: datetime
    approved_at: Optional[datetime] = None

class ApprovalRequest(BaseModel):
    email: EmailStr
    action: str  # approve or reject

@router.post("/request")
async def request_access(
    data: AccessRequestSchema,
    db: AsyncSession = Depends(get_db)
):
    """Submit a new request for platform access."""
    # Check if a request already exists
    result = await db.execute(
        select(AccessRequest).where(AccessRequest.email == data.email)
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        return {
            "success": True,
            "message": "Access request already submitted",
            "status": existing.status
        }
    
    # Create new request
    new_request = AccessRequest(
        email=data.email,
        name=data.name,
        reason=data.reason,
        status=AccessRequestStatus.PENDING
    )
    
    db.add(new_request)
    await db.commit()
    await db.refresh(new_request)
    
    return {
        "success": True,
        "message": "Successfully joined the waitlist",
        "status": new_request.status
    }

@router.get("/status")
async def get_access_status(
    email: EmailStr = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Check the status of an access request."""
    # 1. Check if user already exists (e.g. Admin or already registered)
    user_result = await db.execute(
        select(User).where(User.email == email)
    )
    user = user_result.scalar_one_or_none()
    
    if user:
        return {
            "success": True,
            "data": {
                "email": user.email,
                "status": AccessRequestStatus.APPROVED,
                "created_at": user.created_at,
                "approved_at": user.created_at
            }
        }

    # 2. Check access request table
    result = await db.execute(
        select(AccessRequest).where(AccessRequest.email == email)
    )
    request = result.scalar_one_or_none()
    
    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No access request found for this email"
        )
    
    return {
        "success": True,
        "data": {
            "email": request.email,
            "status": request.status,
            "created_at": request.created_at,
            "approved_at": request.approved_at
        }
    }

from ..routers.auth_router import get_current_user
from ..models import User
from ..config import settings

@router.get("/requests")
async def list_access_requests(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List access requests (Admin only)."""
    # Check if current user is the admin
    if not settings.ADMIN_EMAIL or current_user.email != settings.ADMIN_EMAIL:
         raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    query = select(AccessRequest).order_by(AccessRequest.created_at.desc())
    
    if status:
        query = query.where(AccessRequest.status == status)
        
    query = query.limit(limit).offset(offset)
    
    result = await db.execute(query)
    requests = result.scalars().all()
    
    return {
        "success": True,
        "data": requests
    }

@router.post("/approve")
async def approve_access(
    data: ApprovalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Approve or reject an access request (Admin only)."""
    # Check if current user is the admin
    if not settings.ADMIN_EMAIL or current_user.email != settings.ADMIN_EMAIL:
         raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
        
    new_status = AccessRequestStatus.APPROVED if data.action == "approve" else AccessRequestStatus.REJECTED
    approved_at = datetime.utcnow() if new_status == AccessRequestStatus.APPROVED else None
    
    stmt = (
        update(AccessRequest)
        .where(AccessRequest.email == data.email)
        .values(status=new_status, approved_at=approved_at)
        .returning(AccessRequest)
    )
    
    result = await db.execute(stmt)
    updated = result.scalar_one_or_none()
    
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Access request not found"
        )
        
    await db.commit()
    
    return {
        "success": True,
        "message": f"Request {data.action}d successfully",
        "data": {
            "email": updated.email,
            "status": updated.status
        }
    }
