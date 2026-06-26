"""
Employee & Admin management router for Arrotech Hub.
Handles employee promotion, permission management, and subscriber listing.
"""

import logging
from typing import Optional, List
import uuid
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, UserRole
from ..routers.auth_router import get_current_user
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

EMPLOYEE_EMAIL_DOMAIN = "@arrotechsolutions.com"


# ── Pydantic Schemas ─────────────────────────────────────

class PromoteEmployeeRequest(BaseModel):
    email: str


class UpdatePermissionsRequest(BaseModel):
    permissions: dict  # {"blog_write": true, "blog_publish": true}


class EmployeeOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: str
    permissions: dict
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class SubscriberOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    subscription_tier: str
    subscription_status: Optional[str] = None
    subscription_end_date: Optional[str] = None
    role: str
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


# ── Helper: Admin Guard ──────────────────────────────────

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that ensures the current user is an admin."""
    is_admin_by_role = getattr(current_user, 'role', None) == UserRole.ADMIN
    is_admin_by_email = settings.ADMIN_EMAIL and current_user.email == settings.ADMIN_EMAIL
    if not (is_admin_by_role or is_admin_by_email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


def require_employee_or_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that ensures the current user is an employee or admin."""
    role = getattr(current_user, 'role', 'user') or 'user'
    is_admin_by_email = settings.ADMIN_EMAIL and current_user.email == settings.ADMIN_EMAIL
    if role not in (UserRole.EMPLOYEE, UserRole.ADMIN) and not is_admin_by_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employee or admin access required"
        )
    return current_user


def require_permission(permission_name: str):
    """Returns a dependency that checks for a specific permission."""
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        role = getattr(current_user, 'role', 'user') or 'user'
        is_admin_by_email = settings.ADMIN_EMAIL and current_user.email == settings.ADMIN_EMAIL

        # Admins have all permissions
        if role == UserRole.ADMIN or is_admin_by_email:
            return current_user

        # Check employee role and specific permission
        if role != UserRole.EMPLOYEE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires employee role with '{permission_name}' permission"
            )

        perms = getattr(current_user, 'permissions', {}) or {}
        if not perms.get(permission_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission_name}"
            )
        return current_user
    return dependency


# ── Employee Management Endpoints ─────────────────────────

@router.get("/employees")
async def list_employees(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all employees (users with role=employee)."""
    result = await db.execute(
        select(User).where(User.role == UserRole.EMPLOYEE).order_by(User.created_at.desc())
    )
    employees = result.scalars().all()

    return {
        "success": True,
        "data": [
            {
                "id": e.id,
                "email": e.email,
                "name": e.name,
                "role": e.role or "user",
                "permissions": e.permissions or {},
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in employees
        ]
    }


@router.post("/employees/promote")
async def promote_to_employee(
    data: PromoteEmployeeRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Promote a user to employee role.
    Only @arrotechsolutions.com emails can be promoted.
    """
    # Validate domain
    if not data.email.lower().endswith(EMPLOYEE_EMAIL_DOMAIN):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only {EMPLOYEE_EMAIL_DOMAIN} emails can be promoted to employee"
        )

    # Find user
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. They must register first."
        )

    if (user.role or "user") == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify admin users"
        )

    user.role = UserRole.EMPLOYEE
    # Don't auto-grant permissions — admin must toggle them explicitly
    if not user.permissions:
        user.permissions = {}

    await db.commit()
    await db.refresh(user)

    return {
        "success": True,
        "message": f"{data.email} promoted to employee",
        "data": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "permissions": user.permissions or {},
        }
    }


@router.put("/employees/{user_id}/permissions")
async def update_employee_permissions(
    user_id: uuid.UUID,
    data: UpdatePermissionsRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update an employee's permissions."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if (user.role or "user") not in (UserRole.EMPLOYEE, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only update permissions for employees"
        )

    # Merge permissions — must create a NEW dict for SQLAlchemy JSON change detection
    current_perms = dict(user.permissions or {})
    current_perms.update(data.permissions)
    user.permissions = current_perms  # assign new dict triggers change detection

    # Belt-and-suspenders: explicitly mark as modified
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(user, "permissions")

    await db.commit()
    await db.refresh(user)

    return {
        "success": True,
        "message": "Permissions updated",
        "data": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "permissions": user.permissions,
        }
    }


@router.delete("/employees/{user_id}/demote")
async def demote_employee(
    user_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Demote an employee back to regular user role."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if (user.role or "user") == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot demote admin users"
        )

    user.role = UserRole.USER
    user.permissions = {}

    await db.commit()

    return {
        "success": True,
        "message": f"{user.email} demoted to regular user"
    }


# ── Subscriber Management Endpoints ──────────────────────

@router.get("/subscribers")
async def list_subscribers(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    tier: Optional[str] = None,
    search: Optional[str] = None,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all subscribers (users) with subscription information."""
    query = select(User).order_by(User.created_at.desc())

    if tier:
        query = query.where(User.subscription_tier == tier)

    if search:
        search_term = f"%{search}%"
        from sqlalchemy import or_
        query = query.where(
            or_(
                User.email.ilike(search_term),
                User.name.ilike(search_term),
            )
        )

    # Count total
    count_query = select(sa_func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    users = result.scalars().all()

    import math
    return {
        "success": True,
        "data": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "subscription_tier": u.subscription_tier or "free",
                "subscription_status": u.subscription_status or "active",
                "subscription_end_date": u.subscription_end_date.isoformat() if u.subscription_end_date else None,
                "role": getattr(u, 'role', 'user') or "user",
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, math.ceil(total / per_page)),
    }


# ── Employee Blog Posts (for Employee Hub) ────────────────

@router.get("/my-posts")
async def list_my_posts(
    employee: User = Depends(require_employee_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """List blog posts authored by the current employee."""
    from ..models import BlogPostModel
    result = await db.execute(
        select(BlogPostModel)
        .where(BlogPostModel.author_name == employee.name)
        .order_by(BlogPostModel.created_at.desc())
    )
    posts = result.scalars().all()

    return {
        "success": True,
        "data": [
            {
                "id": p.id,
                "slug": p.slug,
                "title": p.title,
                "description": p.description,
                "status": p.status,
                "is_featured": p.is_featured,
                "read_time": p.read_time,
                "views_count": p.views_count,
                "published_at": p.published_at.isoformat() if p.published_at else None,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in posts
        ]
    }


# ── Admin: manual subscription override ──────────────────

class AdminSetSubscriptionRequest(BaseModel):
    tier: str
    status: str = "active"
    end_date: str  # ISO datetime
    billing_cycle: str = "monthly"


@router.post("/users/{user_id}/subscription")
async def admin_set_user_subscription(
    user_id: uuid.UUID,
    body: AdminSetSubscriptionRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Manually set a user's subscription (support / onboarding).
    Ops: verify Paystack payment → set tier/status/end_date → confirm GET /subscription/status.
    """
    from datetime import datetime, timezone
    from ..services.subscription_service import subscription_service

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        end_dt = datetime.fromisoformat(body.end_date.replace("Z", "+00:00"))
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid end_date format (use ISO 8601)")

    sub_result = await subscription_service.admin_set_subscription(
        user=target,
        tier=body.tier.lower(),
        status=body.status,
        end_date=end_dt,
        billing_cycle=body.billing_cycle,
        db=db,
    )
    logger.info(
        "Admin %s set subscription for user %s: tier=%s end=%s",
        admin.id,
        user_id,
        body.tier,
        body.end_date,
    )
    return sub_result
