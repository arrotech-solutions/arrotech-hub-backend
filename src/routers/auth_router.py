from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import json
import secrets
import httpx
import pyotp
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Any

from ..database import get_db
from ..models import (
    User, AccessRequest, AccessRequestStatus, SubscriptionTier,
    UserSettings, Connection, UsageLog, Workflow, Conversation,
    CreatorProfile, Invoice, MpesaPayment, WebAuthnCredential,
    Organization, OrganizationMember, DeveloperApp, AuthorizationCode, AppToken
)
from ..config import settings
from ..services.email_service import email_service


class GoogleAuthRequest(BaseModel):
    """Request model for Google OAuth authentication."""
    credential: str  # Google ID token


class MicrosoftAuthRequest(BaseModel):
    """Request model for Microsoft OAuth authentication."""
    access_token: str  # Microsoft access token


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
REFRESH_TOKEN_EXPIRE_DAYS = 7


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create a short-lived JWT access token (30 min)."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    if "type" not in to_encode:
        to_encode["type"] = "access"
    to_encode["exp"] = expire
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """Create a long-lived JWT refresh token (7 days)."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def _build_auth_response(
    user: User, access_token: str, refresh_token: str,
    organizations: list = None, is_new_user: bool = False,
) -> dict:
    """Build a standard auth response with both tokens."""
    return {
        "success": True,
        "data": {
            "token": access_token,
            "refresh_token": refresh_token,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "subscription_tier": user.subscription_tier
            },
            "organizations": organizations or [],
            "is_new_user": is_new_user,
        }
    }


async def _get_user_orgs(db: AsyncSession, user_id: int) -> list:
    """Fetch lightweight org list for auth response."""
    result = await db.execute(
        select(Organization, OrganizationMember.role)
        .join(OrganizationMember, OrganizationMember.org_id == Organization.id)
        .where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.is_active == True,
            Organization.is_active == True,
        )
    )
    return [
        {
            "id": org.id, "name": org.name, "slug": org.slug,
            "logo_url": org.logo_url, "role": role,
        }
        for org, role in result.all()
    ]


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
        whitelist = user.settings.ip_whitelist
        if isinstance(whitelist, list) and len(whitelist) > 0:
             if client_host not in whitelist:
                 raise HTTPException(
                     status_code=status.HTTP_403_FORBIDDEN,
                     detail=f"IP address {client_host} is not whitelisted."
                 )

    # Attach app context if present
    request.state.app_id = payload.get("app_id")
    request.state.scopes = payload.get("scopes", [])

    return user


async def get_optional_current_user(
    token: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Get the current user from the JWT token if present, else return None."""
    if not token:
        return None
    try:
        payload = jwt.decode(token.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            return None
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()
    except Exception:
        return None


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
    # from ..config import settings
    # if settings.ADMIN_EMAIL and user_data.email == settings.ADMIN_EMAIL:
    #     pass # Skip access checks for admin
    # else:
    #     access_result = await db.execute(
    #         select(AccessRequest).where(AccessRequest.email == user_data.email)
    #     )
    #     access_request = access_result.scalar_one_or_none()
        
    #     if not access_request:
    #          raise HTTPException(
    #             status_code=status.HTTP_403_FORBIDDEN,
    #             detail="Please request access first."
    #         )
        
    #     if access_request.status != AccessRequestStatus.APPROVED:
    #         raise HTTPException(
    #             status_code=status.HTTP_403_FORBIDDEN,
    #             detail="Your email has not been approved for access yet. Please join the waitlist."
    #         )

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

    # Create tokens
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    refresh_token = create_refresh_token(data={"sub": user.email})

    return _build_auth_response(user, access_token, refresh_token, is_new_user=True)


@router.post("/google")
async def google_auth(
    request: Request,
    data: GoogleAuthRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate user with Google OAuth.
    Verifies the Google ID token and creates/logs in the user.
    """
    try:
        # Verify Google ID token using Google's tokeninfo endpoint
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://oauth2.googleapis.com/tokeninfo?id_token={data.credential}"
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid Google token"
                )
            
            google_user = response.json()
        
        # Verify the audience (client ID) matches our app
        google_client_id = getattr(settings, 'GOOGLE_CLIENT_ID', None)
        if google_client_id and google_user.get('aud') != google_client_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token was not issued for this application"
            )
        
        # Extract user info from Google response
        email = google_user.get('email')
        name = google_user.get('name', email.split('@')[0])
        picture = google_user.get('picture')
        
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email not provided by Google"
            )
        
        # Check if user exists
        result = await db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        
        is_new = user is None
        if not user:
            # Create new user (Sign Up flow)
            api_key = secrets.token_urlsafe(32)
            # Generate a random password hash for Google users (they won't use it)
            random_password = secrets.token_urlsafe(32)
            hashed_password = get_password_hash(random_password)
            
            user = User(
                email=email,
                name=name,
                password_hash=hashed_password,
                api_key=api_key
            )
            
            db.add(user)
            await db.commit()
            await db.refresh(user)
        
        # Create tokens
        access_token = create_access_token(
            data={"sub": user.email}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        refresh_token = create_refresh_token(data={"sub": user.email})
        
        orgs = await _get_user_orgs(db, user.id)
        return _build_auth_response(user, access_token, refresh_token, organizations=orgs, is_new_user=is_new)
        
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to verify Google token"
        )


@router.post("/microsoft")
async def microsoft_auth(
    request: Request,
    data: MicrosoftAuthRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate user with Microsoft OAuth.
    Verifies the Microsoft access token and creates/logs in the user.
    """
    try:
        # Use Microsoft Graph API to get user info
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {data.access_token}"}
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid Microsoft token"
                )
            
            ms_user = response.json()
        
        # Extract user info from Microsoft response
        email = ms_user.get('mail') or ms_user.get('userPrincipalName')
        name = ms_user.get('displayName', email.split('@')[0] if email else 'User')
        
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email not provided by Microsoft"
            )
        
        # Check if user exists
        result = await db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        
        is_new = user is None
        if not user:
            # Create new user (Sign Up flow)
            api_key = secrets.token_urlsafe(32)
            # Generate a random password hash for Microsoft users (they won't use it)
            random_password = secrets.token_urlsafe(32)
            hashed_password = get_password_hash(random_password)
            
            user = User(
                email=email,
                name=name,
                password_hash=hashed_password,
                api_key=api_key
            )
            
            db.add(user)
            await db.commit()
            await db.refresh(user)
        
        # Create tokens
        access_token = create_access_token(
            data={"sub": user.email}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        refresh_token = create_refresh_token(data={"sub": user.email})
        
        orgs = await _get_user_orgs(db, user.id)
        return _build_auth_response(user, access_token, refresh_token, organizations=orgs, is_new_user=is_new)
        
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to verify Microsoft token"
        )


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
    # from ..config import settings
    # if settings.ADMIN_EMAIL and user_data.email == settings.ADMIN_EMAIL:
    #     pass # Skip access checks for admin
    # else:
    #     # 1. Check Access Request Status
    #     access_result = await db.execute(
    #         select(AccessRequest).where(AccessRequest.email == user_data.email)
    #     )
    #     access_request = access_result.scalar_one_or_none()
        
    #     # If they aren't on the list at all
    #     if not access_request:
    #         # Check if they really are a user (legacy support)
    #         user_check = await db.execute(select(User).where(User.email == user_data.email))
    #         if not user_check.scalar_one_or_none():
    #              raise HTTPException(
    #                 status_code=status.HTTP_403_FORBIDDEN,
    #                 detail="Please request access first."
    #             )
        
    #     # If they are on the list but pending/rejected
    #     elif access_request.status != AccessRequestStatus.APPROVED:
    #         raise HTTPException(
    #             status_code=status.HTTP_403_FORBIDDEN,
    #             detail="You are on the list awaiting approval."
    #         )

    # 2. Proceed with Standard Login (User Check)
    result = await db.execute(
        select(User).where(User.email == user_data.email).options(
            selectinload(User.settings),
            selectinload(User.webauthn_credentials)
        )
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

    # 3. Check for 2FA
    if user.settings and user.settings.two_factor_enabled:
        # User has 2FA enabled. Issue a temporary token instead of full access.
        temp_token = create_access_token(
            data={"sub": user.email, "type": "2fa_pending"}, 
            expires_delta=timedelta(minutes=5)
        )
        return {
            "success": True,
            "requires_2fa": True,
            "data": {
                "2fa_token": temp_token,
                "has_totp": bool(user.settings.totp_secret),
                "has_email_2fa": bool(user.settings.email_2fa_enabled),
                "default_2fa_method": user.settings.default_2fa_method or "totp",
                "passkeys_count": len(user.webauthn_credentials) if hasattr(user, 'webauthn_credentials') else 0
            },
            "message": "Two-factor authentication required."
        }

    # 4. Standard Flow: Create tokens
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    refresh_token = create_refresh_token(data={"sub": user.email})

    orgs = await _get_user_orgs(db, user.id)
    return _build_auth_response(user, access_token, refresh_token, organizations=orgs)

class VerifyTOTPLoginRequest(BaseModel):
    two_factor_token: str
    code: str

@router.post("/login/2fa/totp")
async def login_2fa_totp(
    data: VerifyTOTPLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """Verify TOTP code during login flow using the temporary 2fa_token."""
    try:
        payload = jwt.decode(data.two_factor_token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        token_type = payload.get("type")
        
        if not email or token_type != "2fa_pending":
             raise HTTPException(status_code=401, detail="Invalid 2FA token.")
    except JWTError:
        raise HTTPException(status_code=401, detail="Expired or invalid 2FA token.")
        
    result = await db.execute(select(User).where(User.email == email).options(selectinload(User.settings)))
    user = result.scalar_one_or_none()
    
    if not user or not user.settings or not user.settings.totp_secret:
        raise HTTPException(status_code=400, detail="User not configured for TOTP.")
        
    totp = pyotp.TOTP(user.settings.totp_secret)
    if not totp.verify(data.code, valid_window=10):
        # Adding debug logs to help diagnose if it fails again
        import time
        server_time = int(time.time())
        expected_code = totp.now()
        print(f"[2FA DEBUG] Login Code mismatch. Server Time: {server_time}, Expected: {expected_code}, Submitted: {data.code}")
        raise HTTPException(status_code=401, detail="Invalid authenticator code.")
        
    # Valid code, issue full tokens
    access_token = create_access_token(data={"sub": user.email}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    refresh_token = create_refresh_token(data={"sub": user.email})
    
    return _build_auth_response(user, access_token, refresh_token)


class VerifyBackupCodeRequest(BaseModel):
    two_factor_token: str
    code: str

@router.post("/login/2fa/backup")
async def login_2fa_backup(
    data: VerifyBackupCodeRequest,
    db: AsyncSession = Depends(get_db)
):
    """Verify a backup code during login flow."""
    try:
        payload = jwt.decode(data.two_factor_token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        token_type = payload.get("type")
        
        if not email or token_type != "2fa_pending":
             raise HTTPException(status_code=401, detail="Invalid 2FA token.")
    except JWTError:
        raise HTTPException(status_code=401, detail="Expired or invalid 2FA token.")
        
    result = await db.execute(select(User).where(User.email == email).options(selectinload(User.settings)))
    user = result.scalar_one_or_none()
    
    if not user or not user.settings or not user.settings.backup_codes:
        raise HTTPException(status_code=400, detail="No backup codes configured.")
        
    # Check if backup code matches any hashed code
    matched_hash = None
    for hashed_code in user.settings.backup_codes:
        if verify_password(data.code, hashed_code):
            matched_hash = hashed_code
            break
            
    if not matched_hash:
        raise HTTPException(status_code=401, detail="Invalid backup code.")
        
    # Remove the used backup code
    new_codes = [c for c in user.settings.backup_codes if c != matched_hash]
    user.settings.backup_codes = new_codes
    await db.commit()
    
    # Issue full tokens
    access_token = create_access_token(data={"sub": user.email}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    refresh_token = create_refresh_token(data={"sub": user.email})
    
    return _build_auth_response(user, access_token, refresh_token)


class EmailOTPSendRequest(BaseModel):
    two_factor_token: str

@router.post("/login/2fa/email/send")
async def login_2fa_email_send(
    data: EmailOTPSendRequest,
    db: AsyncSession = Depends(get_db)
):
    """Explicitly send an email OTP during the login 2FA flow."""
    try:
        payload = jwt.decode(data.two_factor_token, SECRET_KEY, algorithms=[ALGORITHM])
        email_addr = payload.get("sub")
        token_type = payload.get("type")
        
        if not email_addr or token_type != "2fa_pending":
             raise HTTPException(status_code=401, detail="Invalid 2FA token.")
    except JWTError:
        raise HTTPException(status_code=401, detail="Expired or invalid 2FA token.")
        
    result = await db.execute(select(User).where(User.email == email_addr).options(selectinload(User.settings)))
    user = result.scalar_one_or_none()
    
    if not user or not user.settings or not user.settings.email_2fa_enabled:
        raise HTTPException(status_code=400, detail="User not configured for Email 2FA.")
    
    otp = "".join(str(secrets.randbelow(10)) for _ in range(6))
    user.login_otp = otp
    user.login_otp_expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db.commit()
    
    await email_service.send_2fa_otp_email(user.email, otp)
    
    # Mask the email for the frontend
    parts = user.email.split("@")
    masked = parts[0][:2] + "***@" + parts[1] if len(parts) == 2 else "***"
    
    return {
        "success": True,
        "message": f"Verification code sent to {masked}."
    }


class EmailOTPVerifyRequest(BaseModel):
    two_factor_token: str
    code: str

@router.post("/login/2fa/email/verify")
async def login_2fa_email_verify(
    data: EmailOTPVerifyRequest,
    db: AsyncSession = Depends(get_db)
):
    """Verify the email OTP during the login 2FA flow and issue tokens."""
    try:
        payload = jwt.decode(data.two_factor_token, SECRET_KEY, algorithms=[ALGORITHM])
        email_addr = payload.get("sub")
        token_type = payload.get("type")
        
        if not email_addr or token_type != "2fa_pending":
             raise HTTPException(status_code=401, detail="Invalid 2FA token.")
    except JWTError:
        raise HTTPException(status_code=401, detail="Expired or invalid 2FA token.")
        
    result = await db.execute(select(User).where(User.email == email_addr).options(selectinload(User.settings)))
    user = result.scalar_one_or_none()
    
    if not user or not user.login_otp or not user.login_otp_expiry:
        raise HTTPException(status_code=400, detail="No active email OTP session.")
        
    # Make sure we compare aware datetimes
    now = datetime.now(timezone.utc)
    expiry = user.login_otp_expiry
    if expiry and not expiry.tzinfo:
        expiry = expiry.replace(tzinfo=timezone.utc)
    
    if now > expiry:
        user.login_otp = None
        user.login_otp_expiry = None
        await db.commit()
        raise HTTPException(status_code=400, detail="Verification code expired. Please request a new one.")
    
    if user.login_otp != data.code:
        raise HTTPException(status_code=401, detail="Invalid verification code.")
        
    # Valid code, clear OTP and issue full tokens
    user.login_otp = None
    user.login_otp_expiry = None
    await db.commit()
    
    access_token = create_access_token(data={"sub": user.email}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    refresh_token = create_refresh_token(data={"sub": user.email})
    
    orgs = await _get_user_orgs(db, user.id)
    return _build_auth_response(user, access_token, refresh_token, organizations=orgs)


class SwitchOrgRequest(BaseModel):
    org_id: Optional[int] = None  # None = switch to personal context


@router.post("/switch-org")
async def switch_org(
    data: SwitchOrgRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Switch active organization context. Issues a new JWT with org_id."""
    org_id = data.org_id

    if org_id is not None:
        # Verify user is a member of this org
        result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.org_id == org_id,
                OrganizationMember.user_id == current_user.id,
                OrganizationMember.is_active == True,
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization",
            )

    # Issue new token with org context
    token_data = {"sub": current_user.email}
    if org_id is not None:
        token_data["org_id"] = org_id

    access_token = create_access_token(
        data=token_data,
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token = create_refresh_token(data=token_data)

    orgs = await _get_user_orgs(db, current_user.id)
    return _build_auth_response(
        current_user, access_token, refresh_token, organizations=orgs
    )


class RefreshTokenRequest(BaseModel):
    refresh_token: str


@router.post("/refresh")
async def refresh_token(
    data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """Exchange a valid refresh token for a new access token."""
    try:
        payload = jwt.decode(data.refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Ensure it's actually a refresh token
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type"
            )
        
        email = payload.get("sub")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
        
        # Verify user still exists
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        
        # Issue a new access token
        new_access_token = create_access_token(
            data={"sub": email},
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        
        return {
            "success": True,
            "data": {
                "token": new_access_token,
            }
        }
    
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token. Please log in again."
        )


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
            "subscription_tier": current_user.subscription_tier,
            "subscription_status": current_user.subscription_status,
            "subscription_end_date": current_user.subscription_end_date.isoformat() if current_user.subscription_end_date else None,
            "role": getattr(current_user, 'role', 'user') or 'user',
            "permissions": getattr(current_user, 'permissions', {}) or {},
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

# --- OAuth2 Developer Flows ---

class OAuthAuthorizeRequest(BaseModel):
    client_id: str
    response_type: str = "code"
    redirect_uri: str
    scope: str
    state: Optional[str] = None

class OAuthTokenRequest(BaseModel):
    grant_type: str
    client_id: str
    client_secret: str
    code: Optional[str] = None
    redirect_uri: Optional[str] = None
    refresh_token: Optional[str] = None

@router.get("/authorize")
async def oauth_authorize(
    client_id: str,
    response_type: str,
    redirect_uri: str,
    scope: str,
    state: Optional[str] = None,
    current_user: User = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Step 1 of 3-legged OAuth: Show consent screen.
    Returns app info and requested scopes if logged in.
    """
    if not current_user:
        return JSONResponse(
            status_code=401,
            content={"error": "login_required", "message": "User must be logged in to authorize apps."}
        )

    # Verify App
    result = await db.execute(select(DeveloperApp).where(DeveloperApp.client_id == client_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    
    # Verify Redirect URI
    if redirect_uri not in (app.callback_urls or []):
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")

    return {
        "app_name": app.name,
        "app_description": app.description,
        "developer_name": app.user.name if app.user else "Hidden",
        "requested_scopes": scope.split(" "),
        "state": state
    }

@router.post("/authorize/approve")
async def oauth_approve(
    data: OAuthAuthorizeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Step 2 of 3-legged OAuth: User approves the app.
    Generates a temporary authorization code.
    """
    result = await db.execute(select(DeveloperApp).where(DeveloperApp.client_id == data.client_id))
    app = result.scalar_one_or_none()
    if not app or not app.is_active:
        raise HTTPException(status_code=400, detail="Invalid or inactive application")
    
    if data.redirect_uri not in (app.callback_urls or []):
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")

    # Generate Authorization Code
    auth_code = secrets.token_urlsafe(32)
    new_code = AuthorizationCode(
        user_id=current_user.id,
        app_id=app.id,
        code=auth_code,
        redirect_uri=data.redirect_uri,
        scopes=data.scope.split(" "),
        expires_at=datetime.utcnow() + timedelta(minutes=10)
    )
    
    db.add(new_code)
    await db.commit()
    
    return {
        "code": auth_code,
        "state": data.state,
        "redirect_uri": data.redirect_uri
    }

@router.post("/token")
async def oauth_token(
    data: OAuthTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Step 3 of 3-legged OAuth OR 2-legged flow.
    Exchanges credentials or code for an access token.
    """
    # 2-Legged Flow (Client Credentials)
    if data.grant_type == "client_credentials":
        result = await db.execute(select(DeveloperApp).where(DeveloperApp.client_id == data.client_id))
        app = result.scalar_one_or_none()
        
        if not app or not verify_password(data.client_secret, app.client_secret_hash) or not app.is_active:
            raise HTTPException(status_code=401, detail="Invalid client credentials")
        
        # Issue App-only JWT
        token_data = {
            "sub": f"app_{app.client_id}",
            "app_id": app.id,
            "scopes": app.scopes,
            "type": "app_token"
        }
        access_token = create_access_token(token_data, expires_delta=timedelta(hours=1))
        
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": " ".join(app.scopes or [])
        }

    # 3-Legged Flow (Authorization Code)
    elif data.grant_type == "authorization_code":
        if not data.code:
            raise HTTPException(status_code=400, detail="code is required")
            
        result = await db.execute(
            select(AuthorizationCode)
            .where(AuthorizationCode.code == data.code)
            .options(selectinload(AuthorizationCode.app))
        )
        code_entry = result.scalar_one_or_none()
        
        if not code_entry or code_entry.expires_at < datetime.utcnow():
            raise HTTPException(status_code=400, detail="Invalid or expired code")
            
        app = code_entry.app
        if app.client_id != data.client_id or not verify_password(data.client_secret, app.client_secret_hash):
            raise HTTPException(status_code=401, detail="Client authentication failed")
            
        if code_entry.redirect_uri != data.redirect_uri:
            raise HTTPException(status_code=400, detail="redirect_uri mismatch")

        # Issue User-Delegated App token
        user_result = await db.execute(select(User).where(User.id == code_entry.user_id))
        user = user_result.scalar_one()

        token_data = {
            "sub": user.email,
            "app_id": app.id,
            "scopes": code_entry.scopes,
            "type": "delegated_token"
        }
        access_token = create_access_token(token_data, expires_delta=timedelta(hours=1))
        refresh_token = secrets.token_urlsafe(64)
        
        # Save refresh token
        new_app_token = AppToken(
            user_id=user.id,
            app_id=app.id,
            refresh_token=refresh_token,
            scopes=code_entry.scopes,
            expires_at=datetime.utcnow() + timedelta(days=30)
        )
        db.add(new_app_token)
        await db.delete(code_entry) # Use code only once
        await db.commit()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": " ".join(code_entry.scopes or [])
        }

    raise HTTPException(status_code=400, detail="unsupported_grant_type")
