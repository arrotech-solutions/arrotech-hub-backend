"""
Security router for Mini-Hub MCP Server. Handles 2FA, TOTP, and WebAuthn (Passkeys).
"""

import base64
import json
import secrets
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
from .auth_router import get_current_user, get_password_hash, verify_password

# Configuration
from ..config import settings
RP_ID = getattr(settings, 'RP_ID', "localhost")
RP_NAME = getattr(settings, 'RP_NAME', "Arrotech Hub")
ORIGIN = getattr(settings, 'FRONTEND_URL', "http://localhost:3000")

router = APIRouter(prefix="/security", tags=["security"])

@router.get("/2fa/status")
async def get_2fa_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the current 2FA status for the user."""
    # Ensure settings are loaded
    user = await db.get(User, current_user.id, options=[selectinload(User.settings), selectinload(User.webauthn_credentials)])
    
    return {
        "success": True,
        "data": {
            "two_factor_enabled": user.settings.two_factor_enabled if user.settings else False,
            "has_totp": bool(user.settings and user.settings.totp_secret),
            "passkeys_count": len(user.webauthn_credentials) if hasattr(user, 'webauthn_credentials') else 0,
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
    
    # Generate Provisioning URI
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=user.email, issuer_name="Arrotech Hub")
    
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
    user = await db.get(User, current_user.id, options=[selectinload(User.settings)])
    
    if not user.settings or not user.settings.totp_secret:
        raise HTTPException(status_code=400, detail="TOTP setup not initiated.")
        
    totp = pyotp.TOTP(user.settings.totp_secret)
    if not totp.verify(data.code):
        raise HTTPException(status_code=400, detail="Invalid verification code.")
        
    # Valid code, enable 2FA
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

@router.post("/2fa/disable")
async def disable_2fa(
    verify_data: BaseModel, # Accept any model just to require a body, could require password
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Disable all 2FA methods (TOTP, backup codes). Password requirement generally recommended."""
    # TODO: Require password validation before disabling
    
    user = await db.get(User, current_user.id, options=[selectinload(User.settings), selectinload(User.webauthn_credentials)])
    
    if user.settings:
        user.settings.two_factor_enabled = False
        user.settings.totp_secret = None
        user.settings.backup_codes = None
    
    # Delete passkeys
    for cred in list(user.webauthn_credentials):
        await db.delete(cred)
        
    await db.commit()
    return {"success": True, "message": "Two-factor authentication disabled."}

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
