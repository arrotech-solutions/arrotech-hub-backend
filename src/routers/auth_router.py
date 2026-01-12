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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..database import get_db
from ..models import User, AccessRequest, AccessRequestStatus, SubscriptionTier


class UserRegister(BaseModel):
    email: str
    password: str
    name: str


class UserLogin(BaseModel):
    email: str
    password: str


router = APIRouter()
security = HTTPBearer()

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

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


@router.post("/register")
async def register(
    user_data: UserRegister,
    db: AsyncSession = Depends(get_db)
):
    """Register a new user."""
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
    user_data: UserLogin,
    db: AsyncSession = Depends(get_db)
):
    """Login a user."""
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
