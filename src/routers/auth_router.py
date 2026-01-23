"""
Authentication router for Mini-Hub MCP Server.
"""

import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..database import get_db
from ..models import (
    User, AccessRequest, AccessRequestStatus, SubscriptionTier,
    UserSettings, Connection, UsageLog, Workflow, Conversation,
    CreatorProfile, Invoice, MpesaPayment
)
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
import json


class UserRegister(BaseModel):
    email: str
    password: str
    name: str


class UserLogin(BaseModel):
    email: str
    password: str


router = APIRouter()
security = HTTPBearer()

from ..services.email_service import email_service

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class ValidateResetTokenRequest(BaseModel):
    token: str

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings
SECRET_KEY = "your-secret-key-here"  # In production, use environment variable
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(
    request: Request,
    token: str = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Get the current user from the JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token.credentials, SECRET_KEY, algorithms=[ALGORITHM]
        )
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Load user with settings for IP whitelist check
    result = await db.execute(
        select(User)
        .where(User.email == email)
        .options(selectinload(User.settings))
    )
    user = result.scalar_one_or_none()
    
    if user is None:
        raise credentials_exception

    # IP Whitelist Check
    if user.settings and user.settings.ip_whitelist:
        client_host = request.client.host
        # Handle cases where behind proxy (X-Forwarded-For) - simplistic check for now
        # In production, trust specific proxies or use a library
        whitelist = user.settings.ip_whitelist
        if isinstance(whitelist, list) and len(whitelist) > 0:
             if client_host not in whitelist:
                 # TODO: Check X-Forwarded-For if behind load balancer
                 raise HTTPException(
                     status_code=status.HTTP_403_FORBIDDEN,
                     detail=f"IP address {client_host} is not whitelisted."
                 )

    return user


@router.post("/register")
async def register(
    request: Request,
    user_data: UserRegister,
    db: AsyncSession = Depends(get_db)
):
    """Register a new user."""
    # Check rate limit (use IP or email)
    rate_limit_service = request.app.state.rate_limit_service
    if not await rate_limit_service.check_limit(user_data.email, tier="free"): # Apply strict limit for auth
         raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")

    # Check if user already exists
    result = await db.execute(
        select(User).where(User.email == user_data.email)
    )
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
        
    # Check if the email has been approved for access
    # 0. Check for Admin bypass
    from ..config import settings
    if settings.ADMIN_EMAIL and user_data.email == settings.ADMIN_EMAIL:
        pass # Skip access checks for admin
    else:
        access_result = await db.execute(
            select(AccessRequest).where(AccessRequest.email == user_data.email)
        )
        access_request = access_result.scalar_one_or_none()
        
        if not access_request:
             raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Please request access first."
            )
        
        if access_request.status != AccessRequestStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your email has not been approved for access yet. Please join the waitlist."
            )

    # Create new user
    hashed_password = get_password_hash(user_data.password)
    api_key = secrets.token_urlsafe(32)

    user = User(
        email=user_data.email,
        name=user_data.name,
        password_hash=hashed_password,
        api_key=api_key
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    return {
        "success": True,
        "data": {
            "token": access_token,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "subscription_tier": user.subscription_tier
            }
        }
    }


@router.post("/login")
async def login(
    request: Request,
    user_data: UserLogin,
    db: AsyncSession = Depends(get_db)
):
    """Login a user."""
    # Check rate limit
    rate_limit_service = request.app.state.rate_limit_service
    if not await rate_limit_service.check_limit(user_data.email, tier="free"): 
        raise HTTPException(status_code=429, detail="Too many login attempts. Please try again later.")

    # 0. Check for Admin bypass
    from ..config import settings
    if settings.ADMIN_EMAIL and user_data.email == settings.ADMIN_EMAIL:
        pass # Skip access checks for admin
    else:
        # 1. Check Access Request Status
        access_result = await db.execute(
            select(AccessRequest).where(AccessRequest.email == user_data.email)
        )
        access_request = access_result.scalar_one_or_none()
        
        # If they aren't on the list at all
        if not access_request:
            # Check if they really are a user (legacy support)
            user_check = await db.execute(select(User).where(User.email == user_data.email))
            if not user_check.scalar_one_or_none():
                 raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Please request access first."
                )
        
        # If they are on the list but pending/rejected
        elif access_request.status != AccessRequestStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are on the list awaiting approval."
            )

    # 2. Proceed with Standard Login (User Check)
    result = await db.execute(
        select(User).where(User.email == user_data.email)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # SPECIAL: Auto-upgrade test email to PRO
    if user.email == "info@arrotechsolutions.com" and user.subscription_tier != SubscriptionTier.PRO:
        user.subscription_tier = SubscriptionTier.PRO
        await db.commit()
        await db.refresh(user)

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    return {
        "success": True,
        "data": {
            "token": access_token,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "subscription_tier": user.subscription_tier
            }
        }
    }


@router.post("/logout")
async def logout():
    """Logout a user (client-side token removal)."""
    return {"success": True, "message": "Logged out successfully"}


@router.get("/me")
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """Get current user information."""
    return {
        "success": True,
        "data": {
            "id": current_user.id,
            "email": current_user.email,
            "name": current_user.name,
            "subscription_tier": current_user.subscription_tier
        }
    }


@router.post("/me/regenerate-api-key")
async def regenerate_api_key(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Regenerate the user's API Key."""
    new_api_key = secrets.token_urlsafe(32)
    current_user.api_key = new_api_key
    await db.commit()
    return {
        "success": True, 
        "data": {
            "api_key": new_api_key
        }, 
        "message": "API Key regenerated successfully"
    }


@router.get("/me/export")
async def export_data(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    GDPR/CCPA Right to Data Portability.
    Export all personal data associated with the user.
    """
    # 1. Fetch comprehensive user data
    
    # Settings
    settings = await db.execute(select(UserSettings).where(UserSettings.user_id == current_user.id))
    settings_data = [s.__dict__ for s in settings.scalars().all()]
    for s in settings_data: s.pop('_sa_instance_state', None)

    # Connections
    connections = await db.execute(select(Connection).where(Connection.user_id == current_user.id))
    connections_data = [c.__dict__ for c in connections.scalars().all()]
    for c in connections_data: c.pop('_sa_instance_state', None)

    # Usage Logs (Limit to last 1000)
    logs = await db.execute(select(UsageLog).where(UsageLog.user_id == current_user.id).limit(1000))
    logs_data = [l.__dict__ for l in logs.scalars().all()]
    for l in logs_data: l.pop('_sa_instance_state', None)

    # Workflows
    workflows = await db.execute(select(Workflow).where(Workflow.user_id == current_user.id))
    workflows_data = [w.__dict__ for w in workflows.scalars().all()]
    for w in workflows_data: w.pop('_sa_instance_state', None)

    # Conversations
    conversations = await db.execute(select(Conversation).where(Conversation.user_id == current_user.id))
    conversations_data = [c.__dict__ for c in conversations.scalars().all()]
    for c in conversations_data: c.pop('_sa_instance_state', None)

    # Invoices/Payments
    invoices = await db.execute(select(Invoice).where(Invoice.user_id == current_user.id))
    invoices_data = [i.__dict__ for i in invoices.scalars().all()]
    for i in invoices_data: i.pop('_sa_instance_state', None)

    # Construct Export Object
    export_content = {
        "user_info": {
            "id": current_user.id,
            "email": current_user.email,
            "name": current_user.name,
            "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
            "subscription_tier": current_user.subscription_tier,
        },
        "settings": settings_data,
        "connections": connections_data,
        "workflows": workflows_data,
        "conversations": conversations_data,
        "invoices": invoices_data,
        "usage_logs_sample": logs_data,
        "generated_at": datetime.utcnow().isoformat(),
        "legal_notice": "This export contains your personal data as processed by Arrotech Hub."
    }

    return JSONResponse(
        content=jsonable_encoder(export_content),
        headers={"Content-Disposition": f"attachment; filename=user_data_export_{current_user.id}.json"}
    )


@router.delete("/me")
async def delete_account(
    confirmation: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    GDPR/CCPA Right to Erasure.
    Permanently delete account and all associated data.
    Requires confirmation string 'DELETE'.
    """
    if confirmation != "DELETE":
        raise HTTPException(status_code=400, detail="Confirmation string 'DELETE' required.")

    # Delete dependent data manually
    # 1. Child tables
    await db.execute(delete(UsageLog).where(UsageLog.user_id == current_user.id))
    await db.execute(delete(Conversation).where(Conversation.user_id == current_user.id))
    await db.execute(delete(Workflow).where(Workflow.user_id == current_user.id))
    await db.execute(delete(Connection).where(Connection.user_id == current_user.id))
    await db.execute(delete(UserSettings).where(UserSettings.user_id == current_user.id))
    await db.execute(delete(CreatorProfile).where(CreatorProfile.user_id == current_user.id))
    await db.execute(delete(MpesaPayment).where(MpesaPayment.user_id == current_user.id))
    await db.execute(delete(Invoice).where(Invoice.user_id == current_user.id))
    
    # 2. The User
    await db.delete(current_user)
    await db.commit()

    return {"message": "Account permanently deleted."}


@router.post("/forgot-password")
async def forgot_password(
    data: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Initiate password reset flow.
    Sends an email with a reset token.
    """
    # 1. Check if user exists
    result = await db.execute(
        select(User).where(User.email == data.email)
    )
    user = result.scalar_one_or_none()
    
    # We always return success to prevent email enumeration
    if not user:
        # Simulate processing time to prevent timing attacks
        import asyncio
        await asyncio.sleep(0.5) 
        return {"success": True, "message": "If an account exists, a reset email has been sent."}

    # 2. Generate Reset Token (Short-lived JWT)
    from ..config import settings
    
    reset_token_expires = timedelta(minutes=60) # 1 hour
    reset_token = create_access_token(
        data={"sub": user.email, "type": "password_reset"}, 
        expires_delta=reset_token_expires
    )
    
    # 3. Construct Reset URL
    # Frontend URL should be configured in settings
    reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password"
    
    # 4. Send Email
    await email_service.send_password_reset_email(
        to_email=user.email,
        reset_token=reset_token,
        reset_url=reset_url
    )
    
    return {"success": True, "message": "If an account exists, a reset email has been sent."}


@router.post("/reset-password")
async def reset_password(
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Complete password reset flow.
    Verifies token and updates password.
    """
    try:
        # 1. Verify Token
        payload = jwt.decode(
            data.token, SECRET_KEY, algorithms=[ALGORITHM]
        )
        email: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        if email is None or token_type != "password_reset":
             raise HTTPException(status_code=400, detail="Invalid reset token.")
             
    except JWTError:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")

    # 2. Get User
    result = await db.execute(
        select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
        
    # 3. Update Password
    user.password_hash = get_password_hash(data.new_password)
    await db.commit()
    
    return {"success": True, "message": "Password updated successfully."}


@router.post("/validate-reset-token")
async def validate_reset_token(
    data: ValidateResetTokenRequest
):
    """
    Validate a password reset token.
    Used by frontend to verify link validity before showing form.
    """
    try:
        payload = jwt.decode(
            data.token, SECRET_KEY, algorithms=[ALGORITHM]
        )
        email: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        if email is None or token_type != "password_reset":
             raise HTTPException(status_code=400, detail="Invalid reset token.")
             
    except JWTError:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")

    return {"success": True, "message": "Token is valid."}
