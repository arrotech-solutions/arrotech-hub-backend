"""Rent collection onboarding and readiness endpoints."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Connection, ConnectionStatus, User, Workflow, WorkflowStatus
from ..routers.auth_router import get_current_user
from ..services.rent_mpesa_helpers import mpesa_live_ready
from ..services.rent_tenant_storage_service import rent_tenant_storage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rent-collection", tags=["rent-collection"])


class BootstrapSheetsRequest(BaseModel):
    title: str = Field(default="Rent Collection", max_length=120)
    include_sample: bool = True


@router.post("/bootstrap-sheets")
async def bootstrap_sheets(
    body: BootstrapSheetsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Google Sheet with Tenants + Payments tabs and optional sample row."""
    conn_res = await db.execute(
        select(Connection).where(
            Connection.user_id == user.id,
            Connection.platform == "google_workspace",
            Connection.status == ConnectionStatus.ACTIVE,
        )
    )
    if not conn_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connect Google Workspace before creating a rent spreadsheet.",
        )

    result = await rent_tenant_storage_service.bootstrap_spreadsheet(
        user,
        db,
        title=body.title,
        include_sample=body.include_sample,
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.get("error", "Failed to create spreadsheet"),
        )
    return {"success": True, "data": result}


@router.get("/readiness")
async def rent_readiness(
    spreadsheet_id: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Check whether a property manager is ready for rent collection onboarding."""
    wa_res = await db.execute(
        select(Connection).where(
            Connection.user_id == user.id,
            Connection.platform == "whatsapp",
            Connection.status == ConnectionStatus.ACTIVE,
        )
    )
    whatsapp_connected = wa_res.scalar_one_or_none() is not None

    wf_res = await db.execute(
        select(Workflow).where(
            Workflow.user_id == user.id,
            Workflow.name.ilike("%rent collection%"),
            Workflow.status == WorkflowStatus.ACTIVE,
        )
    )
    rent_workflow_active = wf_res.scalar_one_or_none() is not None

    stk_ready = await mpesa_live_ready(user.id, db)
    mpesa_mode = "stk" if stk_ready else "paybill"

    business_config: Dict[str, Any] = {}
    if spreadsheet_id:
        business_config["storage_spreadsheet_id"] = spreadsheet_id
        business_config["storage_provider"] = "google_sheets"

    tenant_count = 0
    sheets_readable = False
    sample_lookup_ok = False
    if spreadsheet_id:
        tenants = await rent_tenant_storage_service.load_tenants(
            user, business_config, db, force_refresh=True
        )
        tenant_count = len(tenants)
        sheets_readable = True
        if tenants:
            from ..services.rent_collection_service import rent_collection_service

            lookup = await rent_collection_service.lookup_tenant(
                phone_number=str(tenants[0].get("phone", "")),
                tenants_data=tenants,
            )
            sample_lookup_ok = bool(lookup.get("found"))

    ready = whatsapp_connected and rent_workflow_active and sheets_readable and tenant_count > 0

    return {
        "success": True,
        "data": {
            "ready": ready,
            "whatsapp_connected": whatsapp_connected,
            "rent_workflow_active": rent_workflow_active,
            "sheets_readable": sheets_readable,
            "tenant_count": tenant_count,
            "mpesa_mode": mpesa_mode,
            "sample_tenant_lookup_ok": sample_lookup_ok,
        },
    }
