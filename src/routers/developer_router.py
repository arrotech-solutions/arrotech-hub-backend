"""
Developer Application Management Router for Arrotech Hub.
Allows users to create and manage their own developer apps.
"""

import secrets
from typing import List, Optional
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, DeveloperApp
from .auth_router import get_current_user, get_password_hash

router = APIRouter()

# --- Schemas ---

class DeveloperAppBase(BaseModel):
    name: str
    description: Optional[str] = None
    callback_urls: Optional[List[str]] = []
    scopes: Optional[List[str]] = ["data:read"]

class DeveloperAppCreate(DeveloperAppBase):
    pass

class DeveloperAppUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    callback_urls: Optional[List[str]] = None
    scopes: Optional[List[str]] = None
    is_active: Optional[bool] = None

class DeveloperAppRead(DeveloperAppBase):
    id: uuid.UUID
    client_id: str
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class DeveloperAppSecretResponse(DeveloperAppRead):
    client_secret: str  # Only returned once on creation or rotation

# --- Routes ---

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_app(
    app_data: DeveloperAppCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new developer application."""
    # Generate credentials
    client_id = f"ar_{secrets.token_hex(12)}"
    client_secret = f"ars_{secrets.token_urlsafe(32)}"
    secret_hash = get_password_hash(client_secret)
    
    new_app = DeveloperApp(
        user_id=current_user.id,
        name=app_data.name,
        description=app_data.description,
        client_id=client_id,
        client_secret_hash=secret_hash,
        scopes=app_data.scopes,
        callback_urls=app_data.callback_urls
    )
    
    db.add(new_app)
    await db.commit()
    await db.refresh(new_app)
    
    # Return with raw secret (only visible this once)
    return {
        "success": True,
        "data": {
            "app": DeveloperAppRead.from_orm(new_app).dict(),
            "credentials": {
                "client_id": client_id,
                "client_secret": client_secret
            }
        }
    }

@router.get("/")
async def list_apps(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all developer applications owned by the current user."""
    result = await db.execute(
        select(DeveloperApp).where(DeveloperApp.user_id == current_user.id)
    )
    return {
        "success": True,
        "data": [DeveloperAppRead.from_orm(app).dict() for app in result.scalars().all()]
    }

@router.get("/{app_id}")
async def get_app(
    app_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get details of a specific developer application."""
    result = await db.execute(
        select(DeveloperApp).where(
            DeveloperApp.id == app_id, 
            DeveloperApp.user_id == current_user.id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    return {
        "success": True,
        "data": DeveloperAppRead.from_orm(app).dict()
    }

@router.patch("/{app_id}")
async def update_app(
    app_id: uuid.UUID,
    app_update: DeveloperAppUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update developer application metadata."""
    result = await db.execute(
        select(DeveloperApp).where(
            DeveloperApp.id == app_id, 
            DeveloperApp.user_id == current_user.id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    
    update_data = app_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(app, key, value)
        
    await db.commit()
    await db.refresh(app)
    return {
        "success": True,
        "data": DeveloperAppRead.from_orm(app).dict()
    }

@router.post("/{app_id}/rotate-secret")
async def rotate_secret(
    app_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate a new client secret for the application."""
    result = await db.execute(
        select(DeveloperApp).where(
            DeveloperApp.id == app_id, 
            DeveloperApp.user_id == current_user.id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    
    client_secret = f"ars_{secrets.token_urlsafe(32)}"
    app.client_secret_hash = get_password_hash(client_secret)
    
    await db.commit()
    await db.refresh(app)
    
    return {
        "success": True,
        "data": {
            "client_secret": client_secret
        }
    }

@router.delete("/{app_id}")
async def delete_app(
    app_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a developer application."""
    result = await db.execute(
        select(DeveloperApp).where(
            DeveloperApp.id == app_id, 
            DeveloperApp.user_id == current_user.id
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    
    await db.delete(app)
    await db.commit()
    return {
        "success": True,
        "data": None
    }
