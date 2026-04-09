"""
Security router for Mini-Hub MCP Server. Handles 2FA, TOTP, and WebAuthn (Passkeys).
"""

import base64
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import pyotp
import qrcode
import io
from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
)
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    UserVerificationRequirement,
    ResidentKeyRequirement,
    RegistrationCredential,
    AuthenticationCredential,
    PublicKeyCredentialDescriptor,
)

from ..database import get_db
from ..models import User, UserSettings, WebAuthnCredential
from .auth_router import get_current_user, get_password_hash, verify_password, create_access_token, create_refresh_token, ACCESS_TOKEN_EXPIRE_MINUTES
from ..services.email_service import email_service

# Configuration
from ..config import settings
RP_ID = getattr(settings, 'RP_ID', "localhost")
RP_NAME = getattr(settings, 'RP_NAME', "Arrotech Hub")
ORIGIN = getattr(settings, 'FRONTEND_URL', "http://localhost:3000")

router = APIRouter(tags=["security"])

@router.get("/2fa/status")
async def get_2fa_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the current 2FA status for the user."""
    # Ensure settings and credentials are loaded properly with execute
    result = await db.execute(
        select(User)
        .where(User.id == current_user.id)
        .options(selectinload(User.settings), selectinload(User.webauthn_credentials))
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    return {
        "success": True,
        "data": {
            "two_factor_enabled": user.settings.two_factor_enabled if user.settings else False,
            "has_totp": bool(user.settings and user.settings.totp_secret),
            "has_email_2fa": bool(user.settings and user.settings.email_2fa_enabled),
            "default_2fa_method": user.settings.default_2fa_method if user.settings else "totp",
            "passkeys_count": len(user.webauthn_credentials) if hasattr(user, 'webauthn_credentials') and user.webauthn_credentials else 0,
            "has_backup_codes": bool(user.settings and user.settings.backup_codes)
        }
    }

# --- TOTP (Authenticator App) Setup ---

class VerifyTOTPSetupRequest(BaseModel):
    code: str

@router.post("/2fa/totp/setup")
async def setup_totp(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate a TOTP secret and QR code for the user to scan."""
    # Retrieve user and settings
    user = await db.get(User, current_user.id, options=[selectinload(User.settings)])
    if not user.settings:
        user_settings = UserSettings(user_id=user.id)
        db.add(user_settings)
        user.settings = user_settings
        await db.commit()
    
    # Check if already enabled and prevent overwriting without proper flow if desired
    # For now, allow regenerating if not fully enabled
    
    # Generate new secret
    secret = pyotp.random_base32()
    
    # Save secret temporarily (we won't enable 2FA until they verify)
    user.settings.totp_secret = secret
    await db.commit()
    
    # DEBUG: Verify the secret was saved correctly
    await db.refresh(user.settings)
    saved_secret = user.settings.totp_secret
    print(f"[2FA SETUP] Generated secret:  {secret}")
    print(f"[2FA SETUP] Saved in DB:       {saved_secret}")
    print(f"[2FA SETUP] Secrets match:     {secret == saved_secret}")
    
    # Generate Provisioning URI
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=user.email, issuer_name="Arrotech Hub")
    
    # DEBUG: Log URI so we can check what the QR encodes
    print(f"[2FA SETUP] Provisioning URI:  {uri}")
    
    # Generate QR Code
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_b64 = base64.b64encode(img_byte_arr.getvalue()).decode()
    
    return {
        "success": True,
        "data": {
            "secret": secret,
            "qr_code": f"data:image/png;base64,{img_b64}",
            "uri": uri
        }
    }

@router.post("/2fa/totp/verify")
async def verify_totp_setup(
    data: VerifyTOTPSetupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Verify the first TOTP code and enable 2FA, generate backup codes."""
    # Use RAW SQL to completely bypass ORM identity map and session cache
    from sqlalchemy import text
    raw_result = await db.execute(
        text("SELECT totp_secret FROM user_settings WHERE user_id = :uid"),
        {"uid": current_user.id}
    )
    raw_row = raw_result.fetchone()
    
    if not raw_row or not raw_row[0]:
        raise HTTPException(status_code=400, detail="TOTP setup not initiated.")
    
    stored_secret = raw_row[0]
    totp = pyotp.TOTP(stored_secret)
    
    # DEBUG: Log details to diagnose verification failures (remove after fixing)
    import time
    server_time = int(time.time())
    expected_code = totp.now()
    print(f"[2FA DEBUG] Server Unix Time: {server_time}")
    print(f"[2FA DEBUG] Expected TOTP code: {expected_code}")
    print(f"[2FA DEBUG] Submitted code:     {data.code}")
    print(f"[2FA DEBUG] FULL Secret (RAW SQL): {stored_secret}")
    print(f"[2FA DEBUG] Codes match:        {expected_code == data.code}")
    print(f"[2FA DEBUG] verify(window=5):   {totp.verify(data.code, valid_window=5)}")
    
    if not totp.verify(data.code, valid_window=10):
        raise HTTPException(status_code=400, detail="Invalid verification code.")
        
    # Valid code - now load user via ORM to update settings
    result = await db.execute(
        select(User).where(User.id == current_user.id).options(selectinload(User.settings))
    )
    user = result.scalar_one()
    
    # Enable 2FA
    user.settings.two_factor_enabled = True
    
    # Generate 10 backup codes
    raw_backup_codes = [secrets.token_hex(4) for _ in range(10)]
    hashed_backup_codes = [get_password_hash(code) for code in raw_backup_codes]
    
    user.settings.backup_codes = hashed_backup_codes
    await db.commit()
    
    return {
        "success": True,
        "message": "Two-factor authentication enabled successfully.",
        "data": {
            "backup_codes": raw_backup_codes
        }
    }

class Disable2FARequest(BaseModel):
    method: Optional[str] = "all" # 'totp', 'email', 'all'

@router.post("/2fa/disable")
async def disable_2fa(
    verify_data: Disable2FARequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Disable specific or all 2FA methods."""
    user = await db.get(User, current_user.id, options=[selectinload(User.settings), selectinload(User.webauthn_credentials)])
    
    if user.settings:
        if verify_data.method == "totp":
            user.settings.totp_secret = None
        elif verify_data.method == "email":
            user.settings.email_2fa_enabled = False
        else: # 'all'
            user.settings.two_factor_enabled = False
            user.settings.email_2fa_enabled = False
            user.settings.totp_secret = None
            user.settings.backup_codes = None
            
        # If neither TOTP nor Email is enabled, turn off the global flag
        if not user.settings.totp_secret and not user.settings.email_2fa_enabled:
             user.settings.two_factor_enabled = False
    
    if verify_data.method == "all":
        # Delete passkeys
        for cred in list(user.webauthn_credentials):
            await db.delete(cred)
            
    await db.commit()
    return {"success": True, "message": f"Two-factor authentication ({verify_data.method}) disabled."}

# --- Email 2FA Setup ---

class VerifyEmailSetupRequest(BaseModel):
    code: str

@router.post("/2fa/email/setup")
async def setup_email_2fa(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate an OTP and send it via email to verify the user wants to enable Email 2FA."""
    user = await db.get(User, current_user.id, options=[selectinload(User.settings)])
    if not user.settings:
        user_settings = UserSettings(user_id=user.id)
        db.add(user_settings)
        user.settings = user_settings
        
    otp = "".join(str(secrets.randbelow(10)) for _ in range(6))
    user.login_otp = otp
    user.login_otp_expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db.commit()
    
    await email_service.send_2fa_otp_email(user.email, otp)
    
    return {
        "success": True,
        "message": "Verification code sent to your email."
    }

@router.post("/2fa/email/verify")
async def verify_email_setup(
    data: VerifyEmailSetupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Verify the email OTP and enable Email 2FA."""
    user = await db.get(User, current_user.id, options=[selectinload(User.settings)])
    
    if not user.login_otp or not user.login_otp_expiry:
        raise HTTPException(status_code=400, detail="No active Email 2FA setup session.")
        
    # Make sure we compare aware datetimes
    now = datetime.now(timezone.utc)
    if not user.login_otp_expiry.tzinfo:
        user.login_otp_expiry = user.login_otp_expiry.replace(tzinfo=timezone.utc)

    if now > user.login_otp_expiry:
        user.login_otp = None
        user.login_otp_expiry = None
        await db.commit()
        raise HTTPException(status_code=400, detail="Verification code expired.")
        
    if user.login_otp != data.code:
        raise HTTPException(status_code=400, detail="Invalid verification code.")
        
    # Valid code, enable 2FA
    if not user.settings:
        user_settings = UserSettings(user_id=user.id)
        db.add(user_settings)
        user.settings = user_settings

    user.settings.email_2fa_enabled = True
    user.settings.two_factor_enabled = True
    user.login_otp = None
    user.login_otp_expiry = None
    
    # Generate 10 backup codes if none exist
    raw_backup_codes = []
    if not user.settings.backup_codes:
        raw_backup_codes = [secrets.token_hex(4) for _ in range(10)]
        hashed_backup_codes = [get_password_hash(code) for code in raw_backup_codes]
        user.settings.backup_codes = hashed_backup_codes
        
    await db.commit()
    
    return {
        "success": True,
        "message": "Email Two-factor authentication enabled successfully.",
        "data": {
            "backup_codes": raw_backup_codes if raw_backup_codes else None
        }
    }

# --- WebAuthn (Passkeys) Setup ---

@router.post("/webauthn/register/begin")
async def begin_webauthn_registration(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Start the WebAuthn registration process."""
    user = await db.get(User, current_user.id, options=[selectinload(User.webauthn_credentials)])
    
    exclude_credentials = []
    if user.webauthn_credentials:
         for cred in user.webauthn_credentials:
             exclude_credentials.append(
                 PublicKeyCredentialDescriptor(id=base64.urlsafe_b64decode(cred.credential_id + '=='))
             )

    registration_options = generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=str(user.id).encode(),
        user_name=user.email,
        user_display_name=user.name,
        exclude_credentials=exclude_credentials,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.PREFERRED,
            resident_key=ResidentKeyRequirement.PREFERRED,
        ),
        attestation=AttestationConveyancePreference.NONE,
    )
    
    # Store challenge temporarily
    user.login_challenge = base64.urlsafe_b64encode(registration_options.challenge).decode('utf-8').rstrip("=")
    await db.commit()
    
    return json.loads(registration_options.json())

class WebAuthnRegisterRequest(BaseModel):
    credential: Dict[str, Any]
    name: Optional[str] = "My Passkey"

@router.post("/webauthn/register/complete")
async def complete_webauthn_registration(
    data: WebAuthnRegisterRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Complete the WebAuthn registration process."""
    user = await db.get(User, current_user.id, options=[selectinload(User.settings)])
    
    if not user.login_challenge:
        raise HTTPException(status_code=400, detail="No active registration challenge.")
        
    challenge = base64.urlsafe_b64decode(user.login_challenge + "==")
    
    try:
        credential = RegistrationCredential.parse_json(json.dumps(data.credential))
        
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_origin=ORIGIN,
            expected_rp_id=RP_ID,
            require_user_verification=False, # Depends on AuthenticatorSelectionCriteria
        )
        
        # Save new credential
        new_cred = WebAuthnCredential(
            user_id=user.id,
            credential_id=base64.urlsafe_b64encode(verification.credential_id).decode('utf-8').rstrip("="),
            public_key=base64.urlsafe_b64encode(verification.credential_public_key).decode('utf-8').rstrip("="),
            sign_count=verification.sign_count,
            name=data.name or "My Passkey"
        )
        
        db.add(new_cred)
        
        # Enable 2FA generally if not already enabled (and create settings if missing)
        if not user.settings:
            user_settings = UserSettings(user_id=user.id, two_factor_enabled=True)
            db.add(user_settings)
            user.settings = user_settings
        else:
            user.settings.two_factor_enabled = True
            
        # Clear challenge
        user.login_challenge = None
        
        await db.commit()
        
        return {"success": True, "message": "Passkey registered successfully."}
        
    except Exception as e:
        print(f"WebAuthn verification error: {e}")
        # Clear challenge on error
        user.login_challenge = None
        await db.commit()
        raise HTTPException(status_code=400, detail="Failed to verify passkey registration.")


# --- Change Password ---

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Change the user's password. Requires current password verification."""
    # Reload user to ensure we have the latest hash
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Verify current password
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    # Validate new password length
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters.")

    # Update password
    user.password_hash = get_password_hash(data.new_password)
    await db.commit()

    return {"success": True, "message": "Password changed successfully."}


# --- Change Email ---

class ChangeEmailRequest(BaseModel):
    new_email: str
    password: str

@router.post("/change-email")
async def change_email(
    data: ChangeEmailRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Change the user's email address. Requires password verification."""
    from datetime import timedelta

    # Reload user
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Verify password
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Password is incorrect.")

    # Validate email format (basic check)
    if not data.new_email or "@" not in data.new_email:
        raise HTTPException(status_code=400, detail="Invalid email address.")

    # Normalize email
    new_email = data.new_email.strip().lower()

    # Check if same as current
    if new_email == user.email:
        raise HTTPException(status_code=400, detail="New email is the same as the current email.")

    # Check for duplicate email
    existing = await db.execute(select(User).where(User.email == new_email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="This email is already in use by another account.")

    # Update email
    user.email = new_email
    await db.commit()

    # Issue new tokens since JWT subject is the email
    access_token = create_access_token(
        data={"sub": new_email},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    refresh_token = create_refresh_token(data={"sub": new_email})

    return {
        "success": True,
        "message": "Email changed successfully.",
        "data": {
            "token": access_token,
            "refresh_token": refresh_token,
            "email": new_email
        }
    }

