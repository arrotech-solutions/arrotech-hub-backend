"""
Organization router for Arrotech Hub.
RESTful API endpoints for organizations, members, invitations, departments, and audit log.
"""

from typing import Any, Dict, List, Optional
import uuid
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import OrgRole, OrgInvitationStatus, Organization, OrganizationInvitation, User
from ..routers.auth_router import get_current_user
from ..services.organization_service import organization_service
from ..services.email_service import email_service

router = APIRouter()


# ── Request/Response Models ─────────────────────────────────────────────


class CreateOrganizationRequest(BaseModel):
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    billing_email: Optional[str] = None
    logo_url: Optional[str] = None


class UpdateOrganizationRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    billing_email: Optional[str] = None
    logo_url: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


class AddMemberRequest(BaseModel):
    user_id: uuid.UUID
    role: str = OrgRole.MEMBER
    title: Optional[str] = None


class UpdateMemberRequest(BaseModel):
    role: Optional[str] = None
    department_id: Optional[uuid.UUID] = None


class CreateInvitationRequest(BaseModel):
    email: str
    role: str = OrgRole.MEMBER


class AcceptInvitationRequest(BaseModel):
    token: str


class CreateDepartmentRequest(BaseModel):
    name: str
    description: Optional[str] = None
    head_id: Optional[uuid.UUID] = None


class UpdateDepartmentRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    head_id: Optional[uuid.UUID] = None


# ── Helper: require org role ────────────────────────────────────────────

async def _require_role(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, required_role: str
):
    """Raise 403 if user doesn't have sufficient role."""
    has_perm = await organization_service.check_permission(db, org_id, user_id, required_role)
    if not has_perm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires at least '{required_role}' role in this organization",
        )


# ── Organization CRUD ───────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_organization(
    request: Request,
    data: CreateOrganizationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new organization. The creator becomes the owner."""
    try:
        org = await organization_service.create_organization(
            db, name=data.name, slug=data.slug or data.name,
            owner_id=current_user.id,
            description=data.description, website=data.website,
            industry=data.industry, company_size=data.company_size,
            billing_email=data.billing_email, logo_url=data.logo_url,
            ip_address=request.client.host if request.client else None,
        )
        return {
            "success": True,
            "data": {
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "logo_url": org.logo_url,
                "description": org.description,
                "website": org.website,
                "industry": org.industry,
                "company_size": org.company_size,
                "billing_email": org.billing_email,
                "subscription_tier": org.subscription_tier,
                "created_at": org.created_at.isoformat() if org.created_at else None,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("")
async def list_organizations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all organizations the current user belongs to."""
    orgs = await organization_service.list_user_organizations(db, current_user.id)
    return {"success": True, "data": orgs}


@router.get("/{org_id}")
async def get_organization(
    org_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get organization details. Requires at least viewer role."""
    await _require_role(db, org_id, current_user.id, OrgRole.VIEWER)
    org = await organization_service.get_organization(db, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return {
        "success": True,
        "data": {
            "id": org.id,
            "name": org.name,
            "slug": org.slug,
            "logo_url": org.logo_url,
            "description": org.description,
            "website": org.website,
            "industry": org.industry,
            "company_size": org.company_size,
            "billing_email": org.billing_email,
            "subscription_tier": org.subscription_tier,
            "settings": org.settings,
            "is_active": org.is_active,
            "created_at": org.created_at.isoformat() if org.created_at else None,
            "updated_at": org.updated_at.isoformat() if org.updated_at else None,
        },
    }


@router.put("/{org_id}")
async def update_organization(
    org_id: uuid.UUID,
    request: Request,
    data: UpdateOrganizationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update organization details. Requires admin role."""
    await _require_role(db, org_id, current_user.id, OrgRole.ADMIN)
    updates = data.model_dump(exclude_none=True)
    org = await organization_service.update_organization(
        db, org_id, current_user.id, updates,
        ip_address=request.client.host if request.client else None,
    )
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return {"success": True, "data": {"id": org.id, "name": org.name, "slug": org.slug}}


@router.delete("/{org_id}")
async def delete_organization(
    org_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete (deactivate) an organization. Requires owner role."""
    await _require_role(db, org_id, current_user.id, OrgRole.OWNER)
    deleted = await organization_service.delete_organization(
        db, org_id, current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Organization not found")
    return {"success": True, "message": "Organization deleted"}


# ── Members ─────────────────────────────────────────────────────────────


@router.get("/{org_id}/members")
async def list_members(
    org_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all members. Requires viewer role."""
    await _require_role(db, org_id, current_user.id, OrgRole.VIEWER)
    members = await organization_service.get_members(db, org_id)
    return {"success": True, "data": members}


@router.post("/{org_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(
    org_id: uuid.UUID,
    request: Request,
    data: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a member directly. Requires admin role."""
    await _require_role(db, org_id, current_user.id, OrgRole.ADMIN)
    try:
        member = await organization_service.add_member(
            db, org_id, data.user_id, data.role,
            actor_id=current_user.id, title=data.title,
            ip_address=request.client.host if request.client else None,
        )
        return {"success": True, "data": {"id": member.id, "role": member.role}}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{org_id}/members/{user_id}")
async def update_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    data: UpdateMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a member's role and/or department. Requires admin role (owner to promote to owner)."""
    # Role-change permission check
    if data.role is not None:
        if data.role in (OrgRole.OWNER, OrgRole.ADMIN):
            await _require_role(db, org_id, current_user.id, OrgRole.OWNER)
        else:
            await _require_role(db, org_id, current_user.id, OrgRole.ADMIN)
    else:
        # department-only update still needs admin
        await _require_role(db, org_id, current_user.id, OrgRole.ADMIN)

    try:
        member = await organization_service.update_member(
            db, org_id, user_id,
            new_role=data.role,
            department_id=data.department_id,
            actor_id=current_user.id,
            ip_address=request.client.host if request.client else None,
        )
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        return {"success": True, "data": {"user_id": user_id, "role": member.role, "department_id": member.department_id}}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{org_id}/members/{user_id}")
async def remove_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member. Admins can remove members; self-removal allowed."""
    if user_id != current_user.id:
        await _require_role(db, org_id, current_user.id, OrgRole.ADMIN)

    try:
        removed = await organization_service.remove_member(
            db, org_id, user_id,
            actor_id=current_user.id,
            ip_address=request.client.host if request.client else None,
        )
        if not removed:
            raise HTTPException(status_code=404, detail="Member not found")
        return {"success": True, "message": "Member removed"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Invitations ─────────────────────────────────────────────────────────


@router.post("/{org_id}/invitations", status_code=status.HTTP_201_CREATED)
async def create_invitation(
    org_id: uuid.UUID,
    request: Request,
    data: CreateInvitationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an invitation. Requires admin role."""
    await _require_role(db, org_id, current_user.id, OrgRole.ADMIN)
    try:
        invitation = await organization_service.create_invitation(
            db, org_id, data.email, data.role,
            invited_by=current_user.id,
            ip_address=request.client.host if request.client else None,
        )

        # ── Send invitation email ──────────────────────────────────────
        org = await organization_service.get_organization(db, org_id)
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
        invite_url = f"{frontend_url}/invite/{invitation.token}"
        try:
            await email_service.send_org_invitation_email(
                to_email=data.email,
                org_name=org.name if org else "Organization",
                inviter_name=current_user.name or current_user.email,
                role=data.role,
                invite_url=invite_url,
            )
        except Exception:
            pass  # Email failure should not block invitation creation

        return {
            "success": True,
            "data": {
                "id": invitation.id,
                "email": invitation.email,
                "role": invitation.role,
                "token": invitation.token,
                "expires_at": invitation.expires_at.isoformat() if invitation.expires_at else None,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{org_id}/invitations")
async def list_invitations(
    org_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List pending invitations. Requires admin role."""
    await _require_role(db, org_id, current_user.id, OrgRole.ADMIN)
    invitations = await organization_service.list_invitations(db, org_id)
    return {"success": True, "data": invitations}


@router.delete("/{org_id}/invitations/{invitation_id}")
async def revoke_invitation(
    org_id: uuid.UUID,
    invitation_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a pending invitation. Requires admin role."""
    await _require_role(db, org_id, current_user.id, OrgRole.ADMIN)
    revoked = await organization_service.revoke_invitation(
        db, org_id, invitation_id, current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    if not revoked:
        raise HTTPException(status_code=404, detail="Invitation not found")
    return {"success": True, "message": "Invitation revoked"}


@router.post("/invitations/accept")
async def accept_invitation(
    request: Request,
    data: AcceptInvitationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept an invitation by token."""
    try:
        member = await organization_service.accept_invitation(
            db, data.token, current_user.id,
            ip_address=request.client.host if request.client else None,
        )
        return {
            "success": True,
            "data": {"org_id": member.org_id, "role": member.role},
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/invitations/info/{token}")
async def get_invitation_info(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint: get invitation details by token (no auth required)."""
    result = await db.execute(
        select(OrganizationInvitation).where(OrganizationInvitation.token == token)
    )
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    # Fetch org name
    org = await db.get(Organization, invitation.org_id)
    # Fetch inviter name
    inviter = await db.get(User, invitation.invited_by)

    return {
        "success": True,
        "data": {
            "email": invitation.email,
            "role": invitation.role,
            "status": invitation.status,
            "org_name": org.name if org else "Unknown",
            "org_logo": org.logo_url if org else None,
            "inviter_name": inviter.name if inviter else "Someone",
            "expires_at": invitation.expires_at.isoformat() if invitation.expires_at else None,
        },
    }


# ── Departments ─────────────────────────────────────────────────────────


@router.get("/{org_id}/departments")
async def list_departments(
    org_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List departments. Requires viewer role."""
    await _require_role(db, org_id, current_user.id, OrgRole.VIEWER)
    departments = await organization_service.list_departments(db, org_id)
    return {"success": True, "data": departments}


@router.post("/{org_id}/departments", status_code=status.HTTP_201_CREATED)
async def create_department(
    org_id: uuid.UUID,
    request: Request,
    data: CreateDepartmentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a department. Requires admin role."""
    await _require_role(db, org_id, current_user.id, OrgRole.ADMIN)
    dept = await organization_service.create_department(
        db, org_id, data.name, current_user.id,
        description=data.description, head_id=data.head_id,
        ip_address=request.client.host if request.client else None,
    )
    return {
        "success": True,
        "data": {"id": dept.id, "name": dept.name},
    }


@router.put("/{org_id}/departments/{dept_id}")
async def update_department(
    org_id: uuid.UUID,
    dept_id: uuid.UUID,
    request: Request,
    data: UpdateDepartmentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a department. Requires admin role."""
    await _require_role(db, org_id, current_user.id, OrgRole.ADMIN)
    updates = data.model_dump(exclude_none=True)
    dept = await organization_service.update_department(
        db, org_id, dept_id, updates, current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    return {"success": True, "data": {"id": dept.id, "name": dept.name}}


@router.delete("/{org_id}/departments/{dept_id}")
async def delete_department(
    org_id: uuid.UUID,
    dept_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a department. Requires admin role."""
    await _require_role(db, org_id, current_user.id, OrgRole.ADMIN)
    deleted = await organization_service.delete_department(
        db, org_id, dept_id, current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Department not found")
    return {"success": True, "message": "Department deleted"}


# ── Audit Log ───────────────────────────────────────────────────────────


@router.get("/{org_id}/audit-log")
async def get_audit_log(
    org_id: uuid.UUID,
    action: Optional[str] = None,
    actor_id: Optional[uuid.UUID] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Query audit log. Requires admin role."""
    await _require_role(db, org_id, current_user.id, OrgRole.ADMIN)
    result = await organization_service.get_audit_log(
        db, org_id, action_filter=action,
        actor_id_filter=actor_id, limit=limit, offset=offset,
    )
    return {"success": True, "data": result}
