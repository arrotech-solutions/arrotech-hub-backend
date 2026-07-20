"""
Organization service for Arrotech Hub.
Handles CRUD for organizations, memberships, invitations, departments, and audit logging.
"""

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import (
    AuditLogEntry,
    Department,
    OrgInvitationStatus,
    OrgRole,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    User,
)

logger = logging.getLogger(__name__)

INVITATION_EXPIRY_DAYS = 7


def slugify(text: str) -> str:
    """Generate a URL-friendly slug from text."""
    slug = text.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')


class OrganizationService:
    """Organization management service."""

    # ── Organization CRUD ───────────────────────────────────────────────

    async def create_organization(
        self,
        db: AsyncSession,
        name: str,
        slug: str,
        owner_id: uuid.UUID,
        *,
        description: str = None,
        website: str = None,
        industry: str = None,
        company_size: str = None,
        billing_email: str = None,
        logo_url: str = None,
        ip_address: str = None,
    ) -> Organization:
        """Create a new organization and add the creator as owner."""
        # Ensure slug is unique
        slug = slugify(slug) if slug else slugify(name)
        existing = await db.execute(
            select(Organization).where(Organization.slug == slug)
        )
        if existing.scalar_one_or_none():
            # Append random suffix
            slug = f"{slug}-{secrets.token_hex(3)}"

        org = Organization(
            name=name,
            slug=slug,
            description=description,
            website=website,
            industry=industry,
            company_size=company_size,
            billing_email=billing_email,
            logo_url=logo_url,
            created_by=owner_id,
        )
        db.add(org)
        await db.flush()  # get org.id

        # Add creator as owner
        member = OrganizationMember(
            org_id=org.id,
            user_id=owner_id,
            role=OrgRole.OWNER,
        )
        db.add(member)

        # Audit log
        await self._log(db, org.id, owner_id, "org.created", "organization", str(org.id),
                        details={"name": name, "slug": slug}, ip_address=ip_address)

        await db.commit()
        await db.refresh(org)
        return org

    async def get_organization(self, db: AsyncSession, org_id: uuid.UUID) -> Optional[Organization]:
        """Get organization by ID."""
        result = await db.execute(
            select(Organization).where(Organization.id == org_id, Organization.is_active == True)
        )
        return result.scalar_one_or_none()

    async def get_organization_by_slug(self, db: AsyncSession, slug: str) -> Optional[Organization]:
        """Get organization by slug."""
        result = await db.execute(
            select(Organization).where(Organization.slug == slug, Organization.is_active == True)
        )
        return result.scalar_one_or_none()

    async def update_organization(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        actor_id: uuid.UUID,
        updates: Dict[str, Any],
        ip_address: str = None,
    ) -> Optional[Organization]:
        """Update organization details."""
        org = await self.get_organization(db, org_id)
        if not org:
            return None

        allowed_fields = {"name", "description", "website", "industry",
                          "company_size", "billing_email", "logo_url", "settings"}
        changed = {}
        for field, value in updates.items():
            if field in allowed_fields and getattr(org, field) != value:
                changed[field] = {"old": getattr(org, field), "new": value}
                setattr(org, field, value)

        if changed:
            await self._log(db, org_id, actor_id, "org.updated", "organization", str(org_id),
                            details=changed, ip_address=ip_address)
            await db.commit()
            await db.refresh(org)

        return org

    async def delete_organization(
        self, db: AsyncSession, org_id: uuid.UUID, actor_id: uuid.UUID, ip_address: str = None
    ) -> bool:
        """Soft-delete an organization."""
        org = await self.get_organization(db, org_id)
        if not org:
            return False

        org.is_active = False
        await self._log(db, org_id, actor_id, "org.deleted", "organization", str(org_id),
                        ip_address=ip_address)
        await db.commit()
        return True

    async def list_user_organizations(self, db: AsyncSession, user_id: uuid.UUID) -> List[Dict[str, Any]]:
        """List all organizations a user belongs to, with their role."""
        result = await db.execute(
            select(Organization, OrganizationMember.role)
            .join(OrganizationMember, OrganizationMember.org_id == Organization.id)
            .where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.is_active == True,
                Organization.is_active == True,
            )
            .order_by(Organization.name)
        )
        rows = result.all()
        return [
            {
                "id": org.id,
                "name": org.name,
                "slug": org.slug,
                "logo_url": org.logo_url,
                "industry": org.industry,
                "role": role,
                "created_at": org.created_at.isoformat() if org.created_at else None,
            }
            for org, role in rows
        ]

    # ── Membership ──────────────────────────────────────────────────────

    async def get_members(self, db: AsyncSession, org_id: uuid.UUID) -> List[Dict[str, Any]]:
        """List all active members of an organization."""
        result = await db.execute(
            select(OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(
                OrganizationMember.org_id == org_id,
                OrganizationMember.is_active == True,
            )
            .order_by(OrganizationMember.joined_at)
        )
        rows = result.all()
        return [
            {
                "id": member.id,
                "user_id": user.id,
                "email": user.email,
                "name": user.name,
                "role": member.role,
                "title": member.title,
                "department_id": member.department_id,
                "joined_at": member.joined_at.isoformat() if member.joined_at else None,
            }
            for member, user in rows
        ]

    async def get_member(self, db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> Optional[OrganizationMember]:
        """Get a specific membership record."""
        result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.org_id == org_id,
                OrganizationMember.user_id == user_id,
                OrganizationMember.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    async def add_member(
        self, db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, role: str,
        actor_id: uuid.UUID, ip_address: str = None, title: str = None,
    ) -> OrganizationMember:
        """Add a user as a member of an organization."""
        # Check if already a member
        existing = await self.get_member(db, org_id, user_id)
        if existing:
            raise ValueError("User is already a member of this organization")

        member = OrganizationMember(
            org_id=org_id,
            user_id=user_id,
            role=role,
            title=title,
        )
        db.add(member)

        # Get user email for audit log
        user = await db.get(User, user_id)
        await self._log(db, org_id, actor_id, "member.added", "member", str(user_id),
                        details={"email": user.email if user else None, "role": role},
                        ip_address=ip_address)

        await db.commit()
        await db.refresh(member)
        return member

    async def update_member(
        self, db: AsyncSession, org_id: uuid.UUID, target_user_id: uuid.UUID,
        new_role: str = None, department_id: uuid.UUID = None,
        actor_id: uuid.UUID = None, ip_address: str = None,
    ) -> Optional[OrganizationMember]:
        """Update a member's role and/or department."""
        member = await self.get_member(db, org_id, target_user_id)
        if not member:
            return None

        changed = False

        # Handle role change
        if new_role is not None and new_role != member.role:
            old_role = member.role
            # Prevent removing the last owner
            if old_role == OrgRole.OWNER and new_role != OrgRole.OWNER:
                owner_count = await db.execute(
                    select(func.count(OrganizationMember.id)).where(
                        OrganizationMember.org_id == org_id,
                        OrganizationMember.role == OrgRole.OWNER,
                        OrganizationMember.is_active == True,
                    )
                )
                if owner_count.scalar() <= 1:
                    raise ValueError("Cannot remove the last owner of the organization")

            member.role = new_role
            await self._log(db, org_id, actor_id, "member.role_changed", "member", str(target_user_id),
                            details={"old_role": old_role, "new_role": new_role},
                            ip_address=ip_address)
            changed = True

        # Handle department change
        if department_id is not None:
            old_dept = member.department_id
            # A value of 0 or -1 means "unassign"
            new_dept = department_id if department_id > 0 else None
            if old_dept != new_dept:
                member.department_id = new_dept
                await self._log(db, org_id, actor_id, "member.department_changed", "member", str(target_user_id),
                                details={"old_department_id": old_dept, "new_department_id": new_dept},
                                ip_address=ip_address)
                changed = True

        if changed:
            await db.commit()
            await db.refresh(member)

        return member

    # Keep backward-compatible alias
    async def update_member_role(
        self, db: AsyncSession, org_id: uuid.UUID, target_user_id: uuid.UUID,
        new_role: str, actor_id: uuid.UUID, ip_address: str = None,
    ) -> Optional[OrganizationMember]:
        """Update a member's role (backward-compatible wrapper)."""
        return await self.update_member(
            db, org_id, target_user_id,
            new_role=new_role, actor_id=actor_id, ip_address=ip_address,
        )

    async def remove_member(
        self, db: AsyncSession, org_id: uuid.UUID, target_user_id: uuid.UUID,
        actor_id: uuid.UUID, ip_address: str = None,
    ) -> bool:
        """Remove a member from an organization (soft-delete)."""
        member = await self.get_member(db, org_id, target_user_id)
        if not member:
            return False

        # Prevent removing the last owner
        if member.role == OrgRole.OWNER:
            owner_count = await db.execute(
                select(func.count(OrganizationMember.id)).where(
                    OrganizationMember.org_id == org_id,
                    OrganizationMember.role == OrgRole.OWNER,
                    OrganizationMember.is_active == True,
                )
            )
            if owner_count.scalar() <= 1:
                raise ValueError("Cannot remove the last owner of the organization")

        member.is_active = False
        user = await db.get(User, target_user_id)
        await self._log(db, org_id, actor_id, "member.removed", "member", str(target_user_id),
                        details={"email": user.email if user else None},
                        ip_address=ip_address)
        await db.commit()
        return True

    # ── Invitations ─────────────────────────────────────────────────────

    async def create_invitation(
        self, db: AsyncSession, org_id: uuid.UUID, email: str, role: str,
        invited_by: int, ip_address: str = None,
    ) -> OrganizationInvitation:
        """Create an invitation to join an organization."""
        # Check if already a member
        user_result = await db.execute(select(User).where(User.email == email))
        existing_user = user_result.scalar_one_or_none()
        if existing_user:
            existing_member = await self.get_member(db, org_id, existing_user.id)
            if existing_member:
                raise ValueError("User is already a member of this organization")

        # Check for existing pending invitation
        existing_inv = await db.execute(
            select(OrganizationInvitation).where(
                OrganizationInvitation.org_id == org_id,
                OrganizationInvitation.email == email,
                OrganizationInvitation.status == OrgInvitationStatus.PENDING,
            )
        )
        if existing_inv.scalar_one_or_none():
            raise ValueError("A pending invitation already exists for this email")

        token = secrets.token_urlsafe(32)
        invitation = OrganizationInvitation(
            org_id=org_id,
            email=email,
            role=role,
            invited_by=invited_by,
            token=token,
            expires_at=datetime.now(timezone.utc) + timedelta(days=INVITATION_EXPIRY_DAYS),
        )
        db.add(invitation)

        await self._log(db, org_id, invited_by, "invitation.created", "invitation", email,
                        details={"role": role}, ip_address=ip_address)

        await db.commit()
        await db.refresh(invitation)
        return invitation

    async def list_invitations(self, db: AsyncSession, org_id: uuid.UUID) -> List[Dict[str, Any]]:
        """List all pending invitations for an organization."""
        result = await db.execute(
            select(OrganizationInvitation, User.name.label("inviter_name"))
            .join(User, User.id == OrganizationInvitation.invited_by)
            .where(
                OrganizationInvitation.org_id == org_id,
                OrganizationInvitation.status == OrgInvitationStatus.PENDING,
            )
            .order_by(OrganizationInvitation.created_at.desc())
        )
        rows = result.all()
        return [
            {
                "id": inv.id,
                "email": inv.email,
                "role": inv.role,
                "invited_by_name": inviter_name,
                "token": inv.token,
                "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
            }
            for inv, inviter_name in rows
        ]

    async def accept_invitation(
        self, db: AsyncSession, token: str, user_id: uuid.UUID, ip_address: str = None
    ) -> OrganizationMember:
        """Accept an invitation using the token."""
        result = await db.execute(
            select(OrganizationInvitation).where(
                OrganizationInvitation.token == token,
                OrganizationInvitation.status == OrgInvitationStatus.PENDING,
            )
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise ValueError("Invalid or expired invitation")

        # Check expiry
        if invitation.expires_at and invitation.expires_at < datetime.now(timezone.utc):
            invitation.status = OrgInvitationStatus.EXPIRED
            await db.commit()
            raise ValueError("This invitation has expired")

        # Check email matches user
        user = await db.get(User, user_id)
        if not user or user.email != invitation.email:
            raise ValueError("This invitation is for a different email address")

        # Create membership
        member = OrganizationMember(
            org_id=invitation.org_id,
            user_id=user_id,
            role=invitation.role,
        )
        db.add(member)
        invitation.status = OrgInvitationStatus.ACCEPTED

        await self._log(db, invitation.org_id, user_id, "invitation.accepted", "member", str(user_id),
                        details={"email": user.email, "role": invitation.role},
                        ip_address=ip_address)

        await db.commit()
        await db.refresh(member)
        return member

    async def revoke_invitation(
        self, db: AsyncSession, org_id: uuid.UUID, invitation_id: uuid.UUID,
        actor_id: uuid.UUID, ip_address: str = None,
    ) -> bool:
        """Revoke a pending invitation."""
        result = await db.execute(
            select(OrganizationInvitation).where(
                OrganizationInvitation.id == invitation_id,
                OrganizationInvitation.org_id == org_id,
                OrganizationInvitation.status == OrgInvitationStatus.PENDING,
            )
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            return False

        invitation.status = OrgInvitationStatus.DECLINED
        await self._log(db, org_id, actor_id, "invitation.revoked", "invitation", invitation.email,
                        ip_address=ip_address)
        await db.commit()
        return True

    # ── Departments ─────────────────────────────────────────────────────

    async def create_department(
        self, db: AsyncSession, org_id: uuid.UUID, name: str,
        actor_id: uuid.UUID, description: str = None, head_id: uuid.UUID = None,
        ip_address: str = None,
    ) -> Department:
        """Create a department within an organization."""
        dept = Department(
            org_id=org_id,
            name=name,
            description=description,
            head_id=head_id,
        )
        db.add(dept)
        await self._log(db, org_id, actor_id, "department.created", "department", name,
                        details={"name": name}, ip_address=ip_address)
        await db.commit()
        await db.refresh(dept)
        return dept

    async def list_departments(self, db: AsyncSession, org_id: uuid.UUID) -> List[Dict[str, Any]]:
        """List all departments in an organization."""
        result = await db.execute(
            select(Department)
            .where(Department.org_id == org_id)
            .order_by(Department.name)
        )
        departments = result.scalars().all()
        return [
            {
                "id": d.id,
                "name": d.name,
                "description": d.description,
                "head_id": d.head_id,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in departments
        ]

    async def update_department(
        self, db: AsyncSession, org_id: uuid.UUID, dept_id: uuid.UUID,
        updates: Dict[str, Any], actor_id: uuid.UUID, ip_address: str = None,
    ) -> Optional[Department]:
        """Update a department."""
        result = await db.execute(
            select(Department).where(Department.id == dept_id, Department.org_id == org_id)
        )
        dept = result.scalar_one_or_none()
        if not dept:
            return None

        allowed = {"name", "description", "head_id"}
        for field, value in updates.items():
            if field in allowed:
                setattr(dept, field, value)

        await self._log(db, org_id, actor_id, "department.updated", "department", str(dept_id),
                        details=updates, ip_address=ip_address)
        await db.commit()
        await db.refresh(dept)
        return dept

    async def delete_department(
        self, db: AsyncSession, org_id: uuid.UUID, dept_id: uuid.UUID,
        actor_id: uuid.UUID, ip_address: str = None,
    ) -> bool:
        """Delete a department."""
        result = await db.execute(
            select(Department).where(Department.id == dept_id, Department.org_id == org_id)
        )
        dept = result.scalar_one_or_none()
        if not dept:
            return False

        # Unassign members from this department
        members_result = await db.execute(
            select(OrganizationMember).where(OrganizationMember.department_id == dept_id)
        )
        for member in members_result.scalars().all():
            member.department_id = None

        await self._log(db, org_id, actor_id, "department.deleted", "department", dept.name,
                        ip_address=ip_address)
        await db.delete(dept)
        await db.commit()
        return True

    # ── Audit Log ───────────────────────────────────────────────────────

    async def get_audit_log(
        self, db: AsyncSession, org_id: uuid.UUID,
        action_filter: str = None,
        actor_id_filter: int = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Query the audit log for an organization."""
        query = (
            select(AuditLogEntry, User.name.label("actor_name"), User.email.label("actor_email"))
            .outerjoin(User, User.id == AuditLogEntry.actor_id)
            .where(AuditLogEntry.org_id == org_id)
        )
        count_query = select(func.count(AuditLogEntry.id)).where(AuditLogEntry.org_id == org_id)

        if action_filter:
            query = query.where(AuditLogEntry.action.ilike(f"%{action_filter}%"))
            count_query = count_query.where(AuditLogEntry.action.ilike(f"%{action_filter}%"))
        if actor_id_filter:
            query = query.where(AuditLogEntry.actor_id == actor_id_filter)
            count_query = count_query.where(AuditLogEntry.actor_id == actor_id_filter)

        query = query.order_by(AuditLogEntry.created_at.desc()).limit(limit).offset(offset)

        result = await db.execute(query)
        total_result = await db.execute(count_query)
        total = total_result.scalar()

        rows = result.all()
        entries = [
            {
                "id": entry.id,
                "action": entry.action,
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "details": entry.details,
                "ip_address": entry.ip_address,
                "actor_name": actor_name,
                "actor_email": actor_email,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            }
            for entry, actor_name, actor_email in rows
        ]

        return {"entries": entries, "total": total, "limit": limit, "offset": offset}

    # ── Permission Helpers ──────────────────────────────────────────────

    async def check_permission(
        self, db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, required_role: str
    ) -> bool:
        """Check if a user has at least the required role in an organization."""
        member = await self.get_member(db, org_id, user_id)
        if not member:
            return False

        role_hierarchy = {
            OrgRole.VIEWER: 0,
            OrgRole.MEMBER: 1,
            OrgRole.ADMIN: 2,
            OrgRole.OWNER: 3,
        }
        return role_hierarchy.get(member.role, -1) >= role_hierarchy.get(required_role, 99)

    # ── Internal ────────────────────────────────────────────────────────

    async def _log(
        self, db: AsyncSession, org_id: uuid.UUID, actor_id: uuid.UUID,
        action: str, entity_type: str = None, entity_id: str = None,
        details: Dict[str, Any] = None, ip_address: str = None,
    ):
        """Write an audit log entry."""
        entry = AuditLogEntry(
            org_id=org_id,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=ip_address,
        )
        db.add(entry)


# Singleton instance
organization_service = OrganizationService()
