"""
Authentication router for Mini-Hub MCP Server.
"""

import secrets
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User


class UserRegister(BaseModel):
    email: str
    password: str
    name: str


class UserLogin(BaseModel):
    email: str
    password: str
    remember_me: bool = False


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


router = APIRouter()
security = HTTPBearer()

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings
SECRET_KEY = "your-secret-key-here"  # In production, use environment variable
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REMEMBER_ME_EXPIRE_DAYS = 30
PASSWORD_RESET_EXPIRE_HOURS = 24

# Email settings (configure these in production)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USERNAME = "your-email@gmail.com"  # Configure in environment
SMTP_PASSWORD = "your-app-password"  # Configure in environment


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


def create_remember_me_token(user_id: int) -> str:
    """Create a remember me token."""
    token_data = {"sub": str(user_id), "type": "remember_me"}
    expires = datetime.utcnow() + timedelta(days=REMEMBER_ME_EXPIRE_DAYS)
    token_data.update({"exp": expires})
    return jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)


def send_password_reset_email(email: str, token: str):
    """Send password reset email."""
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USERNAME
        msg['To'] = email
        msg['Subject'] = "Password Reset Request - Mini-Hub"
        
        body = f"""
        Hello,
        
        You have requested to reset your password for Mini-Hub.
        
        Click the following link to reset your password:
        http://localhost:3000/reset-password?token={token}
        
        This link will expire in {PASSWORD_RESET_EXPIRE_HOURS} hours.
        
        If you didn't request this password reset, please ignore this email.
        
        Best regards,
        Mini-Hub Team
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        return True
    except Exception as e:
        print(f"Email sending failed: {e}")
        return False


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
    # Find user by email
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

    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    # Handle remember me functionality
    remember_me_token = None
    if user_data.remember_me:
        remember_me_token = create_remember_me_token(user.id)
        user.remember_me_token = remember_me_token
        user.remember_me_expires = datetime.utcnow() + timedelta(days=REMEMBER_ME_EXPIRE_DAYS)
        await db.commit()

    return {
        "success": True,
        "data": {
            "token": access_token,
            "remember_me_token": remember_me_token,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "subscription_tier": user.subscription_tier
            }
        }
    }


@router.post("/forgot-password")
async def forgot_password(
    request: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    """Send password reset email."""
    # Validate email format
    import re
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    if not email_pattern.match(request.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email format"
        )
    
    # Find user by email
    result = await db.execute(
        select(User).where(User.email == request.email)
    )
    user = result.scalar_one_or_none()

    if not user:
        # Don't reveal if email exists or not for security
        return {"success": True, "message": "If the email exists, a password reset link has been sent."}

    # Generate password reset token
    reset_token = secrets.token_urlsafe(32)
    user.password_reset_token = reset_token
    user.password_reset_expires = datetime.utcnow() + timedelta(hours=PASSWORD_RESET_EXPIRE_HOURS)
    
    await db.commit()

    # Send password reset email
    email_sent = send_password_reset_email(user.email, reset_token)
    
    if email_sent:
        return {"success": True, "message": "Password reset email sent successfully."}
    else:
        # Clear the token if email failed
        user.password_reset_token = None
        user.password_reset_expires = None
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send password reset email"
        )


@router.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    """Reset password using token."""
    # Find user by reset token
    result = await db.execute(
        select(User).where(
            User.password_reset_token == request.token,
            User.password_reset_expires > datetime.utcnow()
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )

    # Update password
    user.password_hash = get_password_hash(request.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    
    await db.commit()

    return {"success": True, "message": "Password reset successfully."}


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Change password for authenticated user."""
    # Verify current password
    if not verify_password(request.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    # Update password
    current_user.password_hash = get_password_hash(request.new_password)
    await db.commit()

    return {"success": True, "message": "Password changed successfully."}


@router.post("/validate-reset-token")
async def validate_reset_token(
    token: str,
    db: AsyncSession = Depends(get_db)
):
    """Validate password reset token."""
    result = await db.execute(
        select(User).where(
            User.password_reset_token == token,
            User.password_reset_expires > datetime.utcnow()
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )

    return {"success": True, "message": "Token is valid."}


@router.post("/logout")
async def logout():
    """Logout a user (client-side token removal)."""
    return {"success": True, "message": "Logged out successfully"}


class UserProfileUpdate(BaseModel):
    """User profile update model."""
    name: str
    email: str


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
            "subscription_tier": current_user.subscription_tier,
            "api_key": current_user.api_key,
            "stripe_customer_id": current_user.stripe_customer_id,
            "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
            "updated_at": current_user.updated_at.isoformat() if current_user.updated_at else None
        }
    }


@router.put("/me")
async def update_user_profile(
    profile_data: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update current user profile."""
    # Check if email is already taken by another user
    if profile_data.email != current_user.email:
        result = await db.execute(
            select(User).where(User.email == profile_data.email)
        )
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )

    # Update user profile
    current_user.name = profile_data.name
    current_user.email = profile_data.email
    
    await db.commit()
    await db.refresh(current_user)

    return {
        "success": True,
        "data": {
            "id": current_user.id,
            "email": current_user.email,
            "name": current_user.name,
            "subscription_tier": current_user.subscription_tier,
            "api_key": current_user.api_key,
            "stripe_customer_id": current_user.stripe_customer_id,
            "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
            "updated_at": current_user.updated_at.isoformat() if current_user.updated_at else None
        }
    }


@router.post("/me/regenerate-api-key")
async def regenerate_api_key(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Regenerate API key for current user."""
    # Generate new API key
    new_api_key = secrets.token_urlsafe(32)
    current_user.api_key = new_api_key
    
    await db.commit()
    await db.refresh(current_user)

    return {
        "success": True,
        "data": {
            "api_key": new_api_key,
            "message": "API key regenerated successfully"
        }
    }
